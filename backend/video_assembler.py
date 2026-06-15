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

def make_photo_clip(photo_path, duration, output_path, w=720, h=1280):
    zoom_expr = 'min(1.08,zoom+0.0007)'
    vf = (
        "scale={}:{}:force_original_aspect_ratio=increase,"
        "crop={}:{},setsar=1,"
        "zoompan=z='{}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={}:fps=24:s={}x{}"
    ).format(w*2, h*2, w*2, h*2, zoom_expr, int(duration*24), w, h)
    cmd = ['ffmpeg', '-y', '-loop', '1', '-i', photo_path,
           '-vf', vf,
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
           '-pix_fmt', 'yuv420p',
           '-t', str(duration),
           '-r', '24',
           '-threads', '1',
           '-b:v', '500k', '-maxrate', '600k', '-bufsize', '900k',
           output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        cmd2 = ['ffmpeg', '-y', '-loop', '1', '-i', photo_path,
                '-vf', 'scale={}:{}:force_original_aspect_ratio=increase,crop={}:{},setsar=1'.format(w,h,w,h),
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
                '-pix_fmt', 'yuv420p',
                '-t', str(duration),
                '-r', '24',
                '-threads', '1',
                '-b:v', '500k',
                output_path]
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)
        if r2.returncode != 0:
            raise RuntimeError('photo_clip failed: ' + r2.stderr[-300:])
    return output_path

def trim_video_segment(src, start, duration, output_path, w=720, h=1280):
    cmd = ['ffmpeg', '-y', '-ss', str(start), '-i', src, '-t', str(duration),
           '-vf', 'scale={}:{}:force_original_aspect_ratio=increase,crop={}:{},setsar=1'.format(w,h,w,h),
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
           '-pix_fmt', 'yuv420p', '-r', '24',
           '-c:a', 'aac', '-b:a', '128k',
           '-threads', '1',
           output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError('trim_video failed: ' + r.stderr[-300:])
    return output_path

def add_audio_to_video(video_path, audio_src, start_offset, duration, output_path):
    cmd = ['ffmpeg', '-y',
           '-i', video_path,
           '-ss', str(start_offset), '-t', str(duration), '-i', audio_src,
           '-c:v', 'copy',
           '-c:a', 'aac', '-b:a', '128k',
           '-shortest',
           output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError('add_audio failed: ' + r.stderr[-300:])
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
               '-r', '24',
               '-threads', '2',
               output_path]
        run_ffmpeg(cmd, 'concat_clips', timeout=600)
    finally:
        try:
            os.unlink(listf)
        except Exception:
            pass
    return output_path

def add_silent_audio(video_path, output_path):
    cmd = ['ffmpeg', '-y', '-i', video_path,
           '-f', 'lavfi', '-i', 'aevalsrc=0:c=mono:s=44100',
           '-c:v', 'copy',
           '-c:a', 'aac', '-b:a', '64k',
           '-shortest',
           output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError('add_silent_audio failed: ' + r.stderr[-200:])
    return output_path

def has_audio_stream(path):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        streams = json.loads(r.stdout).get('streams', [])
        return any(s.get('codec_type') == 'audio' for s in streams)
    except Exception:
        return False

def build_walkaround_video(heygen_path, photo_paths, vehicle_video_path,
                           vehicle_name, price, dealer_name, output_path):
    total_duration = get_video_duration(heygen_path)
    print('HeyGen total duration: {}s'.format(round(total_duration, 1)))
    print('Photos available: {}'.format(len(photo_paths)))
    print('Vehicle video: {}'.format(vehicle_video_path or 'none'))

    with tempfile.TemporaryDirectory() as tmpdir:
        # Split photos: first 65% exterior, last 35% interior
        n = len(photo_paths)
        split_idx = max(1, int(n * 0.65))
        ext_photos = photo_paths[:split_idx]
        int_photos = photo_paths[split_idx:]
        if not int_photos:
            int_photos = photo_paths[-2:]

        # Segment durations
        intro_dur = min(8.0, total_duration * 0.15)
        outro_dur = min(8.0, total_duration * 0.15)
        middle_dur = total_duration - intro_dur - outro_dur

        vvid_dur = 0.0
        if vehicle_video_path and os.path.exists(vehicle_video_path):
            raw_vv_dur = get_video_duration(vehicle_video_path)
            vvid_dur = min(8.0, raw_vv_dur)

        # Use up to 10 exterior + 6 interior photos
        n_ext = min(len(ext_photos), 10)
        n_int = min(len(int_photos), 6)
        n_ext = max(n_ext, 1)
        n_int = max(n_int, 1)

        # Calculate per-photo durations
        photos_time = middle_dur - vvid_dur
        per_ext = max(3.0, (photos_time * 0.6) / n_ext)
        per_int = max(3.0, (photos_time * 0.4) / n_int)

        # Ensure we don't exceed available audio
        used = intro_dur + n_ext * per_ext + vvid_dur + n_int * per_int + outro_dur
        if used > total_duration * 1.02:
            available = total_duration - intro_dur - outro_dur - vvid_dur
            per_ext = max(3.0, (available * 0.6) / n_ext)
            per_int = max(3.0, (available * 0.4) / n_int)

        print('Intro={}s, ExtPhotos={}x{}s, VehicleVid={}s, IntPhotos={}x{}s, Outro={}s'.format(
            round(intro_dur,1), n_ext, round(per_ext,1), round(vvid_dur,1),
            n_int, round(per_int,1), round(outro_dur,1)))

        clip_paths = []
        audio_offset = 0.0

        # INTRO: Aaron full-screen with vehicle name + price
        intro_path = os.path.join(tmpdir, 'intro.mp4')
        trim_video_segment(heygen_path, 0, intro_dur, intro_path)
        intro_txt_path = os.path.join(tmpdir, 'intro_txt.mp4')
        safe_name = (vehicle_name or '')[:45].replace("'","").replace(":",' -')
        safe_price = str(price or '').replace('$','').replace(',','')
        safe_dealer = (dealer_name or 'Immaculate Used Cars')[:40].replace("'","")
        vf_intro = "drawtext=text='{}':fontcolor=white:fontsize=26:x=(w-text_w)/2:y=55:box=1:boxcolor=black@0.65:boxborderw=7,drawtext=text='{}':fontcolor=#FFD700:fontsize=32:x=(w-text_w)/2:y=95:box=1:boxcolor=black@0.65:boxborderw=7".format(safe_name, '$'+safe_price if safe_price else '')
        cmd_intro = ['ffmpeg', '-y', '-i', intro_path,
                     '-vf', vf_intro,
                     '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
                     '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-threads', '1',
                     intro_txt_path]
        r = subprocess.run(cmd_intro, capture_output=True, text=True, timeout=60)
        clip_paths.append(intro_txt_path if r.returncode == 0 else intro_path)
        audio_offset += intro_dur

        # EXTERIOR PHOTO CLIPS with Aaron voiceover
        for i, ph in enumerate(ext_photos[:n_ext]):
            clip_path = os.path.join(tmpdir, 'ext_{:02d}_raw.mp4'.format(i))
            clip_with_audio = os.path.join(tmpdir, 'ext_{:02d}.mp4'.format(i))
            make_photo_clip(ph, per_ext, clip_path)
            try:
                add_audio_to_video(clip_path, heygen_path, audio_offset, per_ext, clip_with_audio)
                clip_paths.append(clip_with_audio)
            except Exception as e:
                print('Ext audio overlay failed for clip {}: {}'.format(i, e))
                silent_path = os.path.join(tmpdir, 'ext_{:02d}_silent.mp4'.format(i))
                add_silent_audio(clip_path, silent_path)
                clip_paths.append(silent_path)
            audio_offset += per_ext

        # VEHICLE VIDEO CLIP
        if vvid_dur > 1.0:
            vvid_path = os.path.join(tmpdir, 'vehicle_vid.mp4')
            vvid_with_audio = os.path.join(tmpdir, 'vehicle_vid_audio.mp4')
            try:
                trim_video_segment(vehicle_video_path, 0, vvid_dur, vvid_path)
                add_audio_to_video(vvid_path, heygen_path, audio_offset, vvid_dur, vvid_with_audio)
                clip_paths.append(vvid_with_audio)
                audio_offset += vvid_dur
            except Exception as e:
                print('Vehicle video clip failed: {}'.format(e))

        # INTERIOR PHOTO CLIPS with Aaron voiceover
        for i, ph in enumerate(int_photos[:n_int]):
            clip_path = os.path.join(tmpdir, 'int_{:02d}_raw.mp4'.format(i))
            clip_with_audio = os.path.join(tmpdir, 'int_{:02d}.mp4'.format(i))
            make_photo_clip(ph, per_int, clip_path)
            try:
                add_audio_to_video(clip_path, heygen_path, audio_offset, per_int, clip_with_audio)
                clip_paths.append(clip_with_audio)
            except Exception as e:
                print('Int audio overlay failed for clip {}: {}'.format(i, e))
                silent_path = os.path.join(tmpdir, 'int_{:02d}_silent.mp4'.format(i))
                add_silent_audio(clip_path, silent_path)
                clip_paths.append(silent_path)
            audio_offset += per_int

        # OUTRO: Aaron full-screen with dealer name
        outro_start = total_duration - outro_dur
        outro_path = os.path.join(tmpdir, 'outro.mp4')
        try:
            trim_video_segment(heygen_path, outro_start, outro_dur, outro_path)
            outro_txt_path = os.path.join(tmpdir, 'outro_txt.mp4')
            vf_outro = "drawtext=text='{}':fontcolor=white:fontsize=22:x=(w-text_w)/2:y=h-70:box=1:boxcolor=black@0.6:boxborderw=6".format(safe_dealer)
            cmd_outro = ['ffmpeg', '-y', '-i', outro_path,
                         '-vf', vf_outro,
                         '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
                         '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-threads', '1',
                         outro_txt_path]
            r2 = subprocess.run(cmd_outro, capture_output=True, text=True, timeout=60)
            clip_paths.append(outro_txt_path if r2.returncode == 0 else outro_path)
        except Exception as e:
            print('Outro trim failed: {}'.format(e))
            clip_paths.append(intro_path)

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

    vehicle_video_path = None
    video_url = vehicle.get('video_url')
    if video_url:
        vv_dest = os.path.join(output_dir, job_id + '_vehicle_vid.mp4')
        if download_file(video_url, vv_dest):
            vehicle_video_path = vv_dest
            print('Downloaded vehicle video: {}'.format(vv_dest))
        else:
            print('Vehicle video download failed, skipping')

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
