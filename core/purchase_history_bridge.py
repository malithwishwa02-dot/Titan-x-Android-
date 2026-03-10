"""
Titan V11.3 — Purchase History Bridge
Adapts the v11-release PurchaseHistoryEngine for Android device injection.
Converts browser-oriented purchase artifacts (IndexedDB, localStorage, cookies)
into Android-compatible data (Chrome mobile DBs, SharedPrefs, content providers).

The v11-release engine generates:
  - Purchase records with merchant/amount/status
  - Commerce cookies with aged timestamps
  - Confirmation email artifacts
  - Payment processor trust tokens
  - Autofill CC holder data

This bridge transforms that into:
  - Chrome mobile History entries (purchase confirmation pages)
  - Chrome mobile Cookies (commerce session cookies)
  - Chrome Autofill (CC + address data)
  - Notification history (order confirmations)
  - Email receipt data (for Gmail injection)
"""

import logging
import os
import random
import sys
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.purchase-bridge")

# ═══════════════════════════════════════════════════════════════════════
# IMPORT v11-release PurchaseHistoryEngine (graceful fallback)
# ═══════════════════════════════════════════════════════════════════════

_V11_CORE = os.environ.get("TITAN_V11_CORE", "/root/titan-v11-release/core")
if _V11_CORE not in sys.path:
    sys.path.insert(0, _V11_CORE)

_PURCHASE_ENGINE_OK = False
try:
    from purchase_history_engine import (
        PurchaseHistoryEngine,
        PurchaseHistoryConfig,
        CardHolderData,
        MERCHANT_TEMPLATES,
        EMAIL_SUBJECTS,
    )
    _PURCHASE_ENGINE_OK = True
    logger.info("PurchaseHistoryEngine loaded from v11-release")
except ImportError as e:
    logger.warning(f"PurchaseHistoryEngine not available: {e} — using local fallback")
    MERCHANT_TEMPLATES = {}
    EMAIL_SUBJECTS = {}


# ═══════════════════════════════════════════════════════════════════════
# LOCAL MERCHANT DATA (fallback if v11-release unavailable)
# ═══════════════════════════════════════════════════════════════════════

_FALLBACK_MERCHANTS = {
    "amazon.com": {
        "name": "Amazon.com",
        "items": [
            ("Anker USB-C Hub", 35.99), ("Kindle Paperwhite", 139.99),
            ("AmazonBasics Backpack", 29.99), ("Hydro Flask 32oz", 44.95),
        ],
        "cookie_names": ["session-id", "ubid-main", "session-token", "csm-hit"],
    },
    "walmart.com": {
        "name": "Walmart",
        "items": [
            ("Great Value Paper Towels", 15.97), ("onn. 32\" TV", 98.00),
            ("Ozark Trail Tumbler", 7.97),
        ],
        "cookie_names": ["auth", "cart-item-count", "CRT"],
    },
    "bestbuy.com": {
        "name": "Best Buy",
        "items": [
            ("Insignia 50\" Fire TV", 249.99), ("SanDisk 256GB microSD", 24.99),
            ("JBL Flip 6 Speaker", 99.99),
        ],
        "cookie_names": ["UID", "SID", "CTX"],
    },
    "target.com": {
        "name": "Target",
        "items": [
            ("Threshold Throw Blanket", 25.00), ("Cat & Jack Kids T-Shirt", 8.00),
            ("Room Essentials Desk Lamp", 12.00),
        ],
        "cookie_names": ["visitorId", "TealeafAkaSid"],
    },
    "ebay.com": {
        "name": "eBay",
        "items": [
            ("Refurbished iPhone 14 Pro", 649.00), ("Arduino Starter Kit", 34.99),
        ],
        "cookie_names": ["ebay", "dp1", "nonsession"],
    },
    "nike.com": {
        "name": "Nike",
        "items": [
            ("Air Max 90", 130.00), ("Dri-FIT Running Shirt", 35.00),
        ],
        "cookie_names": ["NIKE_COMMERCE_COUNTRY", "anonymousId"],
    },
}


# ═══════════════════════════════════════════════════════════════════════
# ANDROID PURCHASE HISTORY GENERATOR
# ═══════════════════════════════════════════════════════════════════════

def generate_android_purchase_history(
    persona_name: str,
    persona_email: str,
    country: str = "US",
    age_days: int = 90,
    card_last4: str = "4242",
    card_network: str = "visa",
    purchase_categories: List[str] = None,
    num_purchases: int = 0,
) -> Dict[str, Any]:
    """
    Generate purchase history adapted for Android device injection.

    Returns dict with:
      - chrome_history: URLs for Chrome History DB injection
      - chrome_cookies: Commerce cookies for Chrome Cookies DB
      - notifications: Order notification entries
      - email_receipts: Gmail receipt entries
      - autofill_addresses: Chrome autofill address entries
      - purchase_summary: Stats for trust scoring
    """
    if num_purchases <= 0:
        num_purchases = max(3, age_days // 15)

    rng = random.Random(hashlib.sha256(f"{persona_name}_{age_days}".encode()).hexdigest())

    # Select merchants based on purchase categories or random
    merchants = _select_merchants(purchase_categories, rng)
    now = datetime.now()

    # Generate purchase records
    purchases = []
    for i in range(num_purchases):
        merchant_key = merchants[i % len(merchants)]
        merchant = _get_merchant(merchant_key)

        days_ago = rng.randint(3, age_days)
        purchase_time = now - timedelta(
            days=days_ago,
            hours=rng.randint(9, 22),
            minutes=rng.randint(0, 59),
        )

        item_name, item_price = rng.choice(merchant["items"])
        qty = rng.choices([1, 2, 3], weights=[0.7, 0.2, 0.1])[0]
        amount = round(item_price * qty, 2)

        order_id = _generate_order_id(merchant_key, rng)

        # Delivery 2-7 days after purchase
        delivery_days = rng.randint(2, 7)
        delivered = days_ago > delivery_days
        status = "Delivered" if delivered else "Shipped" if days_ago > 1 else "Confirmed"

        purchases.append({
            "merchant": merchant["name"],
            "merchant_domain": merchant_key,
            "order_id": order_id,
            "amount": amount,
            "currency": {"US": "USD", "GB": "GBP", "DE": "EUR", "FR": "EUR",
                         "CA": "CAD", "AU": "AUD", "JP": "JPY"}.get(country, "USD"),
            "item": item_name,
            "qty": qty,
            "status": status,
            "purchase_time": purchase_time.isoformat(),
            "purchase_epoch": int(purchase_time.timestamp()),
            "card_last4": card_last4,
            "card_network": card_network,
        })

    # ── Build Chrome History entries ───────────────────────────────
    chrome_history = []
    for p in purchases:
        # Order confirmation page
        chrome_history.append({
            "url": f"https://www.{p['merchant_domain']}/order/{p['order_id']}",
            "title": f"Order {p['order_id']} - {p['merchant']}",
            "visit_time": p["purchase_epoch"],
            "visit_count": rng.randint(1, 3),
        })
        # Product page visit (before purchase)
        chrome_history.append({
            "url": f"https://www.{p['merchant_domain']}/product/{secrets.token_hex(6)}",
            "title": f"{p['item']} - {p['merchant']}",
            "visit_time": p["purchase_epoch"] - rng.randint(300, 7200),
            "visit_count": rng.randint(1, 5),
        })
        # Cart page
        chrome_history.append({
            "url": f"https://www.{p['merchant_domain']}/cart",
            "title": f"Shopping Cart - {p['merchant']}",
            "visit_time": p["purchase_epoch"] - rng.randint(60, 600),
            "visit_count": rng.randint(1, 2),
        })

    # ── Build Chrome Cookies ──────────────────────────────────────
    chrome_cookies = []
    seen_domains = set()
    for p in purchases:
        domain = p["merchant_domain"]
        if domain in seen_domains:
            continue
        seen_domains.add(domain)

        merchant = _get_merchant(domain)
        for cookie_name in merchant.get("cookie_names", []):
            creation_epoch = p["purchase_epoch"] - rng.randint(0, age_days * 86400 // 2)
            chrome_cookies.append({
                "host": f".{domain}",
                "name": cookie_name,
                "value": secrets.token_hex(16),
                "path": "/",
                "creation_utc": creation_epoch * 1000000 + 11644473600000000,
                "expires_utc": int((now + timedelta(days=rng.randint(90, 365))).timestamp()) * 1000000 + 11644473600000000,
                "last_access_utc": int((now - timedelta(days=rng.randint(0, 7))).timestamp()) * 1000000 + 11644473600000000,
                "is_secure": 1,
                "is_httponly": 1 if cookie_name in ("session-id", "auth", "UID") else 0,
                "samesite": 0,
            })

    # ── Build Notification entries ────────────────────────────────
    notifications = []
    for p in purchases:
        notifications.append({
            "package": f"com.android.chrome",
            "title": f"Order Confirmation - {p['merchant']}",
            "text": f"Order #{p['order_id']} for ${p['amount']:.2f} confirmed",
            "timestamp": p["purchase_epoch"] * 1000,
            "category": "email",
        })
        if p["status"] == "Delivered":
            notifications.append({
                "package": "com.android.chrome",
                "title": f"Delivery Update - {p['merchant']}",
                "text": f"Your order #{p['order_id']} has been delivered",
                "timestamp": (p["purchase_epoch"] + rng.randint(172800, 604800)) * 1000,
                "category": "email",
            })

    # ── Build Email Receipt entries ───────────────────────────────
    email_receipts = []
    for p in purchases:
        subject_template = EMAIL_SUBJECTS.get(
            p["merchant_domain"],
            f"Your {p['merchant']} order #{{order_id}} is confirmed"
        ) if EMAIL_SUBJECTS else f"Your {p['merchant']} order #{{order_id}} is confirmed"

        email_receipts.append({
            "from": f"noreply@{p['merchant_domain']}",
            "to": persona_email,
            "subject": subject_template.format(
                order_id=p["order_id"],
                status=p["status"].lower(),
            ),
            "merchant": p["merchant"],
            "amount": f"${p['amount']:.2f}",
            "timestamp": p["purchase_epoch"],
            "read": True,
        })

    # ── Summary ───────────────────────────────────────────────────
    total_spent = sum(p["amount"] for p in purchases)
    unique_merchants = list(set(p["merchant"] for p in purchases))

    return {
        "purchases": purchases,
        "chrome_history": chrome_history,
        "chrome_cookies": chrome_cookies,
        "notifications": notifications,
        "email_receipts": email_receipts,
        "purchase_summary": {
            "total_purchases": len(purchases),
            "total_spent": round(total_spent, 2),
            "unique_merchants": len(unique_merchants),
            "merchants": unique_merchants,
            "chrome_history_entries": len(chrome_history),
            "chrome_cookies": len(chrome_cookies),
            "notifications": len(notifications),
            "email_receipts": len(email_receipts),
        },
    }


def _select_merchants(categories: List[str] = None, rng: random.Random = None) -> List[str]:
    """Select merchant domains based on purchase categories."""
    if not rng:
        rng = random.Random()

    available = list(MERCHANT_TEMPLATES.keys()) if MERCHANT_TEMPLATES else list(_FALLBACK_MERCHANTS.keys())

    if categories:
        # Category-to-merchant mapping
        cat_map = {
            "electronics": ["amazon.com", "bestbuy.com", "newegg.com"],
            "clothing": ["fashionnova.com", "nike.com", "zara.com", "asos.com", "shein.com"],
            "groceries": ["walmart.com", "target.com", "instacart.com"],
            "gaming": ["steampowered.com", "g2a.com", "eneba.com"],
            "food_delivery": ["doordash.com", "ubereats.com"],
            "fast_food": ["doordash.com", "ubereats.com"],
            "streaming_subscriptions": ["spotify.com", "netflix.com"],
            "home_improvement": ["amazon.com", "walmart.com", "wayfair.com"],
        }
        selected = set()
        for cat in categories:
            for key_part in cat.lower().split("_"):
                for cat_key, merchants in cat_map.items():
                    if key_part in cat_key:
                        for m in merchants:
                            if m in available:
                                selected.add(m)
        if selected:
            return list(selected)

    # Default: pick 4-6 random merchants
    return rng.sample(available, min(rng.randint(4, 6), len(available)))


def _get_merchant(domain: str) -> dict:
    """Get merchant data from v11-release or fallback."""
    if MERCHANT_TEMPLATES and domain in MERCHANT_TEMPLATES:
        t = MERCHANT_TEMPLATES[domain]
        return {
            "name": t["name"],
            "items": [(item["name"], item["price"]) for item in t["items_pool"]],
            "cookie_names": t.get("cookie_names", []),
        }
    if domain in _FALLBACK_MERCHANTS:
        return _FALLBACK_MERCHANTS[domain]
    return {
        "name": domain.split(".")[0].title(),
        "items": [("Product", random.uniform(10, 100))],
        "cookie_names": ["session", "cart"],
    }


def _generate_order_id(merchant_domain: str, rng: random.Random) -> str:
    """Generate realistic order ID for a merchant."""
    prefix_map = {
        "amazon.com": "114", "walmart.com": "WM", "bestbuy.com": "BBY01",
        "target.com": "TGT", "ebay.com": "EB", "nike.com": "NK",
        "steampowered.com": "ST", "doordash.com": "DD",
    }
    prefix = prefix_map.get(merchant_domain, "ORD")
    seg1 = rng.randint(1000000, 9999999)
    seg2 = rng.randint(1000, 9999)
    return f"{prefix}-{seg1}-{seg2}"


def get_available_merchants() -> List[dict]:
    """Return list of available merchants for API/UI."""
    if MERCHANT_TEMPLATES:
        return [{"domain": k, "name": v["name"]} for k, v in MERCHANT_TEMPLATES.items()]
    return [{"domain": k, "name": v["name"]} for k, v in _FALLBACK_MERCHANTS.items()]
