import requests
import os
import time

HEYGEN_BASE = 'https://api.heygen.com'

def get_headers():
        return {'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}

def list_avatars():
        """List all avatar looks (V3 API)."""
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
        """
            Given avatar group ID, return first available look ID.
                Uses group_id filter to get looks for this specific avatar group.
                    Falls back to avatar_group_id if no looks found.
                        """
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
                                                                                                                    print(f'Using first available look: {first_id}')
                                                                                                                    return first_id
                                                                            except Exception as e2:
        print(f'get_look_id fallback error: {e2}')

    print(f'Using avatar_group_id as fallback: {avatar_group_id}')
    return avatar_group_id

def create_multiscene_avatar_video(avatar_id, voice_id, script_data, ext_photo_url=None, int_photo_url=None, lot_bg_url=None, width=720, height=1280):
        """
            Create HeyGen video with TRANSPARENT background (webm output_format).
                The avatar's background is removed by HeyGen AI so we can composite
                    Aaron directly onto the vehicle photos in FFmpeg - making him look
                        like he's physically standing next to the real car.
                            """
    exterior_script = script_data.get('exterior_script', '')
    interior_script = script_data.get('interior_script', '')
    full_script = script_data.get('full_script', '')
    look_id = get_look_id_for_avatar(avatar_id)
    print(f'Using look_id: {look_id} for avatar_group: {avatar_id}')

    script_to_use = full_script
    if exterior_script and interior_script:
                script_to_use = exterior_script + ' ' + interior_script

    # Request webm with transparent background so Aaron can be composited
    # directly onto vehicle photos. HeyGen removes the studio backdrop entirely.
    payload = {
                'type': 'avatar',
                'avatar_id': look_id,
                'script': script_to_use,
                'voice_id': voice_id,
                'resolution': '720p',
                'aspect_ratio': '9:16',
                'output_format': 'webm',  # transparent alpha channel - background removed by HeyGen
    }

    print(f'Creating HeyGen transparent webm (background removed by HeyGen AI)...')
    resp = requests.post(f'{HEYGEN_BASE}/v3/videos', headers=get_headers(), json=payload)
    print(f'HeyGen V3 create response {resp.status_code}: {resp.text[:500]}')

    if resp.status_code != 200:
                # Fallback: try mp4 with remove_background flag
                print('Webm failed, trying mp4 + remove_background...')
        payload_fallback = {
                        'type': 'avatar',
                        'avatar_id': look_id,
                        'script': script_to_use,
                        'voice_id': voice_id,
                        'resolution': '720p',
                        'aspect_ratio': '9:16',
                        'remove_background': True,
                        'output_format': 'mp4',
        }
        resp = requests.post(f'{HEYGEN_BASE}/v3/videos', headers=get_headers(), json=payload_fallback)
        print(f'HeyGen fallback response {resp.status_code}: {resp.text[:500]}')
        if resp.status_code != 200:
                        raise RuntimeError(f'HeyGen create failed: {resp.status_code}: {resp.text[:300]}')

    data = resp.json().get('data', {})
    video_id = data.get('video_id')
    if not video_id:
                raise RuntimeError(f'No video_id in HeyGen response: {resp.text[:300]}')
    return video_id

def create_avatar_video(avatar_id, voice_id, script, background_url=None):
        """Simple single-scene video creation (legacy helper)."""
    return create_multiscene_avatar_video(
                avatar_id, voice_id,
                {'full_script': script},
                ext_photo_url=background_url
    )

def poll_video_status(video_id, timeout=600, interval=10):
        """Poll HeyGen V3 video status until completed or failed."""
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
                            """Create an instant avatar from a video URL."""
                            payload = {'name': name, 'video_url': video_url}
                            resp = requests.post(f'{HEYGEN_BASE}/v2/instant_avatar', headers=get_headers(), json=payload)
                            resp.raise_for_status()
                            return resp.json()

                    def clone_voice(name, audio_url):
                            """Clone a voice from an audio URL."""
                            payload = {'name': name, 'audio_url': audio_url}
                            resp = requests.post(f'{HEYGEN_BASE}/v2/voice_clone', headers=get_headers(), json=payload)
                            resp.raise_for_status()
                            return resp.json()
