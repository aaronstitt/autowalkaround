import os, requests, time, json, subprocess

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

def get_starfish_voice_id(preferred_voice_id):
    print(f'[TTS] Finding starfish voice, preferred: {preferred_voice_id}')
    try:
        r = requests.get(
            HEYGEN_BASE + '/v3/voices?type=private&engine=starfish&limit=20',
            headers=heygen_headers(), timeout=30
        )
        print(f'[TTS] Private starfish voices: {r.status_code} {r.text[:300]}')
        if r.status_code == 200:
            voices = r.json().get('data', [])
            if voices:
                vid = voices[0].get('voice_id')
                print(f'[TTS] Using private starfish voice: {vid}')
                return vid
    except Exception as e:
        print(f'[TTS] Private voice lookup error: {e}')
    try:
        r = requests.get(
            HEYGEN_BASE + '/v3/voices?type=public&engine=starfish&language=English&gender=male&limit=5',
            headers=heygen_headers(), timeout=30
        )
        print(f'[TTS] Public starfish voices: {r.status_code} {r.text[:300]}')
        if r.status_code == 200:
            voices = r.json().get('data', [])
            if voices:
                vid = voices[0].get('voice_id')
                print(f'[TTS] Using public starfish voice: {vid}')
                return vid
    except Exception as e:
        print(f'[TTS] Public voice lookup error: {e}')
    print(f'[TTS] Falling back to preferred voice: {preferred_voice_id}')
    return preferred_voice_id

def generate_tts_audio(script_text, voice_id, tmpdir):
    print(f'[TTS] Generating audio, script length: {len(script_text)} chars')
    starfish_voice_id = get_starfish_voice_id(voice_id)
    payload = {
        'text': script_text,
        'voice_id': starfish_voice_id,
        'speed': 1.0,
        'input_type': 'text',
        'language': 'en'
    }
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(
                HEYGEN_BASE + '/v3/voices/speech',
                headers=heygen_headers(), json=payload, timeout=180
            )
            print(f'[TTS] Attempt {attempt+1}: {r.status_code} {r.text[:400]}')
            if r.status_code == 200:
                resp_data = r.json().get('data', {})
                audio_url = resp_data.get('audio_url')
                if not audio_url:
                    raise RuntimeError(f'TTS no audio_url: {r.text[:300]}')
                audio_path = os.path.join(tmpdir, 'script_audio.mp3')
                _download_file(audio_url, audio_path)
                print(f'[TTS] Downloaded: {audio_path} ({os.path.getsize(audio_path)} bytes)')
                return audio_path, audio_url
            elif r.status_code in (400, 404, 422):
                # Try with public starfish voice
                pub_r = requests.get(
                    HEYGEN_BASE + '/v3/voices?type=public&engine=starfish&language=English&limit=5',
                    headers=heygen_headers(), timeout=30
                )
                if pub_r.status_code == 200 and pub_r.json().get('data'):
                    payload['voice_id'] = pub_r.json()['data'][0]['voice_id']
                    print(f'[TTS] Retrying with public voice: {payload["voice_id"]}')
                    last_err = RuntimeError(f'TTS failed: {r.status_code} {r.text[:300]}')
                    time.sleep(2)
                    continue
            raise RuntimeError(f'TTS failed: {r.status_code} {r.text[:300]}')
        except RuntimeError as e:
            last_err = e
            if attempt < 2:
                time.sleep(10)
        except Exception as e:
            last_err = e
            print(f'[TTS] Attempt {attempt+1} error: {e}')
            if attempt < 2:
                time.sleep(10)
    raise RuntimeError(f'TTS failed after 3 attempts: {last_err}')

def upload_audio_to_heygen(audio_path):
    print('[Upload] Uploading audio asset...')
    try:
        with open(audio_path, 'rb') as f:
            r = requests.post(
                HEYGEN_BASE + '/v1/asset',
                headers={'x-api-key': os.getenv('HEYGEN_API_KEY')},
                files={'file': ('audio.mp3', f, 'audio/mpeg')},
                timeout=120
            )
        print(f'[Upload] Response: {r.status_code} {r.text[:200]}')
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
    print(f'[VideoTranslation] source: {source_video_url[:80]}...')
    if audio_asset_id:
        audio_field = {'type': 'asset_id', 'asset_id': audio_asset_id}
    elif audio_url:
        audio_field = {'type': 'url', 'url': audio_url}
    else:
        raise RuntimeError('No audio provided for VideoTranslation')
    payload = {
        'video': {'type': 'url', 'url': source_video_url},
        'output_languages': ['English'],
        'title': 'AutoWalkaround Vehicle Video',
        'mode': 'precision',
        'audio': audio_field,
        'translate_audio_only': False,
        'enable_dynamic_duration': True,
        'disable_music_track': True,
        'enable_speech_enhancement': True,
        'speaker_num': 1,
    }
    print(f'[VideoTranslation] Payload audio type: {audio_field["type"]}')
    r = None
    for attempt in range(3):
        try:
            r = requests.post(
                HEYGEN_BASE + '/v3/video-translations',
                headers=heygen_headers(), json=payload, timeout=90
            )
            print(f'[VideoTranslation] Create {attempt+1}: {r.status_code} body={r.text[:500]}')
            break
        except Exception as e:
            print(f'[VideoTranslation] Create attempt {attempt+1} error: {e}')
            if attempt < 2:
                time.sleep(15)
            else:
                raise RuntimeError(f'VideoTranslation create failed: {e}')
    if r is None or r.status_code not in (200, 201, 202):
        raise RuntimeError(f'VideoTranslation HTTP error: {r.status_code if r else "no response"} {r.text[:500] if r else ""}')
    resp_json = r.json()
    print(f'[VideoTranslation] Full response: {json.dumps(resp_json)[:600]}')
    # Parse translation IDs - HeyGen has inconsistent casing
    data = (resp_json.get('data') or resp_json.get('Data') or resp_json.get('DATA') or resp_json)
    if isinstance(data, dict):
        translation_ids = (
            data.get('video_translation_ids') or
            data.get('Video_translation_ids') or
            data.get('VideoTranslationIds') or
            data.get('translation_ids') or []
        )
    else:
        translation_ids = []
    if not translation_ids:
        raise RuntimeError(f'No translation IDs in response: {json.dumps(resp_json)[:500]}')
    translation_id = translation_ids[0]
    print(f'[VideoTranslation] ID: {translation_id} - polling...')
    for i in range(HEYGEN_POLL_MAX):
        time.sleep(HEYGEN_POLL_INTERVAL)
        try:
            sr = requests.get(
                HEYGEN_BASE + '/v3/video-translations/' + translation_id,
                headers=heygen_headers(), timeout=30
            )
            if sr.status_code == 200:
                vdata = sr.json().get('data') or sr.json().get('Data') or {}
                status = str(vdata.get('status') or vdata.get('Status') or 'unknown').lower()
                print(f'[VideoTranslation] Poll {i+1}: {status}')
                if status in ('completed', 'success', 'done'):
                    video_url = (
                        vdata.get('video_url') or vdata.get('output_video_url') or
                        vdata.get('output_url') or vdata.get('VideoUrl')
                    )
                    if not video_url:
                        raise RuntimeError(f'No video_url: {json.dumps(vdata)[:300]}')
                    out_path = os.path.join(tmpdir, 'translated_final.mp4')
                    _download_file(video_url, out_path)
                    print(f'[VideoTranslation] Done: {out_path}')
                    return out_path
                elif status in ('failed', 'error', 'fail'):
                    err = vdata.get('error_message') or vdata.get('error') or json.dumps(vdata)[:300]
                    raise RuntimeError(f'Translation failed: {err}')
            else:
                print(f'[VideoTranslation] Poll {i+1} HTTP {sr.status_code}')
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

def compress_video_for_upload(input_path, tmpdir):
    try:
        input_size = os.path.getsize(input_path)
        print(f'[Compress] Input size: {input_size/1024/1024:.1f} MB')
        if input_size <= 35 * 1024 * 1024:
            print('[Compress] Under 35MB, no compression needed')
            return input_path
        output_path = os.path.join(tmpdir, 'final_compressed.mp4')
        for crf in [28, 32, 36]:
            cmd = [
                'ffmpeg', '-y', '-i', input_path,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', str(crf),
                '-vf', 'scale=720:-2',
                '-c:a', 'aac', '-b:a', '96k',
                '-movflags', '+faststart',
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0 and os.path.exists(output_path):
                out_size = os.path.getsize(output_path)
                print(f'[Compress] CRF {crf}: {out_size/1024/1024:.1f} MB')
                if out_size <= 45 * 1024 * 1024:
                    return output_path
        cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '38',
            '-vf', 'scale=480:-2',
            '-c:a', 'aac', '-b:a', '64k',
            '-movflags', '+faststart',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode == 0:
            print(f'[Compress] Aggressive: {os.path.getsize(output_path)/1024/1024:.1f} MB')
            return output_path
    except Exception as e:
        print(f'[Compress] Error: {e}')
    return input_path

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
    translated_path = run_video_translation(source_video_url, audio_url, audio_asset_id, tmpdir)
    compressed_path = compress_video_for_upload(translated_path, tmpdir)
    return compressed_path
