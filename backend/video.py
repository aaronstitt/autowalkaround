from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
import uuid, os, asyncio
from auth import get_current_user
from scraper import scrape_vehicle_page
from script_generator import generate_walkaround_script
from heygen_client import create_multiscene_avatar_video, poll_video_status
from video_assembler import assemble_final_video
from db import supabase

router = APIRouter()
OUTPUT_DIR = os.getenv('OUTPUT_DIR', '/tmp/autowalkaround_videos')
SUPABASE_BUCKET = os.getenv('SUPABASE_STORAGE_BUCKET', 'videos')
PLAN_LIMITS = {'free': 999999, 'starter': 30, 'growth': 90, 'unlimited': 999999}

class GenerateRequest(BaseModel):
    vehicle_url: str
    salesperson_id: str

@router.post('/generate')
async def generate_video(req: GenerateRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    dealership_id = current_user['dealership_id']
    dr = supabase.table('dealerships').select('*').eq('id', dealership_id).execute()
    if not dr.data:
        raise HTTPException(status_code=404, detail='Dealership not found')
    dealership = dr.data[0]
    limit = PLAN_LIMITS.get(dealership.get('plan', 'free'), 999999)
    if dealership.get('videos_generated_this_month', 0) >= limit:
        raise HTTPException(status_code=429, detail=f'Monthly limit of {limit} videos reached.')
    sr = supabase.table('salespersons').select('*').eq('id', req.salesperson_id).eq('dealership_id', dealership_id).execute()
    if not sr.data:
        raise HTTPException(status_code=404, detail='Salesperson not found. Add in Settings first.')
    sp = sr.data[0]
    if not sp.get('heygen_avatar_id') or not sp.get('heygen_voice_id'):
        raise HTTPException(status_code=400, detail='Salesperson missing HeyGen IDs. Update in Settings.')
    job_id = str(uuid.uuid4())
    row = {'id': job_id, 'dealership_id': dealership_id, 'user_id': current_user['sub'], 'salesperson_id': req.salesperson_id, 'vehicle_url': req.vehicle_url, 'status': 'queued', 'status_message': 'Queued'}
    supabase.table('video_jobs').insert(row).execute()
    background_tasks.add_task(run_pipeline, job_id, req.vehicle_url, sp, dealership_id)
    return {'job_id': job_id, 'status': 'queued', 'message': 'Video generation started. Usually 5-10 minutes.'}

async def run_pipeline(job_id, vehicle_url, salesperson, dealership_id):
    def upd(s, m=''):
        supabase.table('video_jobs').update({'status': s, 'status_message': m}).eq('id', job_id).execute()
    try:
        upd('scraping', 'Scraping vehicle listing...')
        loop = asyncio.get_event_loop()
        vehicle = await loop.run_in_executor(None, scrape_vehicle_page, vehicle_url)
        if not vehicle.get('photos'):
            raise ValueError('No photos found on this vehicle listing page.')
        upd('scripting', 'Writing AI walkaround script...')
        script_data = await loop.run_in_executor(None, lambda: generate_walkaround_script(vehicle=vehicle, salesperson_name=salesperson.get('name', ''), dealer_name=vehicle.get('dealer_name', '')))
        supabase.table('video_jobs').update({'script': script_data.get('full_script', '')}).eq('id', job_id).execute()
        photos = vehicle.get('photos', [])
        ef = vehicle.get('exterior_features', [])
        itf = vehicle.get('interior_features', [])
        tf = max(len(ef) + len(itf), 1)
        xs = max(int(len(photos) * len(ef) / tf), 1)
        ep = photos[0] if photos else None
        ip = photos[xs] if len(photos) > xs else (photos[-1] if photos else None)
        lb = salesperson.get('lot_background_url') or None
        upd('rendering', 'Generating AI salesperson video (4-8 min)...')
        hid = await loop.run_in_executor(None, lambda: create_multiscene_avatar_video(avatar_id=salesperson['heygen_avatar_id'], voice_id=salesperson['heygen_voice_id'], script_data=script_data, ext_photo_url=ep, int_photo_url=ip, lot_bg_url=lb))
        hr = await loop.run_in_executor(None, lambda: poll_video_status(hid, timeout_seconds=720))
        upd('assembling', 'Compositing final video with vehicle photos...')
        fp = await assemble_final_video(vehicle=vehicle, heygen_video_url=hr['video_url'], output_dir=OUTPUT_DIR, job_id=job_id)
        upd('uploading', 'Uploading final video...')
        vu = await loop.run_in_executor(None, upload_to_storage, fp, job_id)
        upd_row = {'status': 'completed', 'status_message': 'Video ready', 'output_path': fp, 'output_url': vu, 'vehicle_name': vehicle.get('name', ''), 'vehicle_vin': vehicle.get('vin', '')}
        supabase.table('video_jobs').update(upd_row).eq('id', job_id).execute()
        cur = supabase.table('dealerships').select('videos_generated_this_month').eq('id', dealership_id).execute()
        cc = cur.data[0].get('videos_generated_this_month', 0) if cur.data else 0
        supabase.table('dealerships').update({'videos_generated_this_month': cc + 1}).eq('id', dealership_id).execute()
    except Exception as e:
        supabase.table('video_jobs').update({'status': 'failed', 'status_message': str(e)[:500]}).eq('id', job_id).execute()

def upload_to_storage(file_path, job_id):
    try:
        if not os.path.exists(file_path):
            return None
        with open(file_path, 'rb') as f:
            data = f.read()
        dp = f'videos/{job_id}_final.mp4'
        supabase.storage.from_(SUPABASE_BUCKET).upload(dp, data, file_options={'content-type': 'video/mp4', 'upsert': 'true'})
        return supabase.storage.from_(SUPABASE_BUCKET).get_public_url(dp)
    except Exception as e:
        print(f'Storage upload failed: {e}')
        return None

@router.get('/status/{job_id}')
async def get_job_status(job_id, current_user=Depends(get_current_user)):
    job = supabase.table('video_jobs').select('*').eq('id', job_id).eq('dealership_id', current_user['dealership_id']).execute()
    if not job.data:
        raise HTTPException(status_code=404, detail='Job not found')
    return job.data[0]

@router.get('/download/{job_id}')
async def download_video(job_id, current_user=Depends(get_current_user)):
    job = supabase.table('video_jobs').select('*').eq('id', job_id).eq('dealership_id', current_user['dealership_id']).execute()
    if not job.data:
        raise HTTPException(status_code=404, detail='Job not found')
    j = job.data[0]
    if j['status'] != 'completed':
        raise HTTPException(status_code=400, detail=f'Not ready. Status: {j["status"]}')
    if j.get('output_url'):
        return RedirectResponse(url=j['output_url'])
    if j.get('output_path') and os.path.exists(j['output_path']):
        return FileResponse(j['output_path'], media_type='video/mp4', filename=(j.get('vehicle_name') or 'walkaround').replace(' ', '_') + '.mp4')
    raise HTTPException(status_code=404, detail='Video not found. Regenerate.')

@router.get('/history')
async def get_history(current_user=Depends(get_current_user)):
    jobs = supabase.table('video_jobs').select('*').eq('dealership_id', current_user['dealership_id']).order('created_at', desc=True).limit(50).execute()
    return jobs.data
