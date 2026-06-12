import requests
from bs4 import BeautifulSoup
import re
import json
from typing import Optional

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}

INTERIOR_KEYWORDS = [
    "leather", "seat", "interior", "moonroof", "sunroof", "temperature",
    "climate", "audio", "steering wheel", "cockpit", "upholstery",
    "heated front", "dual zone", "rear air", "phone connectivity", "wireless",
    "navigation", "screen", "display", "folding rear", "cargo", "armrest",
    "ventilated", "memory", "driver seat", "passenger seat", "heated seat"
]
EXTERIOR_KEYWORDS = [
    "wheel", "alloy", "headlight", "wiper", "mirror", "bumper", "spoiler",
    "approach light", "keyless entry", "perimeter", "fog light", "rain sensing",
    "auto high-beam", "heated door mirror", "power liftgate", "exterior", "paint"
]

def scrape_vehicle_page(url: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    html = resp.text

    vehicle = {}

    # JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and "Car" in str(data.get("@type", "")):
                vehicle = {
                    "name": data.get("name", ""),
                    "year": str(data.get("vehicleModelDate", "")),
                    "make": data.get("brand", {}).get("name", "") if isinstance(data.get("brand"), dict) else "",
                    "model": data.get("model", ""),
                    "color": data.get("color", ""),
                    "interior_color": data.get("vehicleInteriorColor", ""),
                    "vin": data.get("vehicleIdentificationNumber", ""),
                    "price": str(data.get("offers", {}).get("price", "")),
                    "fuel_efficiency": data.get("fuelEfficiency", ""),
                    "transmission": data.get("vehicleTransmission", ""),
                    "drivetrain": data.get("driveWheelConfiguration", ""),
                    "engine": data.get("vehicleEngine", ""),
                    "dealer_name": data.get("offers", {}).get("seller", {}).get("name", "") if isinstance(data.get("offers"), dict) else "",
                    "image_primary": data.get("image", ""),
                    "page_url": url,
                }
                break
        except Exception:
            continue

    # Mileage
    mileage_match = re.search(r'([d,]+)\s*miles', html, re.I)
    if mileage_match:
        vehicle["mileage"] = mileage_match.group(0)

    # Highlighted features - look for the section in HTML
    highlighted = []
    features_header = soup.find(string=re.compile("Highlighted Features", re.I))
    if features_header:
        container = features_header.find_parent()
        for _ in range(6):
            if container:
                items = container.find_all("li")
                if items and len(items) > 2:
                    for item in items[:20]:
                        text = item.get_text(strip=True)
                        if text and 3 < len(text) < 80 and "highlight" not in text.lower():
                            highlighted.append(text)
                    if highlighted:
                        break
                container = container.parent

    # Fallback: extract from script JSON
    if not highlighted:
        match = re.search(r'"highlights":\s*\[([^\]]+)\]', html)
        if match:
            highlighted = re.findall(r'"([^"]+)"', match.group(1))

    vehicle["highlighted_features"] = highlighted[:19]

    # All photos
    photo_pattern = re.compile(r'https://pictures\.dealer\.com/[^\s"\']+\.(?:jpg|png|jpeg)', re.I)
    all_photos = list(dict.fromkeys(photo_pattern.findall(html)))
    vehicle["photos"] = [p for p in all_photos if 'thumb_' not in p]

    # Video URL
    video_xml_match = re.search(r'https://videos\d*\.dealer\.com/clients/[^\s"\']+\.xml', html)
    if video_xml_match:
        xml_url = video_xml_match.group(0)
        video_base = xml_url.rsplit('/', 1)[0] + '/'
        try:
            xml_resp = requests.get(xml_url, headers=HEADERS, timeout=10)
            h264_match = re.search(r'h264_high_src="([^"]+)"', xml_resp.text)
            vehicle["video_url"] = video_base + h264_match.group(1) if h264_match else None
        except Exception:
            vehicle["video_url"] = None
    else:
        vehicle["video_url"] = None

    # 360 view
    vin = vehicle.get("vin", "")
    vehicle["spin_360_url"] = f"https://next.carketa.app/vin/{vin}" if vin else None

    # Categorize features
    interior_features, exterior_features = [], []
    for feature in vehicle.get("highlighted_features", []):
        fl = feature.lower()
        is_int = any(k in fl for k in INTERIOR_KEYWORDS)
        is_ext = any(k in fl for k in EXTERIOR_KEYWORDS)
        if is_int and not is_ext:
            interior_features.append(feature)
        else:
            exterior_features.append(feature)

    vehicle["interior_features"] = interior_features
    vehicle["exterior_features"] = exterior_features

    return vehicle
