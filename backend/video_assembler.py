import os, requests, subprocess, json, shutil, tempfile, math, io, time
import numpy as np
from PIL import Image

HEADERS = {'User-Agent': 'Mozilla/5.0'}
W = 720
H = 1280

# ==============================================================
# LOT BACKGROUND URL - Immaculate Used Cars dealership
# ==============================================================
LOT_BG_URL = 'https://lh3.googleusercontent.com/gps-cs-s/APNQkAGSkAI7-TAoNkcv4m5PEQRwYfsJdYgypmHTVDUN1Sx4vxRvC13WEcVTnRSkCNWVATeqv7iDe9xxsWWn2VM9ya1BQJEIvTdrY35roeZ3_Sw61Pzeqju1TI0-SlJv2U-qOrKjDKAa=w1333-h1000-k-no'

HEYGEN_BASE = 'https://api.heygen.com'

def heygen_headers():
    return {'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}

# ==============================================================
# STEP 1: Get avatar look ID for a salesperson
# ==============================================================
def get_look_id(avatar_group_id):
    """Return the first look ID for this avatar group - prefers outdoor/lot looks."""
    try:
        url = HEYGEN_BASE + '/v3/avatars/looks?ownership=private&group_id=' + avatar_group_id
        r = requests.get(url, headers=heygen_headers(), timeout=30)
        if r.status_code == 200:
            data = r.json().get('data', [])
            looks = data if isinstance(data, list) else data.get('looks', [])
            # Prefer looks with 'sharp', 'car', 'lot', 'outdoor', 'salesman' in name
            preferred_keywords = ['sharp', 'car', 'lot', 'outdoor', 'salesman', 'used']
            for look in looks:
                name = (look.get('name') or look.get('look_name') or '').lower()
                if any(kw in name for kw in preferred_keywords):
                    return look.get('id') or look.get('look_id')
            # Fall back to first look
            if looks:
                return looks[0].get('id') or looks[0].get('look_id')
    except Exception as e:
        print(f'[get_look_id] error: {e}')
    return None

# ==============================================================
# STEP 2: Generate HeyGen Avatar V video - talking + WALKING motion
# Output: webm with transparent background (Aaron walks & talks)
# ==============================================================
def generate_heygen_webm(script_text, avatar_look_id, voice_id, tmpdir):
    """
    Generate Avatar V video with motion_prompt for walking movement.
    output_format=webm gives transparent alpha channel - no green screen needed.
    Returns local path to downloaded webm file.
    """
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
    print(f'[HeyGen] Video ID: {video_id} - polling...')
    
    # Poll until complete
    for i in range(120):
        time.sleep(10)
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
    
    raise RuntimeError('HeyGen timed out after 20 minutes')

# ==============================================================
# STEP 3: Generate Cinematic Avatar clips - Aaron WALKING around vehicle
# These are silent visual-only clips showing Aaron moving around the car
# ==============================================================
def generate_cinematic_clip(look_id, vehicle_photos, vehicle_name, lot_bg_path, duration, tmpdir, clip_index):
    """
    Generate a cinematic avatar clip showing Aaron walking around a vehicle.
    Uses vehicle photos as references so HeyGen knows what vehicle to show.
    Returns local path to downloaded mp4.
    """
    print(f'[Cinematic] Generating clip {clip_index} ({duration}s)...')
    
    # Build references from vehicle photos (up to 3 images per clip per API limit)
    references = []
    # Add lot background as style reference
    references.append({'type': 'url', 'url': LOT_BG_URL})
    # Add up to 2 vehicle photos
    for photo_url in vehicle_photos[:2]:
        references.append({'type': 'url', 'url': photo_url})
    
    prompt = (
        f"A professional used car salesman in a blue button-up shirt walks around a {vehicle_name} "
        f"on a used car dealership lot. He moves from the front to the side of the vehicle, "
        f"gesturing toward specific parts of the car. Shot handheld in selfie-style POV, "
        f"as if the salesman is holding the camera while walking. "
        f"The vehicle is prominently visible in the background as he walks around it. "
        f"Bright daylight, natural lighting, used car lot setting."
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
    
    for i in range(60):
        time.sleep(10)
        sr = requests.get(HEYGEN_BASE + '/v3/videos/' + video_id, headers=heygen_headers(), timeout=30)
        vdata = sr.json().get('data', {})
        status = vdata.get('status', 'unknown')
        if status == 'completed':
            video_url = vdata.get('video_url')
            clip_path = os.path.join(tmpdir, f'cinematic_{clip_index:02d}.mp4')
            _download_file(video_url, clip_path)
            print(f'[Cinematic] Clip {clip_index} downloaded')
            return clip_path
        elif status == 'failed':
            print(f'[Cinematic] Clip {clip_index} failed: {vdata.get("failure_message")}')
            return None
    
    print(f'[Cinematic] Clip {clip_index} timed out')
    return None

# ==============================================================
# HELPER: Download file
# ==============================================================
def _download_file(url, dest_path):
    r = requests.get(url, headers=HEADERS, stream=True, timeout=120)
    r.raise_for_status()
    with open(dest_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)

# ==============================================================
# STEP 4: Download lot background image
# ==============================================================
def get_lot_background(tmpdir):
    lot_path = os.path.join(tmpdir, 'lot_bg.jpg')
    try:
        _download_file(LOT_BG_URL, lot_path)
        # Crop/resize to 9:16 portrait
        img = Image.open(lot_path).convert('RGB')
        # Crop center to portrait
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
        print(f'[Lot BG] Saved: {lot_path}')
        return lot_path
    except Exception as e:
        print(f'[Lot BG] Failed to download: {e}')
        # Create solid dark background
        img = Image.new('RGB', (W, H), (30, 40, 30))
        img.save(lot_path, 'JPEG')
        return lot_path

# ==============================================================
# STEP 5: Composite webm alpha (Aaron) over vehicle photo background
# This creates the "Aaron standing in front of vehicle" effect using FFmpeg
# ==============================================================
def composite_avatar_over_background(webm_path, bg_image_path, audio_start, duration, output_mp4, tmpdir):
    """
    Aaron (webm with alpha) composited over a vehicle photo background.
    Aaron is positioned center-bottom (selfie POV), vehicle photo fills full frame behind him.
    FFmpeg handles the alpha blending natively with webm.
    """
    # First prepare a looping background video from the still image
    bg_video = os.path.join(tmpdir, f'bg_{os.path.basename(output_mp4)}.mp4')
    
    # Create background video from image with Ken Burns zoom effect
    zoom_scale = 1.05 + (hash(bg_image_path) % 10) * 0.005  # slight zoom per image
    
    # Scale image to fill frame with slight zoom
    bg_cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', bg_image_path,
        '-vf', (
            f'scale={W}:{H}:force_original_aspect_ratio=cover,'
            f'crop={W}:{H},'
            f'zoompan=z=\'if(lte(zoom,1.0),1.0,zoom-0.0005)\':x=\'iw/2-(iw/zoom/2)\':y=\'ih*0.3-(ih/zoom/2)\':d={int(duration*30)}:s={W}x{H}:fps=30'
        ),
        '-t', str(duration),
        '-r', '30',
        '-pix_fmt', 'yuv420p',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        bg_video
    ]
    subprocess.run(bg_cmd, check=True, capture_output=True)
    
    # Trim the webm to this segment's audio window
    webm_trim = os.path.join(tmpdir, f'webm_trim_{os.path.basename(output_mp4)}.webm')
    trim_cmd = [
        'ffmpeg', '-y',
        '-ss', str(audio_start),
        '-i', webm_path,
        '-t', str(duration),
        '-c:v', 'libvpx-vp9', '-c:a', 'copy',
        webm_trim
    ]
    result = subprocess.run(trim_cmd, capture_output=True)
    if result.returncode != 0:
        # webm may not have audio, just copy video
        trim_cmd2 = [
            'ffmpeg', '-y',
            '-ss', str(audio_start),
            '-i', webm_path,
            '-t', str(duration),
            '-c:v', 'libvpx-vp9', '-an',
            webm_trim
        ]
        subprocess.run(trim_cmd2, check=True, capture_output=True)
    
    # Composite: bg video (vehicle photo) + Aaron (webm alpha) overlaid centered-bottom
    # Aaron is scaled to 80% of frame height, positioned at center-bottom
    aaron_h = int(H * 0.80)
    aaron_w = int(aaron_h * (9/16))
    aaron_x = (W - aaron_w) // 2
    aaron_y = H - aaron_h - 20  # 20px from bottom
    
    # Extract audio from main webm
    audio_from_webm = os.path.join(tmpdir, f'audio_{os.path.basename(output_mp4)}.aac')
    audio_cmd = [
        'ffmpeg', '-y',
        '-ss', str(audio_start),
        '-i', webm_path,
        '-t', str(duration),
        '-vn', '-c:a', 'aac', '-b:a', '192k',
        audio_from_webm
    ]
    audio_result = subprocess.run(audio_cmd, capture_output=True)
    has_audio = audio_result.returncode == 0 and os.path.exists(audio_from_webm) and os.path.getsize(audio_from_webm) > 100
    
    # Build composite command
    if has_audio:
        composite_cmd = [
            'ffmpeg', '-y',
            '-i', bg_video,
            '-i', webm_trim,
            '-i', audio_from_webm,
            '-filter_complex', (
                f'[1:v]scale={aaron_w}:{aaron_h}[avatar];'
                f'[0:v][avatar]overlay={aaron_x}:{aaron_y}:format=auto[out]'
            ),
            '-map', '[out]',
            '-map', '2:a',
            '-t', str(duration),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            output_mp4
        ]
    else:
        composite_cmd = [
            'ffmpeg', '-y',
            '-i', bg_video,
            '-i', webm_trim,
            '-filter_complex', (
                f'[1:v]scale={aaron_w}:{aaron_h}[avatar];'
                f'[0:v][avatar]overlay={aaron_x}:{aaron_y}:format=auto[out]'
            ),
            '-map', '[out]',
            '-t', str(duration),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
            '-pix_fmt', 'yuv420p',
            '-an',
            output_mp4
        ]
    
    subprocess.run(composite_cmd, check=True, capture_output=True)
    print(f'[Composite] Created: {output_mp4}')

# ==============================================================
# STEP 6: Use cinematic clip as visual with webm audio
# Aaron is ACTUALLY WALKING in the cinematic clip
# The voice from the webm is synced on top
# ==============================================================
def merge_cinematic_with_audio(cinematic_mp4, webm_path, audio_start, duration, output_mp4, tmpdir):
    """
    Take a cinematic clip (Aaron walking around vehicle, silent) and
    overlay the voice audio from the HeyGen webm. This gives us:
    - Aaron actually walking around the vehicle (cinematic visual)
    - Aaron's voice narrating the script (webm audio)
    """
    # Extract audio from webm
    audio_path = os.path.join(tmpdir, f'aud_{os.path.basename(output_mp4)}.aac')
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
    
    # Trim cinematic to needed duration
    cin_trim = os.path.join(tmpdir, f'cin_trim_{os.path.basename(output_mp4)}.mp4')
    trim_cmd = [
        'ffmpeg', '-y',
        '-stream_loop', '-1',  # loop if cinematic is shorter than needed duration
        '-i', cinematic_mp4,
        '-t', str(duration),
        '-vf', f'scale={W}:{H}:force_original_aspect_ratio=cover,crop={W}:{H}',
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
        merge_cmd = [
            'ffmpeg', '-y',
            '-i', cin_trim,
            '-c:v', 'copy',
            '-an',
            output_mp4
        ]
    subprocess.run(merge_cmd, check=True, capture_output=True)
    print(f'[Cinematic+Audio] Created: {output_mp4}')

# ==============================================================
# STEP 7: Build intro/outro - Aaron on lot background
# ==============================================================
def build_intro_outro_segment(webm_path, lot_bg_path, audio_start, duration, output_mp4, tmpdir):
    """
    Intro/outro: Aaron (full frame transparent) composited on lot background.
    Aaron centered, lot background fills frame.
    """
    composite_avatar_over_background(webm_path, lot_bg_path, audio_start, duration, output_mp4, tmpdir)

# ==============================================================
# MAIN ORCHESTRATOR
# ==============================================================
def build_walkaround_video(vehicle, script_segments, heygen_webm_path, 
                           cinematic_clips, vehicle_photos, tmpdir):
    """
    Assemble the final walkaround video from:
    - heygen_webm_path: Avatar V webm with transparent walking Aaron + voice
    - cinematic_clips: list of (path, segment_index) Cinematic Avatar clips
    - vehicle_photos: downloaded vehicle photo paths
    - script_segments: list of dicts with {type, duration, audio_start, photo_index}
    """
    lot_bg_path = get_lot_background(tmpdir)
    segment_files = []
    
    cinematic_map = {idx: path for path, idx in cinematic_clips}
    
    for i, seg in enumerate(script_segments):
        seg_type = seg.get('type')
        audio_start = seg.get('audio_start', 0)
        duration = seg.get('duration', 5)
        seg_out = os.path.join(tmpdir, f'seg_{i:03d}.mp4')
        
        if seg_type in ('intro', 'outro'):
            build_intro_outro_segment(heygen_webm_path, lot_bg_path, audio_start, duration, seg_out, tmpdir)
        
        elif seg_type == 'walkaround':
            photo_idx = seg.get('photo_index', 0)
            cin_idx = seg.get('cinematic_index', None)
            
            if cin_idx is not None and cin_idx in cinematic_map:
                # Use cinematic clip (Aaron walking around vehicle) with voice audio
                merge_cinematic_with_audio(
                    cinematic_map[cin_idx], heygen_webm_path,
                    audio_start, duration, seg_out, tmpdir
                )
            elif photo_idx < len(vehicle_photos):
                # Fall back: Aaron (webm) composited over vehicle photo
                composite_avatar_over_background(
                    heygen_webm_path, vehicle_photos[photo_idx],
                    audio_start, duration, seg_out, tmpdir
                )
            else:
                build_intro_outro_segment(heygen_webm_path, lot_bg_path, audio_start, duration, seg_out, tmpdir)
        
        else:
            build_intro_outro_segment(heygen_webm_path, lot_bg_path, audio_start, duration, seg_out, tmpdir)
        
        if os.path.exists(seg_out):
            segment_files.append(seg_out)
    
    if not segment_files:
        raise RuntimeError('No segments generated')
    
    # Concatenate all segments
    final_path = os.path.join(tmpdir, 'final.mp4')
    concat_file = os.path.join(tmpdir, 'concat.txt')
    with open(concat_file, 'w') as f:
        for sf in segment_files:
            f.write(f"file '{sf}'\n")
    
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
    subprocess.run(concat_cmd, check=True, capture_output=True)
    print(f'[Final] Assembled: {final_path}')
    return final_path
