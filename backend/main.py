from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn, os, requests, tempfile
from auth import router as auth_router
from video import router as video_router
from onboarding import router as onboarding_router
from db import supabase

app = FastAPI(title='AutoWalkaround API', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(auth_router, prefix='/auth', tags=['auth'])
app.include_router(video_router, prefix='/video', tags=['video'])
app.include_router(onboarding_router, prefix='/onboarding', tags=['onboarding'])

def run_migrations():
    """Run DB migrations on startup."""
    try:
        result = supabase.table('salespersons').select('source_video_url').limit(1).execute()
        print('[Migration] source_video_url column exists - OK')
    except Exception as e:
        print(f'[Migration] source_video_url column check failed: {e}')

@app.on_event('startup')
async def startup_event():
    run_migrations()

@app.get('/health')
def health(): return {'status': 'ok'}

@app.get('/debug/looks')
def debug_looks():
    """List all looks for Aaron's avatar group."""
    key = os.getenv('HEYGEN_API_KEY', '')
    group_id = os.getenv('HEYGEN_AVATAR_GROUP_ID', '202a882fdd924622bc00d1eca0bf00cd')
    r = requests.get(
        f'https://api.heygen.com/v3/avatars/looks?ownership=private&group_id={group_id}',
        headers={'x-api-key': key, 'Content-Type': 'application/json'},
        timeout=30
    )
    return r.json()

@app.get('/debug/heygen-videos')
def debug_heygen_videos():
    """List all HeyGen videos."""
    key = os.getenv('HEYGEN_API_KEY', '')
    r = requests.get(
        'https://api.heygen.com/v1/video.list?limit=20',
        headers={'x-api-key': key, 'Content-Type': 'application/json'},
        timeout=30
    )
    return r.json()

@app.get('/debug/heygen-video/{video_id}')
def debug_heygen_video(video_id: str):
    """Get a specific HeyGen video by ID."""
    key = os.getenv('HEYGEN_API_KEY', '')
    r = requests.get(
        f'https://api.heygen.com/v1/video_status.get?video_id={video_id}',
        headers={'x-api-key': key, 'Content-Type': 'application/json'},
        timeout=30
    )
    return r.json()

@app.post('/admin/upload-source-video')
def upload_source_video(
    salesperson_id: str = Query(...),
    heygen_video_id: str = Query(...),
    secret: str = Query(...)
):
    """Download a HeyGen video and store it permanently in Supabase Storage as the source walkaround."""
    if secret != os.getenv('ADMIN_SECRET', 'aw-admin-2024'):
        raise HTTPException(status_code=403, detail='Invalid secret')
    key = os.getenv('HEYGEN_API_KEY', '')
    bucket = os.getenv('SUPABASE_STORAGE_BUCKET', 'videos')
    # Get fresh signed URL from HeyGen
    r = requests.get(
        f'https://api.heygen.com/v1/video_status.get?video_id={heygen_video_id}',
        headers={'x-api-key': key},
        timeout=30
    )
    if r.status_code != 200:
        raise HTTPException(500, f'HeyGen video lookup failed: {r.status_code}')
    data = r.json().get('data', {})
    video_url = data.get('video_url')
    if not video_url:
        raise HTTPException(404, 'No video_url in HeyGen response')
    # Download the video
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        dl = requests.get(video_url, stream=True, timeout=300)
        dl.raise_for_status()
        for chunk in dl.iter_content(65536):
            tmp.write(chunk)
        tmp_path = tmp.name
    # Upload to Supabase Storage
    storage_path = f'walkarounds/{salesperson_id}_source.mp4'
    with open(tmp_path, 'rb') as f:
        supabase.storage.from_(bucket).upload(
            storage_path, f, 
            file_options={'content-type': 'video/mp4', 'upsert': 'true'}
        )
    import os as os_mod
    os_mod.unlink(tmp_path)
    public_url = supabase.storage.from_(bucket).get_public_url(storage_path)
    # Update DB
    supabase.table('salespersons').update(
        {'source_video_url': public_url}
    ).eq('id', salesperson_id).execute()
    return {'status': 'ok', 'public_url': public_url, 'salesperson_id': salesperson_id}

@app.post('/admin/set-source-video')
def set_source_video(
    salesperson_id: str = Query(...),
    video_url: str = Query(...),
    secret: str = Query(...)
):
    """Admin endpoint: store source walkaround video URL for a salesperson."""
    if secret != os.getenv('ADMIN_SECRET', 'aw-admin-2024'):
        raise HTTPException(status_code=403, detail='Invalid secret')
    result = supabase.table('salespersons').update(
        {'source_video_url': video_url}
    ).eq('id', salesperson_id).execute()
    return {'status': 'ok', 'salesperson_id': salesperson_id, 'video_url': video_url, 'updated': result.data}

if __name__ == '__main__':
    uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=True)
