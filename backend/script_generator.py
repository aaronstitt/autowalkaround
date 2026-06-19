import openai
import os
import json

client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# ──────────────────────────────────────────────
# SEGMENTED walkaround script - each segment maps to a camera position
# Order mirrors walkaround v4.mov:
# intro -> selfie face-cam: salesperson intro
# front -> camera faces vehicle front
# driver_side -> walking to driver side
# rear -> at rear of vehicle
# pass_side -> passenger side
# interior -> inside vehicle
# outro -> closing, price, CTA
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert automotive walkaround video scriptwriter.
You write scripts for a salesperson physically walking a phone camera around a vehicle.

THE VIDEO STRUCTURE - script must match this exactly:
- INTRO: Salesperson faces camera, selfie mode, introduces himself and vehicle (15-20 seconds spoken)
- FRONT: Camera now faces vehicle front - salesperson talks about front-end features
- DRIVER_SIDE: Walking to driver side - driver-side features
- REAR: At the rear - rear features including backup camera etc
- PASS_SIDE: Passenger side - wheels, moldings, exterior
- INTERIOR: Camera inside vehicle - all interior features
- OUTRO: Quick wrap-up, price, call to action

STYLE RULES:
1. Sound like a REAL enthusiastic person. Natural speech, not robotic.
2. Use contractions: you're, it's, we've got, let's, she's, that's
3. Add verbal transitions: Now check this out, Come around here, Look at this, Over here we've got
4. Vary pace and energy. Short punchy sentences for exciting features.
5. Use enthusiasm: This is awesome, I love this, Check that out, This one is huge
6. ONLY mention features matching the camera position segment
7. ONLY use features from the Highlighted Features list - never invent features

CRITICAL LENGTH REQUIREMENT:
- Each main segment (front, driver_side, rear, pass_side, interior) must be 20-28 words MAX.
- At normal speaking pace that is 10-13 seconds of audio - this is required for lip sync to work.
- If you write more than 28 words for any segment, the video will not lip sync correctly.
- Intro: 25-35 words. Outro: 20-28 words.
- Count your words carefully before returning the JSON.

Return ONLY valid JSON with exactly these keys:
intro, front, driver_side, rear, pass_side, interior, outro, full_script, word_count"""

def generate_walkaround_script(vehicle, salesperson_name, dealer_name='Immaculate Used Cars'):
    year = vehicle.get('year', '')
    make = vehicle.get('make', '')
    model = vehicle.get('model', '')
    trim_raw = vehicle.get('name', '')
    trim = trim_raw
    for part in [str(year), str(make), str(model)]:
        trim = trim.replace(part, '').strip()
    trim = trim.strip(' -\u2013')
    price = vehicle.get('price', '')
    color = vehicle.get('color', '')
    highlighted = vehicle.get('highlighted_features', [])

    # Categorize features by camera position
    front_kw = ['headlight', 'fog light', 'approach light', 'bumper', 'hood', 'grille', 'front fog', 'delay-off']
    rear_kw = ['camera', 'backup', 'rear window wiper', 'liftgate', 'spoiler', 'parkview', 'rear window', 'back-up']
    driver_kw = ['mirror', 'keyless entry', 'perimeter', 'remote keyless', 'auto-dimming']
    side_kw = ['wheel', 'alloy', 'molding', 'belt molding', 'rack', 'roof rack', 'crossbar', 'touring suspension']
    interior_kw = ['seat', 'leather', 'audio', 'screen', 'display', 'climate', 'air conditioning',
                   'wireless', 'navigation', 'steering wheel', 'folding', 'cargo', 'armrest',
                   'heated', 'sunroof', 'moonroof', 'touchscreen', 'phone', 'connectivity',
                   'carplay', 'android', 'satellite', 'speaker', 'tachometer', 'temperature',
                   'dimming rearview', 'stow', 'bucket seat', '3rd row', 'split fold',
                   'audio control', 'vanity', 'reading light', 'overhead', 'trip computer']

    front_features, rear_features, driver_features = [], [], []
    side_features, interior_feat, unassigned = [], [], []

    for f in highlighted:
        fl = f.lower()
        if any(k in fl for k in interior_kw):
            interior_feat.append(f)
        elif any(k in fl for k in rear_kw):
            rear_features.append(f)
        elif any(k in fl for k in front_kw):
            front_features.append(f)
        elif any(k in fl for k in driver_kw):
            driver_features.append(f)
        elif any(k in fl for k in side_kw):
            side_features.append(f)
        else:
            unassigned.append(f)

    # Distribute unassigned features evenly across segments
    buckets = [front_features, driver_features, rear_features, side_features]
    for i, f in enumerate(unassigned):
        buckets[i % 4].append(f)

    color_str = (' in ' + color) if color else ''

    def feat_list(lst):
        return '\n'.join('- ' + f for f in lst) if lst else '- (general presentation of this area)'

    prompt = (
        'Write a walkaround video script for this vehicle.\n\n'
        'VEHICLE: ' + str(year) + ' ' + str(make) + ' ' + str(model) + ' ' + str(trim) + color_str + '\n'
        'PRICE: $' + str(price) + '\n'
        'SALESPERSON: ' + salesperson_name + '\n'
        'DEALERSHIP: ' + dealer_name + '\n\n'
        'FEATURES BY CAMERA POSITION:\n\n'
        'FRONT of vehicle:\n' + feat_list(front_features) + '\n\n'
        'DRIVER SIDE:\n' + feat_list(driver_features) + '\n\n'
        'REAR of vehicle:\n' + feat_list(rear_features) + '\n\n'
        'PASSENGER SIDE:\n' + feat_list(side_features) + '\n\n'
        'INTERIOR:\n' + feat_list(interior_feat) + '\n\n'
        'INTRO (25-35 words MAX - selfie mode):\n'
        'Aaron faces camera, greets viewer warmly, introduces himself and the vehicle.\n'
        'Must include: his name Aaron, Immaculate Used Cars, year/make/model/trim.\n'
        'End with something like: Let me show you what she has got.\n\n'
        'EACH MAIN SEGMENT (front, driver_side, rear, pass_side, interior):\n'
        'STRICT MAXIMUM: 20-28 words per segment. No more. This is critical for lip sync.\n'
        'Pick 1-2 features max per segment. Be punchy and enthusiastic.\n\n'
        'OUTRO (20-28 words MAX):\n'
        'Mention price $' + str(price) + ', invite to call or visit, sign off with name and dealership.\n\n'
        'TOTAL TARGET: 160-220 words across all segments combined.\n'
        'Make it sound like a genuinely excited real person, not a formal script.\n'
        'COUNT YOUR WORDS. Each segment must be 20-28 words or less.'
    )

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt}
        ],
        response_format={'type': 'json_object'},
        temperature=0.85
    )
    result = json.loads(response.choices[0].message.content)

    intro_s = result.get('intro', '')
    front_s = result.get('front', '')
    driver_s = result.get('driver_side', '')
    rear_s = result.get('rear', '')
    pass_s = result.get('pass_side', '')
    interior_s = result.get('interior', '')
    outro_s = result.get('outro', '')
    full = result.get('full_script', '')
    if not full:
        full = ' '.join(filter(None, [intro_s, front_s, driver_s, rear_s, pass_s, interior_s, outro_s]))

    # Hard truncation safety net: if any segment exceeds ~130 words/min * 13s = ~28 words, trim it
    def _trim_to_words(text, max_words=28):
        words = text.split()
        if len(words) > max_words:
            trimmed = ' '.join(words[:max_words])
            print(f'[Script] Trimmed segment from {len(words)} to {max_words} words')
            return trimmed
        return text

    front_s = _trim_to_words(front_s)
    driver_s = _trim_to_words(driver_s)
    rear_s = _trim_to_words(rear_s)
    pass_s = _trim_to_words(pass_s)
    interior_s = _trim_to_words(interior_s)
    outro_s = _trim_to_words(outro_s)

    vehicle['year_make_model'] = ' '.join(filter(None, [str(year), str(make), str(model), str(trim)]))

    return {
        'full_script': full,
        'intro_script': intro_s,
        'exterior_script': ' '.join(filter(None, [front_s, driver_s, rear_s, pass_s])),
        'interior_script': interior_s,
        'outro_script': outro_s,
        'segments': {
            'intro': intro_s,
            'front': front_s,
            'driver_side': driver_s,
            'rear': rear_s,
            'pass_side': pass_s,
            'interior': interior_s,
            'outro': outro_s,
        },
        'feature_map': {
            'front': front_features,
            'driver_side': driver_features,
            'rear': rear_features,
            'pass_side': side_features,
            'interior': interior_feat,
        },
        'word_count': len(full.split()),
    }
