import json, os, re, sys, time
from curl_cffi import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

CURRENCY = "Gs."


def fix_url(base, src):
    if not src or src.startswith("data:"):
        return None
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("http"):
        return src
    return urljoin(base, src)


def parse_guarani(text):
    if not text:
        return None
    cleaned = re.sub(r"[₲Gs\.\s]", "", text, flags=re.I)
    cleaned = cleaned.replace(",", ".")
    m = re.search(r"\d[\d\.]*", cleaned)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


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
            price_el = card.select_one("span.price span.amount") or card.select_one("span.price")
            price_text = price_el.get_text(strip=True) if price_el else ""
            price = parse_guarani(price_text) or 0.0
            img_el = card.select_one("img.wp-post-image") or card.select_one("img")
            img = fix_url(SUPERMAS_BASE, img_el.get("data-src") or img_el.get("src")) if img_el else None
            link_el = card.select_one("a.woocommerce-LoopProduct-link")
            purl = fix_url(SUPERMAS_BASE, link_el.get("href")) if link_el else None
            if name and price > 0:
                all_products.append({
                    "site": "Supermas", "site_id": "supermas",
                    "name": name, "price": price, "currency": CURRENCY,
                    "image": img, "url": purl, "measure": "",
                })
        page += 1
        url = SUPERMAS_PAGE.format(page)
    print(f"Supermas: {len(all_products)} productos")
    return all_products


# ---------------- Stock ----------------
STOCK_BASE = "https://www.stock.com.py"
STOCK_CAT_LIMIT = 45


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
    return cats[:STOCK_CAT_LIMIT]


def scrape_stock():
    session = get_session()
    cats = get_stock_categories(session)
    print(f"Stock: {len(cats)} categorias (limit {STOCK_CAT_LIMIT})")
    all_products = []
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
                price_el = card.select_one("div.prices")
                price_text = price_el.get_text(strip=True) if price_el else ""
                price = parse_guarani(price_text) or 0.0
                img_el = card.select_one("div.picture img") or card.select_one("img")
                img = fix_url(STOCK_BASE, img_el.get("src") or img_el.get("data-src")) if img_el else None
                link_el = name_el or card.select_one("a.picture-link")
                purl = fix_url(STOCK_BASE, link_el.get("href")) if link_el else None
                if name and price > 0:
                    all_products.append({
                        "site": "Stock", "site_id": "stock",
                        "name": name, "price": price, "currency": CURRENCY,
                        "image": img, "url": purl, "measure": "",
                    })
            page += 1
        print(f"  [{i}/{len(cats)}] OK")
    print(f"Stock: {len(all_products)} productos")
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
