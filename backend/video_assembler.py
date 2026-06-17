import os, requests, time, json, subprocess

HEADERS = {'User-Agent': 'Mozilla/5.0'}
HEYGEN_BASE = 'https://api.heygen.com'
HEYGEN_POLL_INTERVAL = 15
HEYGEN_POLL_MAX = 240

W, H = 1080, 1920

# Aaron's look IDs
INTRO_OUTRO_LOOK = 'ed119cc46f5f4a6d8a6687ac187cd779'   # Sharp Used Car Salesman - facing camera on lot
WALKAROUND_LOOK  = '346a7a4184ec46b985f92fb380ef007c'   # Sharp Used Car Salesman - at vehicle, touching, presenting

def heygen_headers():
    return {'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}

def get_starfish_voice_id(preferred_voice_id):
    try:
        r = requests.get(HEYGEN_BASE + '/v3/voices?type=private&engine=starfish&limit=20',
                         headers=heygen_headers(), timeout=30)
        if r.status_code == 200:
            voices = r.json().get('data', [])
            if voices:
                return voices[0].get('voice_id')
    except Exception:
        pass
    try:
        r = requests.get(
            HEYGEN_BASE + '/v3/voices?type=public&engine=starfish&language=English&gender=male&limit=5',
            headers=heygen_headers(), timeout=30)
        if r.status_code == 200:
            voices = r.json().get('data', [])
            if voices:
                return voices[0].get('voice_id')
    except Exception:
        pass
    return preferred_voice_id

def generate_heygen_clip(text, look_id, voice_id, tmpdir, clip_name):
    print(f'[HeyGen] Generating: {clip_name} with look {look_id[:8]}...')
    sid = get_starfish_voice_id(voice_id)
    payload = {
        'type': 'avatar',
        'avatar_id': look_id,
        'script': text,
        'voice_id': sid,
        'resolution': '720p',
        'aspect_ratio': '9:16',
        'output_format': 'mp4',
    }
    try:
        r = requests.post(HEYGEN_BASE + '/v3/videos',
                          headers=heygen_headers(), json=payload, timeout=60)
        print(f'[HeyGen] {clip_name}: {r.status_code} {r.text[:300]}')
        if r.status_code not in (200, 201):
            return None
        video_id = r.json().get('data', {}).get('video_id')
        if not video_id:
            print(f'[HeyGen] No video_id in response: {r.text[:200]}')
            return None
        for i in range(HEYGEN_POLL_MAX):
            time.sleep(HEYGEN_POLL_INTERVAL)
            pr = requests.get(HEYGEN_BASE + '/v3/videos/' + video_id,
                              headers=heygen_headers(), timeout=30)
            if pr.status_code == 200:
                pd = pr.json().get('data', {})
                st = pd.get('status', '')
                print(f'[HeyGen] {clip_name} poll {i+1}: {st}')
                if st == 'completed':
                    vurl = pd.get('video_url') or pd.get('url')
                    if vurl:
                        out = os.path.join(tmpdir, clip_name + '_heygen.mp4')
                        _download_file(vurl, out)
                        return out
                    return None
                if st == 'failed':
                    print(f'[HeyGen] {clip_name} failed: {pd.get("error", "")}')
                    return None
            else:
                print(f'[HeyGen] poll error {pr.status_code}: {pr.text[:100]}')
    except Exception as e:
        print(f'[HeyGen] Error: {e}')
    return None

def _tts_fallback_clip(text, voice_id, tmpdir, clip_name):
    try:
        sid = get_starfish_voice_id(voice_id)
        payload = {'text': text, 'voice_id': sid, 'speed': 0.92, 'input_type': 'text', 'language': 'en'}
        r = requests.post(HEYGEN_BASE + '/v3/voices/speech',
                          headers=heygen_headers(), json=payload, timeout=180)
        if r.status_code != 200:
            return None
        audio_url = r.json().get('data', {}).get('audio_url')
        if not audio_url:
            return None
        audio_path = os.path.join(tmpdir, f'tts_{clip_name}.mp3')
        _download_file(audio_url, audio_path)
        dur = get_audio_duration(audio_path)
        out = os.path.join(tmpdir, f'tts_clip_{clip_name}.mp4')
        cmd = [
            'ffmpeg', '-y', '-f', 'lavfi',
            '-i', f'color=c=0x1a1a2e:s={W}x{H}:r=24',
            '-i', audio_path,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
            '-c:a', 'aac', '-b:a', '128k', '-shortest', '-t', str(dur),
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=120)
        if res.returncode == 0 and os.path.exists(out):
            return out
    except Exception as e:
        print(f'[TTS-fallback] {clip_name} error: {e}')
    return None

def _download_file(url, dest_path):
    r = requests.get(url, headers=HEADERS, stream=True, timeout=300)
    r.raise_for_status()
    with open(dest_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
    print(f'[Download] {os.path.basename(dest_path)} ({os.path.getsize(dest_path)} bytes)')

def get_audio_duration(path):
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', path],
            capture_output=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 5.0

def _concat_clips(clip_paths, output_path, tmpdir):
    clist = os.path.join(tmpdir, 'concat_list.txt')
    with open(clist, 'w') as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")
    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', clist,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
        '-c:a', 'aac', '-b:a', '128k',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    if result.returncode != 0:
        err = result.stderr[-400:].decode('utf-8', errors='ignore') if result.stderr else ''
        raise RuntimeError(f'Concat failed: {err}')
    print(f'[Concat] done {os.path.getsize(output_path)//1024//1024}MB')

def compress_video_for_upload(input_path, tmpdir):
    try:
        sz = os.path.getsize(input_path)
        if sz <= 40 * 1024 * 1024:
            return input_path
        out = os.path.join(tmpdir, 'final_compressed.mp4')
        for crf in [28, 32, 36]:
            res = subprocess.run([
                'ffmpeg', '-y', '-i', input_path,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', str(crf),
                '-vf', 'scale=1080:-2',
                '-c:a', 'aac', '-b:a', '96k',
                '-movflags', '+faststart', out
            ], capture_output=True, timeout=300)
            if res.returncode == 0 and os.path.exists(out):
                if os.path.getsize(out) <= 45 * 1024 * 1024:
                    return out
        return input_path
    except Exception as e:
        print(f'[Compress] {e}')
        return input_path

def build_walkaround_video(vehicle, script_segments, heygen_audio_path,
                           heygen_result, vehicle_photos, vehicle_video_url, tmpdir):
    segments = script_segments if isinstance(script_segments, dict) else {}
    voice_id = heygen_result.get('voice_id') if isinstance(heygen_result, dict) else None
    voice_id = voice_id or os.getenv('HEYGEN_VOICE_ID', '6ee20575cb9f4a7e9dc19096a958eab1')

    intro_text = segments.get('intro', '')
    outro_text = segments.get('outro', '')
    segment_order = ['front', 'driver_side', 'rear', 'pass_side', 'interior']

    print(f'[Build] Full-frame walkaround. Intro/outro look: {INTRO_OUTRO_LOOK[:8]} Segment look: {WALKAROUND_LOOK[:8]}')

    all_clips = []

    if intro_text:
        print('[Build] == INTRO ==')
        ic = generate_heygen_clip(intro_text, INTRO_OUTRO_LOOK, voice_id, tmpdir, 'intro')
        if not ic:
            ic = _tts_fallback_clip(intro_text, voice_id, tmpdir, 'intro')
        if ic:
            all_clips.append(ic)

    print('[Build] == SEGMENTS ==')
    for seg_name in segment_order:
        seg_text = segments.get(seg_name, '')
        if not seg_text or not seg_text.strip():
            continue
        print(f'[Build] Segment: {seg_name}')
        sc = generate_heygen_clip(seg_text, WALKAROUND_LOOK, voice_id, tmpdir, seg_name)
        if not sc:
            sc = _tts_fallback_clip(seg_text, voice_id, tmpdir, seg_name)
        if sc:
            all_clips.append(sc)

    if outro_text:
        print('[Build] == OUTRO ==')
        oc = generate_heygen_clip(outro_text, INTRO_OUTRO_LOOK, voice_id, tmpdir, 'outro')
        if not oc:
            oc = _tts_fallback_clip(outro_text, voice_id, tmpdir, 'outro')
        if oc:
            all_clips.append(oc)

    if not all_clips:
        raise RuntimeError('No clips built')

    if len(all_clips) == 1:
        final_path = all_clips[0]
    else:
        final_path = os.path.join(tmpdir, 'final_walkaround.mp4')
        _concat_clips(all_clips, final_path, tmpdir)

    return compress_video_for_upload(final_path, tmpdir)

def get_look_id(avatar_group_id):
    return INTRO_OUTRO_LOOK

def upload_audio_to_heygen(audio_path):
    return None

def generate_heygen_audio(script_text, voice_id, tmpdir):
    sid = get_starfish_voice_id(voice_id)
    payload = {'text': script_text, 'voice_id': sid, 'speed': 0.92, 'input_type': 'text', 'language': 'en'}
    r = requests.post(HEYGEN_BASE + '/v3/voices/speech',
                      headers=heygen_headers(), json=payload, timeout=180)
    audio_url = r.json().get('data', {}).get('audio_url')
    audio_path = os.path.join(tmpdir, 'script_audio.mp3')
    _download_file(audio_url, audio_path)
    return audio_path, audio_url

def run_video_translation(video_url, audio_url, tmpdir):
    return None
