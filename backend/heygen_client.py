import requests
import os
import time

HEYGEN_BASE = 'https://api.heygen.com'

def get_headers():
    return {'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}

def list_avatars():
    """List all avatar looks (V3 API - returns digital_twin + stock avatars)."""
    avatars = []
    try:
        resp = requests.get(f'{HEYGEN_BASE}/v3/avatars/looks?avatar_type=digital_twin&ownership=private', headers=get_headers())
        if resp.status_code == 200:
            looks = _extract_looks(resp.json())
            avatars.extend(looks)
    except Exception:
        pass
    try:
        resp2 = requests.get(f'{HEYGEN_BASE}/v2/avatars', headers=get_headers())
        if resp2.status_code == 200:
            avatars.extend(resp2.json().get('data', {}).get('avatars', []))
    except Exception:
        pass
    return avatars

def _extract_looks(json_resp):
    """Handle both list and dict response formats from HeyGen /v3/avatars/looks."""
    raw = json_resp.get('data', [])
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        looks = raw.get('looks', [])
        if isinstance(looks, list):
            return looks
        for key in ('list', 'items', 'avatars'):
            if key in raw and isinstance(raw[key], list):
                return raw[key]
    return []

def list_voices():
    resp = requests.get(f'{HEYGEN_BASE}/v2/voices', headers=get_headers())
    resp.raise_for_status()
    return resp.json().get('data', {}).get('voices', [])

def get_look_id_for_avatar(avatar_group_id):
    """Given avatar group ID, return first available look ID."""
    try:
        resp = requests.get(
            f'{HEYGEN_BASE}/v3/avatars/looks?avatar_type=digital_twin&ownership=private',
            headers=get_headers()
        )
        if resp.status_code != 200:
            return avatar_group_id
        looks = _extract_looks(resp.json())
        print(f'HeyGen looks: {len(looks)} looks found')
        for look in looks:
            if isinstance(look, dict):
                if look.get('avatar_group_id') == avatar_group_id:
                    return look.get('id', avatar_group_id)
                if look.get('id') == avatar_group_id:
                    return avatar_group_id
        prefix = avatar_group_id[:8]
        for look in looks:
            if isinstance(look, dict) and look.get('id', '').startswith(prefix):
                return look.get('id', avatar_group_id)
        if looks and isinstance(looks[0], dict):
            return looks[0].get('id', avatar_group_id)
    except Exception as e:
        print(f'get_look_id error: {e}')
    return avatar_group_id

def create_multiscene_avatar_video(avatar_id, voice_id, script_data, ext_photo_url=None, int_photo_url=None, lot_bg_url=None, width=1080, height=1920):
    """Create video using HeyGen V3 API. Returns video_id."""
    exterior_script = script_data.get('exterior_script', '')
    interior_script = script_data.get('interior_script', '')
    full_script = script_data.get('full_script', '')
    look_id = get_look_id_for_avatar(avatar_id)
    print(f'Using look_id: {look_id} for avatar_group: {avatar_id}')
    script_to_use = full_script
    if exterior_script and interior_script:
        script_to_use = exterior_script + ' ' + interior_script
    bg_url = ext_photo_url or lot_bg_url
    payload = {
        'type': 'avatar',
        'avatar_id': look_id,
        'script': script_to_use,
        'voice_id': voice_id,
        'resolution': '1080p',
        'aspect_ratio': '9:16',
    }
    if bg_url:
        payload['background'] = {'type': 'image', 'url': bg_url}
    resp = requests.post(f'{HEYGEN_BASE}/v3/videos', headers=get_headers(), json=payload)
    print(f'HeyGen V3 create response {resp.status_code}: {resp.text[:500]}')
    if resp.status_code != 200:
        raise Exception(f'HeyGen V3 video creation failed: {resp.status_code} - {resp.text[:500]}')
    resp_json = resp.json()
    data = resp_json.get('data', {})
    if isinstance(data, dict):
        video_id = data.get('video_id') or data.get('id')
        if video_id:
            return video_id
    raise ValueError(f'Unexpected HeyGen V3 response (no video_id): {resp_json}')

def create_avatar_video(avatar_id, voice_id, script_text, background_url=None, width=1080, height=1920):
    """Single-scene video creation using V3 API."""
    look_id = get_look_id_for_avatar(avatar_id)
    payload = {
        'type': 'avatar',
        'avatar_id': look_id,
        'script': script_text,
        'voice_id': voice_id,
        'resolution': '1080p',
        'aspect_ratio': '9:16',
    }
    if background_url:
        payload['background'] = {'type': 'image', 'url': background_url}
    resp = requests.post(f'{HEYGEN_BASE}/v3/videos', headers=get_headers(), json=payload)
    resp.raise_for_status()
    data = resp.json().get('data', {})
    return data.get('video_id') or data.get('id')

def poll_video_status(video_id, timeout_seconds=720):
    """Poll V3 API for video completion."""
    start = time.time()
    while time.time() - start < timeout_seconds:
        resp = requests.get(f'{HEYGEN_BASE}/v3/videos/{video_id}', headers=get_headers())
        resp.raise_for_status()
        resp_json = resp.json()
        data = resp_json.get('data', {})
        if isinstance(data, list):
            print(f'HeyGen V3 poll unexpected list: {resp_json}')
            time.sleep(12)
            continue
        status = data.get('status', '')
        print(f'HeyGen V3 status: {status}')
        if status == 'completed':
            video_url = data.get('video_url')
            if not video_url:
                raise ValueError('HeyGen completed but no video_url returned')
            return {'status': 'completed', 'video_url': video_url, 'duration': data.get('duration')}
        elif status in ('failed', 'error'):
            failure_msg = data.get('failure_message', data.get('error', 'Unknown error'))
            raise Exception(f'HeyGen generation failed: {failure_msg}')
        time.sleep(12)
    raise TimeoutError(f'HeyGen timed out after {timeout_seconds}s')

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
