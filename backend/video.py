from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uuid, os
from auth import get_current_user
from scraper import scrape_vehicle_page
from script_generator import generate_walkaround_script
from heygen_client import create_avatar_video, poll_video_status
from video_assembler import assemble_final_video
from db import supabase

router = APIRouter()
OUTPUT_DIR = os.getenv('OUTPUT_DIR', '/tmp/autowalkaround_videos')

PLAN_LIMITS = {'free': 999999, 'starter': 30, 'growth': 90, 'unlimited': 999999}

class GenerateRequest(BaseModel):
    vehicle_url: str
    salesperson_id: str

@router.post('/generate')
async def generate_video(req: GenerateRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    dealership_id = current_user['dealership_id']
    dealership = supabase.table('dealerships').select('*').eq('id', dealership_id).execute().data[0]
    limit = PLAN_LIMITS.get(dealership.get('plan', 'free'), 999999)
    used = dealership.get('videos_generated_this_month', 0)
    if used >= limit:
        raise HTTPException(status_code=429, detail=f'Monthly limit of {limit} videos reached. Please upgrade your plan.')
    salesperson = supabase.table('salespersons').select('*').eq('id', req.salesperson_id).eq('dealership_id', dealership_id).execute()
    if not salesperson.data:
        raise HTTPException(status_code=404, detail='Salesperson not found. Complete onboarding first.')
    sp = salesperson.data[0]
    job_id = str(uuid.uuid4())
    supabase.table('video_jobs').insert({
        'id': job_id, 'dealership_id': dealership_id, 'user_id': current_user['sub'],
        'salesperson_id': req.salesperson_id, 'vehicle_url': req.vehicle_url, 'status': 'queued'
    }).execute()
    background_tasks.add_task(run_pipeline, job_id, req.vehicle_url, sp, dealership_id)
    return {'job_id': job_id, 'status': 'queued', 'message': 'Video generation started. Check status in 3-8 minutes.'}

async def run_pipeline(job_id: str, vehicle_url: str, salesperson: dict, dealership_id: str):
    def upd(status, msg=''):
        supabase.table('video_jobs').update({'status': status, 'status_message': msg}).eq('id', job_id).execute()
    try:
        upd('scraping', 'Scraping vehicle data...')
        vehicle = scrape_vehicle_page(vehicle_url)
        upd('scripting', 'Generating walkaround script with AI...')
        script_data = generate_walkaround_script(
            vehicle=vehicle, salesperson_name=salesperson.get('name', ''),
            dealer_name=vehicle.get('dealer_name', '')
        )
        full_script = script_data.get('full_script', '')
        supabase.table('video_jobs').update({'script': full_script}).eq('id', job_id).execute()
        upd('rendering', 'Generating AI salesperson video (3-5 min)...')
        heygen_video_id = create_avatar_video(
            avatar_id=salesperson['heygen_avatar_id'],
            voice_id=salesperson['heygen_voice_id'],
            script_text=full_script,
            background_url=salesperson.get('lot_background_url')
        )
        heygen_result = poll_video_status(heygen_video_id, timeout_seconds=600)
        upd('assembling', 'Compositing final video with vehicle photos...')
        final_path = await assemble_final_video(
            vehicle=vehicle, heygen_video_url=heygen_result['video_url'],
            output_dir=OUTPUT_DIR, job_id=job_id
        )
        supabase.table('video_jobs').update({
            'status': 'completed', 'output_path': final_path,
            'vehicle_name': vehicle.get('name', ''), 'vehicle_vin': vehicle.get('vin', '')
        }).eq('id', job_id).execute()
        supabase.table('dealerships').update({
            'videos_generated_this_month': supabase.table('dealerships').select('videos_generated_this_month').eq('id', dealership_id).execute().data[0]['videos_generated_this_month'] + 1
        }).eq('id', dealership_id).execute()
    except Exception as e:
        supabase.table('video_jobs').update({'status': 'failed', 'status_message': str(e)}).eq('id', job_id).execute()
        raise

@router.get('/status/{job_id}')
async def get_job_status(job_id: str, current_user: dict = Depends(get_current_user)):
    job = supabase.table('video_jobs').select('*').eq('id', job_id).eq('dealership_id', current_user['dealership_id']).execute()
    if not job.data:
        raise HTTPException(status_code=404, detail='Job not found')
    return job.data[0]

@router.get('/download/{job_id}')
async def download_video(job_id: str, current_user: dict = Depends(get_current_user)):
    job = supabase.table('video_jobs').select('*').eq('id', job_id).eq('dealership_id', current_user['dealership_id']).execute()
    if not job.data:
        raise HTTPException(status_code=404, detail='Job not found')
    j = job.data[0]
    if j['status'] != 'completed':
        raise HTTPException(status_code=400, detail=f'Video not ready. Status: {j["status"]}')
    if not os.path.exists(j['output_path']):
        raise HTTPException(status_code=404, detail='Video file not found')
    filename = f"{j.get('vehicle_name','walkaround').replace(' ','_')}.mp4"
    return FileResponse(j['output_path'], media_type='video/mp4', filename=filename)

@router.get('/history')
async def get_history(current_user: dict = Depends(get_current_user)):
    jobs = supabase.table('video_jobs').select('*').eq('dealership_id', current_user['dealership_id']).order('created_at', desc=True).limit(50).execute()
    return jobs.data