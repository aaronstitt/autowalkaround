import requests
import os
import time

HEYGEN_BASE = 'https://api.heygen.com'

def get_headers():
        return {'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}

def list_avatars():
        """List all avatar looks (V3 API - returns digital_twin + stock avatars)."""
        avatars = []
        # Get digital twin looks (private custom avatars)
        try:
                    resp = requests.get(f'{HEYGEN_BASE}/v3/avatars/looks?avatar_type=digital_twin&ownership=private', headers=get_headers())
                    if resp.status_code == 200:
                                    looks = _extract_looks(resp.json())
                                    avatars.extend(looks)
        except Exception:
                    pass
                # Also get stock avatars for reference
                try:
                            resp2 = requests.get(f'{HEYGEN_BASE}/v2/avatars', headers=get_headers())
                            if resp2.status_code == 200:
                                            avatars.extend(resp2.json().get('data', {}).get('avatars', []))
                except Exception:
                            pass
                        return avatars

def _extract_looks(json_resp):
        """
            HeyGen /v3/avatars/looks can return data in two formats:
                  Format A: {'data': {'looks': [...]}}
                        Format B: {'data': [...]}  (data is directly a list)
                            Handle both gracefully.
                                """
    raw = json_resp.get('data', [])
    if isinstance(raw, list):
                return raw
            if isinstance(raw, dict):
                        looks = raw.get('looks', [])
                        if isinstance(looks, list):
                                        return looks
                                    # Some responses may nest differently
                                    for key in ('list', 'items', 'avatars'):
                                                    if key in raw and isinstance(raw[key], list):
                                                                        return raw[key]
                                                            return []

def list_voices():
        resp = requests.get(f'{HEYGEN_BASE}/v2/voices', headers=get_headers())
    resp.raise_for_status()
    return resp.json().get('data', {}).get('voices', [])

def get_look_id_for_avatar(avatar_group_id: str) -> str:
        """
            Given an avatar group ID (from the HeyGen web app URL),
                return the first available look ID for that avatar.
                    The look ID is what the V3 API actually requires for video generation.
                        """
    resp = requests.get(
                f'{HEYGEN_BASE}/v3/avatars/looks?avatar_type=digital_twin&ownership=private',
                headers=get_headers()
    )
    if resp.status_code != 200:
                # Fall back to using the group ID directly
                return avatar_group_id

    looks = _extract_looks(resp.json())
    print(f'HeyGen looks response: {resp.json()}')
    print(f'Extracted {len(looks)} looks')

    # Match by avatar_group_id field or by ID prefix
    for look in looks:
                if isinstance(look, dict):
                                if look.get('avatar_group_id') == avatar_group_id:
                                                    return look.get('id', avatar_group_id)
            # Some APIs return the group ID as the look ID for single-look avatars
            if look.get('id') == avatar_group_id:
                                return avatar_group_id

    # If no match found by group ID, check if any look's ID contains the group ID prefix
    prefix = avatar_group_id[:8]
    for look in looks:
                if isinstance(look, dict) and look.get('id', '').startswith(prefix):
                                return look.get('id', avatar_group_id)

    # Return the first look ID as fallback if we have any looks
    if looks and isinstance(looks[0], dict):
                return looks[0].get('id', avatar_group_id)

    return avatar_group_id

def create_multiscene_avatar_video(avatar_id, voice_id, script_data, ext_photo_url=None, int_photo_url=None, lot_bg_url=None, width=1080, height=1920):
        """
            Create a multi-scene video using HeyGen V3 API.
                Uses Digital Twin format with background images.
                    Returns the video_id for polling.
                        """
    exterior_script = script_data.get('exterior_script', '')
    interior_script = script_data.get('interior_script', '')
    full_script = script_data.get('full_script', '')

    # Get the actual look ID from the avatar group ID
    look_id = get_look_id_for_avatar(avatar_id)
    print(f'Using look_id: {look_id} for avatar_group: {avatar_id}')

    # V3 API only supports single-segment videos per request
    # Use full script if we can't split, otherwise use exterior first
    script_to_use = full_script
    if exterior_script and interior_script:
                # Combine into one script with natural transition
                script_to_use = exterior_script + ' ' + interior_script

    # Build background config
    bg_url = ext_photo_url or lot_bg_url
    background = None
    if bg_url:
                background = {'type': 'image', 'url': bg_url}

    # V3 payload
    payload = {
                'type': 'avatar',
                'avatar_id': look_id,
                'script': script_to_use,
                'voice_id': voice_id,
                'resolution': '1080p',
                'aspect_ratio': '9:16',
    }

    if background:
                payload['background'] = background

    resp = requests.post(f'{HEYGEN_BASE}/v3/videos', headers=get_headers(), json=payload)
    print(f'HeyGen V3 create response {resp.status_code}: {resp.text[:500]}')

    if resp.status_code != 200:
                raise Exception(f'HeyGen V3 video creation failed: {resp.status_code} - {resp.text[:500]}')

    resp_json = resp.json()
    # Handle both {'data': {'video_id': '...'}} and {'data': {'id': '...'}} formats
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
                        # Unexpected format - log and wait
                        print(f'HeyGen V3 poll unexpected list response: {resp_json}')
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
