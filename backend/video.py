from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
import uuid, os, asyncio, tempfile, subprocess
from auth import get_current_user
from scraper import scrape_vehicle_page
from script_generator import generate_walkaround_script
from video_assembler import (
    get_look_id,
    build_walkaround_video,
    compress_video_for_upload,
)
from db import supabase

router = APIRouter()
SUPABASE_BUCKET = os.getenv('SUPABASE_STORAGE_BUCKET', 'videos')

HEYGEN_VOICE_ID = os.getenv('HEYGEN_VOICE_ID', '6ee20575cb9f4a7e9dc19096a958eab1')
HEYGEN_AVATAR_GROUP_ID = os.getenv('HEYGEN_AVATAR_GROUP_ID', '202a882fdd924622bc00d1eca0bf00cd')
HEYGEN_LOOK_ID = os.getenv('HEYGEN_LOOK_ID', 'ed119cc46f5f4a6d8a6687ac187cd779')


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
        print('[Pipeline]', status + ':', msg)
    except Exception as e:
        print('[Pipeline] DB update failed:', e)


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

        look_id = salesperson.get('heygen_look_id')
        if not look_id:
            look_id = await loop.run_in_executor(None, lambda: get_look_id(avatar_group_id))
            if look_id:
                try:
                    supabase.table('salespersons').update({'heygen_look_id': look_id}).eq('id', salesperson_id).execute()
                except Exception:
                    pass
        look_id = look_id or HEYGEN_LOOK_ID
        print('[Pipeline] Salesperson:', salesperson_name, 'look_id:', look_id, 'voice_id:', voice_id[:20])

        upd('rendering', 'Scraping vehicle listing...')
        vehicle = await loop.run_in_executor(None, lambda: scrape_vehicle_page(vehicle_url, page_html))
        if not vehicle.get('photos') and not vehicle.get('video_url'):
            raise ValueError('No photos or video found on this vehicle listing page.')

        vehicle_name = vehicle.get('name', 'Vehicle')
        photos = vehicle.get('photos', [])
        vehicle_video_url = vehicle.get('video_url')
        print('[Pipeline] Vehicle:', vehicle_name, 'Photos:', len(photos))

        try:
            supabase.table('video_jobs').update({'vehicle_name': vehicle_name}).eq('id', job_id).execute()
        except Exception:
            pass

        upd('rendering', 'Writing segmented walkaround script...')
        script_data = await loop.run_in_executor(None, lambda: generate_walkaround_script(
            vehicle=vehicle,
            salesperson_name=salesperson_name,
            dealer_name=vehicle.get('dealer_name', 'Immaculate Used Cars')
        ))
        full_script = script_data.get('full_script', '')
        segments = script_data.get('segments', {})
        print('[Pipeline] Script:', len(full_script), 'chars, word_count:', script_data.get('word_count'))
        print('[Pipeline] Segment keys:', list(segments.keys()))
        try:
            _dump = (full_script or '') + '\n\n--PHOTOS--\n' + '\n'.join((vehicle.get('photos') or [])[:22]) + '\n\n--SEGMENTS--\n' + '\n'.join((str(k) + ': ' + str(v)) for k, v in (segments or {}).items())
            supabase.table('video_jobs').update({'script': _dump[:5000]}).eq('id', job_id).execute()
        except Exception:
            pass
        if not full_script:
            raise ValueError('Script generation failed')

        # heygen_result carries all params needed by video_assembler
        heygen_result = {
            'voice_id': voice_id,
            'look_id': look_id,
            'avatar_group_id': avatar_group_id,
        }

        upd('assembling', 'Building walkaround video (intro avatar + vehicle photo segments)...')
        final_path = await loop.run_in_executor(None, lambda: build_walkaround_video(
            vehicle=vehicle,
            script_segments=segments,
            heygen_audio_path=None,
            heygen_result=heygen_result,
            vehicle_photos=photos,
            vehicle_video_url=vehicle_video_url,
            tmpdir=tmpdir
        ))

        upd('uploading', 'Uploading video...')
        storage_path = 'videos/' + job_id + '_final.mp4'
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
        print('[Pipeline] DONE:', public_url)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print('[Pipeline] FAILED:', e, tb)
        _upd(job_id, 'failed', 'Failed: ' + str(e)[:200])
    finally:
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


class FalSampleRequest(BaseModel):
    image_url: str
    prompt: Optional[str] = None


def _run_fal_sample(job_id, image_url, prompt):
    import tempfile, os as _os
    from video_assembler import fal_image_to_video, _upload_file_to_supabase
    try:
        supabase.table('video_jobs').update({'status': 'assembling', 'status_message': 'fal generating'}).eq('id', job_id).execute()
        tmp = tempfile.mkdtemp()
        clip = fal_image_to_video(image_url, prompt, tmp, 'sample')
        if not clip or not _os.path.exists(clip):
            supabase.table('video_jobs').update({'status': 'failed', 'status_message': 'fal returned nothing (check FAL_KEY / credits)'}).eq('id', job_id).execute()
            return
        pub = _upload_file_to_supabase(clip, 'fal_samples/' + job_id + '.mp4')
        supabase.table('video_jobs').update({'status': 'completed', 'status_message': 'Video ready!', 'output_url': pub}).eq('id', job_id).execute()
    except Exception as e:
        supabase.table('video_jobs').update({'status': 'failed', 'status_message': str(e)[:200]}).eq('id', job_id).execute()


@router.post('/fal-sample')
async def fal_sample(req: FalSampleRequest, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    user_id = current_user['sub']
    resp = supabase.table('users').select('dealership_id').eq('id', user_id).single().execute()
    dealership_id = resp.data.get('dealership_id')
    job_id = str(uuid.uuid4())
    prompt = req.prompt or ('Smooth cinematic slow orbit around the parked vehicle at a car dealership lot, '
                            'the camera glides slowly around the car, the vehicle stays exactly the same shape color and details, '
                            'photorealistic, natural daylight, subtle reflections, no people')
    supabase.table('video_jobs').insert({
        'id': job_id, 'user_id': user_id, 'dealership_id': dealership_id,
        'vehicle_url': req.image_url, 'vehicle_name': 'FAL SAMPLE',
        'salesperson_id': 'fa5dc22a-03bc-4d21-b47b-09b460eec9fc',
        'status': 'queued', 'status_message': 'fal queued'
    }).execute()
    background_tasks.add_task(_run_fal_sample, job_id, req.image_url, prompt)
    return {'job_id': job_id, 'status': 'queued'}
