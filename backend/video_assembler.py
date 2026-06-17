import os, requests, time

HEADERS = {'User-Agent': 'Mozilla/5.0'}
HEYGEN_BASE = 'https://api.heygen.com'
HEYGEN_POLL_INTERVAL = 15
HEYGEN_POLL_MAX = 300

WALKAROUND_MOTION_PROMPT = (
        "The person is walking around a car in a car dealership lot, performing a vehicle walkaround video. "
        "They hold the camera in selfie mode (like holding a phone in front of themselves pointing at their face). "
        "They walk around the perimeter of the vehicle, gesturing with their free hand to point out features. "
        "Full body is visible. They move continuously, walking side to side and around the car. "
        "Energetic and enthusiastic salesperson body language throughout."
)

def get_look_id(avatar_group_id):
        try:
                    url = HEYGEN_BASE + '/v3/avatars/looks?ownership=private&group_id=' + avatar_group_id
                    r = requests.get(url, headers={'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}, timeout=30)
                    if r.status_code == 200:
                                    data = r.json().get('data', [])
                                    looks = data if isinstance(data, list) else data.get('looks', [])
                                    preferred_keywords = ['sharp', 'car', 'lot', 'outdoor', 'salesman', 'used']
                                    for look in looks:
                                                        name = (look.get('name') or look.get('look_name') or '').lower()
                                                        if any(kw in name for kw in preferred_keywords):
                                                                                return look.get('id') or look.get('look_id')
                                                                        if looks:
                                                                                            return looks[0].get('id') or looks[0].get('look_id')
        except Exception as e:
                    print(f'[get_look_id] error: {e}')
                return None

def heygen_headers():
        return {'x-api-key': os.getenv('HEYGEN_API_KEY'), 'Content-Type': 'application/json'}

def generate_heygen_audio(script_text, avatar_look_id, voice_id, tmpdir):
        """Generate walkaround video via HeyGen Avatar V with motion prompt."""
    print('[HeyGen] Generating walkaround video with motion prompt...')

    payload = {
                'type': 'avatar',
                'avatar_id': avatar_look_id,
                'voice_id': voice_id,
                'script': script_text,
                'aspect_ratio': '9:16',
                'resolution': '720p',
                'output_format': 'mp4',
                'motion_prompt': WALKAROUND_MOTION_PROMPT,
                'engine': {'type': 'avatar_v'}
    }

    r = requests.post(HEYGEN_BASE + '/v3/videos', headers=heygen_headers(), json=payload, timeout=60)
    if r.status_code != 200:
                raise RuntimeError(f'HeyGen create failed: {r.status_code} {r.text}')

    video_id = r.json()['data']['video_id']
    print(f'[HeyGen] Video ID: {video_id} - polling every {HEYGEN_POLL_INTERVAL}s...')

    for i in range(HEYGEN_POLL_MAX):
                time.sleep(HEYGEN_POLL_INTERVAL)
                try:
                                sr = requests.get(HEYGEN_BASE + '/v3/videos/' + video_id, headers=heygen_headers(), timeout=30)
                                vdata = sr.json().get('data', {})
                                status = vdata.get('status', 'unknown')
                                print(f'[HeyGen] Poll {i+1}: {status}')
                                if status == 'completed':
                                                    video_url = vdata.get('video_url')
                                                    if not video_url:
                                                                            raise RuntimeError('HeyGen completed but no video_url')
                                                                        heygen_mp4 = os.path.join(tmpdir, 'heygen_final.mp4')
                                                    _download_file(video_url, heygen_mp4)
                                                    print(f'[HeyGen] Downloaded: {heygen_mp4}')
                                                    return heygen_mp4, heygen_mp4
elif status == 'failed':
                raise RuntimeError(f'HeyGen failed: {vdata.get("failure_message", "unknown")}')
except RuntimeError:
            raise
except Exception as e:
            print(f'[HeyGen] Poll {i+1} error: {e}')

    raise RuntimeError(f'HeyGen timed out after {HEYGEN_POLL_MAX * HEYGEN_POLL_INTERVAL // 60} min')

def _download_file(url, dest_path):
        r = requests.get(url, headers=HEADERS, stream=True, timeout=300)
    r.raise_for_status()
    with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                                f.write(chunk)
                        print(f'[Download] {dest_path} ({os.path.getsize(dest_path)} bytes)')

def build_walkaround_video(vehicle, script_segments, heygen_audio_path,
                                                       heygen_mp4_path, vehicle_photos, vehicle_video_url, tmpdir):
                                                               """HeyGen video IS the final output - return it directly."""
                                                               print(f'[Build] HeyGen video is final output: {heygen_mp4_path}')
                                                               return heygen_mp4_path
