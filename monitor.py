"""
Bully Collectibles new-product notifier.

Checks the store's Shopify products.json, compares it with the products seen
last time (stored in seen.json), and sends a Telegram message for every new
product. Optionally also alerts when a sold-out product comes back in stock.
"""

import html
import json
import os
import sys
import time

import requests

STORE = "https://www.bullycollectibles.com"
STATE_FILE = "seen.json"
NOTIFY_RESTOCKS = os.environ.get("NOTIFY_RESTOCKS", "true").lower() == "true"
MAX_INDIVIDUAL_ALERTS = 15  # above this, send one summary message instead

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
HEADERS = {"User-Agent": "Mozilla/5.0 (personal new-product notifier)"}


def fetch_all_products():
    """Download every product, following pagination."""
    products, page = [], 1
    while True:
        r = requests.get(
            f"{STORE}/products.json",
            params={"limit": 250, "page": page},
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json().get("products", [])
        products.extend(batch)
        if len(batch) < 250:
            break
        page += 1
        time.sleep(1)  # be polite to the store
    return products


def is_available(product):
    return any(v.get("available") for v in product.get("variants", []))


def describe(product):
    """Build a Telegram caption (HTML formatting) for a product."""
    title = html.escape(product.get("title", "Untitled"))
    variants = product.get("variants") or [{}]
    price = variants[0].get("price", "?")
    url = f"{STORE}/products/{product.get('handle', '')}"
    stock = "In stock" if is_available(product) else "Sold out / unavailable"
    return f"<b>{title}</b>\nPrice: {price}\n{stock}\n{url}"


def send_telegram(text, image_url=None):
    base = f"https://api.telegram.org/bot{TOKEN}"
    try:
        if image_url:
            r = requests.post(
                f"{base}/sendPhoto",
                data={"chat_id": CHAT_ID, "photo": image_url,
                      "caption": text, "parse_mode": "HTML"},
                timeout=30,
            )
            if r.ok:
                return
        # Fallback (or no image): plain text message
        requests.post(
            f"{base}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": "false"},
            timeout=30,
        ).raise_for_status()
    finally:
        time.sleep(1.1)  # stay under Telegram's rate limit


def first_image(product):
    images = product.get("images") or []
    return images[0].get("src") if images else None


def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_state(products):
    state = {str(p["id"]): is_available(p) for p in products}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=0, sort_keys=True)


def main():
    if not TOKEN or not CHAT_ID:
        sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first.")

    products = fetch_all_products()
    if not products:
        # Probably a temporary glitch; don't wipe our memory of seen products.
        print("No products returned; skipping this run.")
        return

    state = load_state()

    if state is None:
        save_state(products)
        send_telegram(
            f"✅ Monitoring started for Bully Collectibles.\n"
            f"Tracking {len(products)} existing products. "
            f"You'll get a message whenever a new one appears."
        )
        print(f"First run: saved {len(products)} products.")
        return

    new_items = [p for p in products if str(p["id"]) not in state]
    restocks = []
    if NOTIFY_RESTOCKS:
        restocks = [
            p for p in products
            if str(p["id"]) in state
            and state[str(p["id"])] is False
            and is_available(p)
        ]

    alerts = [("🆕 NEW", p) for p in new_items] + [("🔁 RESTOCK", p) for p in restocks]

    if len(alerts) > MAX_INDIVIDUAL_ALERTS:
        lines = [f"{tag}: {html.escape(p['title'])}" for tag, p in alerts[:40]]
        more = len(alerts) - 40
        if more > 0:
            lines.append(f"...and {more} more")
        send_telegram(f"<b>{len(alerts)} updates at Bully Collectibles</b>\n"
                      + "\n".join(lines) + f"\n{STORE}/collections/all")
    else:
        for tag, p in alerts:
            send_telegram(f"{tag}\n{describe(p)}", first_image(p))

    save_state(products)
    print(f"New: {len(new_items)}, restocked: {len(restocks)}")


if __name__ == "__main__":
    main()
