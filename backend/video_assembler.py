import os, requests, tempfile, subprocess, json, shutil

HEADERS = {'User-Agent': 'Mozilla/5.0'}
TARGET_W = 1080
TARGET_H = 1920

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

def resize_image(src, dest, max_w=960):
    """Resize image to max_w keeping aspect ratio, output as JPEG."""
    cmd = ['ffmpeg', '-y', '-i', src,
           '-vf', f'scale=if(gt(iw\,{max_w})\,{max_w}\,iw):-2',
           '-q:v', '4', dest]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        # fallback: just copy with no resize
        shutil.copy(src, dest)
    return os.path.exists(dest)

def build_slideshow(photo_paths, output_path, total_duration):
    """Build a simple slideshow MP4 from images."""
    n = len(photo_paths)
    per_photo = max(total_duration / n, 1.0)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Resize images first
        small_paths = []
        for i, p in enumerate(photo_paths):
            ext = os.path.splitext(p)[1] or '.jpg'
            dest = os.path.join(tmpdir, f'sm_{i:03d}.jpg')
            resize_image(p, dest)
            if os.path.exists(dest):
                small_paths.append(dest)
                print(f'Resized photo {i+1}/{n}')

        if not small_paths:
            raise RuntimeError('No photos after resizing')

        n = len(small_paths)
        per_photo = max(total_duration / n, 1.0)

        # Write concat list
        listf = os.path.join(tmpdir, 'imgs.txt')
        with open(listf, 'w') as f:
            for p in small_paths:
                f.write(f"file '{p}'\nduration {per_photo:.2f}\n")
            f.write(f"file '{small_paths[-1]}'\n")

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', listf,
            '-vf', f'scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,crop={TARGET_W}:{TARGET_H},setsar=1,fps=15',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '30',
            '-pix_fmt', 'yuv420p', '-t', str(int(total_duration) + 1),
            '-threads', '1',
            output_path
        ]
        print(f'Slideshow: {n} photos, {total_duration:.1f}s')
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f'Slideshow rc={r.returncode}: {r.stderr[-400:]}')
    return output_path

def composite_avatar_on_background(heygen_path, bg_path, output_path):
    aw = int(TARGET_W * 0.48)
    fc = (
        f'[0:v]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,'
        f'crop={TARGET_W}:{TARGET_H},setsar=1[bg];'
        f'[1:v]scale={aw}:-2[av];'
        f'[av]crop=iw:ih*0.85:0:ih*0.10[ac];'
        f'[bg][ac]overlay=W-w-16:H-h-24:shortest=1[outv]'
    )
    cmd = ['ffmpeg', '-y', '-i', bg_path, '-i', heygen_path,
           '-filter_complex', fc,
           '-map', '[outv]', '-map', '1:a',
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
           '-threads', '1', '-shortest', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=360)
    if r.returncode != 0:
        raise RuntimeError(f'Composite rc={r.returncode}: {r.stderr[-400:]}')
    return output_path

def add_text_overlays(video_path, output_path, vehicle_name, price, dealer_name):
    def safe(s):
        return str(s or '').replace("'", '').replace(':', '-').replace('"', '').replace('\\', '')[:50]
    vname = safe(vehicle_name)
    vprice = ('$' + safe(price)) if price else ''
    vdealer = safe(dealer_name)
    filters = []
    if vname:
        filters.append(f"drawtext=text='{vname}':fontcolor=white:fontsize=28:x=(w-text_w)/2:y=h-180:box=1:boxcolor=black@0.65:boxborderw=8")
    if vprice:
        filters.append(f"drawtext=text='{vprice}':fontcolor=#FFD700:fontsize=36:x=(w-text_w)/2:y=h-125:box=1:boxcolor=black@0.65:boxborderw=7")
    if vdealer:
        filters.append(f"drawtext=text='{vdealer}':fontcolor=white:fontsize=20:x=(w-text_w)/2:y=h-68:box=1:boxcolor=black@0.65:boxborderw=6")
    if not filters:
        shutil.copy(video_path, output_path)
        return output_path
    cmd = ['ffmpeg', '-y', '-i', video_path,
           '-vf', ','.join(filters),
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
           '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-threads', '1', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        # text overlay failed - just copy without text
        print(f'Text overlay failed (non-fatal): {r.stderr[-200:]}')
        shutil.copy(video_path, output_path)
    return output_path

def download_vehicle_photos(photo_urls, tmpdir, max_photos=4):
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
    composite_path = os.path.join(output_dir, f'{job_id}_comp.mp4')
    final_path = os.path.join(output_dir, f'{job_id}_final.mp4')

    if not download_file(heygen_video_url, heygen_path):
        raise ValueError('Failed to download HeyGen video')
    duration = get_video_duration(heygen_path)
    print(f'HeyGen duration: {duration:.1f}s')

    all_photos = vehicle.get('photos', [])
    if not all_photos:
        raise ValueError('No vehicle photos')

    with tempfile.TemporaryDirectory() as tmpdir:
        downloaded = download_vehicle_photos(all_photos, tmpdir, max_photos=4)
        if not downloaded:
            raise ValueError('Could not download vehicle photos')
        print(f'Downloaded {len(downloaded)} photos')
        build_slideshow(downloaded, bg_path, duration)
        composite_avatar_on_background(heygen_path, bg_path, composite_path)
        add_text_overlays(composite_path, final_path,
                         vehicle.get('name', ''), vehicle.get('price', ''), vehicle.get('dealer_name', ''))

    return final_path
