import os, requests, time, json

HEADERS = {'User-Agent': 'Mozilla/5.0'}
HEYGEN_BASE = 'https://api.heygen.com'
HEYGEN_POLL_INTERVAL = 15
HEYGEN_POLL_MAX = 300  # 75 minutes max

def heygen_headers():
    return {'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}

def get_look_id(avatar_group_id):
    """Get best look ID from avatar group - used as fallback only."""
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
    """
    Retrieve the source training video URL for an avatar group.
    This is the original walkaround video the salesperson recorded.
    """
    try:
        # Try v3 looks API with full details
        url = HEYGEN_BASE + '/v3/avatars/looks?ownership=private&group_id=' + avatar_group_id
        r = requests.get(url, headers=heygen_headers(), timeout=30)
        print(f'[Avatar] looks API: {r.status_code}')
        if r.status_code == 200:
            data = r.json()
            print(f'[Avatar] looks data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}')
            looks = data.get('data', [])
            if isinstance(looks, dict):
                looks = looks.get('looks', [])
            print(f'[Avatar] found {len(looks)} looks')
            for look in looks:
                print(f'[Avatar] look keys: {list(look.keys())}')
                # Check for source_video, video_url, source_url, original_video_url etc
                for key in ['source_video_url', 'video_url', 'source_url', 'original_url', 'training_video_url', 'raw_video_url']:
                    if look.get(key):
                        print(f'[Avatar] Found source video at key={key}: {look[key][:80]}')
                        return look[key]
    except Exception as e:
        print(f'[Avatar] get_source error: {e}')

    # Try avatar group detail endpoint
    try:
        r2 = requests.get(HEYGEN_BASE + '/v2/avatar_group/' + avatar_group_id, headers=heygen_headers(), timeout=30)
        print(f'[Avatar] group detail: {r2.status_code} {r2.text[:200]}')
    except Exception as e:
        print(f'[Avatar] group detail error: {e}')

    return None

def generate_tts_audio(script_text, voice_id, tmpdir):
    """Generate TTS audio from script using HeyGen TTS API."""
    print('[TTS] Generating audio...')
    payload = {
        'text': script_text,
        'voice_id': voice_id,
        'speed': 1.0
    }
    r = requests.post(HEYGEN_BASE + '/v1/text_to_speech', headers=heygen_headers(), json=payload, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f'TTS failed: {r.status_code} {r.text[:200]}')
    
    audio_url = r.json().get('data', {}).get('audio_url')
    if not audio_url:
        raise RuntimeError(f'TTS no audio_url: {r.text[:200]}')
    
    audio_path = os.path.join(tmpdir, 'script_audio.mp3')
    _download_file(audio_url, audio_path)
    print(f'[TTS] Downloaded audio: {audio_path}')
    return audio_path, audio_url

def upload_audio_to_heygen(audio_path):
    """Upload audio file to HeyGen assets and return asset_id."""
    print('[Upload] Uploading audio to HeyGen...')
    with open(audio_path, 'rb') as f:
        r = requests.post(
            HEYGEN_BASE + '/v1/asset',
            headers={'x-api-key': os.getenv('HEYGEN_API_KEY')},
            files={'file': ('audio.mp3', f, 'audio/mpeg')},
            timeout=120
        )
    if r.status_code != 200:
        raise RuntimeError(f'Asset upload failed: {r.status_code} {r.text[:200]}')
    asset_id = r.json().get('data', {}).get('id') or r.json().get('data', {}).get('asset_id')
    print(f'[Upload] Asset ID: {asset_id}')
    return asset_id

def generate_heygen_audio(script_text, avatar_look_id, voice_id, tmpdir):
    """
    Main generation function.
    Returns (audio_path, result) where result contains source video info.
    """
    # Generate TTS audio of the new script
    audio_path, audio_url = generate_tts_audio(script_text, voice_id, tmpdir)
    return audio_path, {'audio_path': audio_path, 'audio_url': audio_url, 'look_id': avatar_look_id}

def run_video_translation(source_video_url, audio_url, audio_asset_id, tmpdir):
    """
    Use HeyGen Video Translation API to replace audio in source video with lip sync.
    source_video_url: URL of Aaron's original walkaround recording
    audio_url: URL of the new TTS audio with the vehicle script
    """
    print(f'[VideoTranslation] Starting with source: {source_video_url[:80]}...')
    print(f'[VideoTranslation] Audio: {(audio_url or audio_asset_id or "")[:80]}')

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

    # Add audio track
    if audio_asset_id:
        payload['audio'] = {'type': 'asset_id', 'asset_id': audio_asset_id}
    elif audio_url:
        payload['audio'] = {'type': 'url', 'url': audio_url}

    r = requests.post(HEYGEN_BASE + '/v3/video-translations', headers=heygen_headers(), json=payload, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f'VideoTranslation failed: {r.status_code} {r.text[:300]}')

    translation_ids = r.json().get('data', {}).get('video_translation_ids', [])
    if not translation_ids:
        raise RuntimeError(f'No translation IDs returned: {r.text[:200]}')
    
    translation_id = translation_ids[0]
    print(f'[VideoTranslation] ID: {translation_id} - polling...')

    # Poll for completion
    for i in range(HEYGEN_POLL_MAX):
        time.sleep(HEYGEN_POLL_INTERVAL)
        try:
            sr = requests.get(
                HEYGEN_BASE + '/v3/video-translations/' + translation_id,
                headers=heygen_headers(), timeout=30
            )
            vdata = sr.json().get('data', {})
            status = vdata.get('status', 'unknown')
            print(f'[VideoTranslation] Poll {i+1}: {status}')
            if status in ('completed', 'success'):
                video_url = vdata.get('video_url') or vdata.get('output_video_url')
                if not video_url:
                    raise RuntimeError(f'Completed but no video_url: {json.dumps(vdata)[:200]}')
                out_path = os.path.join(tmpdir, 'translated_final.mp4')
                _download_file(video_url, out_path)
                print(f'[VideoTranslation] Downloaded: {out_path}')
                return out_path
            elif status in ('failed', 'error'):
                raise RuntimeError(f'Translation failed: {vdata.get("error_message", json.dumps(vdata)[:200])}')
        except RuntimeError:
            raise
        except Exception as e:
            print(f'[VideoTranslation] Poll {i+1} error: {e}')

    raise RuntimeError('VideoTranslation timed out')

def _download_file(url, dest_path):
    r = requests.get(url, headers=HEADERS, stream=True, timeout=300)
    r.raise_for_status()
    with open(dest_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
    print(f'[Download] {dest_path} ({os.path.getsize(dest_path)} bytes)')

def build_walkaround_video(vehicle, script_segments, heygen_audio_path,
                           heygen_result, vehicle_photos, vehicle_video_url, tmpdir):
    """
    Build final walkaround video using Video Translation:
    - source = Aaron's original walkaround recording (stored in salespersons.source_video_url)
    - audio = new TTS of the vehicle script
    - HeyGen replaces audio and re-syncs lips to new script
    """
    source_video_url = heygen_result.get('source_video_url') if isinstance(heygen_result, dict) else None
    audio_url = heygen_result.get('audio_url') if isinstance(heygen_result, dict) else None
    audio_asset_id = heygen_result.get('audio_asset_id') if isinstance(heygen_result, dict) else None

    if not source_video_url:
        raise RuntimeError(
            'No source_video_url found. Please add your walkaround video URL to the salesperson profile '
            'in Supabase (salespersons.source_video_url column) via the dashboard /admin/salespersons endpoint.'
        )

    final_path = run_video_translation(source_video_url, audio_url, audio_asset_id, tmpdir)
    return final_path
