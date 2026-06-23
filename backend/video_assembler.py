import os, requests, time, subprocess, hashlib

HEADERS = {'User-Agent': 'Mozilla/5.0'}
HEYGEN_BASE = 'https://api.heygen.com'

CINEMATIC_POLL_INTERVAL = 20
CINEMATIC_POLL_MAX = 18
LIPSYNC_POLL_INTERVAL = 20
LIPSYNC_POLL_MAX = 25
PRESENTER_POLL_INTERVAL = 20
PRESENTER_POLL_MAX = 15

W, H = 1080, 1920

WALKAROUND_LOOK = '346a7a4184ec46b985f92fb380ef007c'
INTRO_LOOK = 'ed119cc46f5f4a6d8a6687ac187cd779'
IMMACULATE_LOT_URL = 'https://lh3.googleusercontent.com/gps-cs-s/APNQkAGSkAI7-TAoNkcv4m5PEQRwYfsJdYgypmHTVDUN1Sx4vxRvC13WEcVTnRSkCNWVATeqv7iDe9xxsWWn2VM9ya1BQJEIvTdrY35roeZ3_Sw61Pzeqju1TI0-SlJv2U-qOrKjDKAa=w1333-h1000-k-no'
IMMACULATE_LOGO_URL = 'https://pictures.dealer.com/i/immaculateusedcarsut/1234/7c8591524703458ab4071edd3f7ff217.png'

CINEMATIC_MIN_DURATION = 5
CINEMATIC_MAX_DURATION = 15

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

def _rehost_to_supabase(url, path_prefix='cinematic_refs'):
    try:
        supa_url = os.getenv('SUPABASE_URL', '')
        svc_key = os.getenv('SUPABASE_SERVICE_KEY', '')
        if not supa_url or not svc_key:
            return None
        resp = requests.get(url, timeout=30, headers=HEADERS)
        if resp.status_code != 200:
            return None
        uid = hashlib.md5(url.encode()).hexdigest()[:16]
        ext = 'mp4' if 'mp4' in url.lower() or 'video' in url.lower() else 'jpg'
        path = f'{path_prefix}/ref_{uid}.{ext}'
        ct = 'video/mp4' if ext == 'mp4' else 'image/jpeg'
        up = requests.post(
            f'{supa_url}/storage/v1/object/videos/{path}',
            headers={'Authorization': f'Bearer {svc_key}', 'Content-Type': ct, 'x-upsert': 'true'},
            data=resp.content, timeout=60)
        if up.status_code in (200, 201, 409):
            pub = f'{supa_url}/storage/v1/object/public/videos/{path}'
            print(f'[Rehost] {pub}')
            return pub
    except Exception as e:
        print(f'[Rehost] {e}')
    return None

def _upload_file_to_supabase(local_path, storage_path):
    try:
        supa_url = os.getenv('SUPABASE_URL', '')
        svc_key = os.getenv('SUPABASE_SERVICE_KEY', '')
        if not supa_url or not svc_key:
            return None
        ext = os.path.splitext(local_path)[1].lower()
        ct = 'video/mp4' if ext == '.mp4' else 'audio/mpeg'
        with open(local_path, 'rb') as f:
            data = f.read()
        up = requests.post(
            f'{supa_url}/storage/v1/object/videos/{storage_path}',
            headers={'Authorization': f'Bearer {svc_key}', 'Content-Type': ct, 'x-upsert': 'true'},
            data=data, timeout=120)
        if up.status_code in (200, 201, 409):
            pub = f'{supa_url}/storage/v1/object/public/videos/{storage_path}'
            print(f'[Upload] {pub}')
            return pub
    except Exception as e:
        print(f'[Upload] {e}')
    return None

def _cinematic_refs(raw_urls):
    refs = []
    for url in raw_urls[:3]:
        if 'googleusercontent' in url or 'supabase.co' in url:
            refs.append({'type': 'url', 'url': url})
            continue
        pub = _rehost_to_supabase(url)
        if pub:
            refs.append({'type': 'url', 'url': pub})
    return refs

def _poll_heygen_video(video_id, clip_name, tmpdir):
    for i in range(PRESENTER_POLL_MAX):
        time.sleep(PRESENTER_POLL_INTERVAL)
        try:
            pr = requests.get(HEYGEN_BASE + '/v3/videos/' + video_id, headers=heygen_headers(), timeout=30)
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
                print(f'[HeyGen] poll error {pr.status_code}')
        except Exception as e:
            print(f'[HeyGen] poll exception: {e}')
    print(f'[HeyGen] {clip_name} timed out after {PRESENTER_POLL_MAX} polls')
    return None

def _poll_cinematic_video(video_id, clip_name, tmpdir):
    for i in range(CINEMATIC_POLL_MAX):
        time.sleep(CINEMATIC_POLL_INTERVAL)
        try:
            pr = requests.get(HEYGEN_BASE + '/v3/videos/' + video_id, headers=heygen_headers(), timeout=30)
            if pr.status_code == 200:
                pd = pr.json().get('data', {})
                st = pd.get('status', '')
                print(f'[Cinematic] {clip_name} poll {i+1}: {st}')
                if st == 'completed':
                    vurl = pd.get('video_url') or pd.get('url')
                    if vurl:
                        out = os.path.join(tmpdir, clip_name + '_cinematic.mp4')
                        _download_file(vurl, out)
                        return out
                    return None
                if st == 'failed':
                    msg = pd.get('failure_message') or pd.get('error', '')
                    print(f'[Cinematic] {clip_name} failed: {msg}')
                    return None
            else:
                print(f'[Cinematic] poll error {pr.status_code}: {pr.text[:100]}')
        except Exception as e:
            print(f'[Cinematic] poll exception: {e}')
    print(f'[Cinematic] {clip_name} timed out after {CINEMATIC_POLL_MAX} polls')
    return None

def _poll_lipsync(lipsync_id, clip_name, tmpdir):
    # HeyGen lipsync GET has no status field - returns video_url when done, failure_message when failed
    for i in range(LIPSYNC_POLL_MAX):
        time.sleep(LIPSYNC_POLL_INTERVAL)
        try:
            pr = requests.get(HEYGEN_BASE + '/v3/lipsyncs/' + lipsync_id,
                              headers=heygen_headers(), timeout=30)
            print(f'[Lipsync] {clip_name} poll {i+1}: HTTP {pr.status_code}')
            if pr.status_code == 200:
                pd = pr.json().get('data', {})
                vurl = pd.get('video_url')
                fail = pd.get('failure_message')
                if vurl:
                    out = os.path.join(tmpdir, clip_name + '_lipsync.mp4')
                    _download_file(vurl, out)
                    print(f'[Lipsync] {clip_name} SUCCESS')
                    return out
                if fail:
                    print(f'[Lipsync] {clip_name} failed: {fail}')
                    return None
                print(f'[Lipsync] {clip_name} pending...')
            else:
                print(f'[Lipsync] poll error {pr.status_code}: {pr.text[:200]}')
        except Exception as e:
            print(f'[Lipsync] poll exception: {e}')
    print(f'[Lipsync] {clip_name} timed out after {LIPSYNC_POLL_MAX} polls')
    return None

def generate_tts_audio_url(text, voice_id, tmpdir, clip_name):
    try:
        sid = get_starfish_voice_id(voice_id)
        payload = {'text': text, 'voice_id': sid, 'speed': 0.92, 'input_type': 'text', 'language': 'en'}
        r = requests.post(HEYGEN_BASE + '/v3/voices/speech', headers=heygen_headers(),
                          json=payload, timeout=180)
        if r.status_code != 200:
            print(f'[TTS] {clip_name} HTTP {r.status_code}: {r.text[:200]}')
            return None, None
        audio_url = r.json().get('data', {}).get('audio_url')
        if not audio_url:
            return None, None
        audio_path = os.path.join(tmpdir, f'tts_{clip_name}.mp3')
        _download_file(audio_url, audio_path)
        uid = hashlib.md5(clip_name.encode()).hexdigest()[:12]
        supa_pub = _upload_file_to_supabase(audio_path, f'lipsync_audio/seg_{uid}.mp3')
        return audio_path, supa_pub or audio_url
    except Exception as e:
        print(f'[TTS] {clip_name}: {e}')
        return None, None

def apply_lipsync(cinematic_local_path, audio_pub_url, clip_name, tmpdir):
    """Apply HeyGen lipsync. enable_dynamic_duration=True lets HeyGen handle timing automatically."""
    uid = hashlib.md5(clip_name.encode()).hexdigest()[:12]
    video_storage_path = f'lipsync_src/cinematic_{uid}.mp4'
    print(f'[Lipsync] Uploading cinematic for {clip_name}...')
    video_pub_url = _upload_file_to_supabase(cinematic_local_path, video_storage_path)
    if not video_pub_url:
        print(f'[Lipsync] Could not upload cinematic for {clip_name}')
        return None

    payload = {
        'video': {'type': 'url', 'url': video_pub_url},
        'audio': {'type': 'url', 'url': audio_pub_url},
        'mode': 'precision',
        'title': f'walkaround_{clip_name}',
        'enable_dynamic_duration': True,
        'enable_speech_enhancement': True,
        'keep_the_same_format': True,
    }
    try:
        r = requests.post(HEYGEN_BASE + '/v3/lipsyncs', headers=heygen_headers(),
                          json=payload, timeout=60)
        print(f'[Lipsync] {clip_name} create: HTTP {r.status_code} {r.text[:300]}')
        if r.status_code not in (200, 201, 202):
            return None
        lipsync_id = r.json().get('data', {}).get('lipsync_id')
        if not lipsync_id:
            print(f'[Lipsync] No lipsync_id in response')
            return None
        print(f'[Lipsync] {clip_name} id={lipsync_id}, polling...')
        return _poll_lipsync(lipsync_id, clip_name, tmpdir)
    except Exception as e:
        print(f'[Lipsync] {clip_name} error: {e}')
        return None

def generate_cinematic_clip(prompt, look_ids, tmpdir, clip_name, reference_urls=None, duration=13):
    print(f'[Cinematic] Generating: {clip_name} ({duration}s)')
    look_list = look_ids if isinstance(look_ids, list) else [look_ids]
    clamped_duration = max(CINEMATIC_MIN_DURATION, min(int(round(duration)), CINEMATIC_MAX_DURATION))
    payload = {
        'type': 'cinematic_avatar',
        'prompt': prompt,
        'avatar_id': look_list,
        'aspect_ratio': '9:16',
        'resolution': '720p',
        'duration': clamped_duration,
        'enhance_prompt': True,
    }
    if reference_urls:
        refs = _cinematic_refs(reference_urls)
        if refs:
            payload['references'] = refs
            print(f'[Cinematic] {len(refs)} refs')
    try:
        r = requests.post(HEYGEN_BASE + '/v3/videos', headers=heygen_headers(), json=payload, timeout=60)
        print(f'[Cinematic] {clip_name}: {r.status_code} {r.text[:300]}')
        if r.status_code not in (200, 201):
            return None
        video_id = r.json().get('data', {}).get('video_id')
        if not video_id:
            return None
        return _poll_cinematic_video(video_id, clip_name, tmpdir)
    except Exception as e:
        print(f'[Cinematic] Error: {e}')
        return None

def generate_presenter_clip(text, look_id, voice_id, tmpdir, clip_name, background_url=None, motion_prompt=None):
    print(f'[Presenter] Generating: {clip_name}')
    sid = get_starfish_voice_id(voice_id)
    payload = {'type': 'avatar', 'avatar_id': look_id, 'script': text, 'voice_id': sid,
               'resolution': '720p', 'aspect_ratio': '9:16', 'output_format': 'mp4'}
    if background_url:
        bg = background_url
        if ('supabase.co' not in background_url) and ('googleusercontent' not in background_url):
            bg = _rehost_to_supabase(background_url, 'segment_bg') or None
        if bg:
            payload['background'] = {'type': 'image', 'url': bg, 'fit': 'cover'}
            payload['remove_background'] = True
            print(f'[Presenter] {clip_name} background set')
    if motion_prompt:
        payload['motion_prompt'] = motion_prompt
    try:
        r = requests.post(HEYGEN_BASE + '/v3/videos', headers=heygen_headers(), json=payload, timeout=60)
        print(f'[Presenter] {clip_name}: {r.status_code} {r.text[:300]}')
        if r.status_code not in (200, 201):
            payload.pop('background', None)
            payload.pop('motion_prompt', None)
            r = requests.post(HEYGEN_BASE + '/v3/videos', headers=heygen_headers(), json=payload, timeout=60)
            print(f'[Presenter] {clip_name} retry-plain: {r.status_code} {r.text[:200]}')
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
        r = requests.post(HEYGEN_BASE + '/v3/voices/speech', headers=heygen_headers(),
                          json=payload, timeout=180)
        if r.status_code != 200:
            return None
        audio_url = r.json().get('data', {}).get('audio_url')
        if not audio_url:
            return None
        audio_path = os.path.join(tmpdir, f'tts_{clip_name}.mp3')
        _download_file(audio_url, audio_path)
        dur = get_audio_duration(audio_path)
        out = os.path.join(tmpdir, f'tts_clip_{clip_name}.mp4')
        cmd = ['ffmpeg', '-y', '-f', 'lavfi', '-i', f'color=c=0x1a1a2e:s={W}x{H}:r=24',
               '-i', audio_path, '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
               '-c:a', 'aac', '-b:a', '128k', '-shortest', '-t', str(dur),
               '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out]
        res = subprocess.run(cmd, capture_output=True, timeout=120)
        if res.returncode == 0 and os.path.exists(out):
            return out
    except Exception as e:
        print(f'[TTS-fallback] {clip_name}: {e}')
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
        r = subprocess.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
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
    cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', clist,
           '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
           '-c:a', 'aac', '-b:a', '128k', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', output_path]
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
            res = subprocess.run(['ffmpeg', '-y', '-i', input_path, '-c:v', 'libx264', '-preset', 'fast',
                                  '-crf', str(crf), '-vf', 'scale=1080:-2', '-c:a', 'aac', '-b:a', '96k',
                                  '-movflags', '+faststart', out], capture_output=True, timeout=300)
            if res.returncode == 0 and os.path.exists(out):
                if os.path.getsize(out) <= 45 * 1024 * 1024:
                    return out
        return input_path
    except Exception as e:
        print(f'[Compress] {e}')
        return input_path

def _overlay_logo(video_path, tmpdir):
    try:
        logo = os.path.join(tmpdir, 'imm_logo.png')
        _download_file(IMMACULATE_LOGO_URL, logo)
        if (not os.path.exists(logo)) or os.path.getsize(logo) < 500:
            return video_path
        out = os.path.join(tmpdir, 'final_logo.mp4')
        fc = '[1:v]scale=210:-1[lg];[0:v][lg]overlay=36:40'
        cmd = ['ffmpeg', '-y', '-i', video_path, '-i', logo, '-filter_complex', fc,
               '-c:v', 'libx264', '-preset', 'fast', '-crf', '24', '-c:a', 'copy',
               '-movflags', '+faststart', out]
        result = subprocess.run(cmd, capture_output=True, timeout=600)
        if result.returncode != 0:
            err = result.stderr[-300:].decode('utf-8', errors='ignore') if result.stderr else ''
            print(f'[Logo] overlay failed: {err}')
            return video_path
        print('[Logo] overlay applied')
        return out
    except Exception as e:
        print(f'[Logo] {e}')
        return video_path

def build_walkaround_video(vehicle, script_segments, heygen_audio_path,
                           heygen_result, vehicle_photos, vehicle_video_url, tmpdir):
    segments = script_segments if isinstance(script_segments, dict) else {}
    voice_id = heygen_result.get('voice_id') if isinstance(heygen_result, dict) else None
    voice_id = voice_id or os.getenv('HEYGEN_VOICE_ID', '6ee20575cb9f4a7e9dc19096a958eab1')
    year = vehicle.get('year', '')
    make = vehicle.get('make', '')
    model = vehicle.get('model', '')
    trim = vehicle.get('trim', '')
    vehicle_name = f'{year} {make} {model} {trim}'.strip()
    intro_text = segments.get('intro', '')
    outro_text = segments.get('outro', '')
    segment_order = ['front', 'driver_side', 'rear', 'pass_side', 'interior']
    raw_refs = [IMMACULATE_LOT_URL] + list(vehicle_photos or [])[:2]
    photos = [p for p in (vehicle_photos or []) if p]
    def pick(frac):
        if not photos:
            return None
        return photos[min(len(photos) - 1, int(frac * len(photos)))]
    hero_bg = pick(0.0)

    print(f'[Build] Cinematic walkaround with lipsync: {vehicle_name}')
    all_clips = []

    if intro_text:
        print('[Build] == INTRO (presenter) ==')
        ic = generate_presenter_clip(intro_text, INTRO_LOOK, voice_id, tmpdir, 'intro', background_url=hero_bg, motion_prompt='Friendly car salesman greeting the camera with a welcoming gesture, standing in front of the vehicle, natural hand movements.')
        if not ic:
            ic = _tts_fallback_clip(intro_text, voice_id, tmpdir, 'intro')
        if ic:
            all_clips.append(ic)

    print('[Build] == WALKAROUND SEGMENTS (presenter over real vehicle photos) ==')
    seg_bg = {
        'front': pick(0.0),
        'driver_side': pick(0.18),
        'rear': pick(0.42),
        'pass_side': pick(0.60),
        'interior': pick(0.82),
    }
    seg_motion = {
        'front': 'Car salesman gesturing toward the vehicle behind him, presenting the front, grille and headlights, enthusiastic natural hand movements, looking at the camera.',
        'driver_side': 'Car salesman gesturing to the side toward the vehicle, presenting the driver side and wheels, natural hand movements, looking at the camera.',
        'rear': 'Car salesman gesturing toward the rear of the vehicle, presenting the back and cargo area, natural hand movements, looking at the camera.',
        'pass_side': 'Car salesman gesturing toward the passenger side of the vehicle, presenting the doors and trim, natural hand movements, looking at the camera.',
        'interior': 'Car salesman gesturing toward the vehicle interior, presenting the seats and dashboard, warm enthusiastic hand movements, looking at the camera.',
    }
    for seg_name in segment_order:
        seg_text = segments.get(seg_name, '')
        if not seg_text or not seg_text.strip():
            continue
        print(f'[Build] Segment: {seg_name}')
        sc = generate_presenter_clip(seg_text, INTRO_LOOK, voice_id, tmpdir, seg_name,
                                     background_url=seg_bg.get(seg_name),
                                     motion_prompt=seg_motion.get(seg_name))
        if not sc:
            sc = generate_presenter_clip(seg_text, INTRO_LOOK, voice_id, tmpdir, seg_name + '_fb')
        if not sc:
            sc = _tts_fallback_clip(seg_text, voice_id, tmpdir, seg_name)
        if sc:
            all_clips.append(sc)
    if outro_text:
        print('[Build] == OUTRO (presenter) ==')
        oc = generate_presenter_clip(outro_text, INTRO_LOOK, voice_id, tmpdir, 'outro', background_url=hero_bg, motion_prompt='Car salesman giving a friendly closing call to action with an inviting gesture toward the camera, standing in front of the vehicle.')
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
    final_path = _overlay_logo(final_path, tmpdir)
    return compress_video_for_upload(final_path, tmpdir)

def get_look_id(avatar_group_id):
    return INTRO_LOOK

def upload_audio_to_heygen(audio_path):
    return None

def generate_heygen_audio(script_text, voice_id, tmpdir):
    sid = get_starfish_voice_id(voice_id)
    payload = {'text': script_text, 'voice_id': sid, 'speed': 0.92, 'input_type': 'text', 'language': 'en'}
    r = requests.post(HEYGEN_BASE + '/v3/voices/speech', headers=heygen_headers(),
                      json=payload, timeout=180)
    audio_url = r.json().get('data', {}).get('audio_url')
    audio_path = os.path.join(tmpdir, 'script_audio.mp3')
    _download_file(audio_url, audio_path)
    return audio_path, audio_url

def run_video_translation(video_url, audio_url, tmpdir):
    return None
