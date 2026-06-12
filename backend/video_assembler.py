import os, requests, tempfile, subprocess
from typing import List

def download_file(url: str, dest: str) -> bool:
    try:
        resp = requests.get(url, stream=True, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        resp.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in resp.iter_content(8192): f.write(chunk)
        return True
    except Exception as e:
        print(f'Download failed {url}: {e}')
        return False

def create_photo_slideshow(photo_urls: List[str], output_path: str, duration: float = 3.5) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        downloaded = []
        for i, url in enumerate(photo_urls[:18]):
            ext = url.split('.')[-1].split('?')[0]
            dest = os.path.join(tmpdir, f'photo_{i:03d}.{ext}')
            if download_file(url, dest): downloaded.append(dest)
        if not downloaded: raise ValueError('No photos downloaded')
        list_file = os.path.join(tmpdir, 'photos.txt')
        with open(list_file, 'w') as f:
            for p in downloaded:
                f.write(f"file '{p}'\nduration {duration}\n")
            f.write(f"file '{downloaded[-1]}'\n")
        cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_file,
               '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1',
               '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p', '-r', '30', output_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0: raise RuntimeError(f'Slideshow failed: {r.stderr[:500]}')
        return output_path

def composite_avatar_over_bg(heygen_path: str, bg_path: str, output_path: str) -> str:
    overlay_w = 486  # ~45% of 1080
    cmd = ['ffmpeg', '-y', '-i', bg_path, '-i', heygen_path,
           '-filter_complex',
           f'[1:v]scale={overlay_w}:-1[ov];[0:v][ov]overlay=(main_w-overlay_w)/2:main_h-overlay_h-40:shortest=1',
           '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-map', '1:a', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(f'Composite failed: {r.stderr[:500]}')
    return output_path

def add_text_overlays(video_path: str, output_path: str, vehicle_name: str, price: str, dealer_name: str) -> str:
    safe = lambda s: s.replace("'", '').replace(':', '-')[:50]
    vname = safe(vehicle_name)
    vprice = f'${safe(price)}' if price else ''
    vdealer = safe(dealer_name)
    drawtext = (
        f"drawtext=text='{vname}':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=h-170:box=1:boxcolor=black@0.65:boxborderw=10,"
        f"drawtext=text='{vprice}':fontcolor=#FFD700:fontsize=44:x=(w-text_w)/2:y=h-115:box=1:boxcolor=black@0.65:boxborderw=8,"
        f"drawtext=text='{vdealer}':fontcolor=white:fontsize=24:x=(w-text_w)/2:y=h-60:box=1:boxcolor=black@0.65:boxborderw=6"
    )
    cmd = ['ffmpeg', '-y', '-i', video_path, '-vf', drawtext,
           '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', '-pix_fmt', 'yuv420p', '-c:a', 'copy', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(f'Text overlay failed: {r.stderr[:500]}')
    return output_path

async def assemble_final_video(vehicle: dict, heygen_video_url: str, output_dir: str, job_id: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    heygen_path = os.path.join(output_dir, f'{job_id}_heygen.mp4')
    bg_path = os.path.join(output_dir, f'{job_id}_bg.mp4')
    composite_path = os.path.join(output_dir, f'{job_id}_composite.mp4')
    final_path = os.path.join(output_dir, f'{job_id}_final.mp4')
    download_file(heygen_video_url, heygen_path)
    photos = vehicle.get('photos', [])
    if not photos: raise ValueError('No vehicle photos available')
    create_photo_slideshow(photos, bg_path)
    composite_avatar_over_bg(heygen_path, bg_path, composite_path)
    add_text_overlays(composite_path, final_path, vehicle.get('name',''), vehicle.get('price',''), vehicle.get('dealer_name',''))
    return final_path