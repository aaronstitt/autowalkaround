import os, requests, tempfile, subprocess, json, shutil

HEADERS = {'User-Agent': 'Mozilla/5.0'}
# Target dimensions - scaled down to save memory
TARGET_W = 1080
TARGET_H = 1920
# Scale images down to at most this size before processing
MAX_IMG_W = 1200

def download_file(url, dest):
    try:
        resp = requests.get(url, stream=True, timeout=30, headers=HEADERS)
        resp.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f'Download failed {url}: {e}')
        return False

def get_video_duration(path):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(json.loads(r.stdout)['format']['duration'])
    except Exception:
        return 60.0

def convert_to_small_jpeg(src, dest):
    """Convert any image to a small JPEG (max MAX_IMG_W wide) for memory-efficient ffmpeg."""
    cmd = [
        'ffmpeg', '-y', '-i', src,
        '-vf', f'scale=min({MAX_IMG_W}\,iw):-2',
        '-q:v', '3', dest
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode == 0 and os.path.exists(dest)

def build_pov_background(photo_paths, output_path, total_duration, width=TARGET_W, height=TARGET_H):
    """Create slideshow from photos. Uses concat demuxer with small JPEGs to save memory."""
    if not photo_paths:
        raise ValueError('No photos')
    
    n = len(photo_paths)
    per_photo = total_duration / n
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Convert to small JPEGs for memory efficiency
        jpeg_paths = []
        for i, p in enumerate(photo_paths):
            jpg = os.path.join(tmpdir, f'img_{i:03d}.jpg')
            if convert_to_small_jpeg(p, jpg):
                jpeg_paths.append(jpg)
                print(f'Converted photo {i+1}/{n} to JPEG')
            else:
                print(f'Warning: skipped photo {i}')
        
        if not jpeg_paths:
            raise RuntimeError('No images could be converted')
        
        n = len(jpeg_paths)
        per_photo = total_duration / n
        
        # Write concat list
        list_file = os.path.join(tmpdir, 'list.txt')
        with open(list_file, 'w') as f:
            for p in jpeg_paths:
                f.write(f"file '{p}'\nduration {round(per_photo, 2)}\n")
            f.write(f"file '{jpeg_paths[-1]}'\n")
        
        # Simple concat slideshow - memory friendly settings
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', list_file,
            '-vf', f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
            '-pix_fmt', 'yuv420p', '-r', '15', '-t', str(total_duration),
            '-threads', '2',
            output_path
        ]
        
        print(f'Building slideshow: {n} photos, {total_duration:.1f}s, ultrafast preset')
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            err = r.stderr[-500:] if r.stderr else 'no stderr'
            print(f'Slideshow failed stderr: {err}')
            raise RuntimeError(f'Slideshow rc={r.returncode}: {err[-300:]}')
    
    return output_path

def composite_avatar_on_background(heygen_path, bg_path, output_path, width=TARGET_W, height=TARGET_H):
    avatar_target_w = int(width * 0.48)
    filter_complex = (
        f'[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[bg];'
        f'[1:v]scale={avatar_target_w}:-2[avatar_scaled];'
        f'[avatar_scaled]crop=iw:ih*0.85:0:ih*0.10[avatar_cropped];'
        f'[bg][avatar_cropped]overlay=W-w-16:H-h-24:shortest=1[outv]'
    )
    cmd = ['ffmpeg', '-y', '-i', bg_path, '-i', heygen_path,
           '-filter_complex', filter_complex,
           '-map', '[outv]', '-map', '1:a',
           '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
           '-threads', '2', '-shortest', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=360)
    if r.returncode != 0:
        raise RuntimeError('Composite failed rc=' + str(r.returncode) + ': ' + r.stderr[-400:])
    return output_path

def add_text_overlays(video_path, output_path, vehicle_name, price, dealer_name):
    def safe(s):
        return str(s or '').replace("'", '').replace(':', '-').replace('"', '').replace('\\', '')[:50]
    vname = safe(vehicle_name)
    vprice = ('$' + safe(price)) if price else ''
    vdealer = safe(dealer_name)
    drawtext_filters = []
    if vname:
        drawtext_filters.append(f"drawtext=text='{vname}':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=h-180:box=1:boxcolor=black@0.65:boxborderw=8")
    if vprice:
        drawtext_filters.append(f"drawtext=text='{vprice}':fontcolor=#FFD700:fontsize=36:x=(w-text_w)/2:y=h-125:box=1:boxcolor=black@0.65:boxborderw=7")
    if vdealer:
        drawtext_filters.append(f"drawtext=text='{vdealer}':fontcolor=white:fontsize=20:x=(w-text_w)/2:y=h-68:box=1:boxcolor=black@0.65:boxborderw=6")
    if not drawtext_filters:
        shutil.copy(video_path, output_path)
        return output_path
    vf = ','.join(drawtext_filters)
    cmd = ['ffmpeg', '-y', '-i', video_path, '-vf', vf,
           '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
           '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-threads', '2', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        raise RuntimeError('Text overlay failed: ' + r.stderr[-400:])
    return output_path

def download_vehicle_photos(photo_urls, tmpdir, max_photos=6):
    downloaded = []
    for i, url in enumerate(photo_urls[:max_photos]):
        ext = url.split('.')[-1].split('?')[0].lower() or 'jpg'
        if ext not in ('jpg', 'jpeg', 'png', 'webp'):
            ext = 'jpg'
        dest = os.path.join(tmpdir, f'photo_{i:03d}.{ext}')
        if download_file(url, dest):
            downloaded.append(dest)
    return downloaded

async def assemble_final_video(vehicle, heygen_video_url, output_dir, job_id):
    os.makedirs(output_dir, exist_ok=True)
    heygen_path = os.path.join(output_dir, f'{job_id}_heygen.mp4')
    bg_path = os.path.join(output_dir, f'{job_id}_bg.mp4')
    composite_path = os.path.join(output_dir, f'{job_id}_composite.mp4')
    final_path = os.path.join(output_dir, f'{job_id}_final.mp4')
    if not download_file(heygen_video_url, heygen_path):
        raise ValueError('Failed to download HeyGen video')
    duration = get_video_duration(heygen_path)
    print(f'HeyGen video duration: {duration:.1f}s')
    all_photos = vehicle.get('photos', [])
    if not all_photos:
        raise ValueError('No vehicle photos available')
    with tempfile.TemporaryDirectory() as tmpdir:
        downloaded = download_vehicle_photos(all_photos, tmpdir, max_photos=6)
        if not downloaded:
            raise ValueError('Failed to download any vehicle photos')
        print(f'Downloaded {len(downloaded)} vehicle photos')
        build_pov_background(downloaded, bg_path, duration)
        composite_avatar_on_background(heygen_path, bg_path, composite_path)
        add_text_overlays(composite_path, final_path, vehicle.get('name', ''), vehicle.get('price', ''), vehicle.get('dealer_name', ''))
    return final_path
