#!/usr/bin/env python3
"""
FINAL E2E Test: Forge 90-day → Async Inject → Poll → Wallet Probe → Gap Report.
Uses the new async inject API with job polling to avoid HTTP timeouts.
"""
import json, logging, os, subprocess, sys, time
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

def api_post(path, data=None, timeout=30):
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
log.info("║  FINAL E2E: Forge → Async Inject → Poll → Wallet Probe     ║")
log.info("╚═══════════════════════════════════════════════════════════════╝")

# ─── STEP 1: Forge ──────────────────────────────────────────────
log.info("\n═══ STEP 1: Forge 90-day profile ═══")
resp, code = api_post("/api/genesis/create", {
    "name": "Derek Vasquez",
    "email": "derek.vasquez.e2e@gmail.com",
    "phone": "+13105554872",
    "country": "US",
    "archetype": "professional",
    "age_days": 90,
    "carrier": "tmobile_us",
    "location": "los_angeles",
    "device_model": "samsung_s25_ultra",
})
assert code == 200, f"Forge failed: {resp}"
profile_id = resp["profile_id"]
stats = resp.get("stats", {})
log.info(f"  Profile: {profile_id}")
log.info(f"  Contacts={stats.get('contacts')}, Calls={stats.get('call_logs')}, "
         f"SMS={stats.get('sms')}, History={stats.get('history')}, "
         f"Gallery={stats.get('gallery')}, Apps={stats.get('apps')}")

# ─── STEP 2: Async Inject ───────────────────────────────────────
log.info("\n═══ STEP 2: Start async inject ═══")
resp, code = api_post(f"/api/genesis/inject/{DEVICE_ID}", {
    "profile_id": profile_id,
    "cc_number": "4716108999716531",
    "cc_exp_month": 7,
    "cc_exp_year": 2027,
    "cc_cvv": "214",
    "cc_cardholder": "Derek Vasquez",
})
assert code == 200, f"Inject start failed: {code} {resp}"
job_id = resp.get("job_id", "")
log.info(f"  Job started: {job_id}")
log.info(f"  Poll URL: {resp.get('poll_url')}")

# ─── STEP 3: Poll until complete ────────────────────────────────
log.info("\n═══ STEP 3: Polling inject job ═══")
max_wait = 300  # 5 minutes max
start = time.time()
while time.time() - start < max_wait:
    job, _ = api_get(f"/api/genesis/inject-status/{job_id}")
    status = job.get("status", "unknown")
    elapsed = int(time.time() - start)
    if status == "completed":
        log.info(f"  ✓ Inject completed in {elapsed}s")
        log.info(f"  Trust score: {job.get('trust_score')}")
        result = job.get("result", {})
        log.info(f"  Wallet: {result.get('wallet_ok')}")
        log.info(f"  Google Account: {result.get('google_account_ok')}")
        for e in result.get("errors", []):
            log.warning(f"  Error: {e}")
        break
    elif status == "failed":
        log.error(f"  ✗ Inject failed: {job.get('error', 'unknown')}")
        break
    else:
        log.info(f"  ... {status} ({elapsed}s)")
        time.sleep(10)
else:
    log.error(f"  ✗ Inject timed out after {max_wait}s")

# ─── STEP 4: Trust Score ────────────────────────────────────────
log.info("\n═══ STEP 4: Trust Score ═══")
ts_resp, _ = api_get(f"/api/genesis/trust-score/{DEVICE_ID}", timeout=30)
trust = ts_resp.get("trust_score", 0)
grade = ts_resp.get("grade", "?")
log.info(f"  Score: {trust}/100 ({grade})")
for k, v in ts_resp.get("checks", {}).items():
    present = v.get("present", v.get("count", "?"))
    weight = v.get("weight", "?")
    got = weight if (present is True or (isinstance(present, int) and present >= 1)) else 0
    log.info(f"    {'✓' if got else '✗'} {k}: {present} ({weight}pts)")

# ─── STEP 5: Wallet Probe ───────────────────────────────────────
log.info("\n═══ STEP 5: Wallet Probe ═══")
gaps = []

# Google Pay tokens
log.info("[GPay] tapandpay.db")
tc = adb_shell("sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db \"SELECT COUNT(*) FROM tokens\" 2>/dev/null")
tc_n = int(tc) if tc.isdigit() else 0
tmc = adb_shell("sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db \"SELECT COUNT(*) FROM token_metadata\" 2>/dev/null")
tmc_n = int(tmc) if tmc.isdigit() else 0
log.info(f"  {'✓' if tc_n else '✗'} tokens: {tc_n}")
log.info(f"  {'✓' if tmc_n else '✗'} token_metadata: {tmc_n}")
if not tc_n: gaps.append("google_pay: no tokens")
if not tmc_n: gaps.append("google_pay: no token_metadata view")

# Google Pay prefs
ds = adb_shell("cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/default_settings.xml 2>/dev/null")
for key in ["wallet_setup_complete", "nfc_enabled", "tap_and_pay_setup_complete", "default_payment_instrument_id"]:
    if key not in ds:
        gaps.append(f"google_pay: missing {key}")
        log.warning(f"  ✗ {key}")
    else:
        log.info(f"  ✓ {key}")
nfc = adb_shell("cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml 2>/dev/null")
if "nfc_setup_done" in nfc:
    log.info("  ✓ nfc_on_prefs.xml")
else:
    gaps.append("google_pay: nfc_on_prefs.xml missing")

# Play Store billing
log.info("[PlayStore] billing")
coin = adb_shell("cat /data/data/com.android.vending/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml 2>/dev/null")
for key in ["has_payment_method", "default_payment_method_last4", "billing_account"]:
    if key in coin:
        log.info(f"  ✓ {key}")
    else:
        gaps.append(f"play_store: missing {key}")
        log.warning(f"  ✗ {key}")
lib = adb_shell("ls /data/data/com.android.vending/databases/library.db 2>/dev/null")
log.info(f"  {'✓' if lib else '✗'} library.db")
if not lib: gaps.append("play_store: no library.db")

# Chrome autofill
log.info("[Chrome] autofill")
cc_out = adb_shell("sqlite3 '/data/data/com.android.chrome/app_chrome/Default/Web Data' \"SELECT name_on_card, nickname FROM credit_cards\" 2>/dev/null")
if cc_out:
    log.info(f"  ✓ credit_cards: {cc_out}")
else:
    gaps.append("chrome: no credit_cards"); log.warning("  ✗ credit_cards")
ap_out = adb_shell("sqlite3 '/data/data/com.android.chrome/app_chrome/Default/Web Data' \"SELECT COUNT(*) FROM autofill_profiles\" 2>/dev/null")
apc = int(ap_out) if ap_out.isdigit() else 0
if apc:
    names = adb_shell("sqlite3 '/data/data/com.android.chrome/app_chrome/Default/Web Data' \"SELECT full_name FROM autofill_profile_names\" 2>/dev/null")
    log.info(f"  ✓ autofill_profiles: {apc} ({names})")
else:
    gaps.append("chrome: no autofill_profiles"); log.warning("  ✗ autofill_profiles")

# Chrome data
log.info("[Chrome] browser data")
ck = adb_shell("sqlite3 /data/data/com.android.chrome/app_chrome/Default/Cookies \"SELECT COUNT(*) FROM cookies\" 2>/dev/null")
ck_n = int(ck) if ck.isdigit() else 0
log.info(f"  {'✓' if ck_n else '✗'} Cookies: {ck_n}")
if not ck_n: gaps.append("chrome: no cookies")
hi = adb_shell("sqlite3 /data/data/com.android.chrome/app_chrome/Default/History \"SELECT COUNT(*) FROM urls\" 2>/dev/null")
hi_n = int(hi) if hi.isdigit() else 0
log.info(f"  {'✓' if hi_n else '✗'} History: {hi_n}")
if not hi_n: gaps.append("chrome: no history")

# Google Account
log.info("[Account]")
accts = adb_shell("sqlite3 /data/system_ce/0/accounts_ce.db \"SELECT name, type FROM accounts\" 2>/dev/null")
if "com.google" in accts:
    log.info(f"  ✓ {accts}")
else:
    gaps.append("google_account: missing")

# Content providers
log.info("[Content]")
sms = adb_shell("content query --uri content://sms --projection _id | wc -l")
sms_n = int(sms) if sms.strip().isdigit() else 0
log.info(f"  {'✓' if sms_n >= 5 else '✗'} SMS: {sms_n}")
if sms_n < 5: gaps.append(f"sms: {sms_n}")
cnt = adb_shell("content query --uri content://contacts/phones --projection _id | wc -l")
cnt_n = int(cnt) if cnt.strip().isdigit() else 0
log.info(f"  ✓ Contacts: {cnt_n}")
call = adb_shell("content query --uri content://call_log/calls --projection _id | wc -l")
call_n = int(call) if call.strip().isdigit() else 0
log.info(f"  ✓ Call logs: {call_n}")
gal = adb_shell("ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l")
gal_n = int(gal) if gal.strip().isdigit() else 0
log.info(f"  ✓ Gallery: {gal_n}")
wifi = adb_shell("ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null")
log.info(f"  {'✓' if wifi else '✗'} WiFi")
if not wifi: gaps.append("wifi: missing")

# ─── FINAL REPORT ────────────────────────────────────────────────
log.info("\n" + "═" * 65)
log.info("FINAL REPORT")
log.info("═" * 65)
log.info(f"  Profile: {profile_id} (Derek Vasquez, 90-day)")
log.info(f"  Trust Score: {trust}/100 ({grade})")
log.info(f"  Wallet Gaps: {len(gaps)}")
if gaps:
    for i, g in enumerate(gaps, 1):
        log.info(f"    {i}. {g}")
else:
    log.info("  ✓ ZERO GAPS — ALL WALLET TARGETS VERIFIED")
log.info("═" * 65)
