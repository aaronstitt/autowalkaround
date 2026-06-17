import os, requests, time, json, subprocess, math

HEADERS = {'User-Agent': 'Mozilla/5.0'}
HEYGEN_BASE = 'https://api.heygen.com'
HEYGEN_POLL_INTERVAL = 15
HEYGEN_POLL_MAX = 240

SEGMENT_PHOTO_MAP = {
    'front':       [0, 1, 2],
    'driver_side': [3, 4],
    'rear':        [5, 6, 7],
    'pass_side':   [8, 9, 10],
    'interior':    list(range(11, 29)),
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
            preferred = ['sharp', 'car', 'lot', 'outdoor', 'salesman', 'used']
            for look in looks:
                name = (look.get('name') or look.get('look_name') or '').lower()
                if any(kw in name for kw in preferred):
                    return look.get('id') or look.get('look_id')
            if looks:
                return looks[0].get('id') or looks[0].get('look_id')
    except Exception as e:
        print('[get_look_id] error:', e)
    return None


def get_starfish_voice_id(preferred_voice_id):
    print('[TTS] Finding starfish voice, preferred:', preferred_voice_id)
    try:
        r = requests.get(HEYGEN_BASE + '/v3/voices?type=private&engine=starfish&limit=20',
                         headers=heygen_headers(), timeout=30)
        print('[TTS] Private starfish voices:', r.status_code, r.text[:300])
        if r.status_code == 200:
            voices = r.json().get('data', [])
            if voices:
                vid = voices[0].get('voice_id')
                print('[TTS] Using private starfish voice:', vid)
                return vid
    except Exception as e:
        print('[TTS] Private voice lookup error:', e)
    try:
        r = requests.get(
            HEYGEN_BASE + '/v3/voices?type=public&engine=starfish&language=English&gender=male&limit=5',
            headers=heygen_headers(), timeout=30)
        if r.status_code == 200:
            voices = r.json().get('data', [])
            if voices:
                vid = voices[0].get('voice_id')
                print('[TTS] Using public starfish voice:', vid)
                return vid
    except Exception as e:
        print('[TTS] Public voice lookup error:', e)
    print('[TTS] Falling back to preferred voice:', preferred_voice_id)
    return preferred_voice_id


def _tts_call(text, voice_id, speed, tmpdir, filename):
    starfish_voice_id = get_starfish_voice_id(voice_id)
    payload = {'text': text, 'voice_id': starfish_voice_id, 'speed': speed,
               'input_type': 'text', 'language': 'en'}
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(HEYGEN_BASE + '/v3/voices/speech',
                              headers=heygen_headers(), json=payload, timeout=180)
            print('[TTS] attempt', attempt+1, r.status_code, r.text[:200])
            if r.status_code == 200:
                audio_url = r.json().get('data', {}).get('audio_url')
                if audio_url:
                    path = os.path.join(tmpdir, filename)
                    _download_file(audio_url, path)
                    return path, audio_url
            elif r.status_code in (400, 404, 422):
                pub = requests.get(HEYGEN_BASE + '/v3/voices?type=public&engine=starfish&language=English&limit=5',
                                   headers=heygen_headers(), timeout=30)
                if pub.status_code == 200 and pub.json().get('data'):
                    payload['voice_id'] = pub.json()['data'][0]['voice_id']
            last_err = RuntimeError('TTS ' + str(r.status_code) + ' ' + r.text[:200])
            time.sleep(5 if attempt == 0 else 15)
        except Exception as e:
            last_err = e
            time.sleep(10)
    raise RuntimeError('TTS failed: ' + str(last_err))


def generate_tts_audio(script_text, voice_id, tmpdir, speed=0.92):
    path, url = _tts_call(script_text, voice_id, speed, tmpdir, 'script_audio.mp3')
    return path, url


def generate_tts_segment_audio(text, voice_id, tmpdir, seg_name, speed=0.92):
    try:
        path, _ = _tts_call(text, voice_id, speed, tmpdir, 'seg_' + seg_name + '.mp3')
        return path
    except Exception as e:
        print('[TTS_SEG] Failed for', seg_name, ':', e)
        return None


def get_audio_duration(audio_path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except Exception as e:
        print('[Duration] Error:', e)
        return 15.0


def generate_heygen_avatar_intro(intro_text, look_id, avatar_group_id, voice_id, tmpdir):
    print('[Intro] Generating HeyGen avatar intro video...')
    starfish_voice_id = get_starfish_voice_id(voice_id)
    payload = {
        'title': 'AutoWalkaround Intro',
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
                'input_text': intro_text,
                'voice_id': starfish_voice_id,
                'speed': 0.92,
            },
            'background': {'type': 'color', 'value': '#1a1a1a'}
        }],
        'dimension': {'width': 1080, 'height': 1920},
        'test': False,
    }
    r = None
    for endpoint in ['/v2/video/generate']:
        try:
            r = requests.post(HEYGEN_BASE + endpoint, headers=heygen_headers(),
                              json=payload, timeout=60)
            print('[Intro] Avatar video', endpoint, r.status_code, r.text[:300])
            if r.status_code in (200, 201, 202):
                break
        except Exception as e:
            print('[Intro] Endpoint error', endpoint, ':', e)
    if r is None or r.status_code not in (200, 201, 202):
        print('[Intro] HeyGen avatar video failed, using TTS fallback')
        return None
    resp = r.json()
    video_id = (resp.get('data', {}) or {}).get('video_id') or resp.get('video_id')
    if not video_id:
        print('[Intro] No video_id:', resp)
        return None
    print('[Intro] Polling video_id:', video_id)
    for i in range(60):
        time.sleep(10)
        sr = requests.get(HEYGEN_BASE + '/v1/video_status.get?video_id=' + video_id,
                          headers=heygen_headers(), timeout=30)
        if sr.status_code == 200:
            sd = sr.json().get('data', {})
            status = sd.get('status', 'unknown').lower()
            print('[Intro] Poll', i+1, ':', status)
            if status == 'completed':
                video_url = sd.get('video_url')
                if video_url:
                    intro_path = os.path.join(tmpdir, 'intro_avatar.mp4')
                    _download_file(video_url, intro_path)
                    return intro_path
                return None
            elif status in ('failed', 'error'):
                print('[Intro] Failed:', sd)
                return None
    print('[Intro] Timed out')
    return None


def _build_photo_clip(photo_paths, audio_path, audio_duration, output_path):
    n = len(photo_paths)
    if n == 0:
        return None
    per_photo = max(1.5, min(audio_duration / n, 6.0))
    try:
        if n == 1:
            cmd = [
                'ffmpeg', '-y',
                '-loop', '1', '-i', photo_paths[0],
                '-i', audio_path,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
                '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1',
                '-c:a', 'aac', '-b:a', '128k', '-shortest',
                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', output_path
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=180)
        else:
            cmd = ['ffmpeg', '-y']
            for p in photo_paths:
                cmd += ['-loop', '1', '-t', str(per_photo + 0.5), '-i', p]
            cmd += ['-i', audio_path]
            parts = []
            for i in range(n):
                parts.append(
                    '[' + str(i) + ':v]scale=1080:1920:force_original_aspect_ratio=decrease,'
                    'pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=24[v' + str(i) + ']'
                )
            xd = 0.4
            prev = 'v0'
            offset = per_photo - xd
            for i in range(1, n):
                out_lbl = 'xf' + str(i) if i < n - 1 else 'vout'
                parts.append('[' + prev + '][v' + str(i) + ']xfade=transition=fade:duration=' +
                             str(xd) + ':offset=' + str(round(offset, 2)) + '[' + out_lbl + ']')
                prev = out_lbl
                offset += per_photo
            cmd += ['-filter_complex', ';'.join(parts)]
            cmd += ['-map', '[vout]', '-map', str(n) + ':a',
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
                    '-c:a', 'aac', '-b:a', '128k', '-shortest',
                    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', output_path]
            result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode == 0 and os.path.exists(output_path):
            print('[Clip] Built:', output_path, str(round(os.path.getsize(output_path)/1024/1024, 1)) + 'MB')
            return output_path
        print('[Clip] ffmpeg error:', result.stderr[-400:] if result.stderr else 'none')
        if n > 1:
            return _build_photo_clip([photo_paths[0]], audio_path, audio_duration, output_path)
    except Exception as e:
        print('[Clip] Error:', e)
    return None


def _concat_clips(clip_paths, output_path, tmpdir):
    concat_list = os.path.join(tmpdir, 'concat_list.txt')
    with open(concat_list, 'w') as f:
        for clip in clip_paths:
            f.write("file '" + clip + "'" + chr(10))
    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
        '-c:a', 'aac', '-b:a', '128k', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    if result.returncode != 0:
        err = result.stderr[-500:].decode('utf-8', errors='ignore') if result.stderr else 'unknown'
        raise RuntimeError('Concat failed: ' + err)
    print('[Concat]', output_path, str(round(os.path.getsize(output_path)/1024/1024, 1)) + 'MB')


def build_intro_tts_clip(intro_text, voice_id, look_id, tmpdir):
    print('[IntroFallback] Building TTS intro clip...')
    audio_path = generate_tts_segment_audio(intro_text, voice_id, tmpdir, 'intro', speed=0.90)
    if not audio_path:
        raise RuntimeError('Could not generate intro TTS')
    look_img_path = None
    if look_id:
        try:
            r = requests.get(HEYGEN_BASE + '/v3/avatars/looks?ownership=private',
                             headers=heygen_headers(), timeout=30)
            if r.status_code == 200:
                data = r.json().get('data', [])
                looks = data if isinstance(data, list) else data.get('looks', [])
                for look in looks:
                    lid = look.get('id') or look.get('look_id')
                    if str(lid) == str(look_id):
                        thumb = look.get('thumbnail_url') or look.get('preview_image_url')
                        if thumb:
                            look_img_path = os.path.join(tmpdir, 'look_thumb.jpg')
                            _download_file(thumb, look_img_path)
                            break
        except Exception as e:
            print('[IntroFallback] Look thumbnail error:', e)
    intro_clip_path = os.path.join(tmpdir, 'intro_clip.mp4')
    if look_img_path and os.path.exists(look_img_path):
        cmd = [
            'ffmpeg', '-y', '-loop', '1', '-i', look_img_path, '-i', audio_path,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
            '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1',
            '-c:a', 'aac', '-b:a', '128k', '-shortest',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', intro_clip_path
        ]
    else:
        dur = get_audio_duration(audio_path)
        cmd = [
            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=1080x1920:r=24',
            '-i', audio_path, '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
            '-c:a', 'aac', '-b:a', '128k', '-shortest', '-t', str(dur),
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', intro_clip_path
        ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode == 0 and os.path.exists(intro_clip_path):
        print('[IntroFallback] Built intro clip:', intro_clip_path)
        return intro_clip_path
    raise RuntimeError('Intro clip build failed')


def build_vehicle_walkaround_video(vehicle_photos, vehicle_video_url, segments, voice_id, tmpdir):
    print('[Vehicle] Building vehicle walkaround... photos:', len(vehicle_photos))
    segment_order = ['front', 'driver_side', 'rear', 'pass_side', 'interior']
    clips = []
    for seg_name in segment_order:
        seg_text = segments.get(seg_name, '')
        if not seg_text:
            continue
        audio_path = generate_tts_segment_audio(seg_text, voice_id, tmpdir, seg_name)
        if not audio_path:
            continue
        audio_dur = get_audio_duration(audio_path)
        print('[Vehicle]', seg_name, 'audio:', round(audio_dur, 1), 's')
        photo_indices = SEGMENT_PHOTO_MAP.get(seg_name, [])
        seg_photos = [vehicle_photos[i] for i in photo_indices if i < len(vehicle_photos)]
        if len(seg_photos) < 1 and vehicle_photos:
            start = min((photo_indices[0] if photo_indices else 0), len(vehicle_photos)-1)
            seg_photos = vehicle_photos[start:start+3]
        if not seg_photos and vehicle_photos:
            seg_photos = vehicle_photos[:2]
        photo_paths = []
        for i, url in enumerate(seg_photos[:4]):
            try:
                pp = os.path.join(tmpdir, 'photo_' + seg_name + '_' + str(i) + '.jpg')
                _download_file(url, pp)
                photo_paths.append(pp)
            except Exception as e:
                print('[Vehicle] Photo error:', e)
        if not photo_paths:
            continue
        clip_path = os.path.join(tmpdir, 'clip_' + seg_name + '.mp4')
        clip = _build_photo_clip(photo_paths, audio_path, audio_dur, clip_path)
        if clip:
            clips.append(clip)
    if not clips:
        raise RuntimeError('No vehicle clips built')
    if vehicle_video_url:
        try:
            lv_path = os.path.join(tmpdir, 'listing_video.mp4')
            _download_file(vehicle_video_url, lv_path)
            lv_trim = os.path.join(tmpdir, 'listing_trimmed.mp4')
            subprocess.run([
                'ffmpeg', '-y', '-i', lv_path, '-t', '12',
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '28', '-an',
                '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1',
                lv_trim
            ], capture_output=True, timeout=60)
            if os.path.exists(lv_trim) and os.path.getsize(lv_trim) > 10000:
                clips.insert(-1, lv_trim)
                print('[Vehicle] Added listing video clip')
        except Exception as e:
            print('[Vehicle] Listing video error (non-fatal):', e)
    vehicle_path = os.path.join(tmpdir, 'vehicle_walkaround.mp4')
    _concat_clips(clips, vehicle_path, tmpdir)
    return vehicle_path


def compress_video_for_upload(input_path, tmpdir):
    try:
        sz = os.path.getsize(input_path)
        print('[Compress] Input:', round(sz/1024/1024, 1), 'MB')
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
                print('[Compress] CRF', crf, ':', round(osz/1024/1024, 1), 'MB')
                if osz <= 45 * 1024 * 1024:
                    return out
        subprocess.run([
            'ffmpeg', '-y', '-i', input_path, '-c:v', 'libx264', '-preset', 'fast', '-crf', '38',
            '-vf', 'scale=720:-2', '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart', out
        ], capture_output=True, timeout=300)
        return out
    except Exception as e:
        print('[Compress] Error:', e)
        return input_path


def _download_file(url, dest_path):
    r = requests.get(url, headers=HEADERS, stream=True, timeout=300)
    r.raise_for_status()
    with open(dest_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
    print('[Download]', dest_path, '(' + str(os.path.getsize(dest_path)) + ' bytes)')


# ── Legacy shims ──────────────────────────────────────────────────────────────

def get_avatar_source_video_url(avatar_group_id):
    return None


def upload_audio_to_heygen(audio_path):
    return None


def generate_heygen_audio(script_text, avatar_look_id, voice_id, tmpdir):
    audio_path, audio_url = generate_tts_audio(script_text, voice_id, tmpdir)
    return audio_path, {'audio_path': audio_path, 'audio_url': audio_url, 'look_id': avatar_look_id}


def build_walkaround_video(vehicle, script_segments, heygen_audio_path,
                            heygen_result, vehicle_photos, vehicle_video_url, tmpdir):
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
    print('[Build] walkaround v4 build, segments:', list(segments.keys()), 'photos:', len(vehicle_photos))

    all_clips = []

    if intro_text:
        intro_clip = generate_heygen_avatar_intro(intro_text, look_id, avatar_group_id, voice_id, tmpdir)
        if not intro_clip:
            print('[Build] HeyGen avatar intro failed, using TTS fallback...')
            try:
                intro_clip = build_intro_tts_clip(intro_text, voice_id, look_id, tmpdir)
            except Exception as e:
                print('[Build] Intro TTS fallback failed:', e)
                intro_clip = None
        if intro_clip:
            all_clips.append(intro_clip)

    vehicle_clip = build_vehicle_walkaround_video(
        vehicle_photos, vehicle_video_url, segments, voice_id, tmpdir
    )
    all_clips.append(vehicle_clip)

    if outro_text:
        last_photo = None
        if vehicle_photos:
            try:
                lp = os.path.join(tmpdir, 'outro_bg.jpg')
                _download_file(vehicle_photos[0], lp)
                last_photo = lp
            except Exception:
                pass
        try:
            outro_audio = generate_tts_segment_audio(outro_text, voice_id, tmpdir, 'outro', speed=0.90)
            if outro_audio:
                outro_dur = get_audio_duration(outro_audio)
                outro_clip = os.path.join(tmpdir, 'outro_clip.mp4')
                if last_photo:
                    res = subprocess.run([
                        'ffmpeg', '-y', '-loop', '1', '-i', last_photo, '-i', outro_audio,
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
                        '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1',
                        '-c:a', 'aac', '-b:a', '128k', '-shortest',
                        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', outro_clip
                    ], capture_output=True, timeout=60)
                else:
                    res = subprocess.run([
                        'ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=1080x1920:r=24',
                        '-i', outro_audio, '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
                        '-c:a', 'aac', '-b:a', '128k', '-t', str(outro_dur),
                        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', outro_clip
                    ], capture_output=True, timeout=60)
                if res.returncode == 0 and os.path.exists(outro_clip):
                    all_clips.append(outro_clip)
        except Exception as e:
            print('[Build] Outro clip error (non-fatal):', e)

    if len(all_clips) == 1:
        final_path = all_clips[0]
    else:
        final_path = os.path.join(tmpdir, 'final_walkaround.mp4')
        _concat_clips(all_clips, final_path, tmpdir)

    return compress_video_for_upload(final_path, tmpdir)
