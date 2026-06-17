import os, requests, time, subprocess, shutil, math

HEADERS = {'User-Agent': 'Mozilla/5.0'}
HEYGEN_BASE = 'https://api.heygen.com'
HEYGEN_POLL_INTERVAL = 15
HEYGEN_POLL_MAX = 300

WALKAROUND_MOTION_PROMPT = (
    "The person is performing a car dealership vehicle walkaround video in selfie mode. "
    "They hold the camera phone in front of themselves pointing at their own face (selfie style). "
    "They physically walk around the entire perimeter of the vehicle, moving continuously. "
    "With their free hand they gesture and point to different parts of the car. "
    "Full body visible. Energetic, enthusiastic used car salesperson body language throughout."
)

def get_look_id(avatar_group_id):
    try:
        url = HEYGEN_BASE + '/v3/avatars/looks?ownership=private&group_id=' + avatar_group_id
        r = requests.get(url, headers={'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}, timeout=30)
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

def heygen_headers():
    return {'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}

def generate_heygen_audio(script_text, avatar_look_id, voice_id, tmpdir):
    """Generate walkaround video via HeyGen Avatar V with transparent background (webm)."""
    print('[HeyGen] Generating walkaround video with transparent background...')

    payload = {
        'type': 'avatar',
        'avatar_id': avatar_look_id,
        'voice_id': voice_id,
        'script': script_text,
        'aspect_ratio': '9:16',
        'resolution': '720p',
        'output_format': 'webm',
        'remove_background': True,
        'motion_prompt': WALKAROUND_MOTION_PROMPT,
        'engine': {'type': 'avatar_v'}
    }

    r = requests.post(HEYGEN_BASE + '/v3/videos', headers=heygen_headers(), json=payload, timeout=60)
    if r.status_code != 200:
        print(f'[HeyGen] webm failed ({r.status_code}), falling back to mp4: {r.text[:200]}')
        payload['output_format'] = 'mp4'
        payload.pop('remove_background', None)
        r = requests.post(HEYGEN_BASE + '/v3/videos', headers=heygen_headers(), json=payload, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f'HeyGen create failed: {r.status_code} {r.text}')

    video_id = r.json()['data']['video_id']
    output_fmt = payload['output_format']
    print(f'[HeyGen] Video ID: {video_id} format={output_fmt} - polling every {HEYGEN_POLL_INTERVAL}s...')

    for i in range(HEYGEN_POLL_MAX):
        time.sleep(HEYGEN_POLL_INTERVAL)
        try:
            sr = requests.get(HEYGEN_BASE + '/v3/videos/' + video_id, headers=heygen_headers(), timeout=30)
            vdata = sr.json().get('data', {})
            status = vdata.get('status', 'unknown')
            print(f'[HeyGen] Poll {i+1}: {status}')
            if status == 'completed':
                video_url = vdata.get('video_url')
                if not video_url:
                    raise RuntimeError('HeyGen completed but no video_url')
                ext = 'webm' if output_fmt == 'webm' else 'mp4'
                heygen_path = os.path.join(tmpdir, f'heygen_avatar.{ext}')
                _download_file(video_url, heygen_path)
                print(f'[HeyGen] Downloaded: {heygen_path}')
                return heygen_path, output_fmt
            elif status == 'failed':
                raise RuntimeError(f'HeyGen failed: {vdata.get("failure_message", "unknown")}')
        except RuntimeError:
            raise
        except Exception as e:
            print(f'[HeyGen] Poll {i+1} error: {e}')

    raise RuntimeError(f'HeyGen timed out after {HEYGEN_POLL_MAX * HEYGEN_POLL_INTERVAL // 60} min')

def _download_file(url, dest_path):
    r = requests.get(url, headers=HEADERS, stream=True, timeout=300)
    r.raise_for_status()
    with open(dest_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
    print(f'[Download] {dest_path} ({os.path.getsize(dest_path)} bytes)')

def _get_video_duration(path):
    """Get video duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', path],
            capture_output=True, text=True, timeout=30
        )
        import json
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except Exception as e:
        print(f'[ffprobe] error getting duration: {e}')
        return 120.0

def _download_photos(photo_urls, tmpdir, max_photos=12):
    """Download vehicle photos for background."""
    photos = []
    photo_dir = os.path.join(tmpdir, 'photos')
    os.makedirs(photo_dir, exist_ok=True)
    for i, url in enumerate(photo_urls[:max_photos]):
        try:
            dest = os.path.join(photo_dir, f'photo_{i:02d}.jpg')
            r = requests.get(url, headers=HEADERS, timeout=30, stream=True)
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
            photos.append(dest)
            print(f'[Photos] Downloaded {i+1}: {dest}')
        except Exception as e:
            print(f'[Photos] Failed photo {i}: {e}')
    return photos

def build_walkaround_video(vehicle, script_segments, heygen_audio_path,
                           heygen_result, vehicle_photos, vehicle_video_url, tmpdir):
    """
    Composite Aaron (transparent webm) over animated vehicle photos.
    heygen_result is (path, format) tuple from generate_heygen_audio.
    """
    if isinstance(heygen_result, tuple):
        heygen_path, output_fmt = heygen_result
    else:
        heygen_path = heygen_result
        output_fmt = 'mp4'

    # If not webm (transparent), just return mp4 as-is (fallback)
    if output_fmt != 'webm':
        print('[Build] No transparency available - returning HeyGen mp4 directly')
        return heygen_path

    print('[Build] Compositing Aaron over vehicle photos...')

    # Get Aaron video duration
    duration = _get_video_duration(heygen_path)
    print(f'[Build] Aaron video duration: {duration:.1f}s')

    # Download vehicle photos
    photos = _download_photos(vehicle_photos, tmpdir, max_photos=12)
    if not photos:
        print('[Build] No photos available - returning HeyGen video directly')
        return heygen_path

    # Calculate seconds per photo
    secs_per_photo = duration / len(photos)
    secs_per_photo = max(secs_per_photo, 4.0)  # minimum 4s per photo

    # Output dimensions: 9:16 at 720p
    out_w, out_h = 720, 1280

    # Build background slideshow using concat
    # Each photo gets a slow ken-burns zoom effect
    photo_clips = []
    for i, photo in enumerate(photos):
        clip_path = os.path.join(tmpdir, f'bg_clip_{i:02d}.mp4')
        duration_this = secs_per_photo
        # Alternate zoom direction for variety
        if i % 2 == 0:
            vf = f"scale=iw*2:ih*2,zoompan=z='min(zoom+0.0005,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration_this*25)}:s={out_w}x{out_h}:fps=25,setsar=1"
        else:
            vf = f"scale=iw*2:ih*2,zoompan=z='if(lte(zoom,1.0),1.3,max(1.0,zoom-0.0005))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration_this*25)}:s={out_w}x{out_h}:fps=25,setsar=1"
        cmd = [
            'ffmpeg', '-y', '-loop', '1', '-i', photo,
            '-vf', vf,
            '-t', str(duration_this),
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-r', '25', clip_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f'[Build] zoompan failed for photo {i}, using simple scale: {result.stderr[-300:]}')
            # Fallback: simple scale without zoompan
            vf_simple = f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},setsar=1"
            cmd2 = [
                'ffmpeg', '-y', '-loop', '1', '-i', photo,
                '-vf', vf_simple,
                '-t', str(duration_this),
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-r', '25', clip_path
            ]
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)
            if result2.returncode != 0:
                print(f'[Build] simple scale also failed for photo {i}')
                continue
        photo_clips.append(clip_path)

    if not photo_clips:
        print('[Build] No background clips created - returning HeyGen webm as-is')
        return heygen_path

    # Concatenate background clips
    bg_list_path = os.path.join(tmpdir, 'bg_list.txt')
    with open(bg_list_path, 'w') as f:
        for clip in photo_clips:
            f.write(f"file '{clip}'\n")

    bg_full_path = os.path.join(tmpdir, 'bg_full.mp4')
    cmd_concat = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', bg_list_path,
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', bg_full_path
    ]
    result = subprocess.run(cmd_concat, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f'[Build] concat failed: {result.stderr[-300:]}')
        return heygen_path

    # Trim background to exact Aaron video duration
    bg_trimmed_path = os.path.join(tmpdir, 'bg_trimmed.mp4')
    cmd_trim = [
        'ffmpeg', '-y', '-i', bg_full_path,
        '-t', str(duration),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', bg_trimmed_path
    ]
    subprocess.run(cmd_trim, capture_output=True, text=True, timeout=60)

    bg_path = bg_trimmed_path if os.path.exists(bg_trimmed_path) else bg_full_path

    # Composite: overlay Aaron (webm with alpha) on background
    # Aaron positioned: centered horizontally, lower 80% of frame, ~70% width
    aaron_scale_w = int(out_w * 0.85)
    overlay_x = (out_w - aaron_scale_w) // 2
    overlay_y = int(out_h * 0.15)  # Aaron fills from 15% down

    final_path = os.path.join(tmpdir, 'final_composite.mp4')
    cmd_overlay = [
        'ffmpeg', '-y',
        '-i', bg_path,
        '-i', heygen_path,
        '-filter_complex',
        f'[1:v]scale={aaron_scale_w}:-1[aaron];[0:v][aaron]overlay={overlay_x}:{overlay_y}:shortest=1[v]',
        '-map', '[v]',
        '-map', '1:a',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k',
        '-r', '25', final_path
    ]
    result = subprocess.run(cmd_overlay, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f'[Build] overlay failed: {result.stderr[-500:]}')
        return heygen_path

    print(f'[Build] Composite complete: {final_path} ({os.path.getsize(final_path)} bytes)')
    return final_path
