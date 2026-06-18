import os, requests, time, subprocess

HEADERS = {'User-Agent': 'Mozilla/5.0'}
HEYGEN_BASE = 'https://api.heygen.com'
HEYGEN_POLL_INTERVAL = 15
HEYGEN_POLL_MAX = 240

W, H = 1080, 1920

# Aaron's look IDs
WALKAROUND_LOOK = '346a7a4184ec46b985f92fb380ef007c'   # at vehicle, touching, presenting
INTRO_LOOK      = 'ed119cc46f5f4a6d8a6687ac187cd779'   # facing camera clean on lot

# Immaculate Used Cars lot photo from Google My Business (used as scene reference)
IMMACULATE_LOT_URL = 'https://lh3.googleusercontent.com/gps-cs-s/APNQkAGSkAI7-TAoNkcv4m5PEQRwYfsJdYgypmHTVDUN1Sx4vxRvC13WEcVTnRSkCNWVATeqv7iDe9xxsWWn2VM9ya1BQJEIvTdrY35roeZ3_Sw61Pzeqju1TI0-SlJv2U-qOrKjDKAa=w1333-h1000-k-no'

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

def _poll_heygen_video(video_id, clip_name, tmpdir):
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
                print(f'[HeyGen] {clip_name} failed: {pd.get("error", pd.get("failure_message", ""))}')
                return None
        else:
            print(f'[HeyGen] poll error {pr.status_code}: {pr.text[:100]}')
    return None

def generate_cinematic_clip(prompt, look_ids, tmpdir, clip_name,
                            reference_urls=None, duration=13):
    """
    Generate a cinematic avatar clip using HeyGen Seedance 2 (cinematic_avatar type).
    Avatar physically moves through the scene. References must be images or videos < 32MB.
    """
    print(f'[Cinematic] Generating: {clip_name}')
    look_list = look_ids if isinstance(look_ids, list) else [look_ids]
    payload = {
        'type': 'cinematic_avatar',
        'prompt': prompt,
        'avatar_id': look_list,
        'aspect_ratio': '9:16',
        'resolution': '720p',
        'duration': min(int(duration), 15),
        'enhance_prompt': True,
    }
    # Only add image references (photos are safe, videos must be < 32MB)
    if reference_urls:
        # Filter to image URLs only - vehicle listing photos are JPEGs, safe to use
        image_refs = [{'type': 'url', 'url': u} for u in reference_urls
                      if any(u.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp'])
                      or 'googleusercontent' in u or 'heygen' in u or 'cdn' in u.lower()][:3]
        if image_refs:
            payload['references'] = image_refs
    try:
        r = requests.post(HEYGEN_BASE + '/v3/videos',
                          headers=heygen_headers(), json=payload, timeout=60)
        print(f'[Cinematic] {clip_name}: {r.status_code} {r.text[:300]}')
        if r.status_code not in (200, 201):
            return None
        video_id = r.json().get('data', {}).get('video_id')
        if not video_id:
            print(f'[Cinematic] No video_id: {r.text[:200]}')
            return None
        return _poll_heygen_video(video_id, clip_name, tmpdir)
    except Exception as e:
        print(f'[Cinematic] Error: {e}')
    return None

def generate_presenter_clip(text, look_id, voice_id, tmpdir, clip_name):
    """Generate a presenter (talking head) clip for intro/outro."""
    print(f'[Presenter] Generating: {clip_name}')
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
        print(f'[Presenter] {clip_name}: {r.status_code} {r.text[:300]}')
        if r.status_code not in (200, 201):
            return None
        video_id = r.json().get('data', {}).get('video_id')
        if not video_id:
            return None
        return _poll_heygen_video(video_id, clip_name, tmpdir)
    except Exception as e:
        print(f'[Presenter] Error: {e}')
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

    year  = vehicle.get('year', '')
    make  = vehicle.get('make', '')
    model = vehicle.get('model', '')
    trim  = vehicle.get('trim', '')
    vehicle_name = f'{year} {make} {model} {trim}'.strip()

    intro_text = segments.get('intro', '')
    outro_text = segments.get('outro', '')
    segment_order = ['front', 'driver_side', 'rear', 'pass_side', 'interior']

    # Image references: lot photo + up to 2 vehicle photos (images only, safe size)
    image_refs = [IMMACULATE_LOT_URL] + list(vehicle_photos or [])[:2]

    print(f'[Build] Cinematic walkaround: {vehicle_name}')

    all_clips = []

    # INTRO — presenter mode
    if intro_text:
        print('[Build] == INTRO (presenter) ==')
        ic = generate_presenter_clip(intro_text, INTRO_LOOK, voice_id, tmpdir, 'intro')
        if not ic:
            ic = _tts_fallback_clip(intro_text, voice_id, tmpdir, 'intro')
        if ic:
            all_clips.append(ic)

    segment_prompts = {
        'front': (
            f'A bald used car salesman in a light blue button-down shirt walks toward '
            f'the front of a {vehicle_name} on an Immaculate Used Cars lot. '
            f'He holds his iPhone in selfie mode pointed back at himself and the vehicle front, '
            f'smiling and gesturing at the hood, grille, and headlights. '
            f'Handheld selfie POV, daylight, enthusiastic energy.'
        ),
        'driver_side': (
            f'A bald used car salesman in a light blue button-down shirt walks along '
            f'the driver side of a {vehicle_name} on an Immaculate Used Cars lot. '
            f'He holds his iPhone in selfie mode, turning to point out the doors, '
            f'mirrors, and wheels as he strides past. Handheld selfie POV, natural daylight.'
        ),
        'rear': (
            f'A bald used car salesman in a light blue button-down shirt stands behind '
            f'a {vehicle_name} on an Immaculate Used Cars lot. '
            f'He holds his iPhone in selfie mode pointing at himself and the rear of the vehicle, '
            f'gesturing at the taillights and hatch. Handheld selfie POV, enthusiastic delivery.'
        ),
        'pass_side': (
            f'A bald used car salesman in a light blue button-down shirt walks along '
            f'the passenger side of a {vehicle_name} on an Immaculate Used Cars lot. '
            f'He holds his iPhone in selfie mode and points to the passenger door and exterior trim. '
            f'Handheld selfie POV, natural walking motion.'
        ),
        'interior': (
            f'A bald used car salesman in a light blue button-down shirt opens the door '
            f'of a {vehicle_name} and leans in, holding his iPhone in selfie mode '
            f'to show the dashboard, seats, and interior. He gestures at the steering wheel '
            f'and center console. Warm interior lighting, close-up selfie POV.'
        ),
    }

    print('[Build] == CINEMATIC SEGMENTS ==')
    for seg_name in segment_order:
        seg_text = segments.get(seg_name, '')
        if not seg_text or not seg_text.strip():
            continue
        print(f'[Build] Cinematic segment: {seg_name}')
        prompt = segment_prompts.get(seg_name, '') + f' Narrating: "{seg_text[:180]}"'
        sc = generate_cinematic_clip(
            prompt=prompt,
            look_ids=[WALKAROUND_LOOK],
            tmpdir=tmpdir,
            clip_name=seg_name,
            reference_urls=image_refs,
            duration=13
        )
        if not sc:
            print(f'[Build] Cinematic failed {seg_name}, trying presenter')
            sc = generate_presenter_clip(seg_text, WALKAROUND_LOOK, voice_id, tmpdir, seg_name + '_fb')
        if not sc:
            sc = _tts_fallback_clip(seg_text, voice_id, tmpdir, seg_name)
        if sc:
            all_clips.append(sc)

    # OUTRO — presenter mode
    if outro_text:
        print('[Build] == OUTRO (presenter) ==')
        oc = generate_presenter_clip(outro_text, INTRO_LOOK, voice_id, tmpdir, 'outro')
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
    return INTRO_LOOK

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
