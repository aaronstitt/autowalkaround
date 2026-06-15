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

def run_ffmpeg(cmd, label='ffmpeg', timeout=300):
    print('Running {}: {}'.format(label, ' '.join(cmd[:6]) + '...'))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError('{} failed rc={}: {}'.format(label, r.returncode, r.stderr[-500:]))
    return r

def has_audio_stream(path):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        streams = json.loads(r.stdout).get('streams', [])
        return any(s.get('codec_type') == 'audio' for s in streams)
    except Exception:
        return False

def prepare_bg_photo(photo_path, duration, output_path, w=720, h=1280):
    """Scale a photo to fill the full 9:16 frame as a looping background video."""
    # Subtle Ken Burns zoom: 1.0x to 1.06x
    zoom_expr = 'min(1.06,zoom+0.0005)'
    vf = (
        "scale={}:{}:force_original_aspect_ratio=increase,"
        "crop={}:{},setsar=1,"
        "zoompan=z='{}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={}:fps=24:s={}x{}"
    ).format(w*2, h*2, w*2, h*2, zoom_expr, int(duration*24), w, h)
    cmd = ['ffmpeg', '-y', '-loop', '1', '-i', photo_path,
           '-vf', vf,
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
           '-pix_fmt', 'yuv420p',
           '-t', str(duration), '-r', '24',
           '-threads', '1', '-an',
           output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        # Fallback: static
        cmd2 = ['ffmpeg', '-y', '-loop', '1', '-i', photo_path,
                '-vf', 'scale={}:{}:force_original_aspect_ratio=increase,crop={}:{},setsar=1'.format(w,h,w,h),
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
                '-pix_fmt', 'yuv420p',
                '-t', str(duration), '-r', '24',
                '-threads', '1', '-an',
                output_path]
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)
        if r2.returncode != 0:
            raise RuntimeError('bg_photo failed: ' + r2.stderr[-300:])
    return output_path

def extract_webm_segment(webm_path, start, duration, output_path):
    """Extract a transparent segment from a WebM file."""
    cmd = ['ffmpeg', '-y', '-ss', str(start), '-i', webm_path, '-t', str(duration),
           '-c:v', 'libvpx-vp9', '-b:v', '1200k',
           '-pix_fmt', 'yuva420p',
           '-auto-alt-ref', '0',
           '-r', '24', '-an',
           '-threads', '1',
           output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError('extract_webm failed: ' + r.stderr[-300:])
    return output_path

def composite_aaron_on_bg(bg_video, aaron_webm, aaron_start, duration,
                          audio_src, audio_start, output_path, w=720, h=1280):
    """
    Composite transparent Aaron WebM over a background video.
    Aaron is positioned in the bottom-left, scaled to ~45% of frame height,
    so the car is visible above and beside him - true walkaround look.
    Audio comes from aaron_webm (already has audio) sliced at aaron_start.
    """
    # Aaron height ~45% of frame = ~576px, maintain aspect
    aaron_h = int(h * 0.45)   # ~576
    # Aaron is positioned bottom-left: x=20, y=h-aaron_h-20
    aaron_x = 20
    aaron_y = h - aaron_h - 20

    # Extract just the WebM segment needed
    seg_webm = output_path + '_seg.webm'
    extract_webm_segment(aaron_webm, aaron_start, duration, seg_webm)

    # Extract audio segment from the full HeyGen MP4 (if available) or WebM
    # We overlay audio_src from audio_start
    # Composite: bg_video + aaron_webm (transparent) + audio
    filter_complex = (
        "[0:v]setsar=1[bg];",
        "[1:v]scale=-1:{}[aaron_scaled];",
        "[bg][aaron_scaled]overlay={}:{}:shortest=1[out]"
    )
    filter_str = ''.join(filter_complex).format(aaron_h, aaron_x, aaron_y)

    cmd = ['ffmpeg', '-y',
           '-i', bg_video,
           '-i', seg_webm,
           '-ss', str(audio_start), '-t', str(duration), '-i', audio_src,
           '-filter_complex', filter_str,
           '-map', '[out]',
           '-map', '2:a',
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
           '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '128k',
           '-r', '24', '-shortest',
           '-threads', '1',
           output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError('composite failed: ' + r.stderr[-400:])
    # Cleanup segment
    try: os.remove(seg_webm)
    except Exception: pass
    return output_path

def trim_video_segment(src, start, duration, output_path, w=720, h=1280):
    """Trim a video to a segment and scale to target resolution."""
    cmd = ['ffmpeg', '-y', '-ss', str(start), '-i', src, '-t', str(duration),
           '-vf', 'scale={}:{}:force_original_aspect_ratio=increase,crop={}:{},setsar=1'.format(w,h,w,h),
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
           '-pix_fmt', 'yuv420p', '-r', '24',
           '-c:a', 'aac', '-b:a', '128k',
           '-threads', '1',
           output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError('trim_video failed: ' + r.stderr[-300:])
    return output_path

def add_silent_audio(video_path, output_path):
    cmd = ['ffmpeg', '-y', '-i', video_path,
           '-f', 'lavfi', '-i', 'aevalsrc=0:c=mono:s=44100',
           '-c:v', 'copy', '-c:a', 'aac', '-b:a', '64k', '-shortest',
           output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError('add_silent_audio failed: ' + r.stderr[-200:])
    return output_path

def concat_clips(clip_paths, output_path):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        listf = f.name
        for p in clip_paths:
            f.write("file '{}'\n".format(p))
    try:
        cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', listf,
               '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
               '-pix_fmt', 'yuv420p',
               '-c:a', 'aac', '-b:a', '128k',
               '-r', '24', '-threads', '2',
               output_path]
        run_ffmpeg(cmd, 'concat_clips', timeout=600)
    finally:
        try: os.unlink(listf)
        except Exception: pass
    return output_path

def add_text_to_clip(video_path, line1, line2, output_path, position='top'):
    """Add two lines of text overlay to a video clip."""
    safe1 = (line1 or '')[:50].replace("'","").replace(":",' -')
    safe2 = (line2 or '')[:30].replace("'","").replace(":",' -')
    if position == 'top':
        y1, y2 = 55, 100
    else:
        y1, y2 = 'h-90', 'h-50'
    vf = ("drawtext=text='{}':fontcolor=white:fontsize=26:x=(w-text_w)/2:y={}:"
          "box=1:boxcolor=black@0.65:boxborderw=7,"
          "drawtext=text='{}':fontcolor=#FFD700:fontsize=30:x=(w-text_w)/2:y={}:"
          "box=1:boxcolor=black@0.65:boxborderw=7").format(safe1, y1, safe2, y2)
    cmd = ['ffmpeg', '-y', '-i', video_path,
           '-vf', vf,
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '24',
           '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-threads', '1',
           output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return video_path  # return original if text overlay fails
    return output_path

def convert_heygen_to_webm(mp4_path, webm_path):
    """Convert a HeyGen MP4 to transparent WebM using chroma key or direct export."""
    # Try direct VP9 encode preserving any alpha (some HeyGen outputs have alpha)
    cmd = ['ffmpeg', '-y', '-i', mp4_path,
           '-c:v', 'libvpx-vp9', '-b:v', '1500k',
           '-pix_fmt', 'yuva420p',
           '-auto-alt-ref', '0',
           '-r', '24',
           '-threads', '1',
           '-an',
           webm_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode == 0:
        return webm_path
    # Fallback: chroma key the lot background (greenish/grey tones behind Aaron)
    # Use a loose chroma key on grey sky/lot area - not perfect but workable
    # Actually: we'll use the MP4 directly with a split-screen approach if WebM fails
    return None

def build_walkaround_video(heygen_path, photo_paths, vehicle_video_path,
                           vehicle_name, price, dealer_name, output_path):
    """
    Build a TRUE walkaround video where Aaron appears IN FRAME with the vehicle.

    Architecture:
    - HeyGen WebM (transparent Aaron) composited ONTO vehicle photos as background
    - Aaron scaled to ~45% frame height, positioned bottom-left
    - Vehicle photos fill the FULL FRAME behind him
    - Photo changes as Aaron 'walks' to each part of the car
    - Intro/outro: Aaron full-screen on lot background
    - Walkaround sections: Aaron composited over exterior photos, then interior photos
    """
    total_duration = get_video_duration(heygen_path)
    print('HeyGen total duration: {}s'.format(round(total_duration, 1)))
    print('Photos available: {}'.format(len(photo_paths)))
    print('Vehicle video: {}'.format(vehicle_video_path or 'none'))

    with tempfile.TemporaryDirectory() as tmpdir:
        # ── Convert MP4 to transparent WebM for compositing ───────────────────
        webm_path = os.path.join(tmpdir, 'aaron_transparent.webm')
        webm_ok = False
        # Check if the input is already WebM
        if heygen_path.endswith('.webm'):
            webm_path = heygen_path
            webm_ok = True
        else:
            print('Converting HeyGen MP4 to transparent WebM...')
            result = convert_heygen_to_webm(heygen_path, webm_path)
            webm_ok = result is not None and os.path.exists(webm_path) and os.path.getsize(webm_path) > 100000
            if not webm_ok:
                print('WebM conversion failed - falling back to split-screen mode')

        # ── Split photos into exterior and interior ────────────────────────────
        n = len(photo_paths)
        split_idx = max(1, int(n * 0.65))
        ext_photos = photo_paths[:split_idx]
        int_photos = photo_paths[split_idx:]
        if not int_photos:
            int_photos = photo_paths[-2:]

        # ── Timing: intro 8s, outro 8s, middle = walkaround ───────────────────
        intro_dur = min(8.0, total_duration * 0.13)
        outro_dur = min(8.0, total_duration * 0.13)
        middle_dur = total_duration - intro_dur - outro_dur

        vvid_dur = 0.0
        if vehicle_video_path and os.path.exists(vehicle_video_path):
            vvid_dur = min(8.0, get_video_duration(vehicle_video_path))

        n_ext = min(len(ext_photos), 8)
        n_int = min(len(int_photos), 5)
        n_ext = max(n_ext, 1)
        n_int = max(n_int, 1)

        photos_time = middle_dur - vvid_dur
        per_ext = max(3.0, (photos_time * 0.6) / n_ext)
        per_int = max(3.0, (photos_time * 0.4) / n_int)
        used = intro_dur + n_ext * per_ext + vvid_dur + n_int * per_int + outro_dur
        if used > total_duration * 1.02:
            available = total_duration - intro_dur - outro_dur - vvid_dur
            per_ext = max(3.0, (available * 0.6) / n_ext)
            per_int = max(3.0, (available * 0.4) / n_int)

        print('Intro={}s, ExtPhotos={}x{}s, VehicleVid={}s, IntPhotos={}x{}s, Outro={}s'.format(
            round(intro_dur,1), n_ext, round(per_ext,1), round(vvid_dur,1),
            n_int, round(per_int,1), round(outro_dur,1)))
        print('WebM compositing: {}'.format('YES' if webm_ok else 'NO - split screen fallback'))

        clip_paths = []
        audio_offset = 0.0
        safe_name = (vehicle_name or '')[:45].replace("'","").replace(":",' -')
        safe_price = str(price or '').replace('$','').replace(',','')
        safe_dealer = (dealer_name or 'Immaculate Used Cars')[:40].replace("'","")

        # ── 1. INTRO: Aaron full-screen on lot background ─────────────────────
        intro_path = os.path.join(tmpdir, 'intro.mp4')
        trim_video_segment(heygen_path, 0, intro_dur, intro_path)
        intro_txt = os.path.join(tmpdir, 'intro_txt.mp4')
        intro_final = add_text_to_clip(intro_path, safe_name,
                                       '$'+safe_price if safe_price else '',
                                       intro_txt, position='top')
        clip_paths.append(intro_final)
        audio_offset += intro_dur

        if webm_ok:
            # ── 2a. WALKAROUND: Aaron composited over vehicle photos ───────────
            # EXTERIOR: Aaron over exterior car photos (car visible, Aaron in front)
            for i, ph in enumerate(ext_photos[:n_ext]):
                bg_path = os.path.join(tmpdir, 'ext_bg_{:02d}.mp4'.format(i))
                out_path = os.path.join(tmpdir, 'ext_{:02d}.mp4'.format(i))
                try:
                    prepare_bg_photo(ph, per_ext, bg_path)
                    composite_aaron_on_bg(
                        bg_video=bg_path,
                        aaron_webm=webm_path,
                        aaron_start=audio_offset,
                        duration=per_ext,
                        audio_src=heygen_path,
                        audio_start=audio_offset,
                        output_path=out_path
                    )
                    clip_paths.append(out_path)
                except Exception as e:
                    print('Ext composite {} failed: {}'.format(i, e))
                    # Fallback to audio-over-photo
                    silent = os.path.join(tmpdir, 'ext_sil_{:02d}.mp4'.format(i))
                    try:
                        prepare_bg_photo(ph, per_ext, bg_path)
                        add_silent_audio(bg_path, silent)
                        clip_paths.append(silent)
                    except Exception as e2:
                        print('Ext fallback also failed: {}'.format(e2))
                audio_offset += per_ext

            # VEHICLE VIDEO (if available): Aaron composited over rolling footage
            if vvid_dur > 1.0:
                vvid_path = os.path.join(tmpdir, 'vehicle_vid_bg.mp4')
                vvid_comp = os.path.join(tmpdir, 'vehicle_vid_comp.mp4')
                try:
                    trim_video_segment(vehicle_video_path, 0, vvid_dur, vvid_path)
                    # Add audio to the vehicle video - aaron talking over it
                    cmd_aud = ['ffmpeg', '-y', '-i', vvid_path,
                               '-ss', str(audio_offset), '-t', str(vvid_dur), '-i', heygen_path,
                               '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
                               '-shortest', vvid_comp]
                    subprocess.run(cmd_aud, capture_output=True, text=True, timeout=60)
                    clip_paths.append(vvid_comp)
                except Exception as e:
                    print('Vehicle video composite failed: {}'.format(e))
                audio_offset += vvid_dur

            # INTERIOR: Aaron composited over interior car photos
            for i, ph in enumerate(int_photos[:n_int]):
                bg_path = os.path.join(tmpdir, 'int_bg_{:02d}.mp4'.format(i))
                out_path = os.path.join(tmpdir, 'int_{:02d}.mp4'.format(i))
                try:
                    prepare_bg_photo(ph, per_int, bg_path)
                    composite_aaron_on_bg(
                        bg_video=bg_path,
                        aaron_webm=webm_path,
                        aaron_start=audio_offset,
                        duration=per_int,
                        audio_src=heygen_path,
                        audio_start=audio_offset,
                        output_path=out_path
                    )
                    clip_paths.append(out_path)
                except Exception as e:
                    print('Int composite {} failed: {}'.format(i, e))
                    silent = os.path.join(tmpdir, 'int_sil_{:02d}.mp4'.format(i))
                    try:
                        prepare_bg_photo(ph, per_int, bg_path)
                        add_silent_audio(bg_path, silent)
                        clip_paths.append(silent)
                    except Exception as e2:
                        print('Int fallback also failed: {}'.format(e2))
                audio_offset += per_int

        else:
            # ── 2b. FALLBACK: Split-screen (Aaron left 40%, car right 60%) ────
            print('Using split-screen fallback...')
            for i, ph in enumerate(ext_photos[:n_ext]):
                bg_path = os.path.join(tmpdir, 'ext_bg_{:02d}.mp4'.format(i))
                out_path = os.path.join(tmpdir, 'ext_{:02d}.mp4'.format(i))
                try:
                    prepare_bg_photo(ph, per_ext, bg_path)
                    # Trim Aaron segment
                    aaron_seg = os.path.join(tmpdir, 'ext_aaron_{:02d}.mp4'.format(i))
                    trim_video_segment(heygen_path, audio_offset, per_ext, aaron_seg,
                                       w=int(W*0.4), h=H)
                    # Stack side by side: aaron (40%) | car (60%)
                    side_path = os.path.join(tmpdir, 'ext_side_{:02d}.mp4'.format(i))
                    fc = ('[0:v]scale={}:{}[car];[1:v]scale={}:{}[person];'
                          '[person][car]hstack=inputs=2[out]').format(
                        int(W*0.6), H, int(W*0.4), H)
                    cmd_ss = ['ffmpeg', '-y',
                              '-i', bg_path,
                              '-i', aaron_seg,
                              '-filter_complex', fc,
                              '-map', '[out]',
                              '-map', '1:a',
                              '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
                              '-pix_fmt', 'yuv420p',
                              '-c:a', 'aac', '-b:a', '128k',
                              '-r', '24', '-threads', '1',
                              side_path]
                    subprocess.run(cmd_ss, capture_output=True, text=True, timeout=120)
                    clip_paths.append(side_path if os.path.exists(side_path) else bg_path)
                except Exception as e:
                    print('Split-screen ext {} failed: {}'.format(i, e))
                audio_offset += per_ext

            if vvid_dur > 1.0:
                vvid_path = os.path.join(tmpdir, 'vehicle_vid.mp4')
                try:
                    trim_video_segment(vehicle_video_path, 0, vvid_dur, vvid_path)
                    clip_paths.append(vvid_path)
                except Exception as e:
                    print('Vehicle video fallback failed: {}'.format(e))
                audio_offset += vvid_dur

            for i, ph in enumerate(int_photos[:n_int]):
                bg_path = os.path.join(tmpdir, 'int_bg_{:02d}.mp4'.format(i))
                out_path = os.path.join(tmpdir, 'int_{:02d}.mp4'.format(i))
                try:
                    prepare_bg_photo(ph, per_int, bg_path)
                    aaron_seg = os.path.join(tmpdir, 'int_aaron_{:02d}.mp4'.format(i))
                    trim_video_segment(heygen_path, audio_offset, per_int, aaron_seg,
                                       w=int(W*0.4), h=H)
                    side_path = os.path.join(tmpdir, 'int_side_{:02d}.mp4'.format(i))
                    fc = ('[0:v]scale={}:{}[car];[1:v]scale={}:{}[person];'
                          '[person][car]hstack=inputs=2[out]').format(
                        int(W*0.6), H, int(W*0.4), H)
                    cmd_ss = ['ffmpeg', '-y',
                              '-i', bg_path,
                              '-i', aaron_seg,
                              '-filter_complex', fc,
                              '-map', '[out]',
                              '-map', '1:a',
                              '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
                              '-pix_fmt', 'yuv420p',
                              '-c:a', 'aac', '-b:a', '128k',
                              '-r', '24', '-threads', '1',
                              side_path]
                    subprocess.run(cmd_ss, capture_output=True, text=True, timeout=120)
                    clip_paths.append(side_path if os.path.exists(side_path) else bg_path)
                except Exception as e:
                    print('Split-screen int {} failed: {}'.format(i, e))
                audio_offset += per_int

        # ── 3. OUTRO: Aaron full-screen ───────────────────────────────────────
        outro_start = total_duration - outro_dur
        outro_path = os.path.join(tmpdir, 'outro.mp4')
        try:
            trim_video_segment(heygen_path, outro_start, outro_dur, outro_path)
            outro_txt = os.path.join(tmpdir, 'outro_txt.mp4')
            outro_final = add_text_to_clip(outro_path, safe_dealer, '', outro_txt, position='bottom')
            clip_paths.append(outro_final)
        except Exception as e:
            print('Outro failed: {}'.format(e))
            clip_paths.append(clip_paths[0] if clip_paths else intro_path)

        print('Concatenating {} clips...'.format(len(clip_paths)))
        concat_clips(clip_paths, output_path)
        print('Walkaround video complete: {}'.format(output_path))

    return output_path

async def assemble_final_video(vehicle, heygen_video_url, output_dir, job_id):
    os.makedirs(output_dir, exist_ok=True)
    heygen_ext = '.webm' if 'webm' in heygen_video_url.lower() else '.mp4'
    heygen_path = os.path.join(output_dir, job_id + '_heygen' + heygen_ext)
    final_path = os.path.join(output_dir, job_id + '_final.mp4')

    print('Downloading HeyGen video from: {}'.format(heygen_video_url[:80]))
    if not download_file(heygen_video_url, heygen_path):
        raise RuntimeError('Failed to download HeyGen video')

    # Detect actual format
    probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', heygen_path]
    probe_r = subprocess.run(probe_cmd, capture_output=True, text=True)
    try:
        fmt_name = json.loads(probe_r.stdout).get('format', {}).get('format_name', '')
        if ('webm' in fmt_name or 'matroska' in fmt_name) and not heygen_path.endswith('.webm'):
            new_path = os.path.join(output_dir, job_id + '_heygen.webm')
            os.rename(heygen_path, new_path)
            heygen_path = new_path
        elif ('mp4' in fmt_name or 'mov' in fmt_name) and not heygen_path.endswith('.mp4'):
            new_path = os.path.join(output_dir, job_id + '_heygen.mp4')
            os.rename(heygen_path, new_path)
            heygen_path = new_path
    except Exception:
        pass

    # Download vehicle photos (up to 45, spread across set)
    photos = vehicle.get('photos', [])
    if not photos:
        raise RuntimeError('No vehicle photos available')
    n_photos = min(len(photos), 45)
    indices = [int(i * len(photos) / n_photos) for i in range(n_photos)]
    selected_photos = [photos[idx] for idx in indices]
    photo_paths = []
    for i, url in enumerate(selected_photos):
        dest = os.path.join(output_dir, '{}_photo_{:02d}.jpg'.format(job_id, i))
        if download_file(url, dest):
            photo_paths.append(dest)
        else:
            print('Photo {} download failed, skipping'.format(i))
    if not photo_paths:
        raise RuntimeError('All vehicle photos failed to download')
    print('Downloaded {} vehicle photos'.format(len(photo_paths)))

    # Download vehicle video (if available)
    vehicle_video_path = None
    video_url = vehicle.get('video_url')
    if video_url:
        vv_dest = os.path.join(output_dir, job_id + '_vehicle_vid.mp4')
        if download_file(video_url, vv_dest):
            vehicle_video_path = vv_dest
            print('Downloaded vehicle video')

    vehicle_name = vehicle.get('year_make_model', vehicle.get('name', ''))
    price = str(vehicle.get('price', '')).replace('$', '').replace(',', '')
    dealer_name = vehicle.get('dealer_name', 'Immaculate Used Cars')

    build_walkaround_video(
        heygen_path=heygen_path,
        photo_paths=photo_paths,
        vehicle_video_path=vehicle_video_path,
        vehicle_name=vehicle_name,
        price=price,
        dealer_name=dealer_name,
        output_path=final_path
    )

    for p in photo_paths:
        try: os.remove(p)
        except Exception: pass
    try: os.remove(heygen_path)
    except Exception: pass
    if vehicle_video_path:
        try: os.remove(vehicle_video_path)
        except Exception: pass

    print('Final walkaround video: {}'.format(final_path))
    return final_path
