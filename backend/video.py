from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
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

PLAN_LIMITS = {
            'free': 999999,
            'starter': 30,
            'growth': 90,
            'unlimited': 999999
}

class GenerateRequest(BaseModel):
            vehicle_url: str
            salesperson_id: str

@router.post('/generate')
async def generate_video(
            req: GenerateRequest,
            background_tasks: BackgroundTasks,
            current_user: dict = Depends(get_current_user)
):
            dealership_id = current_user['dealership_id']

    dealership_result = supabase.table('dealerships').select('*').eq('id', dealership_id).execute()
    if not dealership_result.data:
                    raise HTTPException(status_code=404, detail='Dealership not found')
                dealership = dealership_result.data[0]
    limit = PLAN_LIMITS.get(dealership.get('plan', 'free'), 999999)
    used = dealership.get('videos_generated_this_month', 0)
    if used >= limit:
                    raise HTTPException(status_code=429, detail=f'Monthly limit of {limit} videos reached.')

    salesperson_result = supabase.table('salespersons').select('*').eq('id', req.salesperson_id).eq('dealership_id', dealership_id).execute()
    if not salesperson_result.data:
                    raise HTTPException(status_code=404, detail='Salesperson not found. Add them in Settings first.')
                sp = salesperson_result.data[0]

    if not sp.get('heygen_avatar_id') or not sp.get('heygen_voice_id'):
                    raise HTTPException(status_code=400, detail='Salesperson is missing HeyGen Avatar ID or Voice ID. Update in Settings.')

    job_id = str(uuid.uuid4())
    supabase.table('video_jobs').insert({
                    'id': job_id,
                    'dealership_id': dealership_id,
                    'user_id': current_user['sub'],
                    'salesperson_id': req.salesperson_id,
                    'vehicle_url': req.vehicle_url,
                    'status': 'queued',
                    'status_message': 'Queued for processing'
    }).execute()

    background_tasks.add_task(run_pipeline, job_id, req.vehicle_url, sp, dealership_id)

    return {
                    'job_id': job_id,
                    'status': 'queued',
                    'message': 'Video generation started. Check status every 30s. Usually completes in 5-10 minutes.'
    }

async def run_pipeline(job_id, vehicle_url, salesperson, dealership_id):
            def upd(status, msg=''):
                            supabase.table('video_jobs').update({
                                                'status': status,
                                                'status_message': msg
                            }).eq('id', job_id).execute()

            try:
                            upd('scraping', 'Scraping vehicle listing...')
                            loop = asyncio.get_event_loop()
                            vehicle = await loop.run_in_executor(None, scrape_vehicle_page, vehicle_url)

                n_photos = len(vehicle.get('photos', []))
        n_features = len(vehicle.get('highlighted_features', []))
        print(f'Scraped: {vehicle.get("name")} | {n_photos} photos | {n_features} features')

        if not vehicle.get('photos'):
                            raise ValueError('No photos found on this vehicle listing page. Check the URL.')

        upd('scripting', 'Writing AI walkaround script...')
        script_data = await loop.run_in_executor(
                            None,
                            lambda: generate_walkaround_script(
                                                    vehicle=vehicle,
                                                    salesperson_name=salesperson.get('name', ''),
                                                    dealer_name=vehicle.get('dealer_name', '')
                            )
        )
        supabase.table('video_jobs').update({
                            'script': script_data.get('full_script', '')
        }).eq('id', job_id).execute()
        print(f'Script generated: {script_data.get("word_count", "?")} words')

        photos = vehicle.get('photos', [])
        ext_features = vehicle.get('exterior_features', [])
        int_features = vehicle.get('interior_features', [])
        total_f = max(len(ext_features) + len(int_features), 1)
        ext_split = max(int(len(photos) * len(ext_features) / total_f), 1)

        ext_photo_url = photos[0] if photos else None
        int_photo_url = photos[ext_split] if len(photos) > ext_split else (photos[-1] if photos else None)
        lot_bg_url = salesperson.get('lot_background_url') or None

        upd('rendering', 'Generating AI salesperson video (4-8 min)...')
        heygen_video_id = await loop.run_in_executor(
                            None,
                            lambda: create_multiscene_avatar_video(
                                                    avatar_id=salesperson['heygen_avatar_id'],
                                                    voice_id=salesperson['heygen_voice_id'],
                                                    script_data=script_data,
                                                    ext_photo_url=ext_photo_url,
                                                    int_photo_url=int_photo_url,
                                                    lot_bg_url=lot_bg_url
                            )
        )
        print(f'HeyGen job submitted: {heygen_video_id}')

        heygen_result = await loop.run_in_executor(
                            None,
                            lambda: poll_video_status(heygen_video_id, timeout_seconds=720)
        )
        print(f'HeyGen complete. URL: {heygen_result["video_url"]}')

        upd('assembling', 'Compositing final video with vehicle photos...')
        final_path = await assemble_final_video(
                            vehicle=vehicle,
                            heygen_video_url=heygen_result['video_url'],
                            output_dir=OUTPUT_DIR,
                            job_id=job_id
        )
        print(f'Assembly complete: {final_path}')

        upd('uploading', 'Uploading final video...')
        video_url = await loop.run_in_executor(None, upload_to_storage, final_path, job_id)

        supabase.table('video_jobs').update({
                            'status': 'completed',
                            'status_message': 'Video ready for download',
                            'output_path': final_path,
                            'output_url': video_url,
                            'vehicle_name': vehicle.get('name', ''),
                            'vehicle_vin': vehicle.get('vin', '')
        }).eq('id', job_id).execute()

        cur = supabase.table('dealerships').select('videos_generated_this_month').eq('id', dealership_id).execute()
        cur_count = cur.data[0].get('videos_generated_this_month', 0) if cur.data else 0
        supabase.table('dealerships').update({
                            'videos_generated_this_month': cur_count + 1
        }).eq('id', dealership_id).execute()

        print(f'Job {job_id} completed successfully')

except Exception as e:
        error_msg = str(e)
        print(f'Job {job_id} FAILED: {error_msg}')
        supabase.table('video_jobs').update({
                            'status': 'failed',
                            'status_message': error_msg[:500]
        }).eq('id', job_id).execute()

def upload_to_storage(file_path, job_id):
            try:
                            if not os.path.exists(file_path):
                                                print(f'Upload skipped: file not found at {file_path}')
                                                return None

                            file_size = os.path.getsize(file_path)
                            print(f'Uploading {file_size / 1024 / 1024:.1f} MB to Supabase Storage...')

        with open(file_path, 'rb') as f:
                            data = f.read()

        dest_path = f'videos/{job_id}_final.mp4'

        supabase.storage.from_(SUPABASE_BUCKET).upload(
                            dest_path, data,
                            file_options={'content-type': 'video/mp4', 'upsert': 'true'}
        )

        public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(dest_path)
        print(f'Uploaded to: {public_url}')
        return public_url

except Exception as e:
        print(f'Supabase Storage upload failed (video still available locally): {e}')
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
                    raise HTTPException(status_code=400, detail=f'Video not ready. Current status: {j["status"]}')

    if j.get('output_url'):
                    return RedirectResponse(url=j['output_url'])

    if j.get('output_path') and os.path.exists(j['output_path']):
                    vehicle_name = (j.get('vehicle_name') or 'walkaround').replace(' ', '_')
                    filename = f'{vehicle_name}.mp4'
                    return FileResponse(j['output_path'], media_type='video/mp4', filename=filename)

    raise HTTPException(status_code=404, detail='Video file not found. Regenerate the video.')

@router.get('/history')
async def get_history(current_user=Depends(get_current_user)):
            jobs = supabase.table('video_jobs').select('*').eq('dealership_id', current_user['dealership_id']).order('created_at', desc=True).limit(50).execute()
    return jobs.data
