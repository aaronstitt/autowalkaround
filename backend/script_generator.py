import openai
import os
import json

client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Fixed intro/outro that stays the same every time per requirements
# Only the vehicle-specific details (name, price) are inserted
FIXED_INTRO_TEMPLATE = (
    "Hey what is going on guys, {name} here with Immaculate Used Cars. "
    "I am here today to walk you around this beautiful {year} {make} {model} {trim}. "
    "Let me show you what she's got."
)

FIXED_OUTRO_TEMPLATE = (
    "Guys that is it for this {year} {make} {model} {trim}. "
    "It is priced at {price}. "
    "If you are interested give us a call or come on in and we will get you taken care of. "
    "I am {name} with Immaculate Used Cars - come see us!"
)

SYSTEM_PROMPT = '''You are an expert automotive salesperson script writer.
Write a natural, conversational walkaround video script as if the salesperson is physically walking around the vehicle with the customer.

CRITICAL RULES:
1. Use ONLY the Highlighted Features provided - do not invent or add any features
2. Mention features in this order: exterior features first, then interior features
3. Write as if physically pointing at each feature while standing at the car
4. Sound like a real person talking, not reading from a list
5. Voice inflection should vary - use enthusiasm for great features, be informative for specs
6. Do NOT include intro or outro - those are handled separately
7. Keep total between 150-220 words for the feature walkthrough section only

Return ONLY valid JSON with these keys:
exterior_script: talking about exterior highlighted features while walking the outside
interior_script: talking about interior highlighted features while showing inside
full_script: exterior_script + interior_script combined
word_count: total word count'''

def generate_walkaround_script(vehicle, salesperson_name, dealer_name=''):
    year = vehicle.get('year', '')
    make = vehicle.get('make', '')
    model = vehicle.get('model', '')
    trim = vehicle.get('name', '').replace(str(year), '').replace(str(make), '').replace(str(model), '').strip()
    price = vehicle.get('price', '')
    highlighted = vehicle.get('highlighted_features', [])
    exterior = vehicle.get('exterior_features', [])
    interior = vehicle.get('interior_features', [])

    # Build fixed intro and outro
    intro_script = FIXED_INTRO_TEMPLATE.format(
        name=salesperson_name,
        year=year, make=make, model=model,
        trim=trim or '',
    ).strip()

    outro_script = FIXED_OUTRO_TEMPLATE.format(
        name=salesperson_name,
        year=year, make=make, model=model,
        trim=trim or '',
        price=('$' + str(price)) if price else 'a great price',
    ).strip()

    # Only use highlighted features for the main script content
    # Use all highlighted if categorization is sparse
    if len(exterior) + len(interior) < 3:
        exterior = highlighted[:int(len(highlighted) * 0.6)]
        interior = highlighted[int(len(highlighted) * 0.6):]

    ext_list = chr(10).join('- ' + f for f in exterior)
    int_list = chr(10).join('- ' + f for f in interior)
    all_features = chr(10).join('- ' + f for f in highlighted)

    prompt = (
        'Write the walkaround feature script for this vehicle.\n'
        + 'VEHICLE: ' + str(year) + ' ' + str(make) + ' ' + str(model) + ' ' + str(trim) + '\n'
        + 'PRICE: $' + str(price) + '\n'
        + '\nHIGHLIGHTED FEATURES FROM LISTING PAGE (use ONLY these - in this order):\n'
        + 'EXTERIOR features to mention while walking the outside:\n'
        + (ext_list if ext_list else all_features[:len(all_features)//2]) + '\n'
        + '\nINTERIOR features to mention while showing inside the car:\n'
        + (int_list if int_list else all_features[len(all_features)//2:]) + '\n'
        + '\nWrite ONLY the exterior and interior sections (not intro or outro).\n'
        + 'Sound like you are physically pointing at each feature.\n'
        + 'Voice should vary - excited about great features, informative about specs.\n'
        + '150-220 words total.'
    )

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}],
        response_format={'type': 'json_object'},
        temperature=0.75
    )
    result = json.loads(response.choices[0].message.content)

    exterior_s = result.get('exterior_script', '')
    interior_s = result.get('interior_script', '')
    full_feature = result.get('full_script', '')
    if not full_feature:
        full_feature = ' '.join(filter(None, [exterior_s, interior_s]))

    # Combine: fixed intro + AI features + fixed outro
    full_script = ' '.join(filter(None, [intro_script, full_feature, outro_script]))

    # Build year_make_model for video overlay text
    vehicle['year_make_model'] = ' '.join(filter(None, [str(year), str(make), str(model), str(trim)]))

    return {
        'full_script': full_script,
        'intro_script': intro_script,
        'exterior_script': exterior_s,
        'interior_script': interior_s,
        'outro_script': outro_script,
        'word_count': len(full_script.split()),
    }
