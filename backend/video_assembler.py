import os, requests, subprocess, json, shutil, tempfile, math, io
import numpy as np
from PIL import Image

HEADERS = {'User-Agent': 'Mozilla/5.0'}
W = 720
H = 1280

# ============================================================
# LOT BACKGROUND URLS - Immaculate Used Cars dealership lot
# ============================================================
LOT_BG_URLS = [
    'https://lh3.googleusercontent.com/gps-cs-s/APNQkAGSkAI7-TAoNkcv4m5PEQRwYfsJdYgypmHTVDUN1Sx4vxRvC13WEcVTnRSkCNWVATeqv7iDe9xxsWWn2VM9ya1BQJEIvTdrY35roeZ3_Sw61Pzeqju1TI0-SlJv2U-qOrKjDKAa=w1333-h1000-k-no',
]

# ============================================================
# REMBG - AI background removal (works on ANY background)
# ============================================================
_rembg_session = None

def get_rembg_session():
    global _rembg_session
    if _rembg_session is None:
        try:
            from rembg import new_session
            _rembg_session = new_session('u2net')
            print('rembg session initialized')
        except Exception as e:
            print('rembg init failed: ' + str(e))
            _rembg_session = False
    return _rembg_session

def remove_bg(img_pil):
    session = get_rembg_session()
    if not session:
        return img_pil.convert('RGBA')
    try:
        from rembg import remove
        buf = io.BytesIO()
        img_pil.save(buf, format='PNG')
        result = remove(buf.getvalue(), session=session)
        return Image.open(io.BytesIO(result)).convert('RGBA')
    except Exception as e:
        print('rembg error: ' + str(e))
        return img_pil.convert('RGBA')

# ============================================================
# EXTRACT AVATAR FRAMES from HeyGen MP4
# ============================================================
def extract_avatar_frames(heygen_path, tmpdir, fps=8, max_frames=600):
    frames_dir = os.path.join(tmpdir, 'avatar_frames')
    os.makedirs(frames_dir, exist_ok=True)
    frame_pattern = os.path.join(frames_dir, 'frame_%04d.png')
    cmd = ['ffmpeg', '-y', '-i', heygen_path,
           '-vf', 'fps=' + str(fps) + ',scale=' + str(W) + ':' + str(H) + ':force_original_aspect_ratio=decrease',
           '-frames:v', str(max_frames),
           '-threads', '1', frame_pattern]
    subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    frame_files = sorted([
        os.path.join(frames_dir, f)
        for f in os.listdir(frames_dir)
        if f.endswith('.png')
    ])
    print('Extracted ' + str(len(frame_files)) + ' avatar frames at ' + str(fps) + 'fps')
    print('Removing avatar background with rembg AI...')
    alpha_frames = []
    session = get_rembg_session()
    if session:
        try:
            from rembg import remove
            for i, fp in enumerate(frame_files):
                try:
                    with open(fp, 'rb') as f:
                        raw = f.read()
                    result = remove(raw, session=session)
                    alpha_path = fp.replace('.png', '_alpha.png')
                    with open(alpha_path, 'wb') as f:
                        f.write(result)
                    alpha_frames.append(alpha_path)
                    if i % 20 == 0:
                        print('  rembg frame ' + str(i) + '/' + str(len(frame_files)))
                except Exception as e:
                    print('  rembg frame ' + str(i) + ' failed: ' + str(e))
                    alpha_frames.append(fp)
        except Exception as e:
            print('rembg batch failed: ' + str(e))
            alpha_frames = frame_files
    else:
        alpha_frames = frame_files
    print('Alpha frames ready: ' + str(len(alpha_frames)))
    return alpha_frames, fps

# ============================================================
# DOWNLOAD helpers
# ============================================================
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

# ============================================================
# LOT BACKGROUND
# ============================================================
def get_lot_background(tmpdir):
    lot_path = os.path.join(tmpdir, 'lot_bg.jpg')
    for url in LOT_BG_URLS:
        if download_file(url, lot_path):
            try:
                img = Image.open(lot_path).convert('RGB')
                img.save(lot_path, 'JPEG', quality=90)
                print('Lot background loaded: ' + str(img.size))
                return lot_path
            except Exception as e:
                print('Lot bg load failed: ' + str(e))
    print('Using generated lot background fallback')
    img = Image.new('RGB', (W, H), (110, 120, 90))
    img.save(lot_path)
    return lot_path

# ============================================================
# COMPOSITE ENGINE
# Walkaround frame = lot bg + vehicle photo (right) + avatar cutout (left/selfie)
# ============================================================
def composite_walkaround_frame(lot_bg_path, vehicle_photo_path, avatar_frame_path, output_path):
    '''
    One composite frame for walkaround segments:
    - Lot background fills full frame (slightly darkened)
    - Vehicle photo: right side of frame (65% width)
    - Avatar with removed background: lower-left selfie position
    Simulates salesperson holding phone in selfie mode standing at the vehicle
    '''
    frame = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    try:
        lot = Image.open(lot_bg_path).convert('RGB').resize((W, H), Image.LANCZOS)
        lot_arr = np.array(lot, dtype=np.float32) * 0.65
        frame.paste(Image.fromarray(lot_arr.astype(np.uint8)).convert('RGBA'), (0, 0))
    except Exception as e:
        print('Lot paste error: ' + str(e))
    try:
        car = Image.open(vehicle_photo_path).convert('RGBA')
        car_max_w = int(W * 0.72)
        car_max_h = int(H * 0.70)
        car.thumbnail((car_max_w, car_max_h), Image.LANCZOS)
        car_x = W - car.width - 8
        car_y = int(H * 0.16)
        frame.paste(car, (car_x, car_y), car)
    except Exception as e:
        print('Car paste error: ' + str(e))
    try:
        av = Image.open(avatar_frame_path).convert('RGBA')
        av_h = int(H * 0.80)
        av_w = int(av_h * 9 // 16)
        av = av.resize((av_w, av_h), Image.LANCZOS)
        av_x = -int(av_w * 0.04)
        av_y = H - av_h + int(av_h * 0.06)
        frame.paste(av, (av_x, av_y), av)
    except Exception as e:
        print('Avatar paste error: ' + str(e))
    Image.new('RGB', (W, H)).paste(frame.convert('RGB'), (0, 0))
    rgb = frame.convert('RGB')
    rgb.save(output_path, 'JPEG', quality=88)
    return output_path

def composite_lot_only_frame(lot_bg_path, avatar_frame_path, output_path):
    '''Intro/outro: avatar centered on lot background in full selfie mode.'''
    frame = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    try:
        lot = Image.open(lot_bg_path).convert('RGB').resize((W, H), Image.LANCZOS)
        frame.paste(lot.convert('RGBA'), (0, 0))
    except Exception as e:
        print('Lot paste error: ' + str(e))
    try:
        av = Image.open(avatar_frame_path).convert('RGBA')
        av_h = int(H * 0.88)
        av_w = int(av_h * 9 // 16)
        av = av.resize((av_w, av_h), Image.LANCZOS)
        av_x = (W - av.width) // 2
        av_y = H - av.height - 15
        frame.paste(av, (av_x, av_y), av)
    except Exception as e:
        print('Avatar lot frame error: ' + str(e))
    frame.convert('RGB').save(output_path, 'JPEG', quality=88)
    return output_path

# ============================================================
# BUILD VIDEO SEGMENT from frames list
# ============================================================
def build_segment_from_frames(frame_list, audio_src, audio_start, duration, output_path, input_fps=8):
    if not frame_list:
        raise RuntimeError('No frames for segment')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        listf = f.name
        total_needed = max(1, int(duration * input_fps))
        for i in range(total_needed):
            frame = frame_list[i % len(frame_list)]
            f.write("file '" + frame + "'\n")
            f.write('duration ' + str(round(1.0 / input_fps, 4)) + '\n')
    try:
        vf = ('scale=' + str(W) + ':' + str(H) +
              ':force_original_aspect_ratio=decrease,'
              'pad=' + str(W) + ':' + str(H) + ':(ow-iw)/2:(oh-ih)/2:color=black')
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', listf,
            '-ss', str(audio_start), '-t', str(duration), '-i', audio_src,
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
            '-pix_fmt', 'yuv420p', '-vf', vf,
            '-c:a', 'aac', '-b:a', '128k',
            '-r', '24', '-shortest', '-threads', '1', output_path
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError('segment encode failed: ' + r.stderr[-300:])
    finally:
        try: os.unlink(listf)
        except Exception: pass
    return output_path

def concat_clips(clip_paths, output_path):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        listf = f.name
        for p in clip_paths:
            f.write("file '" + p + "'\n")
    try:
        cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', listf,
               '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
               '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
               '-r', '24', '-threads', '2', output_path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError('concat failed: ' + r.stderr[-400:])
    finally:
        try: os.unlink(listf)
        except Exception: pass
    return output_path

def add_text_overlay(video_path, line1, line2, output_path, position='top'):
    safe1 = (line1 or '')[:50].replace("'", '').replace(':', ' -')
    safe2 = (line2 or '')[:30].replace("'", '').replace(':', ' -')
    if position == 'top':
        y1, y2 = 55, 100
    else:
        y1, y2 = 'h-90', 'h-50'
    vf = (
        "drawtext=text='" + safe1 + "':fontcolor=white:fontsize=26:x=(w-text_w)/2:y=" + str(y1) + ":"
        "box=1:boxcolor=black@0.65:boxborderw=7,"
        "drawtext=text='" + safe2 + "':fontcolor=#FFD700:fontsize=30:x=(w-text_w)/2:y=" + str(y2) + ":"
        "box=1:boxcolor=black@0.65:boxborderw=7"
    )
    cmd = ['ffmpeg', '-y', '-i', video_path, '-vf', vf,
           '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '24',
           '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-threads', '1', output_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return video_path
    return output_path

# ============================================================
# VEHICLE VIDEO segment
# ============================================================
def build_vehicle_video_segment(vehicle_video_path, avatar_frames, avatar_fps,
                                 lot_bg_path, audio_src, audio_start,
                                 duration, tmpdir, seg_idx, output_path):
    vv_frames_dir = os.path.join(tmpdir, 'vv_frames_' + str(seg_idx))
    os.makedirs(vv_frames_dir, exist_ok=True)
    vv_pattern = os.path.join(vv_frames_dir, 'vv_%04d.jpg')
    cmd = ['ffmpeg', '-y', '-i', vehicle_video_path,
           '-vf', 'fps=8,scale=' + str(W) + ':' + str(H) + ':force_original_aspect_ratio=increase,crop=' + str(W) + ':' + str(H),
           '-t', str(duration), '-q:v', '3', '-threads', '1', vv_pattern]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    vv_files = sorted([os.path.join(vv_frames_dir, f) for f in os.listdir(vv_frames_dir) if f.endswith('.jpg')])
    total_needed = max(1, int(duration * 8))
    comp_dir = os.path.join(tmpdir, 'vv_comp_' + str(seg_idx))
    os.makedirs(comp_dir, exist_ok=True)
    av_total = len(avatar_frames)
    av_offset = int(audio_start * avatar_fps)
    comp_frames = []
    for i in range(total_needed):
        comp_path = os.path.join(comp_dir, 'frame_' + str(i).zfill(4) + '.jpg')
        av_f = avatar_frames[(av_offset + i) % av_total]
        bg_path = vv_files[i % len(vv_files)] if vv_files else lot_bg_path
        try:
            bg = Image.open(bg_path).convert('RGB').resize((W, H), Image.LANCZOS)
            frame = bg.convert('RGBA')
            av = Image.open(av_f).convert('RGBA')
            av_h = int(H * 0.72)
            av_w = int(av_h * 9 // 16)
            av = av.resize((av_w, av_h), Image.LANCZOS)
            av_x = -int(av_w * 0.04)
            av_y = H - av_h + int(av_h * 0.06)
            frame.paste(av, (av_x, av_y), av)
            frame.convert('RGB').save(comp_path, 'JPEG', quality=85)
            comp_frames.append(comp_path)
        except Exception as e:
            print('VV frame ' + str(i) + ' error: ' + str(e))
            if comp_frames:
                comp_frames.append(comp_frames[-1])
    return build_segment_from_frames(comp_frames, audio_src, audio_start, duration, output_path)

# ============================================================
# MAIN BUILD FUNCTION
# ============================================================
def build_walkaround_video(heygen_path, photo_paths, vehicle_video_path,
                            vehicle_name, price, dealer_name, output_path):
    '''
    Build complete walkaround video.
    Architecture:
    - Extract avatar frames from HeyGen MP4 at 8fps
    - AI background removal (rembg) strips ANY background from avatar frames
    - Composite per segment: lot bg + vehicle photo (right) + avatar cutout (lower-left selfie)
    - Intro/outro: avatar on lot bg only (no vehicle photo)
    - Vehicle video: listing video with avatar overlay
    - Single frame perspective throughout: selfie POV camera
    '''
    total_duration = get_video_duration(heygen_path)
    print('HeyGen: ' + str(round(total_duration, 1)) + 's | Photos: ' + str(len(photo_paths)))

    with tempfile.TemporaryDirectory() as tmpdir:
        lot_bg = get_lot_background(tmpdir)
        avatar_frames, avatar_fps = extract_avatar_frames(heygen_path, tmpdir, fps=8)
        if not avatar_frames:
            raise RuntimeError('No avatar frames extracted')

        n = len(photo_paths)
        split_idx = max(1, int(n * 0.65))
        ext_photos = photo_paths[:split_idx]
        int_photos = photo_paths[split_idx:] or photo_paths[-2:]

        intro_dur = min(8.0, total_duration * 0.12)
        outro_dur = min(8.0, total_duration * 0.12)
        vvid_dur = 0.0
        if vehicle_video_path and os.path.exists(vehicle_video_path):
            vvid_dur = min(10.0, get_video_duration(vehicle_video_path))

        n_ext = min(len(ext_photos), 10)
        n_int = min(len(int_photos), 6)
        photos_time = total_duration - intro_dur - outro_dur - vvid_dur
        per_ext = max(3.5, (photos_time * 0.62) / max(n_ext, 1))
        per_int = max(3.5, (photos_time * 0.38) / max(n_int, 1))

        print('Timing: intro=' + str(round(intro_dur,1)) + 's ' + str(n_ext) + 'ext*' + str(round(per_ext,1)) +
              's vvid=' + str(round(vvid_dur,1)) + 's ' + str(n_int) + 'int*' + str(round(per_int,1)) + 's outro=' + str(round(outro_dur,1)) + 's')

        clip_paths = []
        audio_offset = 0.0
        safe_name = (vehicle_name or '')[:45].replace("'", '').replace(':', ' -')
        safe_price = str(price or '').replace('$', '').replace(',', '')
        safe_dealer = (dealer_name or 'Immaculate Used Cars')[:40].replace("'", '')
        av_total = len(avatar_frames)

        # ---- 1. INTRO: Avatar on lot background ----
        print('Building intro segment...')
        try:
            intro_comp_dir = os.path.join(tmpdir, 'intro_comp')
            os.makedirs(intro_comp_dir, exist_ok=True)
            n_frames = max(1, int(intro_dur * 8))
            frames = []
            for i in range(n_frames):
                out_f = os.path.join(intro_comp_dir, 'frame_' + str(i).zfill(4) + '.jpg')
                composite_lot_only_frame(lot_bg, avatar_frames[i % av_total], out_f)
                frames.append(out_f)
            intro_raw = os.path.join(tmpdir, 'intro_raw.mp4')
            build_segment_from_frames(frames, heygen_path, 0.0, intro_dur, intro_raw)
            intro_final = os.path.join(tmpdir, 'intro_final.mp4')
            result = add_text_overlay(intro_raw, safe_name, ('$' + safe_price) if safe_price else '', intro_final, 'top')
            clip_paths.append(result)
        except Exception as e:
            print('Intro failed: ' + str(e))
        audio_offset += intro_dur

        # ---- 2. EXTERIOR WALKAROUND ----
        print('Building ' + str(n_ext) + ' exterior segments...')
        for i, ph in enumerate(ext_photos[:n_ext]):
            print('  Exterior ' + str(i+1) + '/' + str(n_ext) + '...')
            try:
                comp_dir = os.path.join(tmpdir, 'ext_' + str(i).zfill(2))
                os.makedirs(comp_dir, exist_ok=True)
                n_frames = max(1, int(per_ext * 8))
                av_offset = int(audio_offset * avatar_fps)
                frames = []
                for j in range(n_frames):
                    out_f = os.path.join(comp_dir, 'frame_' + str(j).zfill(4) + '.jpg')
                    av_f = avatar_frames[(av_offset + j) % av_total]
                    composite_walkaround_frame(lot_bg, ph, av_f, out_f)
                    frames.append(out_f)
                out_seg = os.path.join(tmpdir, 'ext_seg_' + str(i).zfill(2) + '.mp4')
                build_segment_from_frames(frames, heygen_path, audio_offset, per_ext, out_seg)
                clip_paths.append(out_seg)
            except Exception as e:
                print('  Exterior ' + str(i) + ' failed: ' + str(e))
            audio_offset += per_ext

        # ---- 3. VEHICLE VIDEO ----
        if vvid_dur > 1.0:
            print('Building vehicle video segment...')
            try:
                vv_out = os.path.join(tmpdir, 'vehicle_vid.mp4')
                build_vehicle_video_segment(
                    vehicle_video_path, avatar_frames, avatar_fps,
                    lot_bg, heygen_path, audio_offset, vvid_dur,
                    tmpdir, 99, vv_out
                )
                clip_paths.append(vv_out)
            except Exception as e:
                print('Vehicle video failed: ' + str(e))
            audio_offset += vvid_dur

        # ---- 4. INTERIOR WALKAROUND ----
        print('Building ' + str(n_int) + ' interior segments...')
        for i, ph in enumerate(int_photos[:n_int]):
            print('  Interior ' + str(i+1) + '/' + str(n_int) + '...')
            try:
                comp_dir = os.path.join(tmpdir, 'int_' + str(i).zfill(2))
                os.makedirs(comp_dir, exist_ok=True)
                n_frames = max(1, int(per_int * 8))
                av_offset = int(audio_offset * avatar_fps)
                frames = []
                for j in range(n_frames):
                    out_f = os.path.join(comp_dir, 'frame_' + str(j).zfill(4) + '.jpg')
                    av_f = avatar_frames[(av_offset + j) % av_total]
                    composite_walkaround_frame(lot_bg, ph, av_f, out_f)
                    frames.append(out_f)
                out_seg = os.path.join(tmpdir, 'int_seg_' + str(i).zfill(2) + '.mp4')
                build_segment_from_frames(frames, heygen_path, audio_offset, per_int, out_seg)
                clip_paths.append(out_seg)
            except Exception as e:
                print('  Interior ' + str(i) + ' failed: ' + str(e))
            audio_offset += per_int

        # ---- 5. OUTRO ----
        print('Building outro segment...')
        try:
            outro_start = max(0.0, total_duration - outro_dur)
            comp_dir = os.path.join(tmpdir, 'outro_comp')
            os.makedirs(comp_dir, exist_ok=True)
            n_frames = max(1, int(outro_dur * 8))
            av_offset = int(outro_start * avatar_fps)
            frames = []
            for i in range(n_frames):
                out_f = os.path.join(comp_dir, 'frame_' + str(i).zfill(4) + '.jpg')
                av_f = avatar_frames[(av_offset + i) % av_total]
                composite_lot_only_frame(lot_bg, av_f, out_f)
                frames.append(out_f)
            outro_raw = os.path.join(tmpdir, 'outro_raw.mp4')
            build_segment_from_frames(frames, heygen_path, outro_start, outro_dur, outro_raw)
            outro_final = os.path.join(tmpdir, 'outro_final.mp4')
            result = add_text_overlay(outro_raw, safe_dealer, '', outro_final, 'bottom')
            clip_paths.append(result)
        except Exception as e:
            print('Outro failed: ' + str(e))

        if not clip_paths:
            raise RuntimeError('No clips built')
        print('Concatenating ' + str(len(clip_paths)) + ' clips...')
        concat_clips(clip_paths, output_path)
        print('Final video ready: ' + output_path)
    return output_path

async def assemble_final_video(vehicle, heygen_video_url, output_dir, job_id):
    os.makedirs(output_dir, exist_ok=True)
    heygen_ext = '.webm' if 'webm' in heygen_video_url.lower() else '.mp4'
    heygen_path = os.path.join(output_dir, job_id + '_heygen' + heygen_ext)
    final_path = os.path.join(output_dir, job_id + '_final.mp4')
    print('Downloading HeyGen video...')
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
        raise RuntimeError('No vehicle photos')
    n_photos = min(len(photos), 45)
    indices = [int(i * len(photos) / n_photos) for i in range(n_photos)]
    photo_paths = []
    for i, url in enumerate([photos[idx] for idx in indices]):
        dest = os.path.join(output_dir, job_id + '_photo_' + str(i).zfill(2) + '.jpg')
        if download_file(url, dest):
            photo_paths.append(dest)
    if not photo_paths:
        raise RuntimeError('All photos failed to download')
    print('Downloaded ' + str(len(photo_paths)) + ' photos')
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
    for p in photo_paths:
        try: os.remove(p)
        except Exception: pass
    try: os.remove(heygen_path)
    except Exception: pass
    if vehicle_video_path:
        try: os.remove(vehicle_video_path)
        except Exception: pass
    return final_path
