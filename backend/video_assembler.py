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
    cmd = ['ffmpeg', '-y', '-i', src, '-vf', 'scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280', '-q:v', '2', '-frames:v', '1', dest]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode == 0 and os.path.exists(dest)

def check_has_alpha(path):
    """Check if video file has alpha channel (VP9/WebM yuva420p)."""
    probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', path]
    probe_r = subprocess.run(probe_cmd, capture_output=True, text=True)
    has_alpha = False
    try:
        streams = json.loads(probe_r.stdout).get('streams', [])
        for s in streams:
            pix_fmt = s.get('pix_fmt', '')
            codec = s.get('codec_name', '')
            if 'yuva' in pix_fmt:
                has_alpha = True
                print('Alpha confirmed via pix_fmt={}'.format(pix_fmt))
            elif codec in ('vp8', 'vp9') and s.get('codec_type') == 'video':
                # VP9 may carry alpha even if ffprobe doesn't show yuva
                has_alpha = True
                print('Alpha assumed: VP9 video stream (HeyGen webm)')
    except Exception as e:
        print('Alpha check error: {}'.format(e))
    return has_alpha

def build_composite_walkaround(photo_paths, heygen_path, output_path, vehicle_name='', price='', dealer_name=''):
    '''Real walkaround: vehicle photos fill frame, Aaron composited with proper alpha.'''
    n_photos = len(photo_paths)
    if n_photos == 0:
        raise RuntimeError('No photos provided')
    duration = get_video_duration(heygen_path)
    print('HeyGen avatar duration: {}s, photos: {}'.format(round(duration,1), n_photos))
    ext = os.path.splitext(heygen_path)[1].lower()
    has_alpha = check_has_alpha(heygen_path)
    print('HeyGen file: ext={}, has_alpha={}'.format(ext, has_alpha))
    with tempfile.TemporaryDirectory() as tmpdir:
        scaled_paths = []
        for i, p in enumerate(photo_paths):
            dest = os.path.join(tmpdir, 'photo_{:03d}.jpg'.format(i))
            ok = prescale_photo(p, dest)
            if ok:
                scaled_paths.append(dest)
            else:
                print('Warning: failed to scale photo {}: {}'.format(i, p))
        if not scaled_paths:
            raise RuntimeError('All photos failed to scale')
        per_photo = max(duration / len(scaled_paths), 2.0)
        listf = os.path.join(tmpdir, 'list.txt')
        with open(listf, 'w') as f:
            for p in scaled_paths:
                f.write("file '{}'\nduration {}\n".format(p, round(per_photo, 2)))
            f.write("file '{}'\n".format(scaled_paths[-1]))
        slideshow_path = os.path.join(tmpdir, 'slideshow.mp4')
        slide_cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', listf,
                     '-vf', 'fps=15,setsar=1',
                     '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '30',
                     '-pix_fmt', 'yuv420p',
                     '-t', str(int(duration) + 2),
                     '-threads', '1', '-b:v', '600k', '-maxrate', '700k', '-bufsize', '1000k',
                     slideshow_path]
        print('Building slideshow: {} photos at {}s each'.format(len(scaled_paths), round(per_photo,1)))
        r = subprocess.run(slide_cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError('Slideshow failed rc={}: {}'.format(r.returncode, r.stderr[-400:]))
        def safe(s):
            return str(s or '').replace("'", '').replace(':', '-').replace('"', '')[:45]
        vn = safe(vehicle_name)
        vp = safe(price)
        vd = safe(dealer_name)
        aaron_h = int(1280 * 0.65)
        aaron_w = int(720 * 0.70)
        aaron_x = int((720 - aaron_w) / 2)
        aaron_y = 1280 - aaron_h
        text_filters = []
        if vn:
            text_filters.append("drawtext=text='{}':fontcolor=white:fontsize=24:x=(w-text_w)/2:y=60:box=1:boxcolor=black@0.65:boxborderw=6".format(vn))
        if vp:
            text_filters.append("drawtext=text='${}':fontcolor=#FFD700:fontsize=30:x=(w-text_w)/2:y=98:box=1:boxcolor=black@0.65:boxborderw=5".format(vp))
        if vd:
            text_filters.append("drawtext=text='{}':fontcolor=white:fontsize=18:x=(w-text_w)/2:y=h-50:box=1:boxcolor=black@0.55:boxborderw=4".format(vd))
        text_chain = (','.join(text_filters) + ',') if text_filters else ''
        scale_str = str(aaron_w) + ':' + str(aaron_h) + ':force_original_aspect_ratio=decrease'
        ov_str = str(aaron_x) + ':' + str(aaron_y) + ':shortest=1[out]'
        if has_alpha:
            # Split VP9 alpha: extract color+alpha separately, scale both, merge back
            # This is the correct approach for VP9 yuva420p WebM compositing
            fc = (
                '[0:v]' + text_chain + 'setsar=1[bg];'
                + '[1:v]scale=' + scale_str + '[avcolor];'
                + '[1:v]alphaextract,scale=' + scale_str + '[avalpha];'
                + '[avcolor][avalpha]alphamerge[av];'
                + '[bg][av]overlay=' + ov_str
            )
        else:
            fc = (
                '[0:v]' + text_chain + 'setsar=1[bg];'
                + '[1:v]scale=' + scale_str + '[av];'
                + '[bg][av]overlay=' + ov_str
            )
        compose_cmd = ['ffmpeg', '-y',
                       '-i', slideshow_path,
                       '-i', heygen_path,
                       '-filter_complex', fc,
                       '-map', '[out]', '-map', '1:a',
                       '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
                       '-pix_fmt', 'yuv420p',
                       '-c:a', 'aac', '-b:a', '128k',
                       '-b:v', '1000k', '-maxrate', '1200k', '-bufsize', '1800k',
                       '-threads', '2', '-shortest', output_path]
        print('Compositing Aaron onto vehicle photos (alpha={})...'.format(has_alpha))
        print('Filter complex: {}'.format(fc[:200]))
        r = subprocess.run(compose_cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print('Composite stderr: {}'.format(r.stderr[-600:]))
            # Fallback: try without alpha (plain overlay, no background removal)
            print('Trying colorkey fallback (backup plan)...')
            fc_ck = (
                '[0:v]' + text_chain + 'setsar=1[bg];'
                + '[1:v]scale=' + scale_str + '[av];'
                + '[av]colorkey=0x111111:0.4:0.05[avfinal];'
                + '[bg][avfinal]overlay=' + ov_str
            )
            cmd2 = ['ffmpeg', '-y',
                    '-i', slideshow_path,
                    '-i', heygen_path,
                    '-filter_complex', fc_ck,
                    '-map', '[out]', '-map', '1:a',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
                    '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '128k',
                    '-b:v', '1000k', '-maxrate', '1200k', '-bufsize', '1800k',
                    '-threads', '2', '-shortest', output_path]
            r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
            if r2.returncode != 0:
                print('Colorkey fallback stderr: {}'.format(r2.stderr[-400:]))
                # Final fallback: plain overlay no background removal
                fc_plain = (
                    '[0:v]' + text_chain + 'setsar=1[bg];[1:v]scale=' + scale_str + '[av];[bg][av]overlay=' + ov_str
                )
                cmd3 = ['ffmpeg', '-y',
                        '-i', slideshow_path,
                        '-i', heygen_path,
                        '-filter_complex', fc_plain,
                        '-map', '[out]', '-map', '1:a',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
                        '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-b:a', '128k',
                        '-b:v', '1000k', '-maxrate', '1200k', '-bufsize', '1800k',
                        '-threads', '2', '-shortest', output_path]
                r3 = subprocess.run(cmd3, capture_output=True, text=True, timeout=600)
                if r3.returncode != 0:
                    raise RuntimeError('All composite attempts failed: {}'.format(r3.stderr[-400:]))
        return output_path

async def assemble_final_video(vehicle, heygen_video_url, output_dir, job_id):
    os.makedirs(output_dir, exist_ok=True)
    heygen_ext = '.webm' if 'webm' in heygen_video_url.lower() else '.mp4'
    heygen_path = os.path.join(output_dir, job_id + '_heygen' + heygen_ext)
    final_path = os.path.join(output_dir, job_id + '_final.mp4')
    print('Downloading HeyGen avatar from: {}'.format(heygen_video_url[:80]))
    if not download_file(heygen_video_url, heygen_path):
        raise RuntimeError('Failed to download HeyGen video')
    probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', heygen_path]
    probe_r = subprocess.run(probe_cmd, capture_output=True, text=True)
    try:
        fmt_name = json.loads(probe_r.stdout).get('format', {}).get('format_name', '')
        if 'webm' in fmt_name or 'matroska' in fmt_name:
            new_path = os.path.join(output_dir, job_id + '_heygen.webm')
            if heygen_path != new_path:
                os.rename(heygen_path, new_path)
            heygen_path = new_path
            print('Detected webm format')
        elif 'mp4' in fmt_name or 'mov' in fmt_name:
            new_path = os.path.join(output_dir, job_id + '_heygen.mp4')
            if heygen_path != new_path:
                os.rename(heygen_path, new_path)
            heygen_path = new_path
            print('Detected mp4 format')
    except Exception:
        pass
    photos = vehicle.get('photos', [])
    if not photos:
        raise RuntimeError('No vehicle photos available')
    n_photos = min(len(photos), 12)
    indices = [int(i * len(photos) / n_photos) for i in range(n_photos)]
    selected_photos = [photos[i] for i in indices]
    photo_paths = []
    for i, url in enumerate(selected_photos):
        dest = os.path.join(output_dir, '{}_photo_{:02d}.jpg'.format(job_id, i))
        if download_file(url, dest):
            photo_paths.append(dest)
        else:
            print('Photo {} download failed, skipping'.format(i))
    if not photo_paths:
        raise RuntimeError('All vehicle photos failed to download')
    print('Downloaded {} vehicle photos for walkaround'.format(len(photo_paths)))
    vehicle_name = vehicle.get('year_make_model', vehicle.get('name', ''))
    price = str(vehicle.get('price', '')).replace('$', '').replace(',', '')
    dealer_name = vehicle.get('dealer_name', 'Immaculate Used Cars')
    build_composite_walkaround(photo_paths, heygen_path, final_path,
                               vehicle_name=vehicle_name, price=price, dealer_name=dealer_name)
    for p in photo_paths:
        try:
            os.remove(p)
        except Exception:
            pass
    try:
        os.remove(heygen_path)
    except Exception:
        pass
    print('Final walkaround video: {}'.format(final_path))
    return final_path
