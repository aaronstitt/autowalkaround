import os, requests, time, json, subprocess, math, random

HEADERS = {'User-Agent': 'Mozilla/5.0'}
HEYGEN_BASE = 'https://api.heygen.com'
HEYGEN_POLL_INTERVAL = 15
HEYGEN_POLL_MAX = 240

W, H = 1080, 1920
PIP_W = 340
PIP_H = 510
PIP_X = 20
PIP_Y = H - PIP_H - 40

SEGMENT_PHOTO_MAP = {
    'front':       [0, 1, 2],
    'driver_side': [3, 4, 5],
    'rear':        [6, 7, 8],
    'pass_side':   [9, 10, 11],
    'interior':    list(range(12, 29)),
}


def heygen_headers():
    return {'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}


def get_look_id(avatar_group_id):
    try:
        url = HEYGEN_BASE + '/v3/avatars/looks?ownership=private&group_id=' + avatar_group_id
        r = requests.get(url, headers=heygen_headers(), timeout=30)
        if r.status_code == 200:
            data = r.json().get('data', [])
            looks = data if isinstance(data, list) else data.get('looks', [])
            preferred_keywords = ['sharp', 'car', 'lot', 'outdoor', 'salesman', 'used', 'walkaround']
            for look in looks:
                name = (look.get('name') or look.get('look_name') or '').lower()
                if any(kw in name for kw in preferred_keywords):
                    return look.get('id') or look.get('look_id')
            if looks:
                return looks[0].get('id') or looks[0].get('look_id')
    except Exception as e:
        print(f'[get_look_id] error: {e}')
    return None


def get_starfish_voice_id(preferred_voice_id):
    print(f'[TTS] Finding starfish voice, preferred: {preferred_voice_id}')
    try:
        r = requests.get(HEYGEN_BASE + '/v3/voices?type=private&engine=starfish&limit=20',
                         headers=heygen_headers(), timeout=30)
        print(f'[TTS] Private starfish: {r.status_code} {r.text[:150]}')
        if r.status_code == 200:
            voices = r.json().get('data', [])
            if voices:
                vid = voices[0].get('voice_id')
                print(f'[TTS] Using private starfish: {vid}')
                return vid
    except Exception as e:
        print(f'[TTS] Private voice error: {e}')
    try:
        r = requests.get(
            HEYGEN_BASE + '/v3/voices?type=public&engine=starfish&language=English&gender=male&limit=5',
            headers=heygen_headers(), timeout=30)
        if r.status_code == 200:
            voices = r.json().get('data', [])
            if voices:
                vid = voices[0].get('voice_id')
                print(f'[TTS] Using public starfish: {vid}')
                return vid
    except Exception as e:
        print(f'[TTS] Public voice error: {e}')
    print(f'[TTS] Fallback to: {preferred_voice_id}')
    return preferred_voice_id


def _tts_call(text, voice_id, speed=0.92):
    starfish_id = get_starfish_voice_id(voice_id)
    payload = {'text': text, 'voice_id': starfish_id, 'speed': speed,
               'input_type': 'text', 'language': 'en'}
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(HEYGEN_BASE + '/v3/voices/speech',
                              headers=heygen_headers(), json=payload, timeout=180)
            print(f'[TTS] Attempt {attempt+1}: {r.status_code} {r.text[:200]}')
            if r.status_code == 200:
                audio_url = r.json().get('data', {}).get('audio_url')
                if audio_url:
                    return audio_url
            elif r.status_code in (400, 404, 422):
                pub_r = requests.get(
                    HEYGEN_BASE + '/v3/voices?type=public&engine=starfish&language=English&limit=5',
                    headers=heygen_headers(), timeout=30)
                if pub_r.status_code == 200 and pub_r.json().get('data'):
                    payload['voice_id'] = pub_r.json()['data'][0]['voice_id']
            last_err = RuntimeError(f'TTS {r.status_code}: {r.text[:150]}')
            time.sleep(2)
        except Exception as e:
            last_err = e
            time.sleep(2)
    raise last_err or RuntimeError('TTS failed')


def generate_tts_segment_audio(text, voice_id, tmpdir, seg_name, speed=0.92):
    if not text or not text.strip():
        return None
    try:
        audio_url = _tts_call(text, voice_id, speed=speed)
        out = os.path.join(tmpdir, f'seg_{seg_name}.mp3')
        _download_file(audio_url, out)
        return out
    except Exception as e:
        print(f'[TTS] Segment {seg_name} error: {e}')
        return None


def get_audio_duration(path):
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', path],
            capture_output=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 5.0


def _download_file(url, dest_path):
    r = requests.get(url, headers=HEADERS, stream=True, timeout=300)
    r.raise_for_status()
    with open(dest_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
    print(f'[Download] {dest_path} ({os.path.getsize(dest_path)} bytes)')


def generate_heygen_avatar_clip(text, look_id, avatar_group_id, voice_id, tmpdir, clip_name='clip'):
    """Generate a HeyGen avatar video - Aaron talking, full frame, lot background."""
    print(f'[HeyGen] Generating avatar clip: {clip_name}')
    starfish_voice_id = get_starfish_voice_id(voice_id)
    payload = {
        'title': f'AutoWalkaround {clip_name}',
        'video_inputs': [{
            'character': {
                'type': 'avatar',
                'avatar_id': avatar_group_id,
                'avatar_style': 'normal',
                'scale': 1.0,
                'matting': False,
            },
            'voice': {
                'type': 'text',
                'input_text': text,
                'voice_id': starfish_voice_id,
                'speed': 0.92,
            },
            'background': {'type': 'color', 'value': '#1a1a1a'}
        }],
        'dimension': {'width': W, 'height': H},
        'test': False,
    }
    try:
        r = requests.post(HEYGEN_BASE + '/v2/video/generate',
                          headers=heygen_headers(), json=payload, timeout=60)
        print(f'[HeyGen] {clip_name}: {r.status_code} {r.text[:200]}')
        if r.status_code not in (200, 201):
            return None
        video_id = r.json().get('data', {}).get('video_id')
        if not video_id:
            return None
        print(f'[HeyGen] Polling {video_id} for {clip_name}...')
        for poll_i in range(HEYGEN_POLL_MAX):
            time.sleep(HEYGEN_POLL_INTERVAL)
            poll_r = requests.get(HEYGEN_BASE + f'/v1/video_status.get?video_id={video_id}',
                                  headers=heygen_headers(), timeout=30)
            if poll_r.status_code == 200:
                pdata = poll_r.json().get('data', {})
                status = pdata.get('status', '')
                print(f'[HeyGen] {clip_name} poll {poll_i+1}: {status}')
                if status == 'completed':
                    video_url = pdata.get('video_url')
                    if video_url:
                        out_path = os.path.join(tmpdir, f'{clip_name}_heygen.mp4')
                        _download_file(video_url, out_path)
                        return out_path
                    return None
                elif status == 'failed':
                    print(f'[HeyGen] {clip_name} failed: {pdata}')
                    return None
    except Exception as e:
        print(f'[HeyGen] Avatar clip error: {e}')
    return None


def _build_photo_bg_clip(photo_path, duration, output_path):
    """Scale photo to fill 9:16 frame. Simple crop-to-fill, no zoompan."""
    cmd = [
        'ffmpeg', '-y', '-loop', '1', '-framerate', '24', '-i', photo_path,
        '-t', str(duration),
        '-vf', f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
        '-pix_fmt', 'yuv420p', '-an', output_path
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode == 0 and os.path.exists(output_path):
        return True
    err = r.stderr[-200:].decode('utf-8', errors='ignore') if r.stderr else ''
    print(f'[BgClip] Failed: {err[-100:]}')
    return False


def _build_pip_segment(photo_paths, audio_path, audio_dur, pip_source, output_path, seg_name):
    """
    Composite: vehicle photo fills full 9:16 frame + Aaron PIP in bottom-left corner.
    pip_source: path to HeyGen avatar clip used as PIP (looped if shorter than audio_dur).
    """
    n = len(photo_paths)
    if n == 0:
        return None

    per_photo = max(2.0, min(audio_dur / max(n, 1), 6.0))
    tmpdir = os.path.dirname(output_path)

    # Build per-photo bg clips
    bg_clips = []
    for idx, pp in enumerate(photo_paths):
        bg_clip_path = pp + f'_bg{idx}.mp4'
        if _build_photo_bg_clip(pp, per_photo, bg_clip_path):
            bg_clips.append(bg_clip_path)
        else:
            print(f'[PIP] BG clip {idx} failed for {seg_name}')

    if not bg_clips:
        return None

    # Concat bg clips
    if len(bg_clips) == 1:
        bg_video = bg_clips[0]
    else:
        bg_video = os.path.join(tmpdir, f'bg_{seg_name}.mp4')
        concat_list = os.path.join(tmpdir, f'bgc_{seg_name}.txt')
        with open(concat_list, 'w') as f:
            for c in bg_clips:
                f.write(f"file '{c}'\n")
        cr = subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
            '-pix_fmt', 'yuv420p', '-an', bg_video
        ], capture_output=True, timeout=300)
        if cr.returncode != 0:
            bg_video = bg_clips[0]

    # If no pip source, just combine bg + audio
    if not pip_source or not os.path.exists(pip_source):
        cmd = [
            'ffmpeg', '-y', '-i', bg_video, '-i', audio_path,
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
            '-shortest', '-movflags', '+faststart', output_path
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(output_path):
            print(f'[PIP] {seg_name}: audio-only (no pip source)')
            return output_path
        return None

    # Composite PIP over bg
    # bg: scale/crop to WxH, trim to audio_dur
    # pip: scale to PIP_W x PIP_H, loop, trim to audio_dur, place at bottom-left
    # audio from audio_path (input 2)
    pip_w = PIP_W
    pip_h = PIP_H
    pip_x = PIP_X
    pip_y = PIP_Y

    fc = (
        f'[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,'
        f'crop={W}:{H},setsar=1,trim=duration={audio_dur:.3f},setpts=PTS-STARTPTS[bg];'
        f'[1:v]scale={pip_w}:{pip_h}:force_original_aspect_ratio=increase,'
        f'crop={pip_w}:{pip_h},setsar=1,loop=loop=-1:size=32767,'
        f'trim=duration={audio_dur:.3f},setpts=PTS-STARTPTS[pip];'
        f'[bg][pip]overlay={pip_x}:{pip_y}:shortest=1[out]'
    )

    cmd = [
        'ffmpeg', '-y',
        '-i', bg_video,
        '-i', pip_source,
        '-i', audio_path,
        '-filter_complex', fc,
        '-map', '[out]', '-map', '2:a',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
        '-c:a', 'aac', '-b:a', '128k',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
        '-t', str(audio_dur + 0.5),
        output_path
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode == 0 and os.path.exists(output_path):
        sz = os.path.getsize(output_path)
        print(f'[PIP] {seg_name} done: {sz/1024/1024:.1f}MB')
        return output_path

    err = r.stderr[-400:].decode('utf-8', errors='ignore') if r.stderr else ''
    print(f'[PIP] Composite failed for {seg_name}: {err[-200:]}')

    # Fallback: bg + audio, no pip
    cmd2 = [
        'ffmpeg', '-y', '-i', bg_video, '-i', audio_path,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
        '-shortest', '-movflags', '+faststart', output_path
    ]
    r2 = subprocess.run(cmd2, capture_output=True, timeout=120)
    if r2.returncode == 0 and os.path.exists(output_path):
        print(f'[PIP] {seg_name}: fallback (no pip) succeeded')
        return output_path
    return None


def _build_tts_only_clip(text, voice_id, tmpdir, clip_name, vehicle_photos):
    """TTS audio + vehicle photo background. Used when HeyGen avatar fails."""
    try:
        audio_url = _tts_call(text, voice_id, speed=0.92)
        audio_path = os.path.join(tmpdir, f'tts_{clip_name}.mp3')
        _download_file(audio_url, audio_path)
        dur = get_audio_duration(audio_path)
        clip_path = os.path.join(tmpdir, f'tts_clip_{clip_name}.mp4')
        bg_img = None
        if vehicle_photos:
            try:
                bg_img = os.path.join(tmpdir, f'tts_bg_{clip_name}.jpg')
                _download_file(vehicle_photos[0], bg_img)
            except Exception:
                bg_img = None
        if bg_img and os.path.exists(bg_img):
            cmd = [
                'ffmpeg', '-y', '-loop', '1', '-i', bg_img, '-i', audio_path,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
                '-vf', f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1',
                '-c:a', 'aac', '-b:a', '128k', '-shortest',
                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', clip_path
            ]
        else:
            cmd = [
                'ffmpeg', '-y', '-f', 'lavfi',
                '-i', f'color=c=0x1a1a2e:s={W}x{H}:r=24',
                '-i', audio_path, '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
                '-c:a', 'aac', '-b:a', '128k', '-shortest', '-t', str(dur),
                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', clip_path
            ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode == 0 and os.path.exists(clip_path):
            print(f'[TTS-only] Built {clip_name}: {clip_path}')
            return clip_path
    except Exception as e:
        print(f'[TTS-only] Error: {e}')
    return None


def _concat_clips(clip_paths, output_path, tmpdir):
    concat_list = os.path.join(tmpdir, 'concat_list.txt')
    with open(concat_list, 'w') as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")
    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
        '-c:a', 'aac', '-b:a', '128k', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    if result.returncode != 0:
        err = result.stderr[-500:].decode('utf-8', errors='ignore') if result.stderr else ''
        raise RuntimeError(f'Concat failed: {err}')
    print(f'[Concat] {output_path} {round(os.path.getsize(output_path)/1024/1024, 1)}MB')


def compress_video_for_upload(input_path, tmpdir):
    try:
        sz = os.path.getsize(input_path)
        print(f'[Compress] Input: {round(sz/1024/1024, 1)}MB')
        if sz <= 40 * 1024 * 1024:
            return input_path
        out = os.path.join(tmpdir, 'final_compressed.mp4')
        for crf in [28, 32, 36]:
            res = subprocess.run([
                'ffmpeg', '-y', '-i', input_path,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', str(crf),
                '-vf', 'scale=1080:-2', '-c:a', 'aac', '-b:a', '96k',
                '-movflags', '+faststart', out
            ], capture_output=True, timeout=300)
            if res.returncode == 0 and os.path.exists(out):
                osz = os.path.getsize(out)
                print(f'[Compress] CRF {crf}: {round(osz/1024/1024, 1)}MB')
                if osz <= 45 * 1024 * 1024:
                    return out
        subprocess.run([
            'ffmpeg', '-y', '-i', input_path, '-c:v', 'libx264', '-preset', 'fast', '-crf', '38',
            '-vf', 'scale=720:-2', '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart', out
        ], capture_output=True, timeout=300)
        return out
    except Exception as e:
        print(f'[Compress] Error: {e}')
        return input_path


def build_walkaround_video(vehicle, script_segments, heygen_audio_path,
                           heygen_result, vehicle_photos, vehicle_video_url, tmpdir):
    """
    Pipeline:
    1. INTRO  - HeyGen avatar full-frame (Aaron facing camera on lot background)
    2. SEGMENTS - vehicle photo fills full 9:16 frame + Aaron PIP bottom-left corner
    3. OUTRO  - HeyGen avatar full-frame
    """
    segments = script_segments if isinstance(script_segments, dict) else {}
    voice_id = heygen_result.get('voice_id') if isinstance(heygen_result, dict) else None
    look_id = heygen_result.get('look_id') if isinstance(heygen_result, dict) else None
    avatar_group_id = heygen_result.get('avatar_group_id') if isinstance(heygen_result, dict) else None
    if not voice_id:
        voice_id = os.getenv('HEYGEN_VOICE_ID', '6ee20575cb9f4a7e9dc19096a958eab1')
    if not look_id:
        look_id = os.getenv('HEYGEN_LOOK_ID', 'ed119cc46f5f4a6d8a6687ac187cd779')
    if not avatar_group_id:
        avatar_group_id = os.getenv('HEYGEN_AVATAR_GROUP_ID', '202a882fdd924622bc00d1eca0bf00cd')

    intro_text = segments.get('intro', '')
    outro_text = segments.get('outro', '')
    segment_order = ['front', 'driver_side', 'rear', 'pass_side', 'interior']

    print(f'[Build] PIP walkaround. Segments: {list(segments.keys())}. Photos: {len(vehicle_photos)}')

    all_clips = []

    # INTRO: HeyGen avatar full-frame
    if intro_text:
        print('[Build] === INTRO ===')
        intro_clip = generate_heygen_avatar_clip(
            intro_text, look_id, avatar_group_id, voice_id, tmpdir, 'intro')
        if not intro_clip:
            print('[Build] Intro HeyGen failed, using TTS fallback')
            intro_clip = _build_tts_only_clip(intro_text, voice_id, tmpdir, 'intro', vehicle_photos)
        if intro_clip:
            all_clips.append(intro_clip)

    # PIP LOOP: generate short avatar clip to use as looping PIP during segments
    print('[Build] === PIP LOOP ===')
    pip_loop_clip = generate_heygen_avatar_clip(
        'Check this out.', look_id, avatar_group_id, voice_id, tmpdir, 'pip_loop')
    if pip_loop_clip:
        print(f'[Build] PIP loop ready: {pip_loop_clip}')
    else:
        print('[Build] PIP loop failed - segments will be audio-only overlay')

    # WALKAROUND SEGMENTS: vehicle photos + PIP
    print('[Build] === WALKAROUND SEGMENTS ===')
    for seg_name in segment_order:
        seg_text = segments.get(seg_name, '')
        if not seg_text or not seg_text.strip():
            continue

        audio_path = generate_tts_segment_audio(seg_text, voice_id, tmpdir, seg_name, speed=0.92)
        if not audio_path:
            continue

        audio_dur = get_audio_duration(audio_path)
        print(f'[Build] {seg_name}: {audio_dur:.1f}s')

        photo_indices = SEGMENT_PHOTO_MAP.get(seg_name, [])
        seg_photo_urls = [vehicle_photos[i] for i in photo_indices if i < len(vehicle_photos)]
        if len(seg_photo_urls) < 2 and vehicle_photos:
            start = min(photo_indices[0] if photo_indices else 0, len(vehicle_photos)-1)
            seg_photo_urls = vehicle_photos[start:start+3]
        if not seg_photo_urls and vehicle_photos:
            seg_photo_urls = vehicle_photos[:3]

        photo_paths = []
        for i, url in enumerate(seg_photo_urls[:5]):
            try:
                pp = os.path.join(tmpdir, f'photo_{seg_name}_{i}.jpg')
                _download_file(url, pp)
                photo_paths.append(pp)
            except Exception as e:
                print(f'[Build] Photo {i} error: {e}')

        if not photo_paths:
            continue

        seg_output = os.path.join(tmpdir, f'seg_{seg_name}_final.mp4')
        seg_clip = _build_pip_segment(
            photo_paths, audio_path, audio_dur, pip_loop_clip, seg_output, seg_name)
        if seg_clip:
            all_clips.append(seg_clip)

    # OUTRO: HeyGen avatar full-frame
    if outro_text:
        print('[Build] === OUTRO ===')
        outro_clip = generate_heygen_avatar_clip(
            outro_text, look_id, avatar_group_id, voice_id, tmpdir, 'outro')
        if not outro_clip:
            print('[Build] Outro HeyGen failed, using TTS fallback')
            outro_clip = _build_tts_only_clip(outro_text, voice_id, tmpdir, 'outro', vehicle_photos)
        if outro_clip:
            all_clips.append(outro_clip)

    if not all_clips:
        raise RuntimeError('No clips were built')

    print(f'[Build] Concatenating {len(all_clips)} clips...')
    if len(all_clips) == 1:
        final_path = all_clips[0]
    else:
        final_path = os.path.join(tmpdir, 'final_walkaround.mp4')
        _concat_clips(all_clips, final_path, tmpdir)

    return compress_video_for_upload(final_path, tmpdir)


# Legacy shims
def upload_audio_to_heygen(audio_path):
    return None

def generate_heygen_audio(script_text, voice_id, tmpdir):
    audio_url = _tts_call(script_text, voice_id)
    audio_path = os.path.join(tmpdir, 'script_audio.mp3')
    _download_file(audio_url, audio_path)
    return audio_path, audio_url

def run_video_translation(video_url, audio_url, tmpdir):
    return None
