#!/usr/bin/env python3
"""
E2E Test: Forge 90-day profile via API → Inject → Wallet probe → Gap report.
Tests the full console workflow as if a user clicked through every tab.
"""
import json, logging, os, subprocess, sys, tempfile, time, sqlite3
import urllib.request, urllib.error

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('e2e')

API = "http://127.0.0.1:8080"
ADB_TARGET = "127.0.0.1:5555"
DEVICE_ID = "dev-us1"

def api_get(path, timeout=15):
    try:
        req = urllib.request.Request(API + path)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

def api_post(path, data=None, timeout=120):
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(API + path, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

def adb_shell(cmd, timeout=15):
    try:
        r = subprocess.run(["adb", "-s", ADB_TARGET, "shell", cmd],
                          capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except:
        return ""


log.info("╔═══════════════════════════════════════════════════════════════╗")
log.info("║  E2E TEST: Forge 90-Day Profile → Inject → Wallet Probe    ║")
log.info("╚═══════════════════════════════════════════════════════════════╝")

# ═══════════════════════════════════════════════════════════════════
# STEP 1: Forge 90-day profile via /api/genesis/create
# ═══════════════════════════════════════════════════════════════════
log.info("\n═══ STEP 1: Forge 90-day profile ═══")
resp, code = api_post("/api/genesis/create", {
    "name": "Elena Marchetti",
    "email": "elena.marchetti.test@gmail.com",
    "phone": "+12125557890",
    "country": "US",
    "archetype": "professional",
    "age_days": 90,
    "carrier": "tmobile_us",
    "location": "nyc",
    "device_model": "samsung_s25_ultra",
})
assert code == 200, f"Forge failed: {resp}"
profile_id = resp["profile_id"]
stats = resp.get("stats", {})
log.info(f"  Profile ID: {profile_id}")
log.info(f"  Stats: {json.dumps(stats, indent=2)}")

# Verify profile saved
resp2, _ = api_get(f"/api/genesis/profiles/{profile_id}")
assert "id" in resp2, "Profile not persisted"
log.info(f"  Profile persisted: OK")

# ═══════════════════════════════════════════════════════════════════
# STEP 2: Inject profile + CC via /api/genesis/inject (120s timeout)
# ═══════════════════════════════════════════════════════════════════
log.info("\n═══ STEP 2: Inject profile + CC into device ═══")
resp, code = api_post(f"/api/genesis/inject/{DEVICE_ID}", {
    "profile_id": profile_id,
    "cc_number": "5425233430109903",
    "cc_exp_month": 4,
    "cc_exp_year": 2028,
    "cc_cvv": "382",
    "cc_cardholder": "Elena Marchetti",
}, timeout=120)

if code == 200:
    log.info(f"  Inject status: {resp.get('status')}")
    log.info(f"  Trust score: {resp.get('trust_score')}")
    result = resp.get("result", {})
    log.info(f"  Wallet OK: {result.get('wallet_ok')}")
    log.info(f"  Google Account OK: {result.get('google_account_ok')}")
    for e in result.get("errors", []):
        log.warning(f"  Error: {e}")
else:
    log.warning(f"  Inject API returned {code} — may have timed out")
    log.warning(f"  Response: {json.dumps(resp)[:200]}")

# ═══════════════════════════════════════════════════════════════════
# STEP 3: Trust Score via API
# ═══════════════════════════════════════════════════════════════════
log.info("\n═══ STEP 3: Trust Score ═══")
ts_resp, _ = api_get(f"/api/genesis/trust-score/{DEVICE_ID}", timeout=30)
trust = ts_resp.get("trust_score", 0)
grade = ts_resp.get("grade", "?")
log.info(f"  Trust Score: {trust}/100 ({grade})")
for k, v in ts_resp.get("checks", {}).items():
    present = v.get("present", v.get("count", "?"))
    weight = v.get("weight", "?")
    got = weight if (present is True or (isinstance(present, int) and present >= 1)) else 0
    log.info(f"    {'✓' if got else '✗'} {k}: {present} (weight: {weight})")

# ═══════════════════════════════════════════════════════════════════
# STEP 4: Full Wallet Probe — check every target with correct paths
# ═══════════════════════════════════════════════════════════════════
log.info("\n═══ STEP 4: Full Wallet Probe ═══")
gaps = []

# 4a. Google Pay tapandpay.db — tokens + token_metadata
log.info("[4a] Google Pay tapandpay.db")
token_count = adb_shell("sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db \"SELECT COUNT(*) FROM tokens\" 2>/dev/null")
tc = int(token_count) if token_count.isdigit() else 0
if tc > 0:
    card_info = adb_shell("sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db \"SELECT card_description, issuer_name, is_default FROM tokens\"")
    log.info(f"  ✓ Tokens: {tc} ({card_info})")
else:
    gaps.append("google_pay: no tokens in tapandpay.db")
    log.warning("  ✗ No tokens")

# token_metadata compat view
tm = adb_shell("sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db \"SELECT COUNT(*) FROM token_metadata\" 2>/dev/null")
tmc = int(tm) if tm.isdigit() else 0
if tmc > 0:
    log.info(f"  ✓ token_metadata view: {tmc}")
else:
    gaps.append("google_pay: token_metadata view missing")

# 4b. Google Pay SharedPrefs
log.info("[4b] Google Pay SharedPrefs")
ds = adb_shell("cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/default_settings.xml 2>/dev/null")
for check, label in [("wallet_setup_complete", "wallet_setup"), ("nfc_enabled", "nfc"),
                      ("tap_and_pay_setup_complete", "tap_and_pay"), ("default_payment_instrument_id", "default_instrument")]:
    if check in ds:
        log.info(f"  ✓ {label}")
    else:
        gaps.append(f"google_pay: default_settings missing {label}")
        log.warning(f"  ✗ {label}")

nfc = adb_shell("cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml 2>/dev/null")
if "nfc_setup_done" in nfc:
    log.info("  ✓ nfc_on_prefs.xml")
else:
    gaps.append("google_pay: nfc_on_prefs.xml missing")

# 4c. Play Store billing
log.info("[4c] Play Store billing")
coin = adb_shell("cat /data/data/com.android.vending/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml 2>/dev/null")
for check, label in [("has_payment_method", "has_payment"), ("default_payment_method_last4", "last4"),
                      ("default_payment_method_description", "description"), ("billing_account", "account")]:
    if check in coin:
        log.info(f"  ✓ {label}")
    else:
        gaps.append(f"play_store: COIN.xml missing {label}")
        log.warning(f"  ✗ {label}")

lib = adb_shell("ls /data/data/com.android.vending/databases/library.db 2>/dev/null")
log.info(f"  {'✓' if lib else '✗'} library.db")
if not lib:
    gaps.append("play_store: library.db missing")

# 4d. Chrome autofill
log.info("[4d] Chrome autofill")
cc = adb_shell("sqlite3 '/data/data/com.android.chrome/app_chrome/Default/Web Data' \"SELECT name_on_card, expiration_month, expiration_year, use_count, nickname FROM credit_cards\" 2>/dev/null")
if cc:
    log.info(f"  ✓ credit_cards: {cc}")
else:
    gaps.append("chrome: no credit_cards")
    log.warning("  ✗ No credit cards")

ap = adb_shell("sqlite3 '/data/data/com.android.chrome/app_chrome/Default/Web Data' \"SELECT COUNT(*) FROM autofill_profiles\" 2>/dev/null")
apc = int(ap) if ap.isdigit() else 0
if apc > 0:
    names = adb_shell("sqlite3 '/data/data/com.android.chrome/app_chrome/Default/Web Data' \"SELECT full_name FROM autofill_profile_names\" 2>/dev/null")
    log.info(f"  ✓ autofill_profiles: {apc} ({names})")
else:
    gaps.append("chrome: no autofill_profiles (address)")
    log.warning("  ✗ No autofill profiles")

# 4e. Chrome browser data
log.info("[4e] Chrome browser data")
cookies = adb_shell("sqlite3 /data/data/com.android.chrome/app_chrome/Default/Cookies \"SELECT COUNT(*) FROM cookies\" 2>/dev/null")
cc_n = int(cookies) if cookies.isdigit() else 0
log.info(f"  {'✓' if cc_n > 0 else '✗'} Cookies: {cc_n}")
if cc_n == 0: gaps.append("chrome: no cookies")

hist = adb_shell("sqlite3 /data/data/com.android.chrome/app_chrome/Default/History \"SELECT COUNT(*) FROM urls\" 2>/dev/null")
hc = int(hist) if hist.isdigit() else 0
log.info(f"  {'✓' if hc > 0 else '✗'} History: {hc} URLs")
if hc == 0: gaps.append("chrome: no history")

# 4f. Google Account
log.info("[4f] Google Account")
accts = adb_shell("sqlite3 /data/system_ce/0/accounts_ce.db \"SELECT name, type FROM accounts\" 2>/dev/null")
if "com.google" in accts:
    log.info(f"  ✓ Accounts: {accts}")
else:
    gaps.append("google_account: missing")

# 4g. Content providers
log.info("[4g] Content providers")
sms_n = adb_shell("content query --uri content://sms --projection _id | wc -l")
sms_c = int(sms_n) if sms_n.strip().isdigit() else 0
log.info(f"  {'✓' if sms_c >= 5 else '✗'} SMS: {sms_c}")
if sms_c < 5: gaps.append(f"sms: {sms_c} (need >=5)")

contacts_n = adb_shell("content query --uri content://contacts/phones --projection _id | wc -l")
cnt_c = int(contacts_n) if contacts_n.strip().isdigit() else 0
log.info(f"  {'✓' if cnt_c >= 5 else '✗'} Contacts: {cnt_c}")

calls_n = adb_shell("content query --uri content://call_log/calls --projection _id | wc -l")
call_c = int(calls_n) if calls_n.strip().isdigit() else 0
log.info(f"  {'✓' if call_c >= 10 else '✗'} Call logs: {call_c}")

gallery_n = adb_shell("ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l")
gal_c = int(gallery_n) if gallery_n.strip().isdigit() else 0
log.info(f"  {'✓' if gal_c >= 3 else '✗'} Gallery: {gal_c}")

wifi = adb_shell("ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null")
log.info(f"  {'✓' if wifi else '✗'} WiFi")
if not wifi: gaps.append("wifi: missing")

# 4h. App data
log.info("[4h] App SharedPrefs")
for pkg, name in [("com.instagram.android", "Instagram"), ("com.whatsapp", "WhatsApp"),
                   ("com.squareup.cash", "Cash App"), ("com.venmo", "Venmo")]:
    p = adb_shell(f"ls /data/data/{pkg}/shared_prefs/ 2>/dev/null")
    log.info(f"  {'✓' if p else '◌'} {name}")

# ═══════════════════════════════════════════════════════════════════
# STEP 5: Cerberus card validation
# ═══════════════════════════════════════════════════════════════════
log.info("\n═══ STEP 5: Cerberus Card Validation ═══")
cerb, _ = api_post("/api/cerberus/validate", {"card_input": "5425233430109903|04|2028|382"})
log.info(f"  Result: {json.dumps(cerb)[:200]}")

cerb_bin, _ = api_post("/api/cerberus/bin-lookup", {"bin": "542523"})
log.info(f"  BIN 542523: {json.dumps(cerb_bin)[:200]}")

# ═══════════════════════════════════════════════════════════════════
# FINAL REPORT
# ═══════════════════════════════════════════════════════════════════
log.info("\n" + "═" * 65)
log.info("FINAL REPORT")
log.info("═" * 65)
log.info(f"  Profile: {profile_id} (Elena Marchetti, 90-day)")
log.info(f"  Trust Score: {trust}/100 ({grade})")
log.info(f"  Wallet Gaps: {len(gaps)}")

if gaps:
    log.info("  GAPS FOUND:")
    for i, g in enumerate(gaps, 1):
        log.info(f"    {i}. {g}")
else:
    log.info("  ✓ ZERO GAPS — ALL WALLET TARGETS VERIFIED")

log.info("═" * 65)
