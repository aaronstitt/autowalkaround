import requests
from bs4 import BeautifulSoup
import re
import json
import time
import random
from typing import Optional

# NOTE: No brotli (br) in Accept-Encoding since requests doesn't support it natively
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
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

def _fetch_with_retry(url: str, max_retries: int = 4, timeout: int = 20) -> requests.Response:
    """Fetch URL with exponential backoff retry on 429/5xx errors."""
    # Try ScraperAPI if configured (handles bot detection / IP blocking)
    scraper_api_key = __import__('os').getenv('SCRAPER_API_KEY', '')

    session = requests.Session()

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                wait = (2 ** attempt) + random.uniform(1.0, 3.0)
                time.sleep(wait)
            else:
                time.sleep(random.uniform(0.3, 1.0))

            if scraper_api_key:
                # ScraperAPI proxy. Rotate strategies so a render-budget 500 on this
                # heavy dealer.com page does NOT fail the whole job:
                #   attempt 0: render + click the gallery -> loads the full lazy lightbox
                #   attempt 1: NO render (fast static HTML; dealer.com embeds every
                #              pictures.dealer.com photo URL, incl. interiors, in its
                #              page data layer, and render=false never 500s on budget)
                #   attempt 2: render, no instruction (rendered DOM lazy images)
                #   attempt 3: NO render (final safety net)
                use_render = attempt in (0, 2)
                _hdrs = {'x-sapi-api_key': scraper_api_key,
                         'x-sapi-render': 'true' if use_render else 'false'}
                if attempt == 0:
                    _hdrs['x-sapi-instruction_set'] = json.dumps([
                        {'type': 'wait_for_event', 'event': 'networkidle', 'timeout': 10},
                        {'type': 'click', 'selector': {'type': 'css', 'value': "[data-widget-name='ws-vehicle-media'] img"}},
                        {'type': 'wait', 'value': 5}])
                _to = max(timeout, 110) if use_render else max(timeout, 60)
                resp = session.get('https://api.scraperapi.com/', params={'url': url}, timeout=_to, allow_redirects=True, headers=_hdrs)
            else:
                session.headers.update(HEADERS)
                base_url = "/".join(url.split("/")[:3])
                session.headers["Referer"] = base_url + "/"
                resp = session.get(url, timeout=timeout, allow_redirects=True)

            if resp.status_code in (429, 403):
                if not scraper_api_key:
                    raise requests.exceptions.HTTPError(
                        f'{resp.status_code} Client Error: Bot detection - server blocked the request. '
                        f'Set SCRAPER_API_KEY env var to enable proxy scraping.',
                        response=resp
                    )
                retry_after = int(resp.headers.get("Retry-After", 5))
                wait = max(retry_after, 5) + random.uniform(1.0, 3.0)
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp

        except requests.exceptions.HTTPError as e:
            if attempt == max_retries - 1:
                raise
            continue
        except requests.exceptions.ConnectionError:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)
            continue

    raise requests.exceptions.RetryError(f"Failed to fetch {url} after {max_retries} attempts")

def _plausible_price(jsonld_price: str, html: str) -> str:
    """Return a believable vehicle sale price. Doc fees / add-ons (< $2,500) are rejected.
    Fallback: scan the page for dealer.com price fields, then visible $X,XXX amounts."""
    def _num(v):
        try:
            return int(float(str(v).replace(',', '').replace('$', '').strip()))
        except Exception:
            return 0
    LO, HI = 2500, 250000
    n = _num(jsonld_price)
    if LO <= n <= HI:
        return str(n)
    candidates = []
    # dealer.com structured fields, most authoritative first
    for pat in (r'"internetPrice"\s*:\s*"?([\d,\.]+)',
                r'"salePrice"\s*:\s*"?([\d,\.]+)',
                r'"askingPrice"\s*:\s*"?([\d,\.]+)',
                r'itemprop="price"[^>]*content="([\d,\.]+)"',
                r'"price"\s*:\s*"?([\d,\.]+)'):
        for m in re.findall(pat, html):
            v = _num(m)
            if LO <= v <= HI:
                candidates.append(v)
        if candidates:
            break
    if not candidates:
        for m in re.findall(r'\$\s?(\d{1,3}(?:,\d{3})+)', html):
            v = _num(m)
            if LO <= v <= HI:
                candidates.append(v)
    if candidates:
        # most repeated on-page amount is almost always the advertised price
        best = max(set(candidates), key=candidates.count)
        print(f'[Scraper] JSON-LD price {jsonld_price!r} implausible; using on-page price {best}')
        return str(best)
    print(f'[Scraper] JSON-LD price {jsonld_price!r} implausible and no fallback found; leaving empty')
    return ''

def parse_vehicle_html(html: str, url: str) -> dict:
    """Parse vehicle listing HTML into structured data."""
    soup = BeautifulSoup(html, "html.parser")
    vehicle = {}

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

    # v2: JSON-LD offers.price on this dealer.com template can surface the DOC FEE
    # (e.g. $599) instead of the sale price. Sanity-check and fall back to on-page prices.
    vehicle["price"] = _plausible_price(vehicle.get("price", ""), html)

    mileage_match = re.search(r'([\d,]+)\s*miles', html, re.I)
    if mileage_match:
        vehicle["mileage"] = mileage_match.group(0)

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

    if not highlighted:
        match = re.search(r'"highlights":\s*\[([^\]]+)\]', html)
        if match:
            highlighted = re.findall(r'"([^"]+)"', match.group(1))

    vehicle["highlighted_features"] = highlighted[:19]

    # Only grab JPG vehicle photos from dealer.com - filter out PNG files which are
    # 360-viewer UI elements (Carketa spinner graphics, not actual car photos)
    photo_pattern = re.compile(r'https://pictures\.dealer\.com/\S+?\.jpg', re.I)
    _lb = soup.find(id='nuka-carousel') or soup.find(id='nuka-carousel-slider-frame')
    _media = soup.find(attrs={'data-widget-name': 'ws-vehicle-media'})
    if _lb:
        _scope_html = str(_lb)
    elif _media:
        _scope_html = str(_media)
    else:
        _scope_html = html
    all_photos = list(dict.fromkeys(photo_pattern.findall(_scope_html)))
    if len(all_photos) < 5:
        all_photos = list(dict.fromkeys(photo_pattern.findall(html)))
    cleaned = []
    for p in all_photos:
        p = p.rstrip('"').rstrip("'").rstrip('>')
        # Skip thumbnails and non-vehicle UI assets
        if 'thumb_' not in p:
            cleaned.append(p)
    vehicle["photos"] = cleaned
    print(f'Scraper found {len(cleaned)} vehicle photos (JPG only, no 360-viewer PNGs)')

    video_xml_match = re.search(r'https://videos\d*\.dealer\.com/clients/\S+?\.xml', html)
    if video_xml_match:
        xml_url = video_xml_match.group(0).rstrip('"').rstrip("'")
        video_base = xml_url.rsplit('/', 1)[0] + '/'
        try:
            xml_resp = _fetch_with_retry(xml_url)
            h264_match = re.search(r'h264_high_src="([^"]+)"', xml_resp.text)
            vehicle["video_url"] = video_base + h264_match.group(1) if h264_match else None
        except Exception:
            vehicle["video_url"] = None
    else:
        vehicle["video_url"] = None

    vin = vehicle.get("vin", "")
    vehicle["spin_360_url"] = f"https://next.carketa.app/vin/{vin}" if vin else None

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

def scrape_vehicle_page(url: str, page_html: str = None) -> dict:
    """
    Scrape vehicle listing page.
    If page_html is provided (from frontend browser fetch), use it directly.
    Otherwise, fetch the URL from the server.
    """
    if page_html and len(page_html) > 1000:
        # Use HTML provided by the frontend (avoids bot detection)
        return parse_vehicle_html(page_html, url)

    # Fetch from server
    resp = _fetch_with_retry(url)
    return parse_vehicle_html(resp.text, url)
