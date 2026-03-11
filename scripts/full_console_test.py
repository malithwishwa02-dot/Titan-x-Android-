#!/usr/bin/env python3
"""
Titan V11.3 — Full Console API Integration Test
Tests every tab/feature of the Titan console via direct API calls.
Then forges a 90-day test device, injects everything, and probes all wallets for gaps.

Run on VPS:
    python3 -B /opt/titan-v11.3-device/scripts/full_console_test.py 2>&1
"""

import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, '/opt/titan-v11.3-device/core')
sys.path.insert(0, '/opt/titan-v11.3-device/server')
sys.path.insert(0, '/root/titan-v11-release/core')
os.environ['TITAN_DATA'] = '/opt/titan/data'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('test')

API = "http://127.0.0.1:8080"
ADB_TARGET = "127.0.0.1:5555"
DEVICE_ID = "dev-us1"

# ═════════════════════════════════════════════════════════════════
# HTTP HELPER
# ═════════════════════════════════════════════════════════════════

import urllib.request
import urllib.error

def api_get(path):
    try:
        req = urllib.request.Request(API + path)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": body, "status_code": e.code}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

def api_post(path, data=None):
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(API + path, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": body, "status_code": e.code}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

def adb_shell(cmd, timeout=15):
    try:
        r = subprocess.run(["adb", "-s", ADB_TARGET, "shell", cmd],
                          capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except:
        return ""

# ═════════════════════════════════════════════════════════════════
# TEST RESULTS TRACKER
# ═════════════════════════════════════════════════════════════════

results = []

def test(tab, endpoint, method, data=None, expect_key=None):
    """Run one API test, record pass/fail/gap."""
    if method == "GET":
        resp, code = api_get(endpoint)
    else:
        resp, code = api_post(endpoint, data)

    ok = code in (200, 201)
    stub = resp.get("stub", False) if isinstance(resp, dict) else False
    has_key = (expect_key in resp) if (expect_key and isinstance(resp, dict)) else True

    status = "PASS" if (ok and has_key and not stub) else "STUB" if stub else "FAIL"
    results.append({
        "tab": tab, "endpoint": f"{method} {endpoint}",
        "status": status, "code": code, "stub": stub,
        "response_keys": list(resp.keys()) if isinstance(resp, dict) else [],
    })

    icon = "✓" if status == "PASS" else "◌" if status == "STUB" else "✗"
    log.info(f"  [{icon}] {method:4s} {endpoint:45s} → {code} {status}")
    return resp, code, status


# ═════════════════════════════════════════════════════════════════
# TAB 1: DASHBOARD
# ═════════════════════════════════════════════════════════════════

def test_dashboard():
    log.info("═══ TAB: DASHBOARD ═══")
    test("dashboard", "/api/dashboard/summary", "GET", expect_key="total_devices")

# ═════════════════════════════════════════════════════════════════
# TAB 2: DEVICES
# ═════════════════════════════════════════════════════════════════

def test_devices():
    log.info("═══ TAB: DEVICES ═══")
    test("devices", "/api/devices", "GET", expect_key="devices")
    test("devices", f"/api/devices/{DEVICE_ID}", "GET", expect_key="id")
    test("devices", f"/api/devices/{DEVICE_ID}/info", "GET", expect_key="model")
    # Screenshot
    try:
        req = urllib.request.Request(f"{API}/api/devices/{DEVICE_ID}/screenshot")
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
            ok = len(data) > 100
            results.append({"tab": "devices", "endpoint": f"GET /api/devices/{DEVICE_ID}/screenshot",
                          "status": "PASS" if ok else "FAIL", "code": r.status, "stub": False,
                          "response_keys": [f"bytes:{len(data)}"]})
            log.info(f"  [{'✓' if ok else '✗'}] GET  /api/devices/{DEVICE_ID}/screenshot       → {r.status} {'PASS' if ok else 'FAIL'} ({len(data)} bytes)")
    except Exception as e:
        results.append({"tab": "devices", "endpoint": f"GET /api/devices/{DEVICE_ID}/screenshot",
                      "status": "FAIL", "code": 0, "stub": False, "response_keys": [str(e)]})
        log.info(f"  [✗] GET  /api/devices/{DEVICE_ID}/screenshot       → FAIL ({e})")

    # Input (tap center of screen)
    test("devices", f"/api/devices/{DEVICE_ID}/input", "POST",
         {"type": "tap", "x": 0.5, "y": 0.5}, expect_key="ok")

# ═════════════════════════════════════════════════════════════════
# TAB 3: STEALTH
# ═════════════════════════════════════════════════════════════════

def test_stealth():
    log.info("═══ TAB: STEALTH ═══")
    test("stealth", "/api/stealth/presets", "GET", expect_key="presets")
    test("stealth", "/api/stealth/carriers", "GET", expect_key="carriers")
    test("stealth", "/api/stealth/locations", "GET", expect_key="locations")
    test("stealth", f"/api/stealth/{DEVICE_ID}/audit", "GET")

# ═════════════════════════════════════════════════════════════════
# TAB 4: GENESIS (Profile Forge + Inject)
# ═════════════════════════════════════════════════════════════════

def test_genesis():
    log.info("═══ TAB: GENESIS ═══")
    test("genesis", "/api/genesis/profiles", "GET")
    test("genesis", f"/api/genesis/trust-score/{DEVICE_ID}", "GET", expect_key="trust_score")

# ═════════════════════════════════════════════════════════════════
# TAB 5: INTEL
# ═════════════════════════════════════════════════════════════════

def test_intel():
    log.info("═══ TAB: INTEL ═══")
    test("intel", "/api/intel/copilot", "POST", {"query": "test"})
    test("intel", "/api/intel/recon", "POST", {"domain": "google.com"})
    test("intel", "/api/intel/osint", "POST", {"name": "test", "email": "test@test.com"})
    test("intel", "/api/intel/3ds-strategy", "POST", {"merchant": "stripe.com", "bin": "463851", "amount": 50})
    test("intel", "/api/intel/darkweb", "POST", {"query": "test"})

# ═════════════════════════════════════════════════════════════════
# TAB 6: NETWORK
# ═════════════════════════════════════════════════════════════════

def test_network():
    log.info("═══ TAB: NETWORK ═══")
    test("network", "/api/network/status", "GET")
    test("network", "/api/network/forensic", "GET")
    test("network", "/api/network/shield", "GET")

# ═════════════════════════════════════════════════════════════════
# TAB 7: CERBERUS (Card Validation)
# ═════════════════════════════════════════════════════════════════

def test_cerberus():
    log.info("═══ TAB: CERBERUS ═══")
    test("cerberus", "/api/cerberus/validate", "POST",
         {"card_input": "4638512320340405|08|2029|051"})
    test("cerberus", "/api/cerberus/bin-lookup", "POST", {"bin": "463851"})
    test("cerberus", "/api/cerberus/intelligence", "POST", {"bin": "463851"})

# ═════════════════════════════════════════════════════════════════
# TAB 8: TARGETS
# ═════════════════════════════════════════════════════════════════

def test_targets():
    log.info("═══ TAB: TARGETS ═══")
    test("targets", "/api/targets/analyze", "POST", {"domain": "stripe.com"})
    test("targets", "/api/targets/waf", "POST", {"domain": "stripe.com"})
    test("targets", "/api/targets/dns", "POST", {"domain": "google.com"})
    test("targets", "/api/targets/profiler", "POST", {"domain": "paypal.com"})

# ═════════════════════════════════════════════════════════════════
# TAB 9: KYC (Camera Bridge)
# ═════════════════════════════════════════════════════════════════

def test_kyc():
    log.info("═══ TAB: KYC ═══")
    test("kyc", f"/api/kyc/{DEVICE_ID}/status", "GET", expect_key="device")
    test("kyc", f"/api/kyc/{DEVICE_ID}/upload_face", "POST", {})
    test("kyc", f"/api/kyc/{DEVICE_ID}/kyc-flow", "POST", {"provider": "auto"})
    test("kyc", f"/api/kyc/{DEVICE_ID}/voice", "POST", {"text": "hello", "voice": "en-US-male"})

# ═════════════════════════════════════════════════════════════════
# TAB 10: AI
# ═════════════════════════════════════════════════════════════════

def test_ai():
    log.info("═══ TAB: AI ═══")
    test("ai", "/api/ai/status", "GET")
    test("ai", "/api/ai/query", "POST", {"prompt": "test", "model": ""})

# ═════════════════════════════════════════════════════════════════
# TAB 11: BUNDLES
# ═════════════════════════════════════════════════════════════════

def test_bundles():
    log.info("═══ TAB: BUNDLES ═══")
    test("bundles", "/api/bundles", "GET", expect_key="bundles")
    test("bundles", "/api/bundles/US", "GET", expect_key="bundles")
    test("bundles", f"/api/bundles/{DEVICE_ID}/install", "POST",
         {"bundle": "us_banking", "packages": ["com.venmo"]})

# ═════════════════════════════════════════════════════════════════
# TAB 12: ADMIN
# ═════════════════════════════════════════════════════════════════

def test_admin():
    log.info("═══ TAB: ADMIN ═══")
    test("admin", "/api/admin/health", "GET", expect_key="status")
    test("admin", "/api/admin/services", "GET", expect_key="services")
    test("admin", "/api/admin/cpu", "GET")

# ═════════════════════════════════════════════════════════════════
# TAB 13: SETTINGS
# ═════════════════════════════════════════════════════════════════

def test_settings():
    log.info("═══ TAB: SETTINGS ═══")
    test("settings", "/api/settings", "GET")


# ═════════════════════════════════════════════════════════════════
# PHASE 2: FORGE 90-DAY PROFILE + FULL INJECTION + WALLET PROBE
# ═════════════════════════════════════════════════════════════════

def forge_90day_test_device():
    log.info("")
    log.info("═" * 65)
    log.info("PHASE 2: FORGE 90-DAY TEST PROFILE + INJECT + WALLET PROBE")
    log.info("═" * 65)

    # ── 2a: Forge profile via API ──
    log.info("── Step 2a: Forge 90-day profile ──")
    resp, code, st = test("forge", "/api/genesis/create", "POST", {
        "name": "Marcus Rivera",
        "email": "marcus.rivera.test90@gmail.com",
        "phone": "+13105559042",
        "country": "US",
        "archetype": "professional",
        "age_days": 90,
        "carrier": "tmobile_us",
        "location": "los_angeles",
        "device_model": "samsung_s25_ultra",
    }, expect_key="profile_id")

    profile_id = resp.get("profile_id", "")
    if not profile_id:
        log.error("FORGE FAILED — cannot continue")
        return
    log.info(f"  Profile ID: {profile_id}")
    log.info(f"  Stats: {json.dumps(resp.get('stats', {}))}")

    # ── 2b: Inject profile + CC into existing device ──
    log.info("── Step 2b: Inject into dev-us1 with CC ──")
    resp, code, st = test("inject", f"/api/genesis/inject/{DEVICE_ID}", "POST", {
        "profile_id": profile_id,
        "cc_number": "4532015112830366",
        "cc_exp_month": 11,
        "cc_exp_year": 2028,
        "cc_cvv": "789",
        "cc_cardholder": "Marcus Rivera",
    }, expect_key="trust_score")

    inject_trust = resp.get("trust_score", 0)
    log.info(f"  Inject trust score: {inject_trust}")
    if resp.get("result"):
        inj_result = resp["result"]
        log.info(f"  Wallet OK: {inj_result.get('wallet_ok', 'N/A')}")
        log.info(f"  Google Account OK: {inj_result.get('google_account_ok', 'N/A')}")
        for e in inj_result.get("errors", []):
            log.warning(f"  Inject error: {e}")

    # ── 2c: Trust score verification ──
    log.info("── Step 2c: Trust score check ──")
    resp, code, st = test("trust", f"/api/genesis/trust-score/{DEVICE_ID}", "GET", expect_key="trust_score")
    trust = resp.get("trust_score", 0)
    grade = resp.get("grade", "?")
    log.info(f"  Trust Score: {trust}/100 ({grade})")
    checks = resp.get("checks", {})
    for k, v in checks.items():
        present = v.get("present", v.get("count", "?"))
        weight = v.get("weight", "?")
        got = weight if (present is True or (isinstance(present, int) and present >= 1)) else 0
        log.info(f"    {'✓' if got else '✗'} {k}: {present} (weight: {weight})")

    # ── 2d: Wallet gap analysis — probe each wallet target ──
    log.info("── Step 2d: Wallet gap analysis ──")
    wallet_gaps = probe_wallets()

    # ── 2e: Cerberus validate the test CC ──
    log.info("── Step 2e: Cerberus card validation ──")
    test("cerberus_test", "/api/cerberus/validate", "POST",
         {"card_input": "4532015112830366|11|2028|789"})

    return wallet_gaps


def probe_wallets():
    """Probe every wallet injection target on the device for gaps."""
    gaps = []

    log.info("  [Probing Google Pay tapandpay.db]")
    db_path = "/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db"
    exists = adb_shell(f"ls {db_path} 2>/dev/null")
    if exists:
        # Pull and inspect
        tmp = tempfile.mktemp(suffix=".db")
        subprocess.run(["adb", "-s", ADB_TARGET, "pull", db_path, tmp],
                      capture_output=True, timeout=10)
        try:
            conn = sqlite3.connect(tmp)
            c = conn.cursor()
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            log.info(f"    Tables: {tables}")
            if "token_metadata" in tables:
                rows = c.execute("SELECT * FROM token_metadata").fetchall()
                log.info(f"    Tokens: {len(rows)}")
                for row in rows:
                    log.info(f"      {row}")
            else:
                gaps.append("google_pay: no token_metadata table")
                log.warning("    GAP: token_metadata table missing")
            conn.close()
        except Exception as e:
            gaps.append(f"google_pay: db read error: {e}")
        os.unlink(tmp)
    else:
        gaps.append("google_pay: tapandpay.db not found")
        log.warning("    GAP: tapandpay.db not found")

    log.info("  [Probing Google Pay SharedPrefs]")
    nfc_prefs = adb_shell("cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml 2>/dev/null")
    if "nfc_setup_done" in nfc_prefs:
        log.info("    NFC prefs: OK (nfc_setup_done=true)")
    else:
        gaps.append("google_pay: nfc_on_prefs.xml missing or incomplete")
        log.warning("    GAP: NFC prefs not set")

    log.info("  [Probing Play Store billing]")
    billing_prefs = adb_shell("cat /data/data/com.android.vending/shared_prefs/billing.xml 2>/dev/null")
    if billing_prefs:
        log.info(f"    Billing prefs: {len(billing_prefs)} bytes")
        if "default_instrument" in billing_prefs or "instrument" in billing_prefs.lower():
            log.info("    Default payment instrument: SET")
        else:
            gaps.append("play_store: no default_instrument in billing.xml")
            log.warning("    GAP: No default payment instrument")
    else:
        gaps.append("play_store: billing.xml not found")
        log.warning("    GAP: billing.xml missing")

    log.info("  [Probing Play Store library.db]")
    lib_exists = adb_shell("ls /data/data/com.android.vending/databases/library.db 2>/dev/null")
    if lib_exists:
        log.info("    library.db: EXISTS")
    else:
        gaps.append("play_store: library.db not found")
        log.warning("    GAP: library.db missing")

    log.info("  [Probing Chrome autofill Web Data]")
    webdata_path = "/data/data/com.android.chrome/app_chrome/Default/Web Data"
    webdata_exists = adb_shell(f"ls '{webdata_path}' 2>/dev/null")
    if webdata_exists:
        tmp = tempfile.mktemp(suffix=".db")
        subprocess.run(["adb", "-s", ADB_TARGET, "pull", webdata_path, tmp],
                      capture_output=True, timeout=10)
        try:
            conn = sqlite3.connect(tmp)
            c = conn.cursor()
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            log.info(f"    Tables: {tables}")
            if "credit_cards" in tables:
                rows = c.execute("SELECT name_on_card, expiration_month, expiration_year, use_count, nickname FROM credit_cards").fetchall()
                log.info(f"    Cards: {len(rows)}")
                for row in rows:
                    log.info(f"      {row}")
            else:
                gaps.append("chrome: no credit_cards table in Web Data")
                log.warning("    GAP: credit_cards table missing")
            if "autofill_profiles" in tables:
                profiles = c.execute("SELECT COUNT(*) FROM autofill_profiles").fetchone()[0]
                log.info(f"    Autofill profiles: {profiles}")
            conn.close()
        except Exception as e:
            gaps.append(f"chrome: Web Data read error: {e}")
        os.unlink(tmp)
    else:
        gaps.append("chrome: Web Data not found")
        log.warning("    GAP: Chrome Web Data missing")

    log.info("  [Probing Chrome Cookies]")
    cookies_path = "/data/data/com.android.chrome/app_chrome/Default/Cookies"
    cookies_exists = adb_shell(f"ls '{cookies_path}' 2>/dev/null")
    if cookies_exists:
        tmp = tempfile.mktemp(suffix=".db")
        subprocess.run(["adb", "-s", ADB_TARGET, "pull", cookies_path, tmp],
                      capture_output=True, timeout=10)
        try:
            conn = sqlite3.connect(tmp)
            c = conn.cursor()
            count = c.execute("SELECT COUNT(*) FROM cookies").fetchone()[0]
            domains = c.execute("SELECT DISTINCT host_key FROM cookies LIMIT 10").fetchall()
            log.info(f"    Cookies: {count} total, domains: {[d[0] for d in domains]}")
            conn.close()
        except Exception as e:
            gaps.append(f"chrome: Cookies read error: {e}")
        os.unlink(tmp)
    else:
        gaps.append("chrome: Cookies not found")

    log.info("  [Probing Chrome History]")
    history_path = "/data/data/com.android.chrome/app_chrome/Default/History"
    hist_exists = adb_shell(f"ls '{history_path}' 2>/dev/null")
    if hist_exists:
        tmp = tempfile.mktemp(suffix=".db")
        subprocess.run(["adb", "-s", ADB_TARGET, "pull", history_path, tmp],
                      capture_output=True, timeout=10)
        try:
            conn = sqlite3.connect(tmp)
            c = conn.cursor()
            count = c.execute("SELECT COUNT(*) FROM urls").fetchone()[0]
            recent = c.execute("SELECT url FROM urls ORDER BY last_visit_time DESC LIMIT 5").fetchall()
            log.info(f"    URLs: {count} total")
            for r in recent:
                log.info(f"      {r[0][:80]}")
            conn.close()
        except Exception as e:
            gaps.append(f"chrome: History read error: {e}")
        os.unlink(tmp)
    else:
        gaps.append("chrome: History not found")

    log.info("  [Probing Google Account]")
    acct_db = "/data/system_ce/0/accounts_ce.db"
    acct_exists = adb_shell(f"ls {acct_db} 2>/dev/null")
    if acct_exists:
        tmp = tempfile.mktemp(suffix=".db")
        subprocess.run(["adb", "-s", ADB_TARGET, "pull", acct_db, tmp],
                      capture_output=True, timeout=10)
        try:
            conn = sqlite3.connect(tmp)
            c = conn.cursor()
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if "accounts" in tables:
                accts = c.execute("SELECT name, type FROM accounts").fetchall()
                log.info(f"    Accounts: {accts}")
            else:
                gaps.append("google_account: no accounts table in accounts_ce.db")
            conn.close()
        except Exception as e:
            gaps.append(f"google_account: read error: {e}")
        os.unlink(tmp)
    else:
        gaps.append("google_account: accounts_ce.db not found")

    log.info("  [Probing SMS]")
    sms_count = adb_shell("content query --uri content://sms --projection _id | wc -l")
    try:
        sms_n = int(sms_count.strip())
    except:
        sms_n = 0
    log.info(f"    SMS count: {sms_n}")
    if sms_n < 5:
        gaps.append(f"sms: only {sms_n} messages (need >=5)")

    log.info("  [Probing Contacts]")
    contacts_count = adb_shell("content query --uri content://contacts/phones --projection _id | wc -l")
    try:
        contacts_n = int(contacts_count.strip())
    except:
        contacts_n = 0
    log.info(f"    Contacts count: {contacts_n}")
    if contacts_n < 5:
        gaps.append(f"contacts: only {contacts_n} (need >=5)")

    log.info("  [Probing WiFi]")
    wifi = adb_shell("ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null")
    if wifi:
        log.info("    WiFi config: EXISTS")
    else:
        gaps.append("wifi: WifiConfigStore.xml not found")

    log.info("  [Probing App SharedPrefs (Instagram)]")
    ig_prefs = adb_shell("ls /data/data/com.instagram.android/shared_prefs/ 2>/dev/null")
    if ig_prefs:
        log.info(f"    Instagram prefs: {len(ig_prefs.split())} files")
    else:
        gaps.append("app_data: Instagram SharedPrefs missing")

    return gaps


# ═════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════

def main():
    log.info("╔═══════════════════════════════════════════════════════════════╗")
    log.info("║  TITAN V11.3 — FULL CONSOLE INTEGRATION TEST                ║")
    log.info("║  Testing every tab, feature, and API endpoint               ║")
    log.info("╚═══════════════════════════════════════════════════════════════╝")
    log.info("")

    # Verify API is up
    resp, code = api_get("/api/admin/health")
    if code != 200:
        log.error(f"API not reachable: {code}")
        return 1
    log.info(f"API healthy: {resp.get('devices', '?')} devices\n")

    # Phase 1: Test every console tab
    log.info("═" * 65)
    log.info("PHASE 1: CONSOLE TAB-BY-TAB API TESTING")
    log.info("═" * 65)

    test_dashboard()
    test_devices()
    test_stealth()
    test_genesis()
    test_intel()
    test_network()
    test_cerberus()
    test_targets()
    test_kyc()
    test_ai()
    test_bundles()
    test_admin()
    test_settings()

    # Phase 1 Summary
    log.info("")
    log.info("═" * 65)
    log.info("PHASE 1 RESULTS")
    log.info("═" * 65)
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    stubs = sum(1 for r in results if r["status"] == "STUB")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    log.info(f"  PASS: {passed}/{total}  STUB: {stubs}/{total}  FAIL: {failed}/{total}")

    stub_list = [r for r in results if r["status"] == "STUB"]
    if stub_list:
        log.info("  Stub endpoints (backend module not loaded):")
        for r in stub_list:
            log.info(f"    ◌ [{r['tab']}] {r['endpoint']}")

    fail_list = [r for r in results if r["status"] == "FAIL"]
    if fail_list:
        log.info("  Failed endpoints:")
        for r in fail_list:
            log.info(f"    ✗ [{r['tab']}] {r['endpoint']} → {r['code']}")

    # Phase 2: Forge 90-day device + inject + wallet probe
    wallet_gaps = forge_90day_test_device()

    # Final gap report
    log.info("")
    log.info("═" * 65)
    log.info("FINAL GAP ANALYSIS REPORT")
    log.info("═" * 65)

    if wallet_gaps:
        log.info(f"  Found {len(wallet_gaps)} gap(s):")
        for i, g in enumerate(wallet_gaps, 1):
            log.info(f"    {i}. {g}")
    else:
        log.info("  No gaps found — all wallet targets verified!")

    # Consolidated pass rate
    p2_results = [r for r in results if r["tab"] in ("forge", "inject", "trust", "cerberus_test")]
    p2_pass = sum(1 for r in p2_results if r["status"] == "PASS")
    log.info(f"\n  Console API: {passed}/{total} endpoints working ({stubs} stubs)")
    log.info(f"  Forge+Inject: {p2_pass}/{len(p2_results)} operations passed")
    log.info(f"  Wallet Gaps: {len(wallet_gaps) if wallet_gaps else 0}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
