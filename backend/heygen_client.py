import requests
import os
import time

HEYGEN_BASE = 'https://api.heygen.com'

def get_headers():
    return {'X-Api-Key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}

def list_avatars():
    resp = requests.get(f'{HEYGEN_BASE}/v2/avatars', headers=get_headers())
    resp.raise_for_status()
    return resp.json().get('data', {}).get('avatars', [])

def list_voices():
    resp = requests.get(f'{HEYGEN_BASE}/v2/voices', headers=get_headers())
    resp.raise_for_status()
    return resp.json().get('data', {}).get('voices', [])

def _build_background(background_url=None):
    if background_url:
        return {'type': 'image', 'url': background_url}
    return {'type': 'color', 'value': '#1a1a2e'}

def create_avatar_video(avatar_id, voice_id, script_text, background_url=None, width=1080, height=1920):
    """Single-scene video: full script, one background. Used as fallback."""
    payload = {
        'video_inputs': [{
            'character': {'type': 'avatar', 'avatar_id': avatar_id, 'avatar_style': 'normal'},
            'voice': {'type': 'text', 'input_text': script_text, 'voice_id': voice_id, 'speed': 0.95},
            'background': _build_background(background_url)
        }],
        'dimension': {'width': width, 'height': height},
        'test': False
    }
    resp = requests.post(f'{HEYGEN_BASE}/v2/video/generate', headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()['data']['video_id']

def create_multiscene_avatar_video(avatar_id, voice_id, script_data, ext_photo_url=None, int_photo_url=None, lot_bg_url=None, width=1080, height=1920):
    """
    Multi-scene video matching script structure to vehicle photos:
    - Scene 1: exterior script + first exterior vehicle photo as background
    - Scene 2: interior script + first interior vehicle photo as background
    Falls back to single scene if photo URLs not provided.
    """
    exterior_script = script_data.get('exterior_script', '')
    interior_script = script_data.get('interior_script', '')
    full_script = script_data.get('full_script', '')

    if not exterior_script or not interior_script:
        return create_avatar_video(avatar_id, voice_id, full_script, lot_bg_url, width, height)

    video_inputs = []

    ext_bg = _build_background(ext_photo_url or lot_bg_url)
    video_inputs.append({
        'character': {'type': 'avatar', 'avatar_id': avatar_id, 'avatar_style': 'normal'},
        'voice': {'type': 'text', 'input_text': exterior_script, 'voice_id': voice_id, 'speed': 0.95},
        'background': ext_bg
    })

    int_bg = _build_background(int_photo_url or lot_bg_url)
    video_inputs.append({
        'character': {'type': 'avatar', 'avatar_id': avatar_id, 'avatar_style': 'normal'},
        'voice': {'type': 'text', 'input_text': interior_script, 'voice_id': voice_id, 'speed': 0.95},
        'background': int_bg
    })

    payload = {
        'video_inputs': video_inputs,
        'dimension': {'width': width, 'height': height},
        'test': False
    }
    resp = requests.post(f'{HEYGEN_BASE}/v2/video/generate', headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()['data']['video_id']

def poll_video_status(video_id, timeout_seconds=600):
    start = time.time()
    while time.time() - start < timeout_seconds:
        resp = requests.get(f'{HEYGEN_BASE}/v1/video_status.get?video_id={video_id}', headers=get_headers())
        resp.raise_for_status()
        data = resp.json().get('data', {})
        status = data.get('status', '')
        if status == 'completed':
            return {'status': 'completed', 'video_url': data.get('video_url'), 'duration': data.get('duration')}
        elif status == 'failed':
            raise Exception(f'HeyGen failed: {data.get("error", "Unknown")}')
        time.sleep(10)
    raise TimeoutError(f'Timed out after {timeout_seconds}s')

def create_instant_avatar(video_url, avatar_name):
    payload = {'video_url': video_url, 'name': avatar_name}
    resp = requests.post(f'{HEYGEN_BASE}/v2/instant_avatar', headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json().get('data', {}).get('avatar_id', '')

def clone_voice(audio_url, voice_name):
    payload = {'audio_url': audio_url, 'name': voice_name}
    resp = requests.post(f'{HEYGEN_BASE}/v2/voice_clone', headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json().get('data', {}).get('voice_id', '')
