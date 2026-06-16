from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
import uuid, os, asyncio, tempfile, requests as req_lib
from auth import get_current_user
from scraper import scrape_vehicle_page
from script_generator import generate_walkaround_script
from video_assembler import (
    get_look_id,
    generate_heygen_webm,
    generate_cinematic_clip,
    get_lot_background,
    build_walkaround_video,
    _download_file
)
from db import supabase

router = APIRouter()
OUTPUT_DIR = os.getenv('OUTPUT_DIR', '/tmp/autowalkaround_videos')
SUPABASE_BUCKET = os.getenv('SUPABASE_STORAGE_BUCKET', 'videos')
PLAN_LIMITS = {'free': 999999, 'starter': 30, 'growth': 90, 'unlimited': 999999}

class GenerateRequest(BaseModel):
    vehicle_url: str
    salesperson_id: str
    page_html: Optional[str] = None

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
        raise HTTPException(status_code=404, detail='Salesperson not found.')
    sp = sr.data[0]
    if not sp.get('heygen_avatar_id') or not sp.get('heygen_voice_id'):
        raise HTTPException(status_code=400, detail='Salesperson missing HeyGen IDs.')
    job_id = str(uuid.uuid4())
    row = {
        'id': job_id,
        'dealership_id': dealership_id,
        'user_id': current_user['sub'],
        'salesperson_id': req.salesperson_id,
        'vehicle_url': req.vehicle_url,
        'status': 'queued',
        'status_message': 'Queued'
    }
    supabase.table('video_jobs').insert(row).execute()
    background_tasks.add_task(run_pipeline, job_id, req.vehicle_url, sp, dealership_id, req.page_html)
    return {'job_id': job_id, 'status': 'queued', 'message': 'Video generation started. Usually 15-25 minutes.'}

async def run_pipeline(job_id, vehicle_url, salesperson, dealership_id, page_html=None):
    def upd(s, m=''):
        supabase.table('video_jobs').update({'status': s, 'status_message': m}).eq('id', job_id).execute()
    
    tmpdir = tempfile.mkdtemp(prefix='aw_' + job_id[:8] + '_')
    
    try:
        loop = asyncio.get_event_loop()
        
        # ============================================================
        # STEP 1: Scrape vehicle listing
        # ============================================================
        upd('scraping', 'Scraping vehicle listing...')
        vehicle = await loop.run_in_executor(None, lambda: scrape_vehicle_page(vehicle_url, page_html))
        if not vehicle.get('photos'):
            raise ValueError('No photos found on this vehicle listing page.')
        
        vehicle_name = vehicle.get('name', 'Vehicle')
        photos = vehicle.get('photos', [])
        
        # ============================================================
        # STEP 2: Generate walkaround script
        # ============================================================
        upd('scripting', 'Writing AI walkaround script...')
        script_data = await loop.run_in_executor(None, lambda: generate_walkaround_script(
            vehicle=vehicle,
            salesperson_name=salesperson.get('name', ''),
            dealer_name=vehicle.get('dealer_name', 'Immaculate Used Cars')
        ))
        full_script = script_data.get('full_script', '')
        supabase.table('video_jobs').update({'script': full_script}).eq('id', job_id).execute()
        
        # ============================================================
        # STEP 3: Get avatar look ID (preferably "The Sharp Used Car Salesman")
        # ============================================================
        avatar_group_id = salesperson['heygen_avatar_id']
        voice_id = salesperson['heygen_voice_id']
        
        upd('rendering', 'Getting avatar look ID...')
        look_id = await loop.run_in_executor(None, lambda: get_look_id(avatar_group_id))
        if not look_id:
            raise ValueError('Could not get HeyGen avatar look ID')
        print(f'[Pipeline] Using look_id: {look_id}')
        
        # ============================================================
        # STEP 4: Generate Avatar V webm - Aaron talking + walking motion
        # output_format=webm gives transparent alpha - no green screen needed!
        # ============================================================
        upd('rendering', 'Generating avatar video with walking motion (Avatar V)...')
        webm_path = await loop.run_in_executor(None, lambda: generate_heygen_webm(
            script_text=full_script,
            avatar_look_id=look_id,
            voice_id=voice_id,
            tmpdir=tmpdir
        ))
        
        # ============================================================
        # STEP 5: Get actual video duration from webm to build segment map
        # ============================================================
        upd('assembling', 'Planning video segments...')
        segments = _build_segment_map(script_data, vehicle, webm_path, tmpdir)
        
        # ============================================================
        # STEP 6: Download vehicle photos for compositing
        # ============================================================
        upd('assembling', 'Downloading vehicle photos...')
        local_photos = await loop.run_in_executor(None, lambda: _download_vehicle_photos(photos, tmpdir))
        
        # ============================================================
        # STEP 7: Generate Cinematic Avatar clips - Aaron actually walking around vehicle
        # These clips show Aaron moving around/near the vehicle - pure cinematic video
        # ============================================================
        upd('assembling', 'Generating cinematic walkaround clips (Aaron walking)...')
        cinematic_clips = []
        
        walkaround_segs = [s for s in segments if s.get('type') == 'walkaround']
        
        # Group walkaround segments into cinematic clips (max 15s each)
        cin_groups = []
        current_group = []
        current_dur = 0
        for seg in walkaround_segs:
            seg_dur = seg.get('duration', 5)
            if current_dur + seg_dur > 14 and current_group:
                cin_groups.append(current_group)
                current_group = [seg]
                current_dur = seg_dur
            else:
                current_group.append(seg)
                current_dur += seg_dur
        if current_group:
            cin_groups.append(current_group)
        
        for cin_idx, group in enumerate(cin_groups):
            group_dur = sum(s.get('duration', 5) for s in group)
            group_photo_indices = [s.get('photo_index', 0) for s in group]
            group_photos_urls = [photos[i] for i in group_photo_indices if i < len(photos)]
            
            cin_path = await loop.run_in_executor(None, lambda gi=cin_idx, gd=group_dur, gp=group_photos_urls: generate_cinematic_clip(
                look_id=look_id,
                vehicle_photos=gp,
                vehicle_name=vehicle_name,
                lot_bg_path=None,
                duration=gd,
                tmpdir=tmpdir,
                clip_index=gi
            ))
            
            if cin_path:
                cinematic_clips.append((cin_path, cin_idx))
                # Assign this cinematic clip to all segments in the group
                for seg in group:
                    seg['cinematic_index'] = cin_idx
        
        print(f'[Pipeline] Generated {len(cinematic_clips)} cinematic clips')
        
        # ============================================================
        # STEP 8: Assemble final video
        # ============================================================
        upd('assembling', 'Assembling final walkaround video...')
        final_path = await loop.run_in_executor(None, lambda: build_walkaround_video(
            vehicle=vehicle,
            script_segments=segments,
            heygen_webm_path=webm_path,
            cinematic_clips=cinematic_clips,
            vehicle_photos=local_photos,
            tmpdir=tmpdir
        ))
        
        # ============================================================
        # STEP 9: Upload to Supabase Storage
        # ============================================================
        upd('uploading', 'Uploading final video...')
        video_url = await loop.run_in_executor(None, lambda: upload_to_storage(final_path, job_id))
        
        upd_row = {
            'status': 'completed',
            'status_message': 'Video ready!',
            'output_path': final_path,
            'output_url': video_url,
            'vehicle_name': vehicle_name,
            'vehicle_vin': vehicle.get('vin', '')
        }
        supabase.table('video_jobs').update(upd_row).eq('id', job_id).execute()
        
        cur = supabase.table('dealerships').select('videos_generated_this_month').eq('id', dealership_id).execute()
        cc = cur.data[0].get('videos_generated_this_month', 0) if cur.data else 0
        supabase.table('dealerships').update({'videos_generated_this_month': cc + 1}).eq('id', dealership_id).execute()
    
    except Exception as e:
        print(f'[Pipeline] FAILED job {job_id}: {e}')
        import traceback
        traceback.print_exc()
        supabase.table('video_jobs').update({'status': 'failed', 'status_message': str(e)[:500]}).eq('id', job_id).execute()


def _get_webm_duration(webm_path):
    """Get duration of webm file using ffprobe."""
    import subprocess
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', webm_path],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except Exception:
        return 90.0  # default 90 seconds


def _build_segment_map(script_data, vehicle, webm_path, tmpdir):
    """
    Build a list of segment dicts describing what to show at each audio timestamp.
    Uses the script structure to determine intro, feature segments, and outro.
    Each segment has: {type, audio_start, duration, photo_index}
    """
    import subprocess, json
    
    total_dur = _get_webm_duration(webm_path)
    print(f'[SegMap] Total webm duration: {total_dur:.1f}s')
    
    segments_text = script_data.get('segments', [])
    photos = vehicle.get('photos', [])
    n_photos = len(photos)
    
    # If no segment timing data, distribute evenly
    if not segments_text:
        # Simple: intro (10s), walkaround (middle), outro (10s)
        segments = []
        intro_dur = min(12, total_dur * 0.12)
        outro_dur = min(12, total_dur * 0.12)
        walkaround_dur = total_dur - intro_dur - outro_dur
        
        segments.append({'type': 'intro', 'audio_start': 0, 'duration': intro_dur, 'photo_index': 0})
        
        if n_photos > 0 and walkaround_dur > 0:
            n_segs = max(1, min(n_photos, 8))
            seg_dur = walkaround_dur / n_segs
            for i in range(n_segs):
                photo_idx = int(i * n_photos / n_segs)
                segments.append({
                    'type': 'walkaround',
                    'audio_start': intro_dur + i * seg_dur,
                    'duration': seg_dur,
                    'photo_index': photo_idx
                })
        
        segments.append({'type': 'outro', 'audio_start': total_dur - outro_dur, 'duration': outro_dur, 'photo_index': max(0, n_photos-1)})
        return segments
    
    # Use segment data if available
    segments = []
    features = vehicle.get('highlighted_features', [])
    n_features = len(features)
    
    intro_dur = min(12, total_dur * 0.12)
    outro_dur = min(12, total_dur * 0.12)
    walkaround_dur = total_dur - intro_dur - outro_dur
    
    segments.append({'type': 'intro', 'audio_start': 0, 'duration': intro_dur, 'photo_index': 0})
    
    n_segs = max(1, min(n_features if n_features > 0 else n_photos, 10))
    if walkaround_dur > 0:
        seg_dur = walkaround_dur / n_segs
        for i in range(n_segs):
            photo_idx = int(i * n_photos / n_segs) if n_photos > 0 else 0
            segments.append({
                'type': 'walkaround',
                'audio_start': intro_dur + i * seg_dur,
                'duration': seg_dur,
                'photo_index': photo_idx
            })
    
    segments.append({'type': 'outro', 'audio_start': total_dur - outro_dur, 'duration': outro_dur, 'photo_index': max(0, n_photos-1)})
    return segments


def _download_vehicle_photos(photo_urls, tmpdir):
    """Download vehicle photos locally. Returns list of local paths."""
    local_paths = []
    os.makedirs(os.path.join(tmpdir, 'photos'), exist_ok=True)
    for i, url in enumerate(photo_urls[:15]):  # limit to 15 photos
        try:
            local_path = os.path.join(tmpdir, 'photos', f'photo_{i:03d}.jpg')
            _download_file(url, local_path)
            local_paths.append(local_path)
        except Exception as e:
            print(f'[Photos] Failed to download photo {i}: {e}')
    print(f'[Photos] Downloaded {len(local_paths)} photos')
    return local_paths


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
