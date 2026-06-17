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
            preferred = ['sharp', 'car', 'lot', 'outdoor', 'salesman', 'used', 'walkaround']
            for look in looks:
                name = (look.get('name') or look.get('look_name') or '').lower()
                if any(kw in name for kw in preferred):
                    return look.get('id') or look.get('look_id')
            if looks:
                return looks[0].get('id') or looks[0].get('look_id')
    except Exception as e:
        print(f'[get_look_id] error: {e}')
    return None


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


def _tts_call(text, voice_id, speed=0.92):
    sid = get_starfish_voice_id(voice_id)
    payload = {'text': text, 'voice_id': sid, 'speed': speed, 'input_type': 'text', 'language': 'en'}
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(HEYGEN_BASE + '/v3/voices/speech',
                              headers=heygen_headers(), json=payload, timeout=180)
            print(f'[TTS] Attempt {attempt+1}: {r.status_code}')
            if r.status_code == 200:
                audio_url = r.json().get('data', {}).get('audio_url')
                if audio_url:
                    return audio_url
            elif r.status_code in (400, 404, 422):
                pub = requests.get(
                    HEYGEN_BASE + '/v3/voices?type=public&engine=starfish&language=English&limit=5',
                    headers=heygen_headers(), timeout=30)
                if pub.status_code == 200 and pub.json().get('data'):
                    payload['voice_id'] = pub.json()['data'][0]['voice_id']
            last_err = RuntimeError(f'TTS {r.status_code}')
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
    print(f'[Download] {os.path.basename(dest_path)} ({os.path.getsize(dest_path)} bytes)')


def generate_heygen_avatar_clip(text, look_id, avatar_group_id, voice_id, tmpdir, clip_name):
    print(f'[HeyGen] Generating: {clip_name}')
    sid = get_starfish_voice_id(voice_id)
    # Use look_id as avatar_id for /v3/videos endpoint
    avatar_id_to_use = look_id or avatar_group_id
    payload = {
        'type': 'avatar',
        'avatar_id': avatar_id_to_use,
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
def _build_photo_bg_clip(photo_path, duration, output_path):
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
    err = r.stderr[-150:].decode('utf-8', errors='ignore') if r.stderr else ''
    print(f'[BgClip] Failed: {err}')
    return False


def _build_pip_segment(photo_paths, audio_path, audio_dur, pip_source, output_path, seg_name):
    n = len(photo_paths)
    if n == 0:
        return None
    per_photo = max(2.0, min(audio_dur / max(n, 1), 6.0))
    tmpdir = os.path.dirname(output_path)
    bg_clips = []
    for idx, pp in enumerate(photo_paths):
        bgp = pp + f'_bg{idx}.mp4'
        if _build_photo_bg_clip(pp, per_photo, bgp):
            bg_clips.append(bgp)
    if not bg_clips:
        return None
    if len(bg_clips) == 1:
        bg_video = bg_clips[0]
    else:
        bg_video = os.path.join(tmpdir, f'bg_{seg_name}.mp4')
        clist = os.path.join(tmpdir, f'bgc_{seg_name}.txt')
        with open(clist, 'w') as f:
            for c in bg_clips:
                f.write(f"file '{c}'\n")
        cr = subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', clist,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
            '-pix_fmt', 'yuv420p', '-an', bg_video
        ], capture_output=True, timeout=300)
        if cr.returncode != 0:
            bg_video = bg_clips[0]
    if not pip_source or not os.path.exists(pip_source):
        cmd = [
            'ffmpeg', '-y', '-i', bg_video, '-i', audio_path,
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
            '-shortest', '-movflags', '+faststart', output_path
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(output_path):
            return output_path
        return None
    fc = (
        f'[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,'
        f'crop={W}:{H},setsar=1,trim=duration={audio_dur:.3f},setpts=PTS-STARTPTS[bg];'
        f'[1:v]scale={PIP_W}:{PIP_H}:force_original_aspect_ratio=increase,'
        f'crop={PIP_W}:{PIP_H},setsar=1,loop=loop=-1:size=32767,'
        f'trim=duration={audio_dur:.3f},setpts=PTS-STARTPTS[pip];'
        f'[bg][pip]overlay={PIP_X}:{PIP_Y}:shortest=1[out]'
    )
    cmd = [
        'ffmpeg', '-y',
        '-i', bg_video, '-i', pip_source, '-i', audio_path,
        '-filter_complex', fc,
        '-map', '[out]', '-map', '2:a',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
        '-c:a', 'aac', '-b:a', '128k',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
        '-t', str(audio_dur + 0.5), output_path
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode == 0 and os.path.exists(output_path):
        print(f'[PIP] {seg_name} done')
        return output_path
    err = r.stderr[-300:].decode('utf-8', errors='ignore') if r.stderr else ''
    print(f'[PIP] Composite failed {seg_name}: {err[-150:]}')
    cmd2 = [
        'ffmpeg', '-y', '-i', bg_video, '-i', audio_path,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
        '-shortest', '-movflags', '+faststart', output_path
    ]
    r2 = subprocess.run(cmd2, capture_output=True, timeout=120)
    if r2.returncode == 0 and os.path.exists(output_path):
        return output_path
    return None


def _build_tts_only_clip(text, voice_id, tmpdir, clip_name, vehicle_photos):
    try:
        audio_url = _tts_call(text, voice_id, speed=0.92)
        audio_path = os.path.join(tmpdir, f'tts_{clip_name}.mp3')
        _download_file(audio_url, audio_path)
        dur = get_audio_duration(audio_path)
        clip_path = os.path.join(tmpdir, f'tts_clip_{clip_name}.mp4')
        bg_img = None
        if vehicle_photos:
            try:
                bg_img = os.path.join(tmpdir, f'bg_{clip_name}.jpg')
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
                '-i', audio_path,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
                '-c:a', 'aac', '-b:a', '128k', '-shortest', '-t', str(dur),
                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', clip_path
            ]
        res = subprocess.run(cmd, capture_output=True, timeout=120)
        if res.returncode == 0 and os.path.exists(clip_path):
            return clip_path
    except Exception as e:
        print(f'[TTS-only] {clip_name} error: {e}')
    return None


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
    look_id = heygen_result.get('look_id') if isinstance(heygen_result, dict) else None
    avatar_group_id = heygen_result.get('avatar_group_id') if isinstance(heygen_result, dict) else None
    voice_id = voice_id or os.getenv('HEYGEN_VOICE_ID', '6ee20575cb9f4a7e9dc19096a958eab1')
    look_id = look_id or os.getenv('HEYGEN_LOOK_ID', 'ed119cc46f5f4a6d8a6687ac187cd779')
    avatar_group_id = avatar_group_id or os.getenv('HEYGEN_AVATAR_GROUP_ID', '202a882fdd924622bc00d1eca0bf00cd')

    intro_text = segments.get('intro', '')
    outro_text = segments.get('outro', '')
    segment_order = ['front', 'driver_side', 'rear', 'pass_side', 'interior']
    print(f'[Build] PIP walkaround. Photos: {len(vehicle_photos)}')

    all_clips = []

    if intro_text:
        print('[Build] == INTRO ==')
        ic = generate_heygen_avatar_clip(intro_text, look_id, avatar_group_id, voice_id, tmpdir, 'intro')
        if not ic:
            ic = _build_tts_only_clip(intro_text, voice_id, tmpdir, 'intro', vehicle_photos)
        if ic:
            all_clips.append(ic)

    print('[Build] == PIP LOOP ==')
    pip_clip = generate_heygen_avatar_clip(
        'Check this out.', look_id, avatar_group_id, voice_id, tmpdir, 'pip_loop')
    print(f'[Build] PIP loop: {pip_clip}')

    print('[Build] == SEGMENTS ==')
    for seg_name in segment_order:
        seg_text = segments.get(seg_name, '')
        if not seg_text or not seg_text.strip():
            continue
        audio_path = generate_tts_segment_audio(seg_text, voice_id, tmpdir, seg_name)
        if not audio_path:
            continue
        audio_dur = get_audio_duration(audio_path)
        photo_indices = SEGMENT_PHOTO_MAP.get(seg_name, [])
        seg_urls = [vehicle_photos[i] for i in photo_indices if i < len(vehicle_photos)]
        if len(seg_urls) < 2 and vehicle_photos:
            start = min(photo_indices[0] if photo_indices else 0, len(vehicle_photos)-1)
            seg_urls = vehicle_photos[start:start+3]
        if not seg_urls and vehicle_photos:
            seg_urls = vehicle_photos[:3]
        photo_paths = []
        for i, url in enumerate(seg_urls[:5]):
            try:
                pp = os.path.join(tmpdir, f'photo_{seg_name}_{i}.jpg')
                _download_file(url, pp)
                photo_paths.append(pp)
            except Exception as e:
                print(f'[Build] Photo error: {e}')
        if not photo_paths:
            continue
        seg_out = os.path.join(tmpdir, f'seg_{seg_name}_final.mp4')
        sc = _build_pip_segment(photo_paths, audio_path, audio_dur, pip_clip, seg_out, seg_name)
        if sc:
            all_clips.append(sc)

    if outro_text:
        print('[Build] == OUTRO ==')
        oc = generate_heygen_avatar_clip(outro_text, look_id, avatar_group_id, voice_id, tmpdir, 'outro')
        if not oc:
            oc = _build_tts_only_clip(outro_text, voice_id, tmpdir, 'outro', vehicle_photos)
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


def upload_audio_to_heygen(audio_path):
    return None


def generate_heygen_audio(script_text, voice_id, tmpdir):
    audio_url = _tts_call(script_text, voice_id)
    audio_path = os.path.join(tmpdir, 'script_audio.mp3')
    _download_file(audio_url, audio_path)
    return audio_path, audio_url


def run_video_translation(video_url, audio_url, tmpdir):
    return None
