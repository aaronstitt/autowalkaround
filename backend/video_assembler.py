import os, requests, time, json, subprocess, math, random

HEADERS = {'User-Agent': 'Mozilla/5.0'}
HEYGEN_BASE = 'https://api.heygen.com'
HEYGEN_POLL_INTERVAL = 15
HEYGEN_POLL_MAX = 240

# Photo indices per segment - expanded to use more photos per area
SEGMENT_PHOTO_MAP = {
        'front':       [0, 1, 2],
        'driver_side': [3, 4, 5],
        'rear':        [6, 7, 8],
        'pass_side':   [9, 10, 11],
        'interior':    list(range(12, 29)),
}

# How close/zoomed we want per segment to simulate being 1-2 feet from vehicle
SEGMENT_ZOOM = {
        'front':       1.25,   # slightly zoomed in - approaching vehicle
        'driver_side': 1.35,   # close to door handle level
        'rear':        1.20,   # rear badge/taillight shots
        'pass_side':   1.30,   # walking along passenger side
        'interior':    1.40,   # camera through window/door interior
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


def _tts_call(text, voice_id, speed=0.92):
        starfish_id = get_starfish_voice_id(voice_id)
        payload = {'text': text, 'voice_id': starfish_id, 'speed': speed, 'input_type': 'text', 'language': 'en'}
        last_err = None
        for attempt in range(3):
                    try:
                                    r = requests.post(HEYGEN_BASE + '/v3/voices/speech',
                                                                                    headers=heygen_headers(), json=payload, timeout=180)
                                    print(f'[TTS] Attempt {attempt+1}: {r.status_code} {r.text[:300]}')
                                    if r.status_code == 200:
                                                        audio_url = r.json().get('data', {}).get('audio_url')
                                                        if audio_url:
                                                                                return audio_url
                                    elif r.status_code in (400, 404, 422):
                                                        pub_r = requests.get(HEYGEN_BASE + '/v3/voices?type=public&engine=starfish&language=English&limit=5',
                                                                                                                  headers=heygen_headers(), timeout=30)
                                                        if pub_r.status_code == 200 and pub_r.json().get('data'):
                                                                                payload['voice_id'] = pub_r.json()['data'][0]['voice_id']
                                                                                print(f'[TTS] Retrying with public voice: {payload["voice_id"]}')
                                                                        last_err = RuntimeError(f'TTS {r.status_code}: {r.text[:200]}')
                                                    time.sleep(2)
except Exception as e:
            last_err = e
            time.sleep(2)
    raise last_err or RuntimeError('TTS failed after retries')


def generate_tts_audio(script_text, voice_id, tmpdir):
        print(f'[TTS] Full script TTS, {len(script_text)} chars')
        audio_url = _tts_call(script_text, voice_id, speed=0.92)
        audio_path = os.path.join(tmpdir, 'script_audio.mp3')
        _download_file(audio_url, audio_path)
        print(f'[TTS] Downloaded: {audio_path} ({os.path.getsize(audio_path)} bytes)')
        return audio_path, audio_url


def generate_tts_segment_audio(text, voice_id, tmpdir, seg_name, speed=0.92):
        if not text or not text.strip():
                    return None
                try:
                            audio_url = _tts_call(text, voice_id, speed=speed)
                            out = os.path.join(tmpdir, f'seg_{seg_name}.mp3')
                            _download_file(audio_url, out)
                            print(f'[TTS] Segment {seg_name}: {out} ({os.path.getsize(out)} bytes)')
                            return out
except Exception as e:
        print(f'[TTS] Segment {seg_name} error: {e}')
        return None


def get_audio_duration(path):
        try:
                    r = subprocess.run(
                                    ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                                                  '-of', 'default=noprint_wrappers=1:nokey=1', path],
                                    capture_output=True, timeout=30
                    )
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


def _build_motion_clip(photo_paths, audio_path, audio_duration, output_path, seg_name='unknown'):
        """
            Build a video clip from photos with realistic handheld walking motion.
                Simulates a person holding a phone 1-2 feet from a vehicle and walking around it.
                    Uses FFmpeg zoompan filter with drift, subtle rotation, and hard cuts between photos.
                        No crossfades - just direct cuts like real walking footage.
                            """
    n = len(photo_paths)
    if n == 0:
                return None

    # Time per photo - aim for 2-4 seconds each, like real walking footage
    per_photo = max(2.0, min(audio_duration / n, 5.0))
    zoom_level = SEGMENT_ZOOM.get(seg_name, 1.30)

    print(f'[Motion] {seg_name}: {n} photos, {per_photo:.1f}s each, zoom={zoom_level}')

    # Build individual motion clips per photo, then concatenate
    photo_clips = []
    for idx, photo_path in enumerate(photo_paths):
                clip_path = photo_path.replace('.jpg', f'_motion_{idx}.mp4').replace('.jpeg', f'_motion_{idx}.mp4')
        if not clip_path.endswith('.mp4'):
                        clip_path = photo_path + f'_motion_{idx}.mp4'

        # Alternate zoom direction per photo for variety
        # Even photos: zoom in (approaching); odd: zoom out (pulling back slightly)
        if idx % 2 == 0:
                        zoom_start = zoom_level
                        zoom_end = zoom_level * 1.08
else:
            zoom_start = zoom_level * 1.10
            zoom_end = zoom_level * 1.02

        # Gentle drift direction - simulate walking left-to-right or tilting
        drift_directions = [
                        (0, 5),     # slow drift right
                        (0, -5),    # slow drift left
                        (3, 2),     # slight down-right
                        (-3, 2),    # slight down-left
                        (2, -3),    # slight up-right
        ]
        dx, dy = drift_directions[idx % len(drift_directions)]

        # FFmpeg zoompan filter:
        # z: zoom level expression (interpolated over duration)
        # x: horizontal position (with drift)
        # y: vertical position (with drift)
        # d: duration in frames (at 24fps)
        frames = int(per_photo * 24)
        frames = max(frames, 48)  # minimum 2 seconds

        # zoompan works on a 1080x1920 source
        # We scale up to give zoom room, then crop to 1080x1920
        # Input zoom range: 1.0 = original, values >1.0 zoom in
        # zoompan 'z' param: values from 1.0 to 2.0+ (1.0 = no zoom)

        zoom_expr = f'if(lte(on,1),{zoom_start},min(zoom+({zoom_end}-{zoom_start})/{frames},{zoom_end}))'
        x_expr = f'iw/2-(iw/zoom/2)+{dx}*(on/{frames})'
        y_expr = f'ih/2-(ih/zoom/2)+{dy}*(on/{frames})'

        # Build the filter chain:
        # 1. Scale source to 2x to give zoom room (zoompan needs oversized input)
        # 2. Apply zoompan for motion
        # 3. Crop to final 1080x1920
        vf = (
                        f'scale=2160:3840:force_original_aspect_ratio=increase,'
                        f'crop=2160:3840,'
                        f'zoompan=z=\'{zoom_expr}\':x=\'{x_expr}\':y=\'{y_expr}\':'
                        f'd={frames}:s=1080x1920:fps=24,'
                        f'setsar=1'
        )

        cmd = [
                        'ffmpeg', '-y',
                        '-loop', '1', '-framerate', '24', '-i', photo_path,
                        '-t', str(per_photo),
                        '-vf', vf,
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
                        '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                        '-an',  # no audio in individual clips
                        clip_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode == 0 and os.path.exists(clip_path):
                        photo_clips.append(clip_path)
                        print(f'[Motion] Photo {idx} clip OK: {clip_path}')
else:
                err = result.stderr[-300:].decode('utf-8', errors='ignore') if result.stderr else 'unknown'
                print(f'[Motion] Photo {idx} zoompan failed, using simple crop: {err[-100:]}')
                # Fallback: simple crop-to-fill static clip
                fallback_path = photo_path + f'_static_{idx}.mp4'
            fb_cmd = [
                                'ffmpeg', '-y', '-loop', '1', '-framerate', '24', '-i', photo_path,
                                '-t', str(per_photo),
                                '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1',
                                '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
                                '-pix_fmt', 'yuv420p', '-an', fallback_path
            ]
            fb_result = subprocess.run(fb_cmd, capture_output=True, timeout=60)
            if fb_result.returncode == 0:
                                photo_clips.append(fallback_path)

    if not photo_clips:
                return None

    if len(photo_clips) == 1:
                # Single photo clip - add audio
                cmd = [
                                'ffmpeg', '-y', '-i', photo_clips[0], '-i', audio_path,
                                '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
                                '-shortest', '-movflags', '+faststart', output_path
                ]
                subprocess.run(cmd, capture_output=True, timeout=120)
                return output_path if os.path.exists(output_path) else None

    # Concatenate photo clips (hard cuts, no transitions - like real walking video)
    tmpdir = os.path.dirname(output_path)
    concat_no_audio = output_path.replace('.mp4', '_noaudio.mp4')
    concat_list = output_path.replace('.mp4', '_concat.txt')
    with open(concat_list, 'w') as f:
                for clip in photo_clips:
                                f.write(f"file '{clip}'\n")

            concat_cmd = [
                        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
                        '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                        '-an', concat_no_audio
            ]
    concat_result = subprocess.run(concat_cmd, capture_output=True, timeout=300)
    if concat_result.returncode != 0:
                err = concat_result.stderr[-300:].decode('utf-8', errors='ignore')
                print(f'[Motion] Concat failed: {err}')
                return None

    # Add audio to the combined video
    cmd = [
                'ffmpeg', '-y', '-i', concat_no_audio, '-i', audio_path,
                '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
                '-shortest', '-movflags', '+faststart', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=180)
    if result.returncode == 0 and os.path.exists(output_path):
                sz = os.path.getsize(output_path)
                print(f'[Motion] {seg_name} clip done: {output_path} ({sz/1024/1024:.1f}MB)')
                return output_path
            err = result.stderr[-300:].decode('utf-8', errors='ignore') if result.stderr else 'unknown'
    print(f'[Motion] Final combine failed: {err}')
    return None


def _build_video_segment_clip(video_url, audio_path, audio_duration, output_path, seg_name='unknown'):
        """
            Extract a segment from the listing video and use it for a section.
                Crops to 1080x1920 vertical format.
                    """
        tmpdir = os.path.dirname(output_path)
        raw_video = os.path.join(tmpdir, f'raw_video_{seg_name}.mp4')
        try:
                    _download_file(video_url, raw_video)
except Exception as e:
        print(f'[VideoSeg] Download failed: {e}')
        return None

    # Get video duration
    vid_dur = get_audio_duration(raw_video)
    print(f'[VideoSeg] Listing video duration: {vid_dur:.1f}s, need: {audio_duration:.1f}s')

    # Crop listing video to vertical 1080x1920 and loop/trim to audio duration
    cmd = [
                'ffmpeg', '-y',
                '-stream_loop', '-1',  # loop if needed
                '-i', raw_video, '-i', audio_path,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
                '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1',
                '-c:a', 'aac', '-b:a', '128k', '-shortest',
                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode == 0 and os.path.exists(output_path):
                print(f'[VideoSeg] Listing video clip OK: {output_path}')
                return output_path
            err = result.stderr[-300:].decode('utf-8', errors='ignore') if result.stderr else ''
    print(f'[VideoSeg] Failed: {err[-100:]}')
    return None


def generate_heygen_avatar_intro(intro_text, look_id, avatar_group_id, voice_id, tmpdir):
        """Generate HeyGen avatar video for the intro (selfie mode facing camera)."""
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
        if look_id:
                    payload['video_inputs'][0]['character']['avatar_style'] = 'normal'

        try:
                    r = requests.post(HEYGEN_BASE + '/v2/video/generate',
                                                                headers=heygen_headers(), json=payload, timeout=60)
                    print(f'[Intro] HeyGen generate: {r.status_code} {r.text[:400]}')
                    if r.status_code not in (200, 201):
                                    return None
                                video_id = r.json().get('data', {}).get('video_id')
                    if not video_id:
                                    return None
                                # Poll for completion
                                for _ in range(HEYGEN_POLL_MAX // HEYGEN_POLL_INTERVAL):
                                                time.sleep(HEYGEN_POLL_INTERVAL)
                                                poll_r = requests.get(HEYGEN_BASE + f'/v1/video_status.get?video_id={video_id}',
                                                                      headers=heygen_headers(), timeout=30)
                                                if poll_r.status_code == 200:
                                                                    pdata = poll_r.json().get('data', {})
                                                                    status = pdata.get('status', '')
                                                                    print(f'[Intro] Poll status: {status}')
                                                                    if status == 'completed':
                                                                                            video_url = pdata.get('video_url')
                                                                                            if video_url:
                                                                                                                        intro_path = os.path.join(tmpdir, 'intro_heygen.mp4')
                                                                                                                        _download_file(video_url, intro_path)
                                                                                                                        return intro_path
                                                                        elif status == 'failed':
                                                                                                print(f'[Intro] HeyGen video failed: {pdata}')
                                                                                                return None
        except Exception as e:
            print(f'[Intro] HeyGen avatar intro error: {e}')
        return None


def build_intro_tts_clip(intro_text, voice_id, look_id, tmpdir):
        """
            Fallback intro: generate TTS audio + use look thumbnail image.
                Creates a selfie-style portrait clip for the intro.
                    """
        print('[IntroFallback] Building TTS intro clip...')
        audio_url = _tts_call(intro_text, voice_id, speed=0.92)
        audio_path = os.path.join(tmpdir, 'intro_audio.mp3')
        _download_file(audio_url, audio_path)
        dur = get_audio_duration(audio_path)
        print(f'[IntroFallback] Intro audio: {dur:.1f}s')

    # Try to get look thumbnail image
        look_img_path = None
    if look_id:
                try:
                                r = requests.get(
                                                    HEYGEN_BASE + f'/v1/avatar_group.list?include_look=1',
                                                    headers=heygen_headers(), timeout=30
                                )
                                if r.status_code == 200:
                                                    for grp in r.json().get('data', {}).get('avatar_group_list', []):
                                                                            for look in grp.get('look_list', []):
                                                                                                        if look.get('look_id') == look_id or look.get('id') == look_id:
                                                                                                                                        thumb = look.get('preview_image_url') or look.get('thumbnail_url')
                                                                                                                                        if thumb:
                                                                                                                                                                            look_img_path = os.path.join(tmpdir, 'look_thumb.jpg')
                                                                                                                                                                            _download_file(thumb, look_img_path)
                                                                                                                                                                            break
                                                                                                            except Exception as e:
                                                                                            print(f'[IntroFallback] Look thumbnail error: {e}')

                                                            intro_clip_path = os.path.join(tmpdir, 'intro_clip.mp4')
                                        if look_img_path and os.path.exists(look_img_path):
                                                    # Use look thumbnail for background - portrait crop
                                                    cmd = [
                                                                    'ffmpeg', '-y', '-loop', '1', '-i', look_img_path, '-i', audio_path,
                                                                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '26',
                                                                    '-vf', (
                                                                                        'scale=1080:1920:force_original_aspect_ratio=increase,'
                                                                                        'crop=1080:1920,setsar=1'
                                                                    ),
                                                                    '-c:a', 'aac', '-b:a', '128k', '-shortest',
                                                                    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', intro_clip_path
                                                    ]
                else:
                            # Black background fallback
                            cmd = [
                                            'ffmpeg', '-y', '-f', 'lavfi', '-i', f'color=c=black:s=1080x1920:r=24',
                                            '-i', audio_path, '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
                                            '-c:a', 'aac', '-b:a', '128k', '-shortest', '-t', str(dur),
                                            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', intro_clip_path
                            ]
                        result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode == 0 and os.path.exists(intro_clip_path):
                print(f'[IntroFallback] Built intro clip: {intro_clip_path}')
        return intro_clip_path
    raise RuntimeError('Intro clip build failed')


def build_vehicle_walkaround_video(vehicle_photos, vehicle_video_url, segments, voice_id, tmpdir):
        """
            Build the vehicle POV section of the walkaround video.
                Uses motion-simulated photo clips for each segment (front, driver side, rear, pass side, interior).
                    If listing video is available, uses it as the base for some segments.
                        """
    print(f'[Vehicle] Building vehicle walkaround... photos: {len(vehicle_photos)}, video: {bool(vehicle_video_url)}')
    segment_order = ['front', 'driver_side', 'rear', 'pass_side', 'interior']
    clips = []

    for seg_name in segment_order:
                seg_text = segments.get(seg_name, '')
        if not seg_text or not seg_text.strip():
                        print(f'[Vehicle] Skipping empty segment: {seg_name}')
                        continue

        audio_path = generate_tts_segment_audio(seg_text, voice_id, tmpdir, seg_name, speed=0.92)
        if not audio_path:
                        print(f'[Vehicle] No audio for segment: {seg_name}')
                        continue

        audio_dur = get_audio_duration(audio_path)
        print(f'[Vehicle] {seg_name} audio: {audio_dur:.1f}s')

        # Select photos for this segment
        photo_indices = SEGMENT_PHOTO_MAP.get(seg_name, [])
        seg_photos = [vehicle_photos[i] for i in photo_indices if i < len(vehicle_photos)]

        # Fallback: grab sequential photos if primary mapping comes up short
        if len(seg_photos) < 2 and vehicle_photos:
                        start = photo_indices[0] if photo_indices else 0
                        start = min(start, len(vehicle_photos) - 1)
                        seg_photos = vehicle_photos[start:start + 3]
                    if not seg_photos and vehicle_photos:
                                    seg_photos = vehicle_photos[:2]

        # Download photos
        photo_paths = []
        for i, url in enumerate(seg_photos[:5]):  # max 5 photos per segment
                        try:
                                            pp = os.path.join(tmpdir, f'photo_{seg_name}_{i}.jpg')
                                            _download_file(url, pp)
                                            photo_paths.append(pp)
except Exception as e:
                print(f'[Vehicle] Photo {i} error: {e}')

        if not photo_paths:
                        print(f'[Vehicle] No photos for segment: {seg_name}')
                        continue

        clip_path = os.path.join(tmpdir, f'clip_{seg_name}.mp4')

        # Build motion clip
        clip = _build_motion_clip(photo_paths, audio_path, audio_dur, clip_path, seg_name)
        if clip:
                        clips.append(clip)
                        print(f'[Vehicle] Added clip: {clip}')
else:
            print(f'[Vehicle] Clip build failed for: {seg_name}')

    if not clips:
                raise RuntimeError('No vehicle clips were built')

    if len(clips) == 1:
                return clips[0]

    vehicle_path = os.path.join(tmpdir, 'vehicle_walkaround.mp4')
    _concat_clips(clips, vehicle_path, tmpdir)
    return vehicle_path


def _concat_clips(clip_paths, output_path, tmpdir):
        """Concatenate video clips with hard cuts (no transitions)."""
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
                err = result.stderr[-500:].decode('utf-8', errors='ignore') if result.stderr else 'unknown'
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
                                                                   Main entry point: builds the complete walkaround video.
                                                                       Structure:
                                                                             1. Intro (HeyGen avatar or TTS fallback) - salesperson facing camera, selfie mode
                                                                                   2. Vehicle sections (motion-simulated photos) - POV walking around vehicle
                                                                                         3. Outro (TTS + vehicle photo background)
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
    print(f'[Build] Motion walkaround build, segments: {list(segments.keys())}, photos: {len(vehicle_photos)}')

    all_clips = []

    # --- INTRO: Salesperson facing camera (selfie mode) ---
    if intro_text:
                intro_clip = generate_heygen_avatar_intro(intro_text, look_id, avatar_group_id, voice_id, tmpdir)
        if not intro_clip:
                        print('[Build] HeyGen avatar intro failed, using TTS fallback...')
            try:
                                intro_clip = build_intro_tts_clip(intro_text, voice_id, look_id, tmpdir)
except Exception as e:
                print(f'[Build] Intro TTS fallback failed: {e}')
                intro_clip = None
        if intro_clip:
                        all_clips.append(intro_clip)

    # --- VEHICLE SECTIONS: POV walking around vehicle ---
    vehicle_clip = build_vehicle_walkaround_video(
                vehicle_photos, vehicle_video_url, segments, voice_id, tmpdir
    )
    all_clips.append(vehicle_clip)

    # --- OUTRO: Last vehicle photo + TTS ---
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
                                                                                                    '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1',
                                                                                                    '-c:a', 'aac', '-b:a', '128k', '-shortest',
                                                                                                    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', outro_clip
                                                                        ], capture_output=True, timeout=60)
                            else:
                                                    res = subprocess.run([
                                                                                'ffmpeg', '-y', '-f', 'lavfi',
                                                                                '-i', f'color=c=black:s=1080x1920:r=24',
                                                                                '-i', outro_audio, '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
                                                                                '-c:a', 'aac', '-b:a', '128k', '-shortest', '-t', str(outro_dur),
                                                                                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', outro_clip
                                                    ], capture_output=True, timeout=60)
                                                if res.returncode == 0 and os.path.exists(outro_clip):
                                                                        all_clips.append(outro_clip)
except Exception as e:
            print(f'[Build] Outro clip error (non-fatal): {e}')

    if len(all_clips) == 1:
                final_path = all_clips[0]
else:
        final_path = os.path.join(tmpdir, 'final_walkaround.mp4')
        _concat_clips(all_clips, final_path, tmpdir)

    return compress_video_for_upload(final_path, tmpdir)


# ── Legacy shims ─────────────────────────────────────────────────────────────
def upload_audio_to_heygen(audio_path):
        return None

def generate_heygen_audio(script_text, voice_id, tmpdir):
        return generate_tts_audio(script_text, voice_id, tmpdir)

def run_video_translation(video_url, audio_url, tmpdir):
        return None
