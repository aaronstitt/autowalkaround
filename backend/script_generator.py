import openai
import os
import json

client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

SYSTEM_PROMPT = '''You are an expert automotive salesperson script writer for car dealership walkaround videos.
Write natural, conversational scripts as if the salesperson is actually at the dealership with the customer, excited and enthusiastic but not pushy.
The video is edited in this order: salesperson intro -> exterior vehicle photos -> vehicle video clip -> interior vehicle photos -> salesperson outro.
Structure your script to match this edit flow EXACTLY:
- intro_script: salesperson introduces themselves and the car (15-20 seconds of speaking)
- exterior_script: salesperson talks about exterior features as if walking around the outside (25-35 seconds)
- interior_script: salesperson describes interior features as if sitting inside or showing interior (25-35 seconds)
- outro_script: warm closing with price and invitation to come see it (10-15 seconds)
Return ONLY valid JSON with keys:
  full_script: all four sections combined in order,
  intro_script: the opening introduction,
  exterior_script: exterior walkaround section,
  interior_script: interior features section,
  outro_script: closing call to action,
  word_count: total word count
Keep total under 280 words. Sound like a real person, not a robot.'''

def generate_walkaround_script(vehicle, salesperson_name, dealer_name=''):
    exterior = vehicle.get('exterior_features', [])
    interior = vehicle.get('interior_features', [])
    name = vehicle.get('name', 'this vehicle')
    year = vehicle.get('year', '')
    make = vehicle.get('make', '')
    model = vehicle.get('model', '')
    color = vehicle.get('color', '')
    price = vehicle.get('price', '')
    mileage = vehicle.get('mileage', '')
    fuel = vehicle.get('fuel_efficiency', '')
    drivetrain = vehicle.get('drivetrain', '')

    ext_list = chr(10).join(f'- {f}' for f in exterior)
    int_list = chr(10).join(f'- {f}' for f in interior)

    prompt = (
        'Write a walkaround video script for this vehicle.\n'
        + 'VEHICLE: ' + str(year) + ' ' + str(make) + ' ' + str(model) + ' - ' + str(color) + '\n'
        + 'TRIM: ' + str(name) + '\n'
        + 'PRICE: $' + str(price) + '\n'
        + 'MILEAGE: ' + str(mileage) + '\n'
        + 'FUEL: ' + str(fuel) + '  DRIVETRAIN: ' + str(drivetrain) + '\n'
        + 'DEALERSHIP: ' + str(dealer_name or 'Immaculate Used Cars') + '\n'
        + 'SALESPERSON: ' + str(salesperson_name) + '\n'
        + '\nEXTERIOR FEATURES to mention while showing outside of car:\n'
        + ext_list + '\n'
        + '\nINTERIOR FEATURES to mention while showing inside of car:\n'
        + int_list + '\n'
        + '\nWrite 4 sections:\n'
        + '1. INTRO (15-20 sec): ' + str(salesperson_name) + ' introduces themselves at the dealership and introduces the car enthusiastically\n'
        + '2. EXTERIOR (25-35 sec): Walking around the outside pointing out the exterior highlights listed above\n'
        + '3. INTERIOR (25-35 sec): Inside the car describing the interior features listed above\n'
        + '4. OUTRO (10-15 sec): Mention price $' + str(price) + ', warm invitation to come test drive, give ' + str(dealer_name or 'Immaculate Used Cars') + ' a call\n'
        + '\nSound natural and conversational. Speak directly to camera like a real salesperson would.\n'
        + 'Total under 280 words.'
    )

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}],
        response_format={'type': 'json_object'},
        temperature=0.75
    )
    result = json.loads(response.choices[0].message.content)

    intro_s = result.get('intro_script', '')
    exterior_s = result.get('exterior_script', '')
    interior_s = result.get('interior_script', '')
    outro_s = result.get('outro_script', '')

    full = result.get('full_script', '')
    if not full:
        full = ' '.join(filter(None, [intro_s, exterior_s, interior_s, outro_s]))

    result['full_script'] = full
    result['intro_script'] = intro_s
    result['exterior_script'] = exterior_s
    result['interior_script'] = interior_s
    result['outro_script'] = outro_s
    return result
