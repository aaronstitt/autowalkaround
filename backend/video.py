from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
import uuid, os, asyncio, tempfile
from auth import get_current_user
from scraper import scrape_vehicle_page
from script_generator import generate_walkaround_script
from video_assembler import (
    get_look_id,
    get_avatar_source_video_url,
    generate_heygen_audio,
    generate_tts_audio,
    upload_audio_to_heygen,
    run_video_translation,
    build_walkaround_video,
    _download_file
)
from db import supabase

router = APIRouter()
SUPABASE_BUCKET = os.getenv('SUPABASE_STORAGE_BUCKET', 'videos')

HEYGEN_VOICE_ID = os.getenv('HEYGEN_VOICE_ID', '6ee20575cb9f4a7e9dc19096a958eab1')
HEYGEN_AVATAR_GROUP_ID = os.getenv('HEYGEN_AVATAR_GROUP_ID', '202a882fdd924622bc00d1eca0bf00cd')

class GenerateRequest(BaseModel):
    vehicle_url: str
    salesperson_id: str
    page_html: Optional[str] = None

@router.post('/generate')
async def generate_video(req: GenerateRequest, background_tasks: BackgroundTasks,
                         current_user=Depends(get_current_user)):
    user_id = current_user['sub']
    resp = supabase.table('users').select('dealership_id').eq('id', user_id).single().execute()
    dealership_id = resp.data.get('dealership_id')

    job_id = str(uuid.uuid4())
    supabase.table('video_jobs').insert({
        'id': job_id,
        'user_id': user_id,
        'dealership_id': dealership_id,
        'vehicle_url': req.vehicle_url,
        'salesperson_id': req.salesperson_id,
        'status': 'queued',
        'status_message': 'Job queued'
    }).execute()

    background_tasks.add_task(_run_pipeline, job_id, req.vehicle_url,
                              req.salesperson_id, dealership_id, req.page_html)
    return {'job_id': job_id, 'status': 'queued'}

@router.get('/status/{job_id}')
async def get_status(job_id: str):
    resp = supabase.table('video_jobs').select('*').eq('id', job_id).single().execute()
    if not resp.data:
        raise HTTPException(404, 'Job not found')
    return resp.data

@router.get('/history')
async def get_history(current_user=Depends(get_current_user)):
    user_id = current_user['sub']
    resp = supabase.table('video_jobs').select('*').eq('user_id', user_id).order('created_at', desc=True).limit(20).execute()
    return resp.data or []

@router.get('/download/{job_id}')
async def download_video(job_id: str, current_user=Depends(get_current_user)):
    user_id = current_user['sub']
    resp = supabase.table('video_jobs').select('*').eq('id', job_id).single().execute()
    if not resp.data:
        raise HTTPException(404, 'Job not found')
    job = resp.data
    if job.get('user_id') != user_id:
        raise HTTPException(403, 'Not authorized')
    if job.get('status') != 'completed' or not job.get('output_url'):
        raise HTTPException(400, 'Video not ready')
    return RedirectResponse(url=job['output_url'], status_code=302)

def _upd(job_id, status, msg):
    try:
        supabase.table('video_jobs').update({'status': status, 'status_message': msg}).eq('id', job_id).execute()
        print(f'[Pipeline] {status}: {msg}')
    except Exception as e:
        print(f'[Pipeline] DB update failed: {e}')

async def _run_pipeline(job_id, vehicle_url, salesperson_id, dealership_id, page_html):
    loop = asyncio.get_event_loop()
    tmpdir = tempfile.mkdtemp(prefix='aw_')
    try:
        def upd(s, m): _upd(job_id, s, m)

        upd('rendering', 'Loading salesperson profile...')
        sp_resp = supabase.table('salespersons').select('*').eq('id', salesperson_id).single().execute()
        salesperson = sp_resp.data or {}
        salesperson_name = salesperson.get('name', 'Aaron')
        voice_id = salesperson.get('heygen_voice_id') or HEYGEN_VOICE_ID
        avatar_group_id = salesperson.get('heygen_avatar_group_id') or HEYGEN_AVATAR_GROUP_ID
        source_video_url = salesperson.get('source_video_url')

        print(f'[Pipeline] Salesperson: {salesperson_name}, source_video_url: {source_video_url}')

        # If no source video stored yet, try to retrieve from HeyGen
        if not source_video_url:
            upd('rendering', 'Looking up walkaround source video from HeyGen...')
            source_video_url = await loop.run_in_executor(
                None, lambda: get_avatar_source_video_url(avatar_group_id)
            )
            if source_video_url:
                print(f'[Pipeline] Found source video: {source_video_url[:80]}')
                # Store it for future use
                try:
                    supabase.table('salespersons').update({'source_video_url': source_video_url}).eq('id', salesperson_id).execute()
                    print(f'[Pipeline] Stored source_video_url in DB')
                except Exception as e:
                    print(f'[Pipeline] Could not store source_video_url: {e}')
            else:
                print('[Pipeline] WARNING: Could not retrieve source video URL from HeyGen automatically')

        look_id = salesperson.get('heygen_look_id') or get_look_id(avatar_group_id)
        print(f'[Pipeline] Look ID: {look_id}')

        upd('rendering', 'Scraping vehicle listing...')
        vehicle = await loop.run_in_executor(None, lambda: scrape_vehicle_page(vehicle_url, page_html))
        if not vehicle.get('photos') and not vehicle.get('video_url'):
            raise ValueError('No photos or video found on this vehicle listing page.')

        vehicle_name = vehicle.get('name', 'Vehicle')
        photos = vehicle.get('photos', [])
        vehicle_video_url = vehicle.get('video_url')
        print(f'[Pipeline] Vehicle: {vehicle_name}, Photos: {len(photos)}')

        try:
            supabase.table('video_jobs').update({'vehicle_name': vehicle_name}).eq('id', job_id).execute()
        except Exception:
            pass

        upd('rendering', 'Writing AI walkaround script...')
        script_data = await loop.run_in_executor(None, lambda: generate_walkaround_script(
            vehicle=vehicle,
            salesperson_name=salesperson_name,
            dealer_name=vehicle.get('dealer_name', 'Immaculate Used Cars')
        ))
        full_script = script_data.get('full_script', '')
        print(f'[Pipeline] Script: {len(full_script)} chars')
        if not full_script:
            raise ValueError('Script generation failed')

        upd('rendering', 'Generating AI voice for new script...')
        audio_path, audio_url = await loop.run_in_executor(
            None, lambda: generate_tts_audio(full_script, voice_id, tmpdir)
        )

        # Upload audio to HeyGen for use in translation
        audio_asset_id = None
        try:
            audio_asset_id = await loop.run_in_executor(
                None, lambda: upload_audio_to_heygen(audio_path)
            )
        except Exception as e:
            print(f'[Pipeline] Audio upload failed, will use URL: {e}')

        heygen_result = {
            'audio_path': audio_path,
            'audio_url': audio_url,
            'audio_asset_id': audio_asset_id,
            'source_video_url': source_video_url,
            'look_id': look_id
        }

        upd('assembling', 'Applying new script to walkaround video with lip sync (30-45 min)...')
        final_path = await loop.run_in_executor(None, lambda: build_walkaround_video(
            vehicle=vehicle,
            script_segments=script_data.get('segments', []),
            heygen_audio_path=audio_path,
            heygen_result=heygen_result,
            vehicle_photos=photos,
            vehicle_video_url=vehicle_video_url,
            tmpdir=tmpdir
        ))

        upd('uploading', 'Uploading video...')
    # Compress video with FFmpeg before upload to stay under Supabase 50MB limit
    import subprocess as _sp
    _compressed = tmpdir + '/final_compressed.mp4'
    try:
        _sz = os.path.getsize(final_path)
        print(f'[Upload] Video size: {_sz/1024/1024:.1f} MB')
        if _sz > 40 * 1024 * 1024:
            print('[Upload] Compressing with FFmpeg...')
            _r = _sp.run(['ffmpeg','-y','-i',final_path,'-c:v','libx264','-preset','fast','-crf','28','-c:a','aac','-b:a','96k','-movflags','+faststart',_compressed],capture_output=True,timeout=120)
            if _r.returncode == 0 and os.path.exists(_compressed):
                _nsz = os.path.getsize(_compressed)
                print(f'[Upload] Compressed to {_nsz/1024/1024:.1f} MB')
                final_path = _compressed
            else:
                print(f'[Upload] FFmpeg failed (using original)')
        else:
            print(f'[Upload] Size OK, no compression needed')
    except Exception as _e:
        print(f'[Upload] Compression error: {_e}')
        storage_path = f'videos/{job_id}_final.mp4'
        with open(final_path, 'rb') as f:
            supabase.storage.from_(SUPABASE_BUCKET).upload(
                storage_path, f, file_options={'content-type': 'video/mp4', 'upsert': 'true'}
            )
        public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(storage_path)
        supabase.table('video_jobs').update({
            'status': 'completed',
            'status_message': 'Video ready!',
            'output_url': public_url
        }).eq('id', job_id).execute()
        print(f'[Pipeline] DONE: {public_url}')

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f'[Pipeline] FAILED: {e}\n{tb}')
        _upd(job_id, 'failed', f'Failed: {str(e)[:200]}')
    finally:
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
