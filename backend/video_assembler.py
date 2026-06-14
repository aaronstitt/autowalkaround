import os, requests, subprocess, json, shutil, tempfile, math

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
        """Scale photo to exact W x H canvas (fill + crop center). Output JPEG."""
        cmd = [
            'ffmpeg', '-y', '-i', src,
            '-vf', f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}',
            '-q:v', '2', '-frames:v', '1',
            dest
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0 and os.path.exists(dest)

def convert_webm_to_mp4_with_alpha(webm_path, mp4_path):
        """
            Convert HeyGen webm (with alpha) to mp4 for use as overlay.
                We keep the video stream; alpha is handled in overlay step.
                    Also tries to extract if it's already mp4.
                        Returns True if successful.
                            """
        # Check if the file is actually a webm/has alpha
        probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
                     '-show_streams', webm_path]
        probe_r = subprocess.run(probe_cmd, capture_output=True, text=True)
        has_alpha = False
        try:
                    streams = json.loads(probe_r.stdout).get('streams', [])
                    for s in streams:
                                    if s.get('codec_name') in ('vp8', 'vp9', 'av1') or 'alpha' in str(s):
                                                        has_alpha = True
                                                        break
        except Exception:
                    pass

        print(f'Avatar file has_alpha={has_alpha}, path={webm_path}')

    if has_alpha:
                # Convert webm with alpha to a format we can overlay (keep as webm or convert)
                # We'll extract just the video stream for compositing
                cmd = [
                                'ffmpeg', '-y', '-i', webm_path,
                                '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
                                '-auto-alt-ref', '0',
                                '-b:v', '1200k',
                                mp4_path.replace('.mp4', '_alpha.webm')
                ]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if r.returncode == 0:
                                return mp4_path.replace('.mp4', '_alpha.webm'), True

            # Fallback: just copy as-is
            shutil.copy2(webm_path, mp4_path)
    return mp4_path, False

def build_composite_walkaround(photo_paths, heygen_path, output_path,
                                                               vehicle_name='', price='', dealer_name=''):
                                                                       """
                                                                           THE REAL WALKAROUND VIDEO:

                                                                                   For each vehicle photo (which fills the 9:16 frame), composite Aaron 
                                                                                       DIRECTLY onto it as if he's physically standing there next to the car.
                                                                                           Aaron occupies the lower 55% of the frame at full width, his background 
                                                                                               removed by HeyGen. Result: Aaron appears to be standing IN the car lot 
                                                                                                   next to the actual vehicle - exactly like a real iPhone walkaround video.
                                                                                                       
                                                                                                           The vehicle changes every few seconds (like walking to a new angle),
                                                                                                               and Aaron talks over it continuously.
                                                                                                                   
                                                                                                                       Pipeline:
                                                                                                                           1. Get HeyGen video duration
                                                                                                                               2. Pre-scale all photos to W x H
                                                                                                                                   3. Build photo slideshow (one ffmpeg concat pass, no scale filter = low memory)
                                                                                                                                       4. Composite: [slideshow bg] + [Aaron with alpha removed] -> final
                                                                                                                                           
                                                                                                                                               Aaron is positioned at bottom-center, full frame width, lower 55%.
                                                                                                                                                   This creates the illusion he's standing IN the scene.
                                                                                                                                                       """
                                                                       n_photos = len(photo_paths)
                                                                       if n_photos == 0:
                                                                                   raise RuntimeError('No photos provided')

                                                                       duration = get_video_duration(heygen_path)
                                                                       print(f'HeyGen avatar duration: {duration:.1f}s, photos: {n_photos}')

    # Check if HeyGen gave us a webm (transparent) or mp4
    ext = os.path.splitext(heygen_path)[1].lower()
    is_webm = ext == '.webm'

    probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', heygen_path]
    probe_r = subprocess.run(probe_cmd, capture_output=True, text=True)
    has_alpha = False
    try:
                streams = json.loads(probe_r.stdout).get('streams', [])
                for s in streams:
                                codec = s.get('codec_name', '')
                                pix_fmt = s.get('pix_fmt', '')
                                if codec in ('vp8', 'vp9', 'av1') or 'yuva' in pix_fmt:
                                                    has_alpha = True
                                                    break
    except Exception:
                pass
            print(f'HeyGen file: ext={ext}, has_alpha={has_alpha}')

    with tempfile.TemporaryDirectory() as tmpdir:
                # Step 1: Pre-scale each photo individually (memory safe)
                scaled_paths = []
                for i, p in enumerate(photo_paths):
                                dest = os.path.join(tmpdir, f'photo_{i:03d}.jpg')
                                ok = prescale_photo(p, dest)
                                if ok:
                                                    scaled_paths.append(dest)
else:
                print(f'Warning: failed to scale photo {i}: {p}')

        if not scaled_paths:
                        raise RuntimeError('All photos failed to scale')

        # Step 2: Build photo slideshow (no scale filter - images already correct size)
        per_photo = max(duration / len(scaled_paths), 2.0)
        listf = os.path.join(tmpdir, 'list.txt')
        with open(listf, 'w') as f:
                        for p in scaled_paths:
                                            f.write(f"file '{p}'\nduration {round(per_photo, 2)}\n")
                                        f.write(f"file '{scaled_paths[-1]}'\n")  # avoid concat timing issue

        slideshow_path = os.path.join(tmpdir, 'slideshow.mp4')
        slide_cmd = [
                        'ffmpeg', '-y',
                        '-f', 'concat', '-safe', '0', '-i', listf,
                        '-vf', 'fps=15,setsar=1',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '30',
                        '-pix_fmt', 'yuv420p',
                        '-t', str(int(duration) + 2),
                        '-threads', '1',
                        '-b:v', '600k', '-maxrate', '700k', '-bufsize', '1000k',
                        slideshow_path
        ]
        print(f'Building slideshow: {len(scaled_paths)} photos at {per_photo:.1f}s each')
        r = subprocess.run(slide_cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
                        raise RuntimeError(f'Slideshow failed rc={r.returncode}: {r.stderr[-400:]}')

        # Step 3: Composite Aaron onto the vehicle photos
        # Aaron is positioned at bottom of frame, full width, lower portion
        # This makes him look like he's standing IN the scene

        def safe(s):
                        return str(s or '').replace("'", '').replace(':', '-').replace('"', '')[:45]

        vn = safe(vehicle_name)
        vp = safe(price)
        vd = safe(dealer_name)

        # Aaron height: 60% of frame height, at bottom
        # Width: 60% of frame width, centered
        aaron_h = int(H * 0.60)
        aaron_w = int(W * 0.60)
        # Position: centered horizontally, at very bottom
        aaron_x = int((W - aaron_w) / 2)
        aaron_y = H - aaron_h  # pinned to bottom

        text_filters = []
        if vn:
                        text_filters.append(f"drawtext=text='{vn}':fontcolor=white:fontsize=24:x=(w-text_w)/2:y=60:box=1:boxcolor=black@0.65:boxborderw=6")
        if vp:
                        text_filters.append(f"drawtext=text='${vp}':fontcolor=#FFD700:fontsize=30:x=(w-text_w)/2:y=98:box=1:boxcolor=black@0.65:boxborderw=5")
        if vd:
                        text_filters.append(f"drawtext=text='{vd}':fontcolor=white:fontsize=18:x=(w-text_w)/2:y=h-50:box=1:boxcolor=black@0.55:boxborderw=4")

        if has_alpha:
                        # WebM with alpha: use overlay with alpha channel
                        # [0:v] = slideshow bg, [1:v] = Aaron transparent webm
                        text_chain = (','.join(text_filters) + ',') if text_filters else ''
            filter_complex = (
                                f'[0:v]{text_chain}setsar=1[bg];'
                                f'[1:v]scale={aaron_w}:{aaron_h}:force_original_aspect_ratio=decrease[av];'
                                f'[bg][av]overlay={aaron_x}:{aaron_y}:format=auto:shortest=1[out]'
            )
else:
            # MP4 without alpha: use chromakey on green background HeyGen may have used,
                # or just overlay as-is (may have white/grey bg from HeyGen)
            # Try colorkey to remove common HeyGen studio backgrounds
            text_chain = (','.join(text_filters) + ',') if text_filters else ''
            filter_complex = (
                                f'[0:v]{text_chain}setsar=1[bg];'
                                f'[1:v]scale={aaron_w}:{aaron_h}:force_original_aspect_ratio=decrease,'
                                f'colorkey=0xFFFFFF:0.3:0.2[av];'
                                f'[bg][av]overlay={aaron_x}:{aaron_y}:shortest=1[out]'
            )

        compose_cmd = [
                        'ffmpeg', '-y',
                        '-i', slideshow_path,
                        '-i', heygen_path,
                        '-filter_complex', filter_complex,
                        '-map', '[out]',
                        '-map', '1:a',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
                        '-b:v', '1000k', '-maxrate', '1200k', '-bufsize', '1800k',
                        '-threads', '2', '-shortest',
                        output_path
        ]
        print(f'Compositing Aaron onto vehicle photos (alpha={has_alpha})...')
        r = subprocess.run(compose_cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
                        # Fallback: if alpha composite failed, try simple overlay (no colorkey)
                        print(f'Composite failed rc={r.returncode}, trying simple overlay...')
            text_chain = (','.join(text_filters) + ',') if text_filters else ''
            filter_simple = (
                                f'[0:v]{text_chain}setsar=1[bg];'
                                f'[1:v]scale={aaron_w}:{aaron_h}:force_original_aspect_ratio=decrease[av];'
                                f'[bg][av]overlay={aaron_x}:{aaron_y}:shortest=1[out]'
            )
            compose_cmd2 = [
                                'ffmpeg', '-y',
                                '-i', slideshow_path,
                                '-i', heygen_path,
                                '-filter_complex', filter_simple,
                                '-map', '[out]', '-map', '1:a',
                                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
                                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
                                '-b:v', '1000k', '-maxrate', '1200k', '-bufsize', '1800k',
                                '-threads', '2', '-shortest',
                                output_path
            ]
            r2 = subprocess.run(compose_cmd2, capture_output=True, text=True, timeout=600)
            if r2.returncode != 0:
                                raise RuntimeError(f'Composite fallback failed rc={r2.returncode}: {r2.stderr[-400:]}')

    return output_path

async def assemble_final_video(vehicle, heygen_video_url, output_dir, job_id):
        os.makedirs(output_dir, exist_ok=True)

    # Determine file extension from URL or content-type
    heygen_ext = '.webm' if 'webm' in heygen_video_url.lower() else '.mp4'
    heygen_path = os.path.join(output_dir, job_id + '_heygen' + heygen_ext)
    final_path = os.path.join(output_dir, job_id + '_final.mp4')

    # Download HeyGen avatar video
    print(f'Downloading HeyGen avatar from: {heygen_video_url[:80]}')
    if not download_file(heygen_video_url, heygen_path):
                raise RuntimeError('Failed to download HeyGen video')

    # Detect actual file type (URL extension may be wrong)
    probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', heygen_path]
    probe_r = subprocess.run(probe_cmd, capture_output=True, text=True)
    try:
                fmt_name = json.loads(probe_r.stdout).get('format', {}).get('format_name', '')
        if 'webm' in fmt_name or 'matroska' in fmt_name:
                        new_path = heygen_path.replace('.mp4', '.webm')
            if heygen_path != new_path:
                                os.rename(heygen_path, new_path)
                                heygen_path = new_path
                            print(f'Detected webm format')
elif 'mp4' in fmt_name or 'mov' in fmt_name:
            new_path = heygen_path.replace('.webm', '.mp4')
            if heygen_path != new_path:
                                os.rename(heygen_path, new_path)
                                heygen_path = new_path
                            print(f'Detected mp4 format')
except Exception:
        pass

    # Download vehicle photos
    photos = vehicle.get('photos', [])
    if not photos:
                raise RuntimeError('No vehicle photos available')

    # Use up to 12 photos spread across all available
    n_photos = min(len(photos), 12)
    indices = [int(i * len(photos) / n_photos) for i in range(n_photos)]
    selected_photos = [photos[i] for i in indices]

    photo_paths = []
    for i, url in enumerate(selected_photos):
                dest = os.path.join(output_dir, f'{job_id}_photo_{i:02d}.jpg')
        if download_file(url, dest):
                        photo_paths.append(dest)
else:
            print(f'Photo {i} download failed, skipping')

    if not photo_paths:
                raise RuntimeError('All vehicle photos failed to download')

    print(f'Downloaded {len(photo_paths)} vehicle photos for walkaround')

    # Build the composite walkaround video
    vehicle_name = vehicle.get('year_make_model', vehicle.get('name', ''))
    price = str(vehicle.get('price', '')).replace('$', '').replace(',', '')
    dealer_name = vehicle.get('dealer_name', 'Immaculate Used Cars')

    build_composite_walkaround(
                photo_paths, heygen_path, final_path,
                vehicle_name=vehicle_name,
                price=price,
                dealer_name=dealer_name
    )

    # Clean up photo files (keep final)
    for p in photo_paths:
                try:
                                os.remove(p)
except Exception:
            pass
    try:
                os.remove(heygen_path)
except Exception:
        pass

    print(f'Final walkaround video: {final_path}')
    return final_path
