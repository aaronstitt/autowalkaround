import os, requests, tempfile, subprocess
from typing import List
import json

HEADERS = {'User-Agent': 'Mozilla/5.0'}

def download_file(url, dest):
    try:
        resp = requests.get(url, stream=True, timeout=30, headers=HEADERS)
        resp.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in resp.iter_content(8192): f.write(chunk)
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

def _simple_slideshow(downloaded, output_path, total_duration):
    with tempfile.TemporaryDirectory() as tmpdir:
        n = len(downloaded)
        per_photo = total_duration / n
        list_file = os.path.join(tmpdir, 'photos.txt')
        with open(list_file, 'w') as f:
            for p in downloaded:
                f.write("file '" + p + "'\nduration " + str(round(per_photo, 2)) + "\n")
            f.write("file '" + downloaded[-1] + "'\n")
        cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_file,
               '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1',
               '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p',
               '-r', '30', '-t', str(total_duration), output_path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            raise RuntimeError('Slideshow failed: ' + r.stderr[:500])
        return output_path

def create_pov_slideshow(photo_urls, output_path, total_duration):
    with tempfile.TemporaryDirectory() as tmpdir:
        downloaded = []
        for i, url in enumerate(photo_urls[:18]):
            ext = url.split('.')[-1].split('?')[0] or 'jpg'
            dest = os.path.join(tmpdir, f'photo_{i:03d}.{ext}')
            if download_file(url, dest):
                downloaded.append(dest)
        if not downloaded:
            raise ValueError('No photos downloaded')
        n = len(downloaded)
        per_photo = total_duration / n
        fps = 30
        frames_per = max(int(per_photo * fps), 30)
        filter_parts = []
        concat_parts = []
        inputs = []
        for i, photo in enumerate(downloaded):
            inputs += ['-loop', '1', '-t', str(per_photo + 0.5), '-i', photo]
            if i % 3 == 0:
                zf = 'zoompan=z=min(zoom+0.0012\\,1.4):x=iw/2-(iw/zoom/2):y=ih/2-(ih/zoom/2):d=' + str(frames_per) + ':s=1080x1920:fps=' + str(fps)
            elif i % 3 == 1:
                zf = 'zoompan=z=1.3:x=iw*0.1:y=ih/2-(ih/zoom/2):d=' + str(frames_per) + ':s=1080x1920:fps=' + str(fps)
            else:
                zf = 'zoompan=z=1.2:x=iw*0.05:y=ih/2-(ih/zoom/2):d=' + str(frames_per) + ':s=1080x1920:fps=' + str(fps)
            scale_f = 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920'
            filter_parts.append('[' + str(i) + ':v]' + scale_f + ',' + zf + ',setsar=1[v' + str(i) + ']')
            concat_parts.append('[v' + str(i) + ']')
        filter_complex = ';'.join(filter_parts) + ';' + ''.join(concat_parts) + 'concat=n=' + str(n) + ':v=1:a=0[outv]'
        cmd = ['ffmpeg', '-y'] + inputs + [
            '-filter_complex', filter_complex,
            '-map', '[outv]',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p',
            '-t', str(total_duration), output_path
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=360)
        if r.returncode != 0:
            return _simple_slideshow(downloaded, output_path, total_duration)
        return output_path

def composite_pov_video(heygen_path, bg_path, output_path):
    filter_complex = (
        '[1:v]scale=400:-1,'
        'crop=400:in_h*0.80:0:in_h*0.12,'
        'format=yuva420p[avatar];'
        '[0:v][avatar]overlay=W-w-20:H-h-72:shortest=1[outv]'
    )
    cmd = ['ffmpeg', '-y',
           '-i', bg_path, '-i', heygen_path,
           '-filter_complex', filter_complex,
           '-map', '[outv]', '-map', '1:a',
           '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-shortest', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError('Composite failed: ' + r.stderr[:600])
    return output_path

def add_text_overlays(video_path, output_path, vehicle_name, price, dealer_name):
    def safe(s): return str(s).replace("'", '').replace(':', '-').replace('"', '')[:50]
    vname = safe(vehicle_name)
    vprice = '$' + safe(price) if price else ''
    vdealer = safe(dealer_name)
    parts = ["drawtext=text='" + vname + "':fontcolor=white:fontsize=32:x=(w-text_w)/2:y=h-175:box=1:boxcolor=black@0.6:boxborderw=10"]
    if vprice:
        parts.append("drawtext=text='" + vprice + "':fontcolor=#FFD700:fontsize=42:x=(w-text_w)/2:y=h-120:box=1:boxcolor=black@0.6:boxborderw=8")
    if vdealer:
        parts.append("drawtext=text='" + vdealer + "':fontcolor=white:fontsize=22:x=(w-text_w)/2:y=h-60:box=1:boxcolor=black@0.6:boxborderw=6")
    cmd = ['ffmpeg', '-y', '-i', video_path, '-vf', ','.join(parts),
           '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', '-pix_fmt', 'yuv420p', '-c:a', 'copy', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError('Text overlay failed: ' + r.stderr[:500])
    return output_path

async def assemble_final_video(vehicle, heygen_video_url, output_dir, job_id):
    os.makedirs(output_dir, exist_ok=True)
    heygen_path    = os.path.join(output_dir, job_id + '_heygen.mp4')
    bg_path        = os.path.join(output_dir, job_id + '_bg.mp4')
    composite_path = os.path.join(output_dir, job_id + '_composite.mp4')
    final_path     = os.path.join(output_dir, job_id + '_final.mp4')
    if not download_file(heygen_video_url, heygen_path):
        raise ValueError('Failed to download HeyGen video')
    duration = get_video_duration(heygen_path)
    photos = vehicle.get('photos', [])
    if not photos:
        raise ValueError('No vehicle photos available')
    n_ext = len(vehicle.get('exterior_features', []))
    n_int = len(vehicle.get('interior_features', []))
    total = max(n_ext + n_int, 1)
    split = max(int(len(photos) * n_ext / total), 2)
    ordered = photos[:split] + photos[split:]
    create_pov_slideshow(ordered, bg_path, duration)
    composite_pov_video(heygen_path, bg_path, composite_path)
    add_text_overlays(composite_path, final_path, vehicle.get('name', ''), vehicle.get('price', ''), vehicle.get('dealer_name', ''))
    return final_path
