import os, requests, subprocess, json, shutil, tempfile, math, io, time
import numpy as np
from PIL import Image

HEADERS = {'User-Agent': 'Mozilla/5.0'}
W = 720
H = 1280

LOT_BG_URL = 'https://lh3.googleusercontent.com/gps-cs-s/APNQkAGSkAI7-TAoNkcv4m5PEQRwYfsJdYgypmHTVDUN1Sx4vxRvC13WEcVTnRSkCNWVATeqv7iDe9xxsWWn2VM9ya1BQJEIvTdrY35roeZ3_Sw61Pzeqju1TI0-SlJv2U-qOrKjDKAa=w1333-h1000-k-no'

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


def generate_heygen_webm(script_text, avatar_look_id, voice_id, tmpdir):
            print('[HeyGen] Generating Avatar V webm with walking motion...')

    motion_prompt = (
                    "The person walks forward and sideways energetically, turning slightly left and right. "
                    "Gestures with both arms extended, points forward and to the sides enthusiastically. "
                    "Moves around dynamically while speaking, like a car salesperson doing a walkaround."
    )

    payload = {
                    'type': 'avatar',
                    'avatar_id': avatar_look_id,
                    'voice_id': voice_id,
                    'script': script_text,
                    'aspect_ratio': '9:16',
                    'resolution': '1080p',
                    'output_format': 'webm',
                    'motion_prompt': motion_prompt,
                    'engine': {'type': 'avatar_v'}
    }

    r = requests.post(HEYGEN_BASE + '/v3/videos', headers=heygen_headers(), json=payload, timeout=60)
    if r.status_code != 200:
                    print(f'[HeyGen] Create error {r.status_code}: {r.text}')
        raise RuntimeError(f'HeyGen create failed: {r.status_code} {r.text}')

    video_id = r.json()['data']['video_id']
    print(f'[HeyGen] Video ID: {video_id} - polling every {HEYGEN_POLL_INTERVAL}s max {HEYGEN_POLL_MAX} polls...')

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
                webm_path = os.path.join(tmpdir, 'aaron_alpha.webm')
                _download_file(video_url, webm_path)
                print(f'[HeyGen] Downloaded webm: {webm_path}')
                return webm_path
elif status == 'failed':
                raise RuntimeError(f'HeyGen failed: {vdata.get("failure_message", "unknown")}')
except RuntimeError:
            raise
except Exception as e:
            print(f'[HeyGen] Poll {i+1} error: {e} - continuing...')

    raise RuntimeError(f'HeyGen timed out after {HEYGEN_POLL_MAX * HEYGEN_POLL_INTERVAL // 60} minutes')


def generate_cinematic_clip(look_id, vehicle_photos, vehicle_name, lot_bg_path, duration, tmpdir, clip_index):
            print(f'[Cinematic] Generating clip {clip_index} ({duration}s)...')

    references = [{'type': 'url', 'url': LOT_BG_URL}]
    for photo_url in vehicle_photos[:2]:
                    references.append({'type': 'url', 'url': photo_url})

    prompt = (
                    "A professional used car salesman in a blue button-up shirt walks around a "
                    + vehicle_name +
                    " on a used car dealership lot. He moves from the front to the side of the vehicle, "
                    "gesturing toward specific parts of the car. Shot handheld in selfie-style POV, "
                    "as if the salesman is holding the camera while walking. "
                    "The vehicle is prominently visible in the background as he walks around it. "
                    "Bright daylight, natural lighting, used car lot setting."
    )

    payload = {
                    'type': 'cinematic_avatar',
                    'prompt': prompt,
                    'avatar_id': [look_id],
                    'references': references,
                    'aspect_ratio': '9:16',
                    'resolution': '1080p',
                    'duration': min(int(duration), 15),
                    'enhance_prompt': True
    }

    r = requests.post(HEYGEN_BASE + '/v3/videos', headers=heygen_headers(), json=payload, timeout=60)
    if r.status_code != 200:
                    print(f'[Cinematic] Error {r.status_code}: {r.text}')
        return None

    video_id = r.json()['data']['video_id']
    print(f'[Cinematic] Clip {clip_index} video_id: {video_id} - polling...')

    for i in range(120):
                    time.sleep(HEYGEN_POLL_INTERVAL)
        try:
                            sr = requests.get(HEYGEN_BASE + '/v3/videos/' + video_id, headers=heygen_headers(), timeout=30)
            vdata = sr.json().get('data', {})
            status = vdata.get('status', 'unknown')
            print(f'[Cinematic] Clip {clip_index} poll {i+1}: {status}')
            if status == 'completed':
                                    video_url = vdata.get('video_url')
                clip_path = os.path.join(tmpdir, 'cinematic_' + str(clip_index).zfill(2) + '.mp4')
                _download_file(video_url, clip_path)
                print(f'[Cinematic] Clip {clip_index} downloaded')
                return clip_path
elif status == 'failed':
                print(f'[Cinematic] Clip {clip_index} failed: {vdata.get("failure_message")}')
                return None
except Exception as e:
            print(f'[Cinematic] Clip {clip_index} poll error: {e}')

    print(f'[Cinematic] Clip {clip_index} timed out')
    return None


def _download_file(url, dest_path):
            r = requests.get(url, headers=HEADERS, stream=True, timeout=120)
    r.raise_for_status()
    with open(dest_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=65536):
                                        f.write(chunk)


def _make_solid_bg(color_rgb, duration, output_path):
            """Create solid color background video using FFmpeg lavfi."""
    r, g, b = color_rgb
    color_hex = f'{r:02x}{g:02x}{b:02x}'
    cmd = [
                    'ffmpeg', '-y',
                    '-f', 'lavfi',
                    '-i', f'color=c=0x{color_hex}:size={W}x{H}:rate=30',
                    '-t', str(duration),
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-pix_fmt', 'yuv420p',
                    output_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
                    raise RuntimeError(f'Solid BG failed: {result.stderr.decode(errors="replace")[:300]}')


def get_lot_background(tmpdir):
            lot_path = os.path.join(tmpdir, 'lot_bg.jpg')
    try:
                    r = requests.get(LOT_BG_URL, headers={
                                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                        'Referer': 'https://www.google.com/'
                    }, stream=True, timeout=30)
        if r.status_code == 200 and 'image' in r.headers.get('content-type', ''):
                            with open(lot_path, 'wb') as f:
                                                    for chunk in r.iter_content(65536):
                                                                                f.write(chunk)
                                                                        img = Image.open(lot_path).convert('RGB')
            iw, ih = img.size
            target_ratio = W / H
            if iw / ih > target_ratio:
                                    new_w = int(ih * target_ratio)
                x0 = (iw - new_w) // 2
                img = img.crop((x0, 0, x0 + new_w, ih))
else:
                new_h = int(iw / target_ratio)
                y0 = (ih - new_h) // 2
                img = img.crop((0, y0, iw, y0 + new_h))
            img = img.resize((W, H), Image.LANCZOS)
            img.save(lot_path, 'JPEG', quality=90)
            print(f'[Lot BG] Downloaded and saved: {lot_path}')
            return lot_path
else:
            print(f'[Lot BG] Bad response: {r.status_code} {r.headers.get("content-type")}')
except Exception as e:
        print(f'[Lot BG] Download failed: {e}')

    # Fallback: green grass/lot colored background
    img = Image.new('RGB', (W, H), (45, 80, 35))
    img.save(lot_path, 'JPEG')
    print(f'[Lot BG] Using fallback green background')
    return lot_path


def _make_bg_video(bg_image_path, duration, output_path, tmpdir):
            """Create background video from image, with solid color fallback."""
    # First verify the image file is valid
    is_valid = False
    try:
                    img = Image.open(bg_image_path)
        img.verify()
        is_valid = True
except Exception as e:
        print(f'[BG Video] Image invalid: {e}, using solid color')

    if is_valid:
                    cmd = [
                                        'ffmpeg', '-y',
                                        '-loop', '1',
                                        '-i', bg_image_path,
                                        '-vf', 'scale=' + str(W) + ':' + str(H) + ':force_original_aspect_ratio=cover,crop=' + str(W) + ':' + str(H),
                                        '-t', str(duration),
                                        '-r', '30',
                                        '-pix_fmt', 'yuv420p',
                                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                                        output_path
                    ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0:
                            return
        stderr = result.stderr.decode('utf-8', errors='replace')
        print(f'[BG Video] FFmpeg error (last 500 chars): {stderr[-500:]}')

    # Fallback to solid color
    print(f'[BG Video] Using solid color fallback')
    _make_solid_bg((45, 80, 35), duration, output_path)


def composite_avatar_over_background(webm_path, bg_image_path, audio_start, duration, output_mp4, tmpdir):
            seg_name = os.path.splitext(os.path.basename(output_mp4))[0]
    bg_video = os.path.join(tmpdir, 'bg_' + seg_name + '.mp4')

    _make_bg_video(bg_image_path, duration, bg_video, tmpdir)

    webm_trim = os.path.join(tmpdir, 'wt_' + seg_name + '.webm')
    trim_cmd = [
                    'ffmpeg', '-y',
                    '-ss', str(audio_start),
                    '-i', webm_path,
                    '-t', str(duration),
                    '-c:v', 'libvpx-vp9',
                    '-an',
                    webm_trim
    ]
    subprocess.run(trim_cmd, capture_output=True)

    audio_path = os.path.join(tmpdir, 'aud_' + seg_name + '.aac')
    audio_cmd = [
                    'ffmpeg', '-y',
                    '-ss', str(audio_start),
                    '-i', webm_path,
                    '-t', str(duration),
                    '-vn', '-c:a', 'aac', '-b:a', '192k',
                    audio_path
    ]
    audio_result = subprocess.run(audio_cmd, capture_output=True)
    has_audio = audio_result.returncode == 0 and os.path.exists(audio_path) and os.path.getsize(audio_path) > 100

    aaron_h = int(H * 0.85)
    aaron_w = int(aaron_h * 9 / 16)
    aaron_x = (W - aaron_w) // 2
    aaron_y = H - aaron_h - 10

    overlay_filter = '[1:v]scale=' + str(aaron_w) + ':' + str(aaron_h) + '[avatar];[0:v][avatar]overlay=' + str(aaron_x) + ':' + str(aaron_y) + ':format=auto[out]'

    if has_audio:
                    comp_cmd = [
                                        'ffmpeg', '-y',
                                        '-i', bg_video,
                                        '-i', webm_trim,
                                        '-i', audio_path,
                                        '-filter_complex', overlay_filter,
                                        '-map', '[out]',
                                        '-map', '2:a',
                                        '-t', str(duration),
                                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                                        '-c:a', 'aac', '-b:a', '192k',
                                        '-pix_fmt', 'yuv420p',
                                        output_mp4
                    ]
else:
        comp_cmd = [
                            'ffmpeg', '-y',
                            '-i', bg_video,
                            '-i', webm_trim,
                            '-filter_complex', overlay_filter,
                            '-map', '[out]',
                            '-t', str(duration),
                            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                            '-pix_fmt', 'yuv420p',
                            '-an',
                            output_mp4
        ]

    result = subprocess.run(comp_cmd, capture_output=True)
    if result.returncode != 0:
                    stderr = result.stderr.decode('utf-8', errors='replace')
        print(f'[Composite] Error (last 500): {stderr[-500:]}')
        if has_audio:
                            fallback_cmd = [
                                                    'ffmpeg', '-y',
                                                    '-i', bg_video,
                                                    '-i', audio_path,
                                                    '-c:v', 'copy',
                                                    '-c:a', 'aac',
                                                    '-shortest',
                                                    output_mp4
                            ]
            subprocess.run(fallback_cmd, capture_output=True)
else:
            shutil.copy(bg_video, output_mp4)
else:
        print(f'[Composite] Created: {output_mp4}')


def merge_cinematic_with_audio(cinematic_mp4, webm_path, audio_start, duration, output_mp4, tmpdir):
            seg_name = os.path.splitext(os.path.basename(output_mp4))[0]

    audio_path = os.path.join(tmpdir, 'aud_' + seg_name + '.aac')
    audio_cmd = [
                    'ffmpeg', '-y',
                    '-ss', str(audio_start),
                    '-i', webm_path,
                    '-t', str(duration),
                    '-vn', '-c:a', 'aac', '-b:a', '192k',
                    audio_path
    ]
    audio_result = subprocess.run(audio_cmd, capture_output=True)
    has_audio = audio_result.returncode == 0 and os.path.exists(audio_path) and os.path.getsize(audio_path) > 100

    cin_trim = os.path.join(tmpdir, 'ct_' + seg_name + '.mp4')
    trim_cmd = [
                    'ffmpeg', '-y',
                    '-stream_loop', '-1',
                    '-i', cinematic_mp4,
                    '-t', str(duration),
                    '-vf', 'scale=' + str(W) + ':' + str(H) + ':force_original_aspect_ratio=cover,crop=' + str(W) + ':' + str(H),
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                    '-pix_fmt', 'yuv420p',
                    '-an',
                    cin_trim
    ]
    subprocess.run(trim_cmd, check=True, capture_output=True)

    if has_audio:
                    merge_cmd = [
                                        'ffmpeg', '-y',
                                        '-i', cin_trim,
                                        '-i', audio_path,
                                        '-c:v', 'copy',
                                        '-c:a', 'aac', '-b:a', '192k',
                                        '-shortest',
                                        output_mp4
                    ]
else:
        merge_cmd = ['ffmpeg', '-y', '-i', cin_trim, '-c:v', 'copy', '-an', output_mp4]
    subprocess.run(merge_cmd, check=True, capture_output=True)
    print(f'[Cinematic+Audio] Created: {output_mp4}')


def build_walkaround_video(vehicle, script_segments, heygen_webm_path,
                                                       cinematic_clips, vehicle_photos, tmpdir):
                                                                   lot_bg_path = get_lot_background(tmpdir)
                                                                   segment_files = []

    cinematic_map = {idx: path for path, idx in cinematic_clips}

    for i, seg in enumerate(script_segments):
                    seg_type = seg.get('type')
        audio_start = seg.get('audio_start', 0)
        duration = seg.get('duration', 5)
        seg_out = os.path.join(tmpdir, 'seg_' + str(i).zfill(3) + '.mp4')

        try:
                            if seg_type in ('intro', 'outro'):
                                                    composite_avatar_over_background(heygen_webm_path, lot_bg_path, audio_start, duration, seg_out, tmpdir)

elif seg_type == 'walkaround':
                photo_idx = seg.get('photo_index', 0)
                cin_idx = seg.get('cinematic_index', None)

                if cin_idx is not None and cin_idx in cinematic_map:
                                            merge_cinematic_with_audio(
                                                                            cinematic_map[cin_idx], heygen_webm_path,
                                                                            audio_start, duration, seg_out, tmpdir
                                            )
elif photo_idx < len(vehicle_photos):
                    composite_avatar_over_background(
                                                    heygen_webm_path, vehicle_photos[photo_idx],
                                                    audio_start, duration, seg_out, tmpdir
                    )
else:
                    composite_avatar_over_background(heygen_webm_path, lot_bg_path, audio_start, duration, seg_out, tmpdir)

else:
                composite_avatar_over_background(heygen_webm_path, lot_bg_path, audio_start, duration, seg_out, tmpdir)

except Exception as e:
            print(f'[Segment {i}] Error: {e}')
            import traceback
            traceback.print_exc()

        if os.path.exists(seg_out) and os.path.getsize(seg_out) > 1000:
                            segment_files.append(seg_out)
else:
            print(f'[Segment {i}] Missing or empty output: {seg_out}')

    if not segment_files:
                    raise RuntimeError('No segments generated successfully')

    final_path = os.path.join(tmpdir, 'final.mp4')
    concat_file = os.path.join(tmpdir, 'concat.txt')
    with open(concat_file, 'w') as f:
                    for sf in segment_files:
                                        f.write("file '" + sf + "'\n")

    concat_cmd = [
                    'ffmpeg', '-y',
                    '-f', 'concat', '-safe', '0',
                    '-i', concat_file,
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                    '-c:a', 'aac', '-b:a', '192k',
                    '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart',
                    final_path
    ]
    result = subprocess.run(concat_cmd, capture_output=True)
    if result.returncode != 0:
                    raise RuntimeError(f'Concat failed: {result.stderr.decode(errors="replace")[-500:]}')
    print(f'[Final] Assembled: {final_path}')
    return final_path
