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
        """Use vehicle photo as background, or transparent if none provided."""
        if background_url:
                    return {'type': 'image', 'url': background_url}
                # Use a clean dark background - the video_assembler will add vehicle photos behind the avatar
                return {'type': 'color', 'value': '#1a1a1a'}

def _build_character(avatar_id, avatar_style='normal'):
        """Build character config. Use 'normal' for full-body, 'closeup' for waist-up POV feel."""
    return {
                'type': 'avatar',
                'avatar_id': avatar_id,
                'avatar_style': avatar_style,  # 'normal' or 'closeup'
                'matting': True  # Request background removal when available
    }

def create_avatar_video(avatar_id, voice_id, script_text, background_url=None, width=1080, height=1920):
        """
            Single-scene video: full script, one background.
                Used as fallback or when multi-scene is not needed.
                    Width/height: 1080x1920 for 9:16 mobile portrait format.
                        """
    payload = {
                'video_inputs': [{
                                'character': _build_character(avatar_id, 'normal'),
                                'voice': {
                                                    'type': 'text',
                                                    'input_text': script_text,
                                                    'voice_id': voice_id,
                                                    'speed': 0.95
                                },
                                'background': _build_background(background_url)
                }],
                'dimension': {'width': width, 'height': height},
                'test': False
    }
    resp = requests.post(f'{HEYGEN_BASE}/v2/video/generate', headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()['data']['video_id']

def create_multiscene_avatar_video(
        avatar_id, voice_id, script_data,
        ext_photo_url=None, int_photo_url=None, lot_bg_url=None,
        width=1080, height=1920
):
        """
            Multi-scene video:
                - Scene 1: exterior script segments + exterior vehicle photo as background
                    - Scene 2: interior script segments + interior vehicle photo as background

                        Background strategy:
                            - If we have actual vehicle photos, use them as HeyGen backgrounds.
                                  The video_assembler will ALSO add the vehicle photos as the full bg behind the avatar.
                                      - If no vehicle photos, use the lot background or a neutral color.
                                          - Avatar style: 'normal' (full body) so the avatar appears as a person in front of the scene.

                                              The video_assembler composites this output over the animated vehicle photo slideshow,
                                                  so the HeyGen background here acts as a secondary blending layer.
                                                      """
    exterior_script = script_data.get('exterior_script', '')
    interior_script = script_data.get('interior_script', '')
    full_script = script_data.get('full_script', '')

    # If we don't have separate scripts, fall back to single scene
    if not exterior_script or not interior_script:
                bg = ext_photo_url or lot_bg_url
                return create_avatar_video(avatar_id, voice_id, full_script, bg, width, height)

    video_inputs = []

    # Scene 1: Exterior
    # Use first exterior vehicle photo, or lot background
    ext_bg_url = ext_photo_url or lot_bg_url
    video_inputs.append({
                'character': _build_character(avatar_id, 'normal'),
                'voice': {
                                'type': 'text',
                                'input_text': exterior_script,
                                'voice_id': voice_id,
                                'speed': 0.95
                },
                'background': _build_background(ext_bg_url)
    })

    # Scene 2: Interior
    # Use an interior vehicle photo, or lot background
    int_bg_url = int_photo_url or lot_bg_url
    video_inputs.append({
                'character': _build_character(avatar_id, 'normal'),
                'voice': {
                                'type': 'text',
                                'input_text': interior_script,
                                'voice_id': voice_id,
                                'speed': 0.95
                },
                'background': _build_background(int_bg_url)
    })

    payload = {
                'video_inputs': video_inputs,
                'dimension': {'width': width, 'height': height},
                'test': False
    }
    resp = requests.post(f'{HEYGEN_BASE}/v2/video/generate', headers=get_headers(), json=payload)
    resp.raise_for_status()
    data = resp.json()
    if 'data' not in data or 'video_id' not in data.get('data', {}):
                raise ValueError(f'Unexpected HeyGen response: {data}')
            return data['data']['video_id']

def poll_video_status(video_id, timeout_seconds=720):
        """Poll until HeyGen video is completed or failed."""
    start = time.time()
    while time.time() - start < timeout_seconds:
                resp = requests.get(
                                f'{HEYGEN_BASE}/v1/video_status.get?video_id={video_id}',
                                headers=get_headers()
                )
                resp.raise_for_status()
                data = resp.json().get('data', {})
                status = data.get('status', '')
                print(f'HeyGen status: {status}')
                if status == 'completed':
                                video_url = data.get('video_url')
                                if not video_url:
                                                    raise ValueError('HeyGen completed but no video_url returned')
                                                return {
                                    'status': 'completed',
                                    'video_url': video_url,
                                    'duration': data.get('duration')
                                }
elif status in ('failed', 'error'):
            error_msg = data.get('error', data.get('msg', 'Unknown error'))
            raise Exception(f'HeyGen generation failed: {error_msg}')
        time.sleep(12)
    raise TimeoutError(f'HeyGen video timed out after {timeout_seconds}s. video_id={video_id}')

def create_instant_avatar(video_url, avatar_name):
        """Create a HeyGen instant avatar from a video URL."""
    payload = {'video_url': video_url, 'name': avatar_name}
    resp = requests.post(f'{HEYGEN_BASE}/v2/instant_avatar', headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json().get('data', {}).get('avatar_id', '')

def clone_voice(audio_url, voice_name):
        """Clone a voice from an audio URL."""
    payload = {'audio_url': audio_url, 'name': voice_name}
    resp = requests.post(f'{HEYGEN_BASE}/v2/voice_clone', headers=get_headers(), json=payload)
    resp.raise_for_status()
    return resp.json().get('data', {}).get('voice_id', '')

def get_avatar_info(avatar_id):
        """Get details about a specific avatar."""
    try:
                avatars = list_avatars()
                for a in avatars:
                                if a.get('avatar_id') == avatar_id:
                                                    return a
                                            return None
except Exception:
        return None
