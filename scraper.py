import json, os, re, sys, time
from curl_cffi import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

CURRENCY = "Gs."

# Marcas conocidas de supermercados PY (buscadas en el nombre del producto).
# Se ordena de mayor a menor longitud para evitar matches parciales.
KNOWN_BRANDS = [
    "JOHNNIE WALKER", "ROBINSON CRUSOE", "LA CAMPAGNOLA", "CAMPESINO", "LACTOLANDA",
    "DOÑA ANGELA", "LA PRADERA", "NATURALE", "NATURAL CARE", "VAN CAMPS", "VITALIPETS",
    "OM LUCKY", "PLUSBELLE", "CAVALLARO", "CITROMAX", "COLGATE", "NIVEA", "NOSOTRAS",
    "HUGGIES", "SIMOND", "EXCELLENT", "ROBINSON", "CHIVAS REGAL", "OLICA", "BIANCA",
    "NATURA", "TREBOL", "COCINERO", "ROCIO", "BORGES", "DAYO", "DOVE", "OK", "MIRASOL",
    "ALCAZAR", "FORATTINI", "KUKA", "BES", "PRIMICIA", "LESTELLO", "CAREY", "DEL MAR",
    "FRANZ", "AJAX", "POETT", "SPRITE", "FRISCO", "INDEMAR", "JOSEFINA", "LA FORTUNA",
    "LU-FIT", "DUL-CESAR", "SUPERMA",
]


def fix_url(base, src):
    if not src or src.startswith("data:"):
        return None
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("http"):
        return src
    return urljoin(base, src)


def parse_guarani(text):
    """Parsea un precio en guaraníes desde texto. Toma el PRIMER número con
    separador de miles válido. Evita concatenar varios precios (precio tachado
    + actual + sugerencias) que rompía el parser anterior."""
    if not text:
        return None
    # Quitar símbolos de moneda y espacios, pero conservar puntos y comas.
    cleaned = re.sub(r"[₲Gs\s]", "", text, flags=re.I)
    # Buscar patrones tipo 28.700 o 1.200 o 350 (hasta 2 grupos de 3 dígitos)
    # El primer match suele ser el precio actual.
    m = re.search(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d{1,6}(?:,\d+)?", cleaned)
    if not m:
        return None
    num = m.group(0).replace(".", "").replace(",", ".")
    try:
        val = float(num)
    except ValueError:
        return None
    # Sanity check: precios realistas entre 100 y 5.000.000 Gs.
    if 100 <= val <= 5_000_000:
        return val
    return None


# Unidades de medida reales. Se busca "NUMERO + UNIDAD"; si no hay número,
# solo se aceptan unidades a granel (KG, G, L, UN).
UNIT = r"(ML|CC|LT|LTS|L|GR|G|KG|UNID|UN|UND|LITRO|LITROS)"
MEASURE_RE = re.compile(r"(\d[\d.,]*)\s*(x\s*)?(" + UNIT + r")\b", re.I)
BULK_RE = re.compile(r"\b(x\s*)?(KG|G|L|UN)\b", re.I)


def extract_measure(name):
    """Extrae la unidad de medida del nombre del producto.
    Devuelve '500 ML', '1.5 LT', '250 GR', o a granel 'KG', 'UN'."""
    if not name:
        return ""
    m = MEASURE_RE.search(name)
    if m:
        qty = m.group(1)
        unit = m.group(3).upper()
        unit_map = {
            "LT": "LT", "L": "LT", "ML": "ML", "CC": "CC",
            "KG": "KG", "G": "GR", "GR": "GR",
            "UNID": "UN", "UN": "UN", "UND": "UN",
        }
        unit = unit_map.get(unit, unit)
        return f"{qty} {unit}".strip()
    # Medida a granel sin número (ej. "PEPINO KG", "CHORIZO FRANZ KG")
    b = BULK_RE.search(name)
    if b:
        u = b.group(2).upper()
        u = {"LT": "LT", "L": "LT", "G": "GR", "KG": "KG", "UN": "UN"}.get(u, u)
        return u
    return ""


def extract_brand(name):
    """Extrae la marca buscándola en el nombre (case-insensitive)."""
    if not name:
        return ""
    up = name.upper()
    # Quitar acentos para comparar
    upn = re.sub(r"[ÁÀÄÂ]", "A", up)
    upn = re.sub(r"[ÉÈËÊ]", "E", upn)
    upn = re.sub(r"[ÍÌÏÎ]", "I", upn)
    upn = re.sub(r"[ÓÒÖÔ]", "O", upn)
    upn = re.sub(r"[ÚÙÜÛ]", "U", upn)
    for b in KNOWN_BRANDS:
        bn = re.sub(r"[ÁÀÄÂ]", "A", b)
        bn = re.sub(r"[ÉÈËÊ]", "E", bn)
        bn = re.sub(r"[ÍÌÏÎ]", "I", bn)
        bn = re.sub(r"[ÓÒÖÔ]", "O", bn)
        bn = re.sub(r"[ÚÙÜÛ]", "U", bn)
        if bn in upn:
            return b.title()
    return ""


def get_session():
    return requests.Session(impersonate="chrome120")


def fetch(session, url, tries=3):
    for i in range(tries):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        time.sleep(2)
    return None


# ---------------- Supermas ----------------
SUPERMAS_BASE = "https://www.supermas.com.py"
SUPERMAS_LIST = SUPERMAS_BASE + "/productos"
SUPERMAS_PAGE = SUPERMAS_BASE + "/productos.{}"


def scrape_supermas():
    session = get_session()
    all_products = []
    seen_urls = set()
    page = 1
    url = SUPERMAS_LIST
    while page <= 250:
        r = fetch(session, url)
        if not r:
            page += 1
            url = SUPERMAS_PAGE.format(page)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.product")
        if not cards:
            break
        for card in cards:
            name_el = card.select_one("h2.woocommerce-loop-product__title")
            name = name_el.get_text(strip=True) if name_el else ""
            # El precio puede estar en varios span.amount; tomar el PRIMERO
            # con texto no vacío dentro de span.price (evita el <ins> vacío).
            price = 0.0
            price_box = card.select_one("span.price")
            if price_box:
                for amt in price_box.select("span.amount"):
                    ptxt = amt.get_text(strip=True)
                    p = parse_guarani(ptxt)
                    if p:
                        price = p
                        break
                if price == 0.0:
                    price = parse_guarani(price_box.get_text()) or 0.0
            img_el = card.select_one("img.wp-post-image") or card.select_one("img")
            img = fix_url(SUPERMAS_BASE, img_el.get("data-src") or img_el.get("src")) if img_el else None
            link_el = card.select_one("a.woocommerce-LoopProduct-link")
            purl = fix_url(SUPERMAS_BASE, link_el.get("href")) if link_el else None
            if name and price > 0 and purl and purl not in seen_urls:
                seen_urls.add(purl)
                all_products.append({
                    "site": "Supermas", "site_id": "supermas",
                    "name": name, "price": price, "currency": CURRENCY,
                    "image": img, "url": purl,
                    "brand": extract_brand(name),
                    "measure": extract_measure(name),
                })
        page += 1
        url = SUPERMAS_PAGE.format(page)
    print(f"Supermas: {len(all_products)} productos (sin duplicados)")
    return all_products


# ---------------- Stock ----------------
STOCK_BASE = "https://www.stock.com.py"


def get_stock_categories(session):
    r = fetch(session, STOCK_BASE + "/")
    cats = []
    if r:
        soup = BeautifulSoup(r.text, "html.parser")
        seen = set()
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if "/category/" in h:
                full = h if h.startswith("http") else urljoin(STOCK_BASE, h)
                if full not in seen:
                    seen.add(full)
                    cats.append(full)
    return cats


def scrape_stock():
    session = get_session()
    cats = get_stock_categories(session)
    print(f"Stock: {len(cats)} categorias (TODAS)", flush=True)
    all_products = []
    seen_urls = set()
    for i, c in enumerate(cats, 1):
        page = 1
        while page <= 100:
            url = c if page == 1 else f"{c}?pageindex={page}"
            r = fetch(session, url)
            if not r:
                break
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("div.product-item")
            if not cards:
                break
            for card in cards:
                name_el = card.select_one("h2.product-title a.product-title-link")
                name = name_el.get_text(strip=True) if name_el else ""
                # Tomar SOLO el primer precio válido de la tarjeta (el actual).
                price = None
                price_el = card.select_one("div.prices") or card.select_one("span.price-label")
                if price_el:
                    # Recorrer spans de precio y quedarse con el primero válido.
                    spans = price_el.select("span, strong, div")
                    if not spans:
                        spans = [price_el]
                    for sp in spans:
                        p = parse_guarani(sp.get_text())
                        if p:
                            price = p
                            break
                    if price is None:
                        price = parse_guarani(price_el.get_text())
                price = price or 0.0
                img_el = card.select_one("div.picture img") or card.select_one("img")
                img = fix_url(STOCK_BASE, img_el.get("src") or img_el.get("data-src")) if img_el else None
                link_el = name_el or card.select_one("a.picture-link")
                purl = fix_url(STOCK_BASE, link_el.get("href")) if link_el else None
                if name and 0 < price <= 5000000 and purl and purl not in seen_urls:
                    seen_urls.add(purl)
                    all_products.append({
                        "site": "Stock", "site_id": "stock",
                        "name": name, "price": price, "currency": CURRENCY,
                        "image": img, "url": purl,
                        "brand": extract_brand(name),
                        "measure": extract_measure(name),
                    })
            page += 1
        time.sleep(0.3)
        print(f"  [{i}/{len(cats)}] OK", flush=True)
    print(f"Stock: {len(all_products)} productos (sin duplicados)", flush=True)
    return all_products


def main():
    os.makedirs("data", exist_ok=True)
    products = []
    products += scrape_supermas()
    products += scrape_stock()
    with open("data/products.json", "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    print(f"\nTOTAL: {len(products)} productos guardados.")


if __name__ == "__main__":
    main()
