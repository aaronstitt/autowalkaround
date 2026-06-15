import requests
import os
import time

HEYGEN_BASE = 'https://api.heygen.com'

def get_headers():
    return {'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}

def list_avatars():
    avatars = []
    try:
        resp = requests.get(f'{HEYGEN_BASE}/v3/avatars/looks?ownership=private', headers=get_headers())
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
    try:
        resp = requests.get(
            f'{HEYGEN_BASE}/v3/avatars/looks?group_id={avatar_group_id}',
            headers=get_headers()
        )
        print(f'HeyGen looks by group_id {resp.status_code}: {resp.text[:300]}')
        if resp.status_code == 200:
            looks = _extract_looks(resp.json())
            print(f'HeyGen looks by group_id: {len(looks)} looks found')
            if looks and isinstance(looks[0], dict):
                look_id = looks[0].get('id')
                if look_id:
                    return look_id
    except Exception as e:
        print(f'get_look_id group_id error: {e}')
    try:
        resp2 = requests.get(
            f'{HEYGEN_BASE}/v3/avatars/looks?ownership=private',
            headers=get_headers()
        )
        if resp2.status_code == 200:
            looks2 = _extract_looks(resp2.json())
            print(f'HeyGen all private looks: {len(looks2)} found')
            for look in looks2:
                if isinstance(look, dict):
                    gid = look.get('group_id', '')
                    lid = look.get('id', '')
                    if gid == avatar_group_id or lid == avatar_group_id:
                        return lid or avatar_group_id
            if looks2 and isinstance(looks2[0], dict):
                first_id = looks2[0].get('id')
                if first_id:
                    return first_id
    except Exception as e2:
        print(f'get_look_id fallback error: {e2}')
    return avatar_group_id

def _rehost_background_image(url):
    '''Download image from any URL and re-upload to Supabase storage so HeyGen can access it.'''
    try:
        import hashlib
        if 'supabase.co' in url and '/public/' in url:
            return url
        supabase_url = os.getenv('SUPABASE_URL', '')
        service_key = os.getenv('SUPABASE_SERVICE_KEY', '')
        if not supabase_url or not service_key:
            print('No SUPABASE_SERVICE_KEY env var - cannot rehost background')
            return None
        resp = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
        if resp.status_code != 200:
            print(f'Background image fetch failed: {resp.status_code}')
            return None
        img_data = resp.content
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        storage_path = f'backgrounds/lot_bg_{url_hash}.jpg'
        upload_resp = requests.post(
            f'{supabase_url}/storage/v1/object/videos/{storage_path}',
            headers={
                'Authorization': f'Bearer {service_key}',
                'Content-Type': 'image/jpeg',
                'x-upsert': 'true'
            },
            data=img_data,
            timeout=30
        )
        if upload_resp.status_code in (200, 201, 409):
            public_url = f'{supabase_url}/storage/v1/object/public/videos/{storage_path}'
            print(f'Background re-hosted at: {public_url}')
            return public_url
        else:
            print(f'Background rehost upload failed: {upload_resp.status_code}: {upload_resp.text[:100]}')
            return None
    except Exception as e:
        print(f'_rehost_background_image error: {e}')
        return None

def create_multiscene_avatar_video(avatar_id, voice_id, script_data, ext_photo_url=None, int_photo_url=None, lot_bg_url=None, width=720, height=1280):
    '''
    Create HeyGen transparent WebM video of Aaron talking.
    output_format=webm gives us a transparent (alpha channel) video so we can
    composite Aaron directly onto vehicle photo backgrounds in FFmpeg.
    '''
    exterior_script = script_data.get('exterior_script', '')
    interior_script = script_data.get('interior_script', '')
    full_script = script_data.get('full_script', '')
    look_id = get_look_id_for_avatar(avatar_id)
    print(f'Using look_id: {look_id} for avatar_group: {avatar_id}')

    script_to_use = full_script
    if exterior_script and interior_script:
        script_to_use = exterior_script + ' ' + interior_script

    # Use WebM output for transparent alpha channel compositing
    # This lets us overlay Aaron on vehicle photos in FFmpeg
    payload = {
        'type': 'avatar',
        'avatar_id': look_id,
        'script': script_to_use,
        'voice_id': voice_id,
        'resolution': '720p',
        'aspect_ratio': '9:16',
        'output_format': 'mp4',
    }

    print('Creating HeyGen MP4 for vstack walkaround compositing...')
    resp = requests.post(f'{HEYGEN_BASE}/v3/videos', headers=get_headers(), json=payload)
    print(f'HeyGen V3 create response {resp.status_code}: {resp.text[:500]}')

    if resp.status_code != 200:
        raise RuntimeError(f'HeyGen create failed: {resp.status_code}: {resp.text[:300]}')

    data = resp.json().get('data', {})
    video_id = data.get('video_id')
    if not video_id:
        raise RuntimeError(f'No video_id in HeyGen response: {resp.text[:300]}')
    return video_id

def create_avatar_video(avatar_id, voice_id, script, background_url=None):
    return create_multiscene_avatar_video(
        avatar_id, voice_id,
        {'full_script': script},
        lot_bg_url=background_url
    )

def poll_video_status(video_id, timeout=600, interval=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f'{HEYGEN_BASE}/v3/videos/{video_id}', headers=get_headers())
            if resp.status_code == 200:
                data = resp.json().get('data', {})
                status = data.get('status', 'unknown')
                print(f'HeyGen video {video_id} status: {status}')
                if status == 'completed':
                    video_url = data.get('video_url') or data.get('url')
                    return {'status': 'completed', 'video_url': video_url}
                elif status == 'failed':
                    return {'status': 'failed', 'error': data.get('error', 'unknown')}
            else:
                print(f'HeyGen poll {resp.status_code}: {resp.text[:200]}')
        except Exception as e:
            print(f'HeyGen poll error: {e}')
        time.sleep(interval)
    return {'status': 'failed', 'error': 'timeout'}

def create_instant_avatar(name, video_url):
    payload = {'name': name, 'video_url': video_url}
    resp = requests.post(f'{HEYGEN_BASE}/v2/instant_avatar', headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()

def clone_voice(name, audio_url):
    payload = {'name': name, 'audio_url': audio_url}
    resp = requests.post(f'{HEYGEN_BASE}/v2/voice_clone', headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()
