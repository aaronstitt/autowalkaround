import os, requests, time, json

HEADERS = {'User-Agent': 'Mozilla/5.0'}
HEYGEN_BASE = 'https://api.heygen.com'
HEYGEN_POLL_INTERVAL = 15
HEYGEN_POLL_MAX = 300

def heygen_headers():
    return {'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}

def get_look_id(avatar_group_id):
    try:
        url = HEYGEN_BASE + '/v3/avatars/looks?ownership=private&group_id=' + avatar_group_id
        r = requests.get(url, headers=heygen_headers(), timeout=30)
        if r.status_code == 200:
            data = r.json().get('data', [])
            looks = data if isinstance(data, list) else data.get('looks', [])
            preferred_keywords = ['sharp', 'car', 'lot', 'outdoor', 'salesman', 'used']
            for look in looks:
                name = (look.get('name') or look.get('look_name') or '').lower()
                if any(kw in name for kw in preferred_keywords):
                    return look.get('id') or look.get('look_id')
            if looks:
                return looks[0].get('id') or looks[0].get('look_id')
    except Exception as e:
        print(f'[get_look_id] error: {e}')
    return None

def get_avatar_source_video_url(avatar_group_id):
    """Attempt to retrieve source training video URL from HeyGen API."""
    try:
        url = HEYGEN_BASE + '/v3/avatars/looks?ownership=private&group_id=' + avatar_group_id
        r = requests.get(url, headers=heygen_headers(), timeout=30)
        if r.status_code == 200:
            data = r.json()
            looks = data.get('data', [])
            if isinstance(looks, dict):
                looks = looks.get('looks', [])
            for look in looks:
                for key in ['source_video_url', 'video_url', 'source_url', 'original_url', 'training_video_url']:
                    if look.get(key):
                        return look[key]
    except Exception as e:
        print(f'[Avatar] get_source error: {e}')
    return None

def generate_tts_audio(script_text, voice_id, tmpdir):
    """Generate TTS audio using HeyGen /v3/voices/speech endpoint."""
    print('[TTS] Generating audio with /v3/voices/speech...')
    payload = {
        'text': script_text,
        'voice_id': voice_id,
        'speed': 1.0,
        'input_type': 'text',
        'language': 'en'
    }
    r = requests.post(HEYGEN_BASE + '/v3/voices/speech', headers=heygen_headers(), json=payload, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f'TTS failed: {r.status_code} {r.text[:300]}')

    resp_data = r.json().get('data', {})
    audio_url = resp_data.get('audio_url')
    if not audio_url:
        raise RuntimeError(f'TTS no audio_url in response: {r.text[:300]}')

    audio_path = os.path.join(tmpdir, 'script_audio.mp3')
    _download_file(audio_url, audio_path)
    print(f'[TTS] Downloaded: {audio_path} ({os.path.getsize(audio_path)} bytes)')
    return audio_path, audio_url

def upload_audio_to_heygen(audio_path):
    """Upload audio to HeyGen assets, returns asset_id."""
    print('[Upload] Uploading audio asset...')
    try:
        with open(audio_path, 'rb') as f:
            r = requests.post(
                HEYGEN_BASE + '/v1/asset',
                headers={'x-api-key': os.getenv('HEYGEN_API_KEY')},
                files={'file': ('audio.mp3', f, 'audio/mpeg')},
                timeout=120
            )
        if r.status_code == 200:
            asset_id = r.json().get('data', {}).get('id') or r.json().get('data', {}).get('asset_id')
            print(f'[Upload] Asset ID: {asset_id}')
            return asset_id
        else:
            print(f'[Upload] Failed: {r.status_code} {r.text[:200]}')
    except Exception as e:
        print(f'[Upload] Error: {e}')
    return None

def generate_heygen_audio(script_text, avatar_look_id, voice_id, tmpdir):
    audio_path, audio_url = generate_tts_audio(script_text, voice_id, tmpdir)
    return audio_path, {'audio_path': audio_path, 'audio_url': audio_url, 'look_id': avatar_look_id}

def run_video_translation(source_video_url, audio_url, audio_asset_id, tmpdir):
    """Submit HeyGen Video Translation job: replace audio + re-sync lips.
    HeyGen returns 202 Accepted with translation IDs on success."""
    print(f'[VideoTranslation] source: {source_video_url[:80]}...')

    payload = {
        'video': {'type': 'url', 'url': source_video_url},
        'output_languages': ['English'],
        'title': 'AutoWalkaround Vehicle Video',
        'mode': 'precision',
        'translate_audio_only': False,
        'enable_dynamic_duration': True,
        'disable_music_track': True,
        'enable_speech_enhancement': True,
        'speaker_num': 1,
    }

    if audio_asset_id:
        payload['audio'] = {'type': 'asset_id', 'asset_id': audio_asset_id}
    elif audio_url:
        payload['audio'] = {'type': 'url', 'url': audio_url}

    r = requests.post(HEYGEN_BASE + '/v3/video-translations', headers=heygen_headers(), json=payload, timeout=60)
    print(f'[VideoTranslation] Create: {r.status_code} {r.text[:300]}')

    # HeyGen returns 202 Accepted on success for Video Translation
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f'VideoTranslation failed: {r.status_code} {r.text[:300]}')

    resp_data = r.json()
    # Handle various response formats
    data = resp_data.get('data') or resp_data.get('Data') or resp_data
    if isinstance(data, dict):
        translation_ids = (data.get('video_translation_ids') or 
                          data.get('Video_translation_ids') or
                          data.get('translation_ids') or [])
    else:
        translation_ids = []

    if not translation_ids:
        raise RuntimeError(f'No translation IDs in response: {r.text[:300]}')

    translation_id = translation_ids[0]
    print(f'[VideoTranslation] ID: {translation_id} - polling...')

    for i in range(HEYGEN_POLL_MAX):
        time.sleep(HEYGEN_POLL_INTERVAL)
        try:
            sr = requests.get(HEYGEN_BASE + '/v3/video-translations/' + translation_id,
                            headers=heygen_headers(), timeout=30)
            print(f'[VideoTranslation] Poll {i+1}: HTTP {sr.status_code} {sr.text[:100]}')
            if sr.status_code == 200:
                vdata = sr.json().get('data', {})
                status = vdata.get('status', 'unknown')
                print(f'[VideoTranslation] Poll {i+1}: status={status}')
                if status in ('completed', 'success', 'done'):
                    video_url = (vdata.get('video_url') or vdata.get('output_video_url') or 
                                vdata.get('output_url'))
                    if not video_url:
                        raise RuntimeError(f'No video_url in completed response: {json.dumps(vdata)[:300]}')
                    out_path = os.path.join(tmpdir, 'translated_final.mp4')
                    _download_file(video_url, out_path)
                    print(f'[VideoTranslation] Downloaded: {out_path}')
                    return out_path
                elif status in ('failed', 'error'):
                    raise RuntimeError(f'Translation failed: {vdata.get("error_message", json.dumps(vdata)[:300])}')
            else:
                print(f'[VideoTranslation] Poll {i+1} HTTP error: {sr.status_code}')
        except RuntimeError:
            raise
        except Exception as e:
            print(f'[VideoTranslation] Poll {i+1} error: {e}')

    raise RuntimeError('VideoTranslation timed out after 75 minutes')

def _download_file(url, dest_path):
    r = requests.get(url, headers=HEADERS, stream=True, timeout=300)
    r.raise_for_status()
    with open(dest_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
    print(f'[Download] {dest_path} ({os.path.getsize(dest_path)} bytes)')

def build_walkaround_video(vehicle, script_segments, heygen_audio_path,
                            heygen_result, vehicle_photos, vehicle_video_url, tmpdir):
    source_video_url = heygen_result.get('source_video_url') if isinstance(heygen_result, dict) else None
    audio_url = heygen_result.get('audio_url') if isinstance(heygen_result, dict) else None
    audio_asset_id = heygen_result.get('audio_asset_id') if isinstance(heygen_result, dict) else None

    if not source_video_url:
        raise RuntimeError(
            'source_video_url not set for this salesperson. '
            'Please add it via Settings page or POST /admin/set-source-video'
        )

    return run_video_translation(source_video_url, audio_url, audio_asset_id, tmpdir)
