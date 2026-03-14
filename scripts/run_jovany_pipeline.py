#!/usr/bin/env python3
"""
Titan V11.3 — Complete Jovany Owens Pipeline Script
Performs: Google account injection, profile forge+inject, CC injection, payment history simulation.
All programmatic — no Play Store or GMS apps needed.
"""
import json
import logging
import os
import sys
import time

# Add paths
sys.path.insert(0, "/root/titan-v11.3-device/core")
sys.path.insert(0, "/root/titan-v11.3-device/server")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("titan.pipeline")

ADB_TARGET = "127.0.0.1:5555"

# ── Persona ──
PERSONA = {
    "name": "Jovany Owens",
    "email": "ranpatidewage6@gmail.com",
    "password": "Chilaw@123",
    "phone": "(707)836-1915",
    "country": "US",
    "age_days": 600,
}

CC_DATA = {
    "number": "4638512320340405",
    "exp_month": 8,
    "exp_year": 2029,
    "cvv": "051",
    "cardholder": "Jovany Owens",
}


def step(msg):
    logger.info(f"\n{'='*60}\n  {msg}\n{'='*60}")


def main():
    step("STEP 1: Verify device is alive")
    import subprocess
    r = subprocess.run(f"adb -s {ADB_TARGET} shell getprop sys.boot_completed",
                       shell=True, capture_output=True, text=True, timeout=10)
    if r.stdout.strip() != "1":
        logger.error(f"Device not booted! Got: '{r.stdout.strip()}'")
        sys.exit(1)
    logger.info("Device is booted and ADB connected")

    # Get device model
    r2 = subprocess.run(f"adb -s {ADB_TARGET} shell getprop ro.product.model",
                        shell=True, capture_output=True, text=True, timeout=10)
    logger.info(f"Device model: {r2.stdout.strip()}")

    step("STEP 2: Forge 600-day Jovany Owens profile")
    from android_profile_forge import AndroidProfileForge
    forge = AndroidProfileForge()
    profile = forge.forge_profile(
        persona_name=PERSONA["name"],
        persona_email=PERSONA["email"],
        persona_phone=PERSONA["phone"],
        country=PERSONA["country"],
        age_days=PERSONA["age_days"],
        archetype="professional",
    )
    profile_id = profile.get("uuid", profile.get("id", "unknown"))
    logger.info(f"Profile forged: {profile_id}")
    logger.info(f"  Contacts: {len(profile.get('contacts', []))}")
    logger.info(f"  Call logs: {len(profile.get('call_logs', []))}")
    logger.info(f"  SMS: {len(profile.get('sms', []))}")
    logger.info(f"  Cookies: {len(profile.get('cookies', []))}")
    logger.info(f"  History: {len(profile.get('history', []))}")
    logger.info(f"  Gallery: {len(profile.get('gallery_paths', []))}")

    # Save profile
    os.makedirs("/opt/titan/data/profiles", exist_ok=True)
    with open(f"/opt/titan/data/profiles/{profile_id}.json", "w") as f:
        json.dump(profile, f, indent=2, default=str)
    logger.info(f"  Profile saved to /opt/titan/data/profiles/{profile_id}.json")

    step("STEP 3: Inject full profile + CC into device")
    from profile_injector import ProfileInjector
    injector = ProfileInjector(adb_target=ADB_TARGET)
    result = injector.inject_full_profile(profile, card_data=CC_DATA)

    res = result.to_dict()
    logger.info(f"\n  Injection Results:")
    logger.info(f"  Profile ID: {res['profile_id']}")
    logger.info(f"  Cookies: {res['cookies']}")
    logger.info(f"  History: {res['history']}")
    logger.info(f"  Contacts: {res['contacts']}")
    logger.info(f"  Call logs: {res['call_logs']}")
    logger.info(f"  SMS: {res['sms']}")
    logger.info(f"  Photos: {res['photos']}")
    logger.info(f"  Google Account: {'✓' if res['google_account'] else '✗'}")
    logger.info(f"  Wallet/CC: {'✓' if res['wallet'] else '✗'}")
    logger.info(f"  App Data: {'✓' if res['app_data'] else '✗'}")
    logger.info(f"  Play Purchases: {'✓' if res['play_purchases'] else '✗'}")
    logger.info(f"  Trust Score: {res['trust_score']}/100")
    if res['errors']:
        logger.warning(f"  Errors ({len(res['errors'])}):")
        for e in res['errors'][:10]:
            logger.warning(f"    - {e}")

    step("STEP 4: Apply stealth patch")
    from anomaly_patcher import AnomalyPatcher
    patcher = AnomalyPatcher(adb_target=ADB_TARGET)
    patch_result = patcher.full_patch(
        preset="samsung_s25_ultra",
        carrier="att_us",
        location="la",
    )
    logger.info(f"  Stealth: {patch_result.get('score', '?')}% ({patch_result.get('passed','?')}/{patch_result.get('total','?')})")

    step("STEP 5: Inject Samsung Pay data")
    # Create Samsung Pay directories and databases
    def adb_sh(cmd):
        subprocess.run(f"adb -s {ADB_TARGET} shell {cmd}", shell=True,
                       capture_output=True, text=True, timeout=15)

    adb_sh("mkdir -p /data/data/com.samsung.android.spay/databases")
    adb_sh("mkdir -p /data/data/com.samsung.android.spay/shared_prefs")

    # Create Samsung Pay shared_prefs indicating card is registered
    spay_prefs = f"""<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="registered_card_last4">{CC_DATA['number'][-4:]}</string>
    <string name="card_network">visa</string>
    <string name="card_holder">{CC_DATA['cardholder']}</string>
    <int name="card_exp_month" value="{CC_DATA['exp_month']}" />
    <int name="card_exp_year" value="{CC_DATA['exp_year']}" />
    <boolean name="card_registered" value="true" />
    <boolean name="nfc_enabled" value="true" />
    <string name="default_payment">samsung_pay</string>
    <long name="card_added_timestamp" value="{int(time.time()*1000) - 86400000*30}" />
</map>"""

    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
        f.write(spay_prefs)
        spay_tmp = f.name

    subprocess.run(f"adb -s {ADB_TARGET} push {spay_tmp} /data/data/com.samsung.android.spay/shared_prefs/spay_card_prefs.xml",
                   shell=True, capture_output=True, timeout=15)
    adb_sh("chmod 660 /data/data/com.samsung.android.spay/shared_prefs/spay_card_prefs.xml")
    os.unlink(spay_tmp)
    logger.info("  Samsung Pay card data injected (Visa ****0405)")

    step("STEP 6: Payment history simulation")
    # Create payment transaction history in Google Pay wallet DB
    import sqlite3
    wallet_db_path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(wallet_db_path)
    c = conn.cursor()

    # Create tap-and-pay transaction history table
    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        _id INTEGER PRIMARY KEY,
        merchant_name TEXT,
        amount_cents INTEGER,
        currency TEXT DEFAULT 'USD',
        card_last4 TEXT,
        card_network TEXT DEFAULT 'visa',
        timestamp INTEGER,
        status TEXT DEFAULT 'completed',
        merchant_category TEXT,
        location TEXT
    )""")

    # Generate realistic payment history over the last 600 days
    import random
    merchants = [
        ("Starbucks", "coffee_shop", 495), ("Walmart", "grocery", 4523),
        ("Amazon", "online_retail", 2999), ("Target", "retail", 3456),
        ("Shell Gas Station", "gas_station", 4500), ("McDonald's", "fast_food", 899),
        ("Uber", "rideshare", 1845), ("Netflix", "subscription", 1599),
        ("Spotify", "subscription", 999), ("Apple Store", "electronics", 9999),
        ("Whole Foods", "grocery", 6789), ("CVS Pharmacy", "pharmacy", 2345),
        ("Home Depot", "home_improvement", 8756), ("Chipotle", "fast_food", 1245),
        ("Costco", "wholesale", 15678), ("Trader Joe's", "grocery", 5432),
        ("Lyft", "rideshare", 2156), ("DoorDash", "food_delivery", 3499),
        ("Best Buy", "electronics", 19999), ("Walgreens", "pharmacy", 1567),
    ]
    locations = ["Los Angeles, CA", "Santa Monica, CA", "Beverly Hills, CA",
                 "Pasadena, CA", "Burbank, CA", "Long Beach, CA"]

    now = int(time.time() * 1000)
    transactions = []
    for i in range(85):  # ~85 transactions over 600 days
        merchant, category, base_amount = random.choice(merchants)
        amount = base_amount + random.randint(-200, 500)
        ts = now - random.randint(86400000, 600 * 86400000)  # Random time in last 600 days
        loc = random.choice(locations)
        transactions.append((merchant, amount, "USD", CC_DATA["number"][-4:], "visa",
                            ts, "completed", category, loc))

    transactions.sort(key=lambda x: x[5])  # Sort by timestamp
    c.executemany("INSERT INTO transactions (merchant_name, amount_cents, currency, card_last4, card_network, timestamp, status, merchant_category, location) VALUES (?,?,?,?,?,?,?,?,?)",
                  transactions)

    # Create token table (Google Pay tokenized card)
    c.execute("""CREATE TABLE IF NOT EXISTS tokens (
        _id INTEGER PRIMARY KEY,
        token_id TEXT,
        card_last4 TEXT,
        card_network TEXT,
        issuer TEXT DEFAULT 'Chase',
        status TEXT DEFAULT 'active',
        created_at INTEGER,
        dpan_last4 TEXT
    )""")
    c.execute("INSERT INTO tokens (token_id, card_last4, card_network, issuer, status, created_at, dpan_last4) VALUES (?,?,?,?,?,?,?)",
              (f"tok_{random.randint(100000,999999)}", CC_DATA["number"][-4:], "visa",
               "Chase", "active", now - 30*86400000, f"{random.randint(1000,9999)}"))

    conn.commit()
    conn.close()

    # Push wallet DB to device
    subprocess.run(f"adb -s {ADB_TARGET} push {wallet_db_path} /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db",
                   shell=True, capture_output=True, timeout=15)
    adb_sh("chmod 660 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db")
    os.unlink(wallet_db_path)

    total_spent = sum(t[1] for t in transactions) / 100
    logger.info(f"  Payment history: {len(transactions)} transactions")
    logger.info(f"  Total spent: ${total_spent:.2f}")
    logger.info(f"  Card: Visa ****{CC_DATA['number'][-4:]}")
    logger.info(f"  Merchants: {len(set(t[0] for t in transactions))} unique")

    step("STEP 7: Final verification")
    # Verify data on device
    checks = {
        "Chrome cookies": "ls /data/data/com.android.chrome/app_chrome/Default/Cookies 2>/dev/null",
        "Chrome history": "ls /data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null",
        "GMS shared_prefs": "ls /data/data/com.google.android.gms/shared_prefs/ 2>/dev/null",
        "Wallet DB": "ls /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 2>/dev/null",
        "Samsung Pay prefs": "ls /data/data/com.samsung.android.spay/shared_prefs/spay_card_prefs.xml 2>/dev/null",
        "Contacts": "content query --uri content://com.android.contacts/raw_contacts --projection _id 2>/dev/null",
        "Call logs": "content query --uri content://call_log/calls --projection _id 2>/dev/null",
        "SMS": "content query --uri content://sms --projection _id 2>/dev/null",
        "Gallery": "ls /sdcard/DCIM/Camera/ 2>/dev/null",
    }

    passed = 0
    for name, cmd in checks.items():
        r = subprocess.run(f"adb -s {ADB_TARGET} shell \"{cmd}\"",
                          shell=True, capture_output=True, text=True, timeout=15)
        ok = bool(r.stdout.strip()) and r.returncode == 0
        status = "✓" if ok else "✗"
        if ok:
            passed += 1
        logger.info(f"  {status} {name}")

    logger.info(f"\n  Verification: {passed}/{len(checks)} checks passed")
    logger.info(f"  Trust Score: {res['trust_score']}/100")

    step("PIPELINE COMPLETE")
    logger.info(f"""
  Persona: {PERSONA['name']} ({PERSONA['email']})
  Device: Samsung S25 Ultra (SM-S938U)
  Profile: {profile_id}
  Age: {PERSONA['age_days']} days
  CC: Visa ****{CC_DATA['number'][-4:]} (exp {CC_DATA['exp_month']}/{CC_DATA['exp_year']})
  Transactions: {len(transactions)} payment records
  Trust Score: {res['trust_score']}/100
""")


if __name__ == "__main__":
    main()
