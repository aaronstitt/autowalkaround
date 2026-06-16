import os, requests, subprocess, json, shutil, tempfile, time
from PIL import Image

HEADERS = {'User-Agent': 'Mozilla/5.0'}
W = 720
H = 1280

HEYGEN_BASE = 'https://api.heygen.com'
HEYGEN_POLL_INTERVAL = 15
HEYGEN_POLL_MAX = 300



def get_look_id(avatar_group_id):
    import os, requests
    heygen_base = 'https://api.heygen.com'
    try:
        url = heygen_base + '/v3/avatars/looks?ownership=private&group_id=' + avatar_group_id
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
    """Generate Aaron's voice-only video via HeyGen Avatar V, extract audio."""
    print('[HeyGen] Generating voice audio...')

    payload = {
        'type': 'avatar',
        'avatar_id': avatar_look_id,
        'voice_id': voice_id,
        'script': script_text,
        'aspect_ratio': '9:16',
        'resolution': '720p',
        'output_format': 'mp4',
        'engine': {'type': 'avatar_v'}
    }

    r = requests.post(HEYGEN_BASE + '/v3/videos', headers=heygen_headers(), json=payload, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f'HeyGen create failed: {r.status_code} {r.text}')

    video_id = r.json()['data']['video_id']
    print(f'[HeyGen] Video ID: {video_id} - polling every {HEYGEN_POLL_INTERVAL}s...')

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
                heygen_mp4 = os.path.join(tmpdir, 'heygen_voice.mp4')
                _download_file(video_url, heygen_mp4)
                print(f'[HeyGen] Downloaded: {heygen_mp4}')
                # Extract audio only
                audio_path = os.path.join(tmpdir, 'voice.aac')
                cmd = ['ffmpeg', '-y', '-i', heygen_mp4, '-vn', '-c:a', 'aac', '-b:a', '192k', audio_path]
                result = subprocess.run(cmd, capture_output=True)
                if result.returncode != 0:
                    raise RuntimeError(f'Audio extract failed: {result.stderr.decode(errors="replace")[-300:]}')
                print(f'[HeyGen] Audio extracted: {audio_path}')
                return audio_path, heygen_mp4
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


def get_vehicle_video_duration(video_path):
    """Get duration of a video file in seconds."""
    result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', video_path],
        capture_output=True
    )
    if result.returncode == 0:
        info = json.loads(result.stdout)
        dur = float(info.get('format', {}).get('duration', 0))
        print(f'[Duration] {video_path}: {dur:.1f}s')
        return dur
    return 0


def build_walkaround_video(vehicle, script_segments, heygen_audio_path,
                           heygen_mp4_path, vehicle_photos, vehicle_video_url, tmpdir):
    """
    New MVP approach:
    - Download the vehicle listing video (actual car footage)
    - Loop/extend it to match the audio duration
    - Overlay Aaron's HeyGen audio on top
    - Add a small Aaron picture-in-picture in corner using heygen_mp4
    - Output final 9:16 MP4
    """
    print(f'[Build] Starting walkaround assembly...')

    # Get audio duration
    audio_dur = get_vehicle_video_duration(heygen_audio_path)
    if audio_dur < 5:
        raise RuntimeError(f'Audio too short: {audio_dur}s')
    print(f'[Build] Audio duration: {audio_dur:.1f}s')

    # Download vehicle listing video
    vehicle_video_path = None
    if vehicle_video_url:
        try:
            vehicle_video_path = os.path.join(tmpdir, 'vehicle_listing.mp4')
            print(f'[Build] Downloading vehicle video: {vehicle_video_url}')
            _download_file(vehicle_video_url, vehicle_video_path)
        except Exception as e:
            print(f'[Build] Vehicle video download failed: {e}')
            vehicle_video_path = None

    # If no listing video, create slideshow from photos
    if not vehicle_video_path or not os.path.exists(vehicle_video_path) or os.path.getsize(vehicle_video_path) < 10000:
        print(f'[Build] No vehicle video - building photo slideshow...')
        vehicle_video_path = _build_photo_slideshow(vehicle_photos, audio_dur, tmpdir)
    else:
        print(f'[Build] Using vehicle listing video')

    # Scale/loop vehicle video to match audio duration
    looped_vehicle = os.path.join(tmpdir, 'vehicle_looped.mp4')
    loop_cmd = [
        'ffmpeg', '-y',
        '-stream_loop', '-1',
        '-i', vehicle_video_path,
        '-t', str(audio_dur),
        '-vf', f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
        '-pix_fmt', 'yuv420p',
        '-an',
        looped_vehicle
    ]
    result = subprocess.run(loop_cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f'Vehicle video loop failed: {result.stderr.decode(errors="replace")[-300:]}')
    print(f'[Build] Vehicle video looped to {audio_dur:.1f}s')

    # Add Aaron PIP (picture-in-picture) in bottom-left corner
    pip_w = int(W * 0.30)
    pip_h = int(pip_w * 16 / 9)
    pip_x = 20
    pip_y = H - pip_h - 20

    # Scale HeyGen mp4 for PIP
    pip_video = os.path.join(tmpdir, 'pip_aaron.mp4')
    pip_cmd = [
        'ffmpeg', '-y',
        '-stream_loop', '-1',
        '-i', heygen_mp4_path,
        '-t', str(audio_dur),
        '-vf', f'scale={pip_w}:{pip_h}',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
        '-pix_fmt', 'yuv420p',
        '-an',
        pip_video
    ]
    result = subprocess.run(pip_cmd, capture_output=True)
    has_pip = result.returncode == 0 and os.path.exists(pip_video) and os.path.getsize(pip_video) > 1000

    # Composite: vehicle video + Aaron PIP + audio
    final_path = os.path.join(tmpdir, 'final.mp4')

    if has_pip:
        print(f'[Build] Compositing with Aaron PIP at ({pip_x},{pip_y}) size {pip_w}x{pip_h}')
        filter_complex = (
            f'[0:v][1:v]overlay={pip_x}:{pip_y}:format=auto[out]'
        )
        comp_cmd = [
            'ffmpeg', '-y',
            '-i', looped_vehicle,
            '-i', pip_video,
            '-i', heygen_audio_path,
            '-filter_complex', filter_complex,
            '-map', '[out]',
            '-map', '2:a',
            '-t', str(audio_dur),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            final_path
        ]
    else:
        print(f'[Build] No PIP - vehicle video + audio only')
        comp_cmd = [
            'ffmpeg', '-y',
            '-i', looped_vehicle,
            '-i', heygen_audio_path,
            '-map', '0:v',
            '-map', '1:a',
            '-t', str(audio_dur),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            final_path
        ]

    result = subprocess.run(comp_cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f'Final composite failed: {result.stderr.decode(errors="replace")[-500:]}')

    print(f'[Build] Final assembled: {final_path} ({os.path.getsize(final_path)} bytes)')
    return final_path


def _build_photo_slideshow(vehicle_photos, total_duration, tmpdir):
    """Build a slideshow from vehicle photos if no listing video available."""
    print(f'[Slideshow] Building from {len(vehicle_photos)} photos, duration {total_duration:.1f}s')

    downloaded = []
    for i, url in enumerate(vehicle_photos[:20]):
        try:
            img_path = os.path.join(tmpdir, f'slide_{i:02d}.jpg')
            r = requests.get(url, headers=HEADERS, timeout=30, stream=True)
            if r.status_code == 200 and 'image' in r.headers.get('content-type', ''):
                with open(img_path, 'wb') as f:
                    for chunk in r.iter_content(65536):
                        f.write(chunk)
                # Validate and resize
                try:
                    img = Image.open(img_path).convert('RGB')
                    iw, ih = img.size
                    tr = W / H
                    if iw / ih > tr:
                        nw = int(ih * tr)
                        x0 = (iw - nw) // 2
                        img = img.crop((x0, 0, x0 + nw, ih))
                    else:
                        nh = int(iw / tr)
                        y0 = (ih - nh) // 2
                        img = img.crop((0, y0, iw, y0 + nh))
                    img = img.resize((W, H), Image.LANCZOS)
                    img.save(img_path, 'JPEG', quality=85)
                    downloaded.append(img_path)
                except Exception as e:
                    print(f'[Slideshow] Image {i} invalid: {e}')
        except Exception as e:
            print(f'[Slideshow] Download {i} failed: {e}')

    if not downloaded:
        raise RuntimeError('No photos available for slideshow')

    secs_per_photo = total_duration / len(downloaded)
    concat_file = os.path.join(tmpdir, 'slides.txt')
    with open(concat_file, 'w') as f:
        for img_path in downloaded:
            f.write(f"file '{img_path}'\n")
            f.write(f'duration {secs_per_photo:.2f}\n')
        # ffmpeg concat needs a final entry
        f.write(f"file '{downloaded[-1]}'\n")

    slideshow_path = os.path.join(tmpdir, 'slideshow.mp4')
    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', concat_file,
        '-vf', f'scale={W}:{H},fps=30',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
        '-pix_fmt', 'yuv420p',
        '-an',
        slideshow_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f'Slideshow failed: {result.stderr.decode(errors="replace")[-300:]}')
    print(f'[Slideshow] Built: {slideshow_path}')
    return slideshow_path
