import os, requests, subprocess, json, shutil, tempfile

HEADERS = {'User-Agent': 'Mozilla/5.0'}
W = 1080
H = 1920

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

def assemble_with_single_pass(photo_path, heygen_path, output_path, duration, vehicle_name='', price='', dealer_name=''):
    aw = int(W * 0.48)
    def safe(s):
        return str(s or '').replace("'", '').replace(':', '-').replace('"', '')[:45]
    texts = []
    vn = safe(vehicle_name)
    vp = safe(price)
    vd = safe(dealer_name)
    if vn:
        texts.append("drawtext=text='" + vn + "':fontcolor=white:fontsize=26:x=(w-text_w)/2:y=h-175:box=1:boxcolor=black@0.65:boxborderw=7")
    if vp:
        texts.append("drawtext=text='$" + vp + "':fontcolor=#FFD700:fontsize=32:x=(w-text_w)/2:y=h-120:box=1:boxcolor=black@0.65:boxborderw=6")
    if vd:
        texts.append("drawtext=text='" + vd + "':fontcolor=white:fontsize=18:x=(w-text_w)/2:y=h-65:box=1:boxcolor=black@0.65:boxborderw=5")
    text_filter = (',' + ','.join(texts)) if texts else ''
    filter_complex = (
        '[0:v]scale=' + str(W) + ':' + str(H) + ':force_original_aspect_ratio=increase,crop=' + str(W) + ':' + str(H) + ',setsar=1[bg];'
        '[1:v]scale=' + str(aw) + ':-2[av];'
        '[av]crop=iw:ih*0.85:0:ih*0.10[ac];'
        '[bg][ac]overlay=W-w-16:H-h-24:shortest=1[ov];'
        '[ov]fps=15' + text_filter + '[outv]'
    )
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-t', str(int(duration) + 2), '-i', photo_path,
        '-i', heygen_path,
        '-filter_complex', filter_complex,
        '-map', '[outv]', '-map', '1:a',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
        '-threads', '2', '-shortest',
        output_path
    ]
    print('Single-pass assemble: duration=' + str(duration))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=480)
    if r.returncode != 0:
        raise RuntimeError('Assemble rc=' + str(r.returncode) + ': ' + r.stderr[-500:])
    return output_path

async def assemble_final_video(vehicle, heygen_video_url, output_dir, job_id):
    os.makedirs(output_dir, exist_ok=True)
    heygen_path = os.path.join(output_dir, job_id + '_heygen.mp4')
    final_path = os.path.join(output_dir, job_id + '_final.mp4')
    if not download_file(heygen_video_url, heygen_path):
        raise ValueError('Failed to download HeyGen video')
    duration = get_video_duration(heygen_path)
    print('HeyGen duration: ' + str(duration))
    all_photos = vehicle.get('photos', [])
    if not all_photos:
        raise ValueError('No vehicle photos available')
    with tempfile.TemporaryDirectory() as tmpdir:
        photo_path = None
        for i, url in enumerate(all_photos[:5]):
            ext = url.split('.')[-1].split('?')[0].lower()
            if ext not in ('jpg', 'jpeg', 'png', 'webp'):
                ext = 'jpg'
            dest = os.path.join(tmpdir, 'photo_' + str(i) + '.' + ext)
            if download_file(url, dest):
                photo_path = dest
                print('Using photo ' + str(i+1) + ' as background')
                break
        if not photo_path:
            raise ValueError('Could not download any vehicle photo')
        assemble_with_single_pass(
            photo_path, heygen_path, final_path, duration,
            vehicle.get('name', ''), vehicle.get('price', ''), vehicle.get('dealer_name', '')
        )
    return final_path
