import os, requests, subprocess, json, shutil, tempfile, math

HEADERS = {'User-Agent': 'Mozilla/5.0'}
W = 720
H = 1280

# GREEN_SCREEN_MODE: set env var GREEN_SCREEN_MODE=true in Railway once
# Aaron re-records HeyGen avatar in front of green screen.
# When True: Aaron chroma-keyed and composited ONTO vehicle photos (true walkaround)
# When False: vstack split - car top 60%, Aaron bottom 40%
GREEN_SCREEN_MODE = os.environ.get('GREEN_SCREEN_MODE', 'false').lower() == 'true'


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
    print('Running {}: {}...'.format(label, ' '.join(cmd[:6])))
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
    """Scale photo to full 9:16 frame with subtle Ken Burns zoom."""
    zoom_expr = 'min(1.06,zoom+0.0005)'
    vf = (
        "scale={}:{}:force_original_aspect_ratio=increase,"
        "crop={}:{},setsar=1,"
        "zoompan=z='{}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={}:fps=24:s={}x{}"
    ).format(w*2, h*2, w*2, h*2, zoom_expr, int(duration*24), w, h)
    cmd = ['ffmpeg', '-y', '-loop', '1', '-i', photo_path,
           '-vf', vf, '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
           '-pix_fmt', 'yuv420p', '-t', str(duration), '-r', '24',
           '-threads', '1', '-an', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        cmd2 = ['ffmpeg', '-y', '-loop', '1', '-i', photo_path,
                '-vf', 'scale={}:{}:force_original_aspect_ratio=increase,crop={}:{},setsar=1'.format(w, h, w, h),
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
                '-pix_fmt', 'yuv420p', '-t', str(duration), '-r', '24',
                '-threads', '1', '-an', output_path]
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)
        if r2.returncode != 0:
            raise RuntimeError('bg_photo failed: ' + r2.stderr[-300:])
    return output_path


def composite_greenscreen(bg_video, aaron_mp4, aaron_start, duration,
                           audio_start, output_path, w=720, h=1280):
    """
    TRUE WALKAROUND: Chroma-key Aaron's green screen background, overlay him
    onto the vehicle photo. Aaron appears physically IN FRONT OF the car.

    Aaron is placed lower-center at 55% frame height so the car is visible
    above and around him - exactly like a real dealership walkaround video.

    Tune via Railway env vars:
      GREEN_COLOR (default 0x00b140) - your green screen hex color
      GREEN_SIMILARITY (default 0.35) - how aggressively to key (0.1-0.5)
      GREEN_BLEND (default 0.1) - edge softness
    """
    green_color = os.environ.get('GREEN_COLOR', '0x00b140')
    similarity = float(os.environ.get('GREEN_SIMILARITY', '0.35'))
    blend = float(os.environ.get('GREEN_BLEND', '0.1'))

    # Aaron: 55% of frame height, centered, 20px from bottom
    aaron_h = int(h * 0.55)           # 704px tall
    aaron_w = int(aaron_h * 9 / 16)   # 396px wide (9:16)
    aaron_x = (w - aaron_w) // 2      # center x
    aaron_y = h - aaron_h - 20        # near bottom

    filter_str = (
        '[1:v]scale={aw}:{ah}:force_original_aspect_ratio=decrease,'
        'pad={aw}:{ah}:(ow-iw)/2:(oh-ih)/2,'
        'colorkey={color}:{sim}:{blend},'
        'format=yuva420p[aaron];'
        '[0:v][aaron]overlay={ax}:{ay}:format=auto[out]'
    ).format(aw=aaron_w, ah=aaron_h, color=green_color,
             sim=similarity, blend=blend, ax=aaron_x, ay=aaron_y)

    cmd = ['ffmpeg', '-y',
           '-i', bg_video,
           '-ss', str(aaron_start), '-t', str(duration), '-i', aaron_mp4,
           '-ss', str(audio_start), '-t', str(duration), '-i', aaron_mp4,
           '-filter_complex', filter_str,
           '-map', '[out]', '-map', '2:a',
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
           '-r', '24', '-shortest', '-threads', '1', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError('greenscreen composite failed: ' + r.stderr[-400:])
    return output_path


def composite_vstack(bg_video, aaron_mp4, aaron_start, duration,
                     audio_start, output_path, w=720, h=1280):
    """VSTACK fallback: car top 60%, Aaron bottom 40%."""
    car_h = int(h * 0.60)   # 768px
    aaron_h = h - car_h     # 512px

    filter_str = (
        '[0:v]scale={w}:{car_h}:force_original_aspect_ratio=increase,'
        'crop={w}:{car_h},setsar=1[car];'
        '[1:v]scale={w}:{aaron_h}:force_original_aspect_ratio=increase,'
        'crop={w}:{aaron_h},setsar=1[aaron];'
        '[car][aaron]vstack=inputs=2[out]'
    ).format(w=w, car_h=car_h, aaron_h=aaron_h)

    cmd = ['ffmpeg', '-y',
           '-i', bg_video,
           '-ss', str(aaron_start), '-t', str(duration), '-i', aaron_mp4,
           '-ss', str(audio_start), '-t', str(duration), '-i', aaron_mp4,
           '-filter_complex', filter_str,
           '-map', '[out]', '-map', '2:a',
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
           '-r', '24', '-shortest', '-threads', '1', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError('vstack composite failed: ' + r.stderr[-400:])
    return output_path


def composite_aaron_on_bg(bg_video, aaron_webm, aaron_start, duration,
                           audio_src, audio_start, output_path, w=720, h=1280):
    """Route to green screen overlay or vstack based on GREEN_SCREEN_MODE."""
    if GREEN_SCREEN_MODE:
        print('Compositing: GREEN SCREEN mode')
        return composite_greenscreen(bg_video, aaron_webm, aaron_start, duration,
                                     audio_start, output_path, w, h)
    else:
        print('Compositing: VSTACK mode (awaiting green screen avatar)')
        return composite_vstack(bg_video, aaron_webm, aaron_start, duration,
                                audio_start, output_path, w, h)


def trim_video_segment(src, start, duration, output_path, w=720, h=1280):
    cmd = ['ffmpeg', '-y', '-ss', str(start), '-i', src, '-t', str(duration),
           '-vf', 'scale={}:{}:force_original_aspect_ratio=increase,crop={}:{},setsar=1'.format(w, h, w, h),
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
           '-pix_fmt', 'yuv420p', '-r', '24',
           '-c:a', 'aac', '-b:a', '128k', '-threads', '1', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError('trim_video failed: ' + r.stderr[-300:])
    return output_path


def add_silent_audio(video_path, output_path):
    cmd = ['ffmpeg', '-y', '-i', video_path,
           '-f', 'lavfi', '-i', 'aevalsrc=0:c=mono:s=44100',
           '-c:v', 'copy', '-c:a', 'aac', '-b:a', '64k', '-shortest', output_path]
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
               '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
               '-r', '24', '-threads', '2', output_path]
        run_ffmpeg(cmd, 'concat_clips', timeout=600)
    finally:
        try:
            os.unlink(listf)
        except Exception:
            pass
    return output_path


def add_text_to_clip(video_path, line1, line2, output_path, position='top'):
    safe1 = (line1 or '')[:50].replace("'", "").replace(":", ' -')
    safe2 = (line2 or '')[:30].replace("'", "").replace(":", ' -')
    if position == 'top':
        y1, y2 = 55, 100
    else:
        y1, y2 = 'h-90', 'h-50'
    vf = ("drawtext=text='{}':fontcolor=white:fontsize=26:x=(w-text_w)/2:y={}:"
          "box=1:boxcolor=black@0.65:boxborderw=7,"
          "drawtext=text='{}':fontcolor=#FFD700:fontsize=30:x=(w-text_w)/2:y={}:"
          "box=1:boxcolor=black@0.65:boxborderw=7").format(safe1, y1, safe2, y2)
    cmd = ['ffmpeg', '-y', '-i', video_path, '-vf', vf,
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '24',
           '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-threads', '1', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return video_path
    return output_path


def build_walkaround_video(heygen_path, photo_paths, vehicle_video_path,
                            vehicle_name, price, dealer_name, output_path):
    total_duration = get_video_duration(heygen_path)
    mode = 'GREEN SCREEN' if GREEN_SCREEN_MODE else 'VSTACK'
    print('HeyGen: {}s | Mode: {} | Photos: {}'.format(
        round(total_duration, 1), mode, len(photo_paths)))

    with tempfile.TemporaryDirectory() as tmpdir:
        # Split photos exterior / interior (65% / 35%)
        n = len(photo_paths)
        split_idx = max(1, int(n * 0.65))
        ext_photos = photo_paths[:split_idx]
        int_photos = photo_paths[split_idx:] or photo_paths[-2:]

        intro_dur = min(8.0, total_duration * 0.13)
        outro_dur = min(8.0, total_duration * 0.13)
        middle_dur = total_duration - intro_dur - outro_dur

        vvid_dur = 0.0
        if vehicle_video_path and os.path.exists(vehicle_video_path):
            vvid_dur = min(8.0, get_video_duration(vehicle_video_path))

        n_ext = min(max(len(ext_photos), 1), 8)
        n_int = min(max(len(int_photos), 1), 5)
        photos_time = middle_dur - vvid_dur
        per_ext = max(3.0, (photos_time * 0.6) / n_ext)
        per_int = max(3.0, (photos_time * 0.4) / n_int)
        used = intro_dur + n_ext * per_ext + vvid_dur + n_int * per_int + outro_dur
        if used > total_duration * 1.02:
            available = total_duration - intro_dur - outro_dur - vvid_dur
            per_ext = max(3.0, (available * 0.6) / n_ext)
            per_int = max(3.0, (available * 0.4) / n_int)

        print('intro={}s  {}ext*{}s  vvid={}s  {}int*{}s  outro={}s'.format(
            round(intro_dur, 1), n_ext, round(per_ext, 1), round(vvid_dur, 1),
            n_int, round(per_int, 1), round(outro_dur, 1)))

        clip_paths = []
        audio_offset = 0.0
        safe_name = (vehicle_name or '')[:45].replace("'", "").replace(":", ' -')
        safe_price = str(price or '').replace('$', '').replace(',', '')
        safe_dealer = (dealer_name or 'Immaculate Used Cars')[:40].replace("'", "")

        # 1. INTRO: Aaron full-screen
        intro_raw = os.path.join(tmpdir, 'intro.mp4')
        trim_video_segment(heygen_path, 0, intro_dur, intro_raw)
        intro_txt = os.path.join(tmpdir, 'intro_txt.mp4')
        intro_final = add_text_to_clip(intro_raw, safe_name,
                                        '$' + safe_price if safe_price else '',
                                        intro_txt, position='top')
        clip_paths.append(intro_final)
        audio_offset += intro_dur

        # 2. EXTERIOR: Aaron over exterior vehicle photos
        for i, ph in enumerate(ext_photos[:n_ext]):
            bg = os.path.join(tmpdir, 'ext_bg_{:02d}.mp4'.format(i))
            out = os.path.join(tmpdir, 'ext_{:02d}.mp4'.format(i))
            try:
                prepare_bg_photo(ph, per_ext, bg)
                composite_aaron_on_bg(bg, heygen_path, audio_offset, per_ext,
                                       heygen_path, audio_offset, out)
                clip_paths.append(out)
            except Exception as e:
                print('Ext {} failed: {}'.format(i, e))
                try:
                    sil = os.path.join(tmpdir, 'ext_sil_{:02d}.mp4'.format(i))
                    prepare_bg_photo(ph, per_ext, bg)
                    add_silent_audio(bg, sil)
                    clip_paths.append(sil)
                except Exception as e2:
                    print('Ext fallback failed: {}'.format(e2))
            audio_offset += per_ext

        # 3. VEHICLE VIDEO: Aaron voiceover on listing footage
        if vvid_dur > 1.0:
            vv_bg = os.path.join(tmpdir, 'vvid_bg.mp4')
            vv_out = os.path.join(tmpdir, 'vvid_out.mp4')
            try:
                trim_video_segment(vehicle_video_path, 0, vvid_dur, vv_bg)
                cmd_a = ['ffmpeg', '-y', '-i', vv_bg,
                         '-ss', str(audio_offset), '-t', str(vvid_dur), '-i', heygen_path,
                         '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
                         '-shortest', vv_out]
                subprocess.run(cmd_a, capture_output=True, text=True, timeout=60)
                clip_paths.append(vv_out if os.path.exists(vv_out) else vv_bg)
            except Exception as e:
                print('Vehicle video failed: {}'.format(e))
            audio_offset += vvid_dur

        # 4. INTERIOR: Aaron over interior vehicle photos
        for i, ph in enumerate(int_photos[:n_int]):
            bg = os.path.join(tmpdir, 'int_bg_{:02d}.mp4'.format(i))
            out = os.path.join(tmpdir, 'int_{:02d}.mp4'.format(i))
            try:
                prepare_bg_photo(ph, per_int, bg)
                composite_aaron_on_bg(bg, heygen_path, audio_offset, per_int,
                                       heygen_path, audio_offset, out)
                clip_paths.append(out)
            except Exception as e:
                print('Int {} failed: {}'.format(i, e))
                try:
                    sil = os.path.join(tmpdir, 'int_sil_{:02d}.mp4'.format(i))
                    prepare_bg_photo(ph, per_int, bg)
                    add_silent_audio(bg, sil)
                    clip_paths.append(sil)
                except Exception as e2:
                    print('Int fallback failed: {}'.format(e2))
            audio_offset += per_int

        # 5. OUTRO: Aaron full-screen
        outro_raw = os.path.join(tmpdir, 'outro.mp4')
        try:
            trim_video_segment(heygen_path, total_duration - outro_dur, outro_dur, outro_raw)
            outro_txt = os.path.join(tmpdir, 'outro_txt.mp4')
            outro_final = add_text_to_clip(outro_raw, safe_dealer, '', outro_txt, position='bottom')
            clip_paths.append(outro_final)
        except Exception as e:
            print('Outro failed: {}'.format(e))
            if clip_paths:
                clip_paths.append(clip_paths[0])

        print('Concatenating {} clips...'.format(len(clip_paths)))
        concat_clips(clip_paths, output_path)
        print('Complete: {}'.format(output_path))

    return output_path


async def assemble_final_video(vehicle, heygen_video_url, output_dir, job_id):
    os.makedirs(output_dir, exist_ok=True)
    heygen_ext = '.webm' if 'webm' in heygen_video_url.lower() else '.mp4'
    heygen_path = os.path.join(output_dir, job_id + '_heygen' + heygen_ext)
    final_path = os.path.join(output_dir, job_id + '_final.mp4')

    print('Downloading HeyGen video...')
    if not download_file(heygen_video_url, heygen_path):
        raise RuntimeError('Failed to download HeyGen video')

    # Detect actual format and rename if needed
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

    # Download up to 45 vehicle photos (spread evenly)
    photos = vehicle.get('photos', [])
    if not photos:
        raise RuntimeError('No vehicle photos available')
    n_photos = min(len(photos), 45)
    indices = [int(i * len(photos) / n_photos) for i in range(n_photos)]
    photo_paths = []
    for i, url in enumerate([photos[idx] for idx in indices]):
        dest = os.path.join(output_dir, '{}_photo_{:02d}.jpg'.format(job_id, i))
        if download_file(url, dest):
            photo_paths.append(dest)
    if not photo_paths:
        raise RuntimeError('All vehicle photos failed to download')
    print('Downloaded {} photos'.format(len(photo_paths)))

    # Download vehicle video if available
    vehicle_video_path = None
    video_url = vehicle.get('video_url')
    if video_url:
        vv_dest = os.path.join(output_dir, job_id + '_vehicle_vid.mp4')
        if download_file(video_url, vv_dest):
            vehicle_video_path = vv_dest

    build_walkaround_video(
        heygen_path=heygen_path,
        photo_paths=photo_paths,
        vehicle_video_path=vehicle_video_path,
        vehicle_name=vehicle.get('year_make_model', vehicle.get('name', '')),
        price=str(vehicle.get('price', '')).replace('$', '').replace(',', ''),
        dealer_name=vehicle.get('dealer_name', 'Immaculate Used Cars'),
        output_path=final_path
    )

    # Cleanup
    for p in photo_paths:
        try: os.remove(p)
        except Exception: pass
    try: os.remove(heygen_path)
    except Exception: pass
    if vehicle_video_path:
        try: os.remove(vehicle_video_path)
        except Exception: pass

    return final_path
