import json, re, os
from curl_cffi import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Busca números con formato paraguayo: 54.500 o 25.500,50
GUARANI_REGEX = re.compile(r'(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\b')

def load_config():
    with open('config.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def fix_url(base, src):
    if not src or src.startswith('data:'): return None
    if src.startswith('//'): return 'https:' + src
    if src.startswith('http'): return src
    return urljoin(base, src)

def parse_guarani(text):
    match = GUARANI_REGEX.search(text)
    if not match: return None
    price_str = match.group(1).replace('.', '').replace(',', '.')
    try: return float(price_str)
    except: return None

def scrape_via_api(site):
    base_url = site['url'].rsplit('/', 1)[0]
    api_url = base_url + '/wp-json/wc/store/v1/products?per_page=100'
    print(f"Intentando API: {api_url}")
    session = requests.Session(impersonate="chrome120")
    try:
        res = session.get(api_url, timeout=20)
        if res.status_code == 200:
            data = res.json()
            products = []
            for p in data:
                price = parse_guarani(p.get('price_html', '') or p.get('price', '0'))
                if not price and p.get('price'):
                    try: price = float(p['price'])
                    except: price = 0
                img = p.get('images', [{}])[0].get('src') if p.get('images') else None
                if img: img = fix_url(base_url, img)
                products.append({"site": site['name'], "site_id": site['id'], "name": p.get('name', ''), "price": price, "image": img, "measure": ""})
            print(f"API exitosa: {len(products)} productos")
            return products
    except: pass
    print("API no disponible, buscando en HTML...")
    return None

def scrape_via_html(site):
    session = requests.Session(impersonate="chrome120")
    try:
        res = session.get(site['url'], timeout=30)
        if res.status_code == 403:
            print(f"Bloqueado (403): {site['name']}")
            return []
    except Exception as e:
        print(f"Error de conexion: {e}")
        return []

    soup = BeautifulSoup(res.text, 'html.parser')
    
    # Si hay selectores personalizados, los usa
    if site.get('product_selector'):
        cards = soup.select(site['product_selector'])
        products = []
        for card in cards:
            item = {"site": site['name'], "site_id": site['id']}
            name_el = card.select_one(site.get('name_selector') or 'h2, h3, h4, a')
            item['name'] = name_el.get_text(strip=True) if name_el else ""
            price_el = card.select_one(site.get('price_selector')) if site.get('price_selector') else card
            item['price'] = parse_guarani(price_el.get_text(strip=True)) or 0
            img_el = card.select_one(site.get('image_selector') or 'img')
            if img_el:
                src = img_el.get('src') or img_el.get('data-src')
                item['image'] = fix_url(site['url'], src)
            else:
                item['image'] = None
            if item['name'] and item['price'] > 0: products.append(item)
        print(f"Selectores: {len(products)} productos")
        return products

    # MODO AUTOMÁTICO: Busca precios en todo el HTML sin selectores
    print("Modo automatico activado...")
    all_elements = soup.find_all(True)
    cards = []
    seen = set()
    for el in all_elements:
        text = el.get_text(strip=True)
        if parse_guarani(text):
            parent = el.parent
            for _ in range(5):
                if parent and parent.name in ['li', 'div', 'article', 'tr']:
                    sig = hash(str(parent)[:200])
                    if sig not in seen:
                        seen.add(sig)
                        cards.append(parent)
                        break
                parent = parent.parent if parent else None
            if len(seen) > 300: break

    products = []
    for card in cards:
        item = {"site": site['name'], "site_id": site['id']}
        name_el = card.select_one('h1, h2, h3, h4, a, span, p')
        item['name'] = name_el.get_text(strip=True) if name_el else ""
        item['price'] = parse_guarani(card.get_text(strip=True)) or 0
        img_el = card.select_one('img')
        if img_el:
            src = img_el.get('src') or img_el.get('data-src')
            item['image'] = fix_url(site['url'], src)
        else:
            item['image'] = None
        if item['name'] and item['price'] > 0: products.append(item)
        
    print(f"Automatico: {len(products)} productos")
    return products

def scrape_site(site):
    print(f"\n--- Scrapeando: {site['name']} ---")
    api_products = scrape_via_api(site)
    if api_products is not None: return api_products
    return scrape_via_html(site)

def main():
    config = load_config()
    os.makedirs('data', exist_ok=True)
    all_products = []
    for site in config:
        all_products.extend(scrape_site(site))
    with open('data/products.json', 'w', encoding='utf-8') as f:
        json.dump(all_products, f, ensure_ascii=False, indent=2)
    print(f"\nTotal guardado: {len(all_products)} productos")

if __name__ == "__main__":
    main()
