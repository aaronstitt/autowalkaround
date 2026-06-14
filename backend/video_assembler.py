import os, requests, subprocess, json, shutil, tempfile

HEADERS = {'User-Agent': 'Mozilla/5.0'}
W = 720
H = 1280

def download_file(url, dest):
    try:
        resp = requests.get(url, stream=True, timeout=30, headers=HEADERS)
        resp.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        print('Download failed ' + url + ': ' + str(e))
        return False

def get_video_duration(path):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(json.loads(r.stdout)['format']['duration'])
    except Exception:
        return 60.0

def prescale_photo(src, dest):
    """Scale photo to exact W x H canvas (letterbox/fill). Output JPEG."""
    # Scale to fill W x H, crop center. Done in one small ffmpeg call.
    cmd = [
        'ffmpeg', '-y', '-i', src,
        '-vf', 'scale=' + str(W) + ':' + str(H) + ':force_original_aspect_ratio=increase,crop=' + str(W) + ':' + str(H),
        '-q:v', '3', '-frames:v', '1',
        dest
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode == 0 and os.path.exists(dest)

def build_walkaround_slideshow(scaled_paths, output_path, duration):
    """Build slideshow from pre-scaled W x H images. No scaling needed = low memory."""
    n = len(scaled_paths)
    per_photo = max(duration / n, 1.5)

    with tempfile.TemporaryDirectory() as tmpdir:
        listf = os.path.join(tmpdir, 'list.txt')
        with open(listf, 'w') as f:
            for p in scaled_paths:
                f.write("file '" + p + "'\nduration " + str(round(per_photo, 2)) + "\n")
            # repeat last frame to avoid concat timing issues
            f.write("file '" + scaled_paths[-1] + "'\n")

        # Images are already W x H so no scale filter needed - very low memory
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', listf,
            '-vf', 'fps=15,setsar=1',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
            '-pix_fmt', 'yuv420p',
            '-t', str(int(duration) + 1),
            '-threads', '2',
            '-b:v', '800k', '-maxrate', '900k', '-bufsize', '1500k',
            output_path
        ]
        print('Building walkaround slideshow: ' + str(n) + ' photos, ' + str(round(duration, 1)) + 's, ' + str(round(per_photo, 1)) + 's/photo')
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError('Slideshow failed rc=' + str(r.returncode) + ': ' + r.stderr[-400:])
    return output_path

def overlay_avatar_and_text(slideshow_path, heygen_path, output_path, vehicle_name='', price='', dealer_name=''):
    """Overlay the HeyGen avatar as a bottom-right PIP over the slideshow."""
    aw = int(W * 0.42)  # avatar width ~42% of screen

    def safe(s):
        return str(s or '').replace("'", '').replace(':', '-').replace('"', '')[:45]

    texts = []
    vn = safe(vehicle_name)
    vp = safe(price)
    vd = safe(dealer_name)
    if vn:
        texts.append("drawtext=text='" + vn + "':fontcolor=white:fontsize=22:x=(w-text_w)/2:y=h-140:box=1:boxcolor=black@0.7:boxborderw=6")
    if vp:
        texts.append("drawtext=text='$" + vp + "':fontcolor=#FFD700:fontsize=28:x=(w-text_w)/2:y=h-98:box=1:boxcolor=black@0.7:boxborderw=5")
    if vd:
        texts.append("drawtext=text='" + vd + "':fontcolor=white:fontsize=16:x=(w-text_w)/2:y=h-55:box=1:boxcolor=black@0.7:boxborderw=4")

    text_filter = (','.join(texts) + ',') if texts else ''

    # Avatar: scale down, crop top 10% (usually empty space), place bottom-right
    filter_complex = (
        '[0:v]' + text_filter + 'setsar=1[bg];'
        '[1:v]scale=' + str(aw) + ':-2[av];'
        '[av]crop=iw:ih*0.85:0:ih*0.10[avc];'
        '[bg][avc]overlay=W-w-12:H-h-20:shortest=1[out]'
    )

    cmd = [
        'ffmpeg', '-y',
        '-i', slideshow_path,
        '-i', heygen_path,
        '-filter_complex', filter_complex,
        '-map', '[out]', '-map', '1:a',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
        '-b:v', '1200k', '-maxrate', '1400k', '-bufsize', '2000k',
        '-threads', '2', '-shortest',
        output_path
    ]
    print('Overlaying avatar PIP...')
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=480)
    if r.returncode != 0:
        raise RuntimeError('Overlay failed rc=' + str(r.returncode) + ': ' + r.stderr[-400:])
    return output_path

async def assemble_final_video(vehicle, heygen_video_url, output_dir, job_id):
    os.makedirs(output_dir, exist_ok=True)
    heygen_path = os.path.join(output_dir, job_id + '_heygen.mp4')
    slideshow_path = os.path.join(output_dir, job_id + '_slide.mp4')
    final_path = os.path.join(output_dir, job_id + '_final.mp4')

    # 1. Download HeyGen avatar video
    if not download_file(heygen_video_url, heygen_path):
        raise ValueError('Failed to download HeyGen video')
    duration = get_video_duration(heygen_path)
    print('HeyGen duration: ' + str(round(duration, 1)) + 's')

    # 2. Get vehicle photos - use all available, up to 12
    all_photos = vehicle.get('photos', [])
    if not all_photos:
        raise ValueError('No vehicle photos available from listing')

    # Pick a good spread: exterior first, then interior
    # Listing photos are typically ordered: exterior angles then interior
    # Use up to 10 photos spread across the full list
    max_photos = min(10, len(all_photos))
    if len(all_photos) > max_photos:
        step = len(all_photos) / max_photos
        photo_urls = [all_photos[int(i * step)] for i in range(max_photos)]
    else:
        photo_urls = all_photos

    print('Using ' + str(len(photo_urls)) + ' photos from listing (of ' + str(len(all_photos)) + ' total)')

    with tempfile.TemporaryDirectory() as tmpdir:
        # 3. Download and pre-scale each photo to exact W x H
        scaled_paths = []
        for i, url in enumerate(photo_urls):
            ext = url.split('.')[-1].split('?')[0].lower()
            if ext not in ('jpg', 'jpeg', 'png', 'webp'):
                ext = 'jpg'
            raw = os.path.join(tmpdir, 'raw_' + str(i) + '.' + ext)
            scaled = os.path.join(tmpdir, 'scaled_' + str(i) + '.jpg')
            if download_file(url, raw) and prescale_photo(raw, scaled):
                scaled_paths.append(scaled)
                print('Photo ' + str(i+1) + ' ready (' + str(round(os.path.getsize(scaled)/1024)) + 'KB)')
            else:
                print('Skipped photo ' + str(i+1))

        if not scaled_paths:
            raise ValueError('Could not download/scale any vehicle photos')

        print('Scaled ' + str(len(scaled_paths)) + ' photos to ' + str(W) + 'x' + str(H))

        # 4. Build walkaround slideshow (vehicle photos fill the screen)
        build_walkaround_slideshow(scaled_paths, slideshow_path, duration)

        # 5. Overlay avatar as PIP + text
        overlay_avatar_and_text(
            slideshow_path, heygen_path, final_path,
            vehicle.get('name', ''), vehicle.get('price', ''), vehicle.get('dealer_name', '')
        )

    return final_path
