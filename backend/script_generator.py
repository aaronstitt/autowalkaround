import openai
import os
import json

client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

SYSTEM_PROMPT = '''You are an expert automotive salesperson script writer.
Write natural, conversational vehicle walkaround scripts as if the salesperson is holding a phone in selfie mode.
Structure: exterior walk first (pointing at features), then interior.
Return ONLY valid JSON with keys:
  full_script: complete combined script (under 220 words),
  exterior_script: just the outdoor/exterior portion,
  interior_script: just the indoor/interior portion,
  word_count: total word count'''

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

    prompt = f'''Create a 60-90 second POV selfie-style vehicle walkaround script.
The salesperson is holding their phone in selfie mode walking around then getting inside the car.
VEHICLE: {year} {make} {model} - {color}
TRIM: {name}
PRICE: ${price}
MILEAGE: {mileage}
FUEL: {fuel}  DRIVETRAIN: {drivetrain}
DEALERSHIP: {dealer_name or 'our dealership'}
SALESPERSON: {salesperson_name}
EXTERIOR FEATURES (say while walking around outside):
{ext_list}
INTERIOR FEATURES (say after getting inside):
{int_list}
Keep under 220 words total. Mention price once. End with warm invitation to come see it.
Split into exterior_script and interior_script clearly.'''

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}],
        response_format={'type': 'json_object'},
        temperature=0.75
    )
    result = json.loads(response.choices[0].message.content)
    # Ensure all keys exist
    full = result.get('full_script', '')
    ext_s = result.get('exterior_script', full)
    int_s = result.get('interior_script', '')
    if not int_s and ext_s != full:
        int_s = full[len(ext_s):].strip()
    result['full_script'] = full
    result['exterior_script'] = ext_s
    result['interior_script'] = int_s
    return result
