import openai
import os
import json

client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

SYSTEM_PROMPT = '''You are an expert automotive salesperson script writer.
Write natural, conversational 90-second vehicle walkaround scripts.
The salesperson walks outside first, then shows the interior.
Return ONLY valid JSON with keys: full_script, exterior_notes, interior_notes, word_count'''

def generate_walkaround_script(vehicle: dict, salesperson_name: str, dealer_name: str = '') -> dict:
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

    prompt = f'''Create a 90-second vehicle walkaround script:
VEHICLE: {year} {make} {model} - {color}
TRIM: {name}
PRICE: ${price}
MILEAGE: {mileage}
FUEL: {fuel}  DRIVETRAIN: {drivetrain}
DEALERSHIP: {dealer_name or 'our dealership'}
SALESPERSON: {salesperson_name}
EXTERIOR FEATURES (outside, walking around):
{ext_list}
INTERIOR FEATURES (inside the car):
{int_list}
Write naturally, under 220 words. Mention price once. End with warm invitation.'''

    response = client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}],
        response_format={'type': 'json_object'},
        temperature=0.75
    )
    return json.loads(response.choices[0].message.content)