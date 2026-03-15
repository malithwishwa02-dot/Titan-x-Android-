#!/usr/bin/env python3
"""
E2E Full Pipeline Test — OVH Cuttlefish (Android 15)
Forge 90-day AI OSINT profile → Inject + CC → Stealth Patch → 37-vector Audit
→ Trust Score → Wallet Verify → Deep Forensic Probe → Gap Report.

Targets OVH KS-4 (51.68.33.34):
  - API: http://127.0.0.1:8080
  - ADB: 127.0.0.1:6520 (Cuttlefish CVD)
  - Device: cvd-ovh-1
"""
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("e2e-ovh")

API = "http://127.0.0.1:8080"
ADB_TARGET = "127.0.0.1:6520"
DEVICE_ID = "cvd-ovh-1"

gaps = []       # (category, description)
warnings = []   # non-critical issues


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def api_get(path, timeout=30):
    try:
        req = urllib.request.Request(API + path)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": body}, e.code
    except Exception as e:
        return {"error": str(e)}, 0


def api_post(path, data=None, timeout=120):
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            API + path, data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": body}, e.code
    except Exception as e:
        return {"error": str(e)}, 0


def adb(cmd, timeout=15):
    try:
        r = subprocess.run(
            ["adb", "-s", ADB_TARGET, "shell", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def sql(db, query):
    return adb(f"sqlite3 '{db}' \"{query}\" 2>/dev/null")


def gap(cat, desc):
    gaps.append((cat, desc))
    log.warning(f"  GAP [{cat}] {desc}")


def warn(desc):
    warnings.append(desc)
    log.info(f"  WARN: {desc}")


def section(title):
    log.info(f"\n{'='*65}")
    log.info(f"  {title}")
    log.info(f"{'='*65}")


# ═══════════════════════════════════════════════════════════════════
# PRE-FLIGHT
# ═══════════════════════════════════════════════════════════════════
section("PRE-FLIGHT CHECKS")

# Verify ADB
boot = adb("getprop sys.boot_completed")
if boot != "1":
    log.error(f"Device not booted! sys.boot_completed={boot!r}")
    sys.exit(1)
log.info(f"  ADB: {ADB_TARGET} — booted")

model = adb("getprop ro.product.model")
android = adb("getprop ro.build.version.release")
sdk = adb("getprop ro.build.version.sdk")
log.info(f"  Model: {model}, Android {android} (SDK {sdk})")

# Verify API
resp, code = api_get("/api/stealth/presets")
if code != 200:
    log.error(f"API not responding: {resp}")
    sys.exit(1)
log.info(f"  API: OK ({len(resp.get('presets', []))} presets)")

# Verify device registered
dev_resp, dev_code = api_get(f"/api/devices/{DEVICE_ID}")
if dev_code != 200:
    log.error(f"Device {DEVICE_ID} not registered in API: {dev_resp}")
    sys.exit(1)
log.info(f"  Device: {DEVICE_ID} state={dev_resp.get('state', '?')}")


# ═══════════════════════════════════════════════════════════════════
# STEP 1: FORGE 90-DAY PROFILE
# ═══════════════════════════════════════════════════════════════════
section("STEP 1: Forge 90-day AI OSINT Profile")

forge_resp, forge_code = api_post("/api/genesis/create", {
    "name": "Marcus Chen",
    "email": "marcus.chen.e2e@gmail.com",
    "phone": "+14155559032",
    "country": "US",
    "archetype": "professional",
    "age_days": 90,
    "carrier": "tmobile_us",
    "location": "nyc",
    "device_model": "samsung_s25_ultra",
})

if forge_code != 200:
    gap("forge", f"API returned {forge_code}: {forge_resp}")
    log.error("Forge failed — cannot continue pipeline")
    # Continue to collect other gaps
    profile_id = None
else:
    profile_id = forge_resp.get("profile_id")
    stats = forge_resp.get("stats", {})
    log.info(f"  Profile: {profile_id}")
    log.info(f"  Contacts={stats.get('contacts', '?')}, "
             f"Calls={stats.get('call_logs', '?')}, "
             f"SMS={stats.get('sms', '?')}, "
             f"History={stats.get('history', '?')}, "
             f"Gallery={stats.get('gallery', '?')}, "
             f"Apps={stats.get('apps', '?')}")

    # Check behavioral depth minimums
    for key, minimum in [("contacts", 5), ("call_logs", 20), ("sms", 10),
                         ("history", 30), ("gallery", 3)]:
        val = stats.get(key, 0)
        if isinstance(val, int) and val < minimum:
            gap("forge_depth", f"{key}={val} (minimum {minimum})")


# ═══════════════════════════════════════════════════════════════════
# STEP 2: INJECT PROFILE + CC
# ═══════════════════════════════════════════════════════════════════
section("STEP 2: Inject Profile + CC into Device")

inject_ok = False
if profile_id:
    inject_resp, inject_code = api_post(f"/api/genesis/inject/{DEVICE_ID}", {
        "profile_id": profile_id,
        "cc_number": "4716108999716531",
        "cc_exp_month": 7,
        "cc_exp_year": 2027,
        "cc_cvv": "214",
        "cc_cardholder": "Marcus Chen",
    })

    if inject_code != 200:
        gap("inject", f"API returned {inject_code}: {inject_resp}")
    else:
        job_id = inject_resp.get("job_id", "")
        if job_id:
            log.info(f"  Async job: {job_id}")
            # Poll for completion
            max_wait = 300
            start = time.time()
            while time.time() - start < max_wait:
                job, _ = api_get(f"/api/genesis/inject-status/{job_id}")
                status = job.get("status", "unknown")
                elapsed = int(time.time() - start)
                if status == "completed":
                    log.info(f"  Inject completed in {elapsed}s")
                    inject_ok = True
                    result = job.get("result", {})
                    for e in result.get("errors", []):
                        gap("inject_error", e)
                    break
                elif status == "failed":
                    gap("inject", f"Job failed: {job.get('error', 'unknown')}")
                    break
                else:
                    log.info(f"  ... {status} ({elapsed}s)")
                    time.sleep(10)
            else:
                gap("inject", f"Job timed out after {max_wait}s")
        else:
            # Synchronous inject
            inject_ok = True
            trust = inject_resp.get("trust_score", 0)
            log.info(f"  Inject complete (trust={trust})")
            for e in inject_resp.get("errors", []):
                gap("inject_error", e)
else:
    gap("inject", "Skipped — no profile_id from forge step")


# ═══════════════════════════════════════════════════════════════════
# STEP 3: STEALTH PATCH
# ═══════════════════════════════════════════════════════════════════
section("STEP 3: Stealth Patch (Samsung S25 Ultra / T-Mobile / NYC)")

patch_resp, patch_code = api_post(f"/api/stealth/{DEVICE_ID}/patch", {
    "preset": "samsung_s25_ultra",
    "carrier": "tmobile_us",
    "location": "nyc",
})

if patch_code != 200:
    gap("patch", f"API returned {patch_code}: {patch_resp}")
else:
    score = patch_resp.get("score", 0)
    total = patch_resp.get("total", 0)
    passed = patch_resp.get("passed", 0)
    failed = patch_resp.get("failed", 0)
    log.info(f"  Stealth: {score}% ({passed}/{total})")
    if failed > 0:
        for r in patch_resp.get("results", []):
            if isinstance(r, dict) and not r.get("ok"):
                gap("patch_fail", f"{r.get('name', '?')}: {r.get('detail', '')}")
    # Log first few failed phases for visibility
    fail_list = [r for r in patch_resp.get("results", []) if isinstance(r, dict) and not r.get("ok")]
    if fail_list:
        log.info(f"  Failed phases ({len(fail_list)}):")
        for r in fail_list[:10]:
            log.info(f"    - {r.get('name','?')}: {r.get('detail','')}")
        if len(fail_list) > 10:
            log.info(f"    ... and {len(fail_list)-10} more")


# ═══════════════════════════════════════════════════════════════════
# STEP 4: 37-VECTOR AUDIT
# ═══════════════════════════════════════════════════════════════════
section("STEP 4: 37-Vector Forensic Audit")

audit_resp, audit_code = api_get(f"/api/stealth/{DEVICE_ID}/audit", timeout=60)

if audit_code != 200:
    gap("audit", f"API returned {audit_code}: {audit_resp}")
else:
    audit_pass = audit_resp.get("passed", 0)
    audit_total = audit_resp.get("total", 37)
    audit_score = audit_resp.get("score", 0)
    checks = audit_resp.get("checks", {})
    # checks is {"name": bool, ...}
    # adb_disabled is expected — ADB is intentionally kept on for device management
    KNOWN_EXCEPTIONS = {"adb_disabled"}
    for name, ok in checks.items():
        if ok:
            log.info(f"  PASS {name}")
        elif name in KNOWN_EXCEPTIONS:
            log.info(f"  SKIP {name} (known exception: ADB kept on for management)")
        else:
            gap("audit_fail", f"{name}")
    log.info(f"  Audit: {audit_pass}/{audit_total} ({audit_score}%)")
    if audit_score < 100:
        failed_checks = [n for n, v in checks.items() if not v]
        log.info(f"  Failed ({len(failed_checks)}): {', '.join(failed_checks)}")


# ═══════════════════════════════════════════════════════════════════
# STEP 5: TRUST SCORE
# ═══════════════════════════════════════════════════════════════════
section("STEP 5: Trust Score")

ts_resp, ts_code = api_get(f"/api/genesis/trust-score/{DEVICE_ID}", timeout=30)

trust_score = 0
trust_grade = "?"
if ts_code != 200:
    gap("trust", f"API returned {ts_code}: {ts_resp}")
else:
    trust_score = ts_resp.get("trust_score", 0)
    trust_grade = ts_resp.get("grade", "?")
    log.info(f"  Score: {trust_score}/100 ({trust_grade})")
    for k, v in ts_resp.get("checks", {}).items():
        present = v.get("present", v.get("count", "?"))
        weight = v.get("weight", "?")
        ok = present is True or (isinstance(present, int) and present >= 1)
        log.info(f"    {'PASS' if ok else 'FAIL'} {k}: present={present} weight={weight}")
        if not ok:
            gap("trust_check", f"{k}: present={present}")


# ═══════════════════════════════════════════════════════════════════
# STEP 6: WALLET VERIFY (13-check)
# ═══════════════════════════════════════════════════════════════════
section("STEP 6: Wallet Verification (13-check)")

wv_resp, wv_code = api_get(f"/api/stealth/{DEVICE_ID}/wallet-verify", timeout=30)

if wv_code != 200:
    gap("wallet_verify", f"API returned {wv_code}: {wv_resp}")
else:
    wv_pass = wv_resp.get("passed", 0)
    wv_total = wv_resp.get("total", 0)
    log.info(f"  Wallet verify: {wv_pass}/{wv_total}")
    for c in wv_resp.get("checks", []):
        name = c.get("name", "?")
        ok = c.get("passed", False)
        detail = c.get("detail", "")
        if ok:
            log.info(f"    PASS {name}: {detail}")
        else:
            gap("wallet", f"{name}: {detail}")


# ═══════════════════════════════════════════════════════════════════
# STEP 7: DEEP FORENSIC PROBE (ADB-level)
# ═══════════════════════════════════════════════════════════════════
section("STEP 7: Deep Forensic Probe (ADB)")

# --- 7a. Google Pay: tapandpay.db ---
log.info("[GPay] tapandpay.db")
gpay_db = "/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db"
tc = sql(gpay_db, "SELECT COUNT(*) FROM tokens")
tc_n = int(tc) if tc.isdigit() else 0
log.info(f"  {'PASS' if tc_n else 'FAIL'} tokens: {tc_n}")
if not tc_n:
    gap("gpay", "No tokens in tapandpay.db")

# Transaction history (new R6 feature)
txh = sql(gpay_db, "SELECT COUNT(*) FROM transaction_history")
txh_n = int(txh) if txh.isdigit() else 0
log.info(f"  {'PASS' if txh_n else 'FAIL'} transaction_history: {txh_n}")
if not txh_n:
    gap("gpay", "No transaction_history rows (R6 enhancement)")

# Token metadata
tmc = sql(gpay_db, "SELECT COUNT(*) FROM token_metadata")
tmc_n = int(tmc) if tmc.isdigit() else 0
log.info(f"  {'PASS' if tmc_n else 'FAIL'} token_metadata: {tmc_n}")
if not tmc_n:
    gap("gpay", "No token_metadata view/table")

# Session keys
sk = sql(gpay_db, "SELECT COUNT(*) FROM session_keys")
sk_n = int(sk) if sk.isdigit() else 0
log.info(f"  {'PASS' if sk_n else 'FAIL'} session_keys: {sk_n}")
if not sk_n:
    gap("gpay", "No session_keys")

# GPay shared_prefs
ds = adb("cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/default_settings.xml 2>/dev/null")
for key in ["wallet_setup_complete", "nfc_enabled", "tap_and_pay_setup_complete", "default_payment_instrument_id"]:
    if key in ds:
        log.info(f"  PASS {key}")
    else:
        gap("gpay_prefs", f"missing {key}")

nfc = adb("cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml 2>/dev/null")
if "nfc_setup_done" in nfc:
    log.info("  PASS nfc_on_prefs.xml")
else:
    gap("gpay_prefs", "nfc_on_prefs.xml missing")

# --- 7b. Play Store billing ---
log.info("\n[PlayStore] billing")
coin = adb("cat /data/data/com.android.vending/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml 2>/dev/null")
for key in ["has_payment_method", "default_payment_method_last4", "billing_account"]:
    if key in coin:
        log.info(f"  PASS {key}")
    else:
        gap("playstore", f"missing {key}")

# Check vending background denied (R6 cloud reconciliation mitigation)
bg_status = adb("cmd appops get com.android.vending RUN_IN_BACKGROUND 2>/dev/null")
if "deny" in bg_status.lower():
    log.info("  PASS vending background denied (cloud reconciliation mitigation)")
else:
    warn("vending RUN_IN_BACKGROUND not denied — cloud reconciliation risk")

# --- 7c. Chrome autofill ---
log.info("\n[Chrome] autofill")
chrome_webdata = "/data/data/com.android.chrome/app_chrome/Default/Web Data"
cc_out = sql(chrome_webdata, "SELECT name_on_card, nickname FROM credit_cards")
if cc_out:
    log.info(f"  PASS credit_cards: {cc_out}")
else:
    gap("chrome", "No credit_cards in Web Data")

ap_out = sql(chrome_webdata, "SELECT COUNT(*) FROM autofill_profiles")
apc = int(ap_out) if ap_out.isdigit() else 0
if apc:
    log.info(f"  PASS autofill_profiles: {apc}")
else:
    gap("chrome", "No autofill_profiles")

# --- 7d. Chrome browser data ---
log.info("\n[Chrome] browser data")
ck = sql("/data/data/com.android.chrome/app_chrome/Default/Cookies", "SELECT COUNT(*) FROM cookies")
ck_n = int(ck) if ck.isdigit() else 0
log.info(f"  {'PASS' if ck_n else 'FAIL'} Cookies: {ck_n}")
if not ck_n:
    gap("chrome", "No cookies")

hi = sql("/data/data/com.android.chrome/app_chrome/Default/History", "SELECT COUNT(*) FROM urls")
hi_n = int(hi) if hi.isdigit() else 0
log.info(f"  {'PASS' if hi_n else 'FAIL'} History: {hi_n}")
if not hi_n:
    gap("chrome", "No history URLs")

# --- 7e. Content providers ---
log.info("\n[Content] providers")
sms_n_raw = adb("sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db 'SELECT COUNT(*) FROM sms' 2>/dev/null")
sms_n = int(sms_n_raw) if sms_n_raw.strip().isdigit() else 0
log.info(f"  {'PASS' if sms_n >= 5 else 'FAIL'} SMS: {sms_n}")
if sms_n < 5:
    gap("content", f"SMS count {sms_n} < 5")

cnt_raw = adb("content query --uri content://contacts/phones --projection _id 2>/dev/null | wc -l")
cnt_n = int(cnt_raw) if cnt_raw.strip().isdigit() else 0
log.info(f"  {'PASS' if cnt_n >= 3 else 'FAIL'} Contacts: {cnt_n}")
if cnt_n < 3:
    gap("content", f"Contacts count {cnt_n} < 3")

call_raw = adb("content query --uri content://call_log/calls --projection _id 2>/dev/null | wc -l")
call_n = int(call_raw) if call_raw.strip().isdigit() else 0
log.info(f"  {'PASS' if call_n >= 10 else 'FAIL'} Call logs: {call_n}")
if call_n < 10:
    gap("content", f"Call logs count {call_n} < 10")

gal_raw = adb("ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l")
gal_n = int(gal_raw) if gal_raw.strip().isdigit() else 0
log.info(f"  {'PASS' if gal_n >= 1 else 'FAIL'} Gallery: {gal_n}")
if gal_n < 1:
    gap("content", f"Gallery count {gal_n}")

wifi = adb("ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null")
log.info(f"  {'PASS' if wifi else 'FAIL'} WiFi config")
if not wifi:
    gap("content", "WifiConfigStore.xml missing")

# --- 7f. Google Account ---
log.info("\n[Account]")
accts = adb('sqlite3 /data/system_ce/0/accounts_ce.db "SELECT name, type FROM accounts" 2>/dev/null')
if "com.google" in accts:
    log.info(f"  PASS Google account: {accts}")
else:
    gap("account", "No com.google account in accounts_ce.db")

# --- 7g. /proc stealth (R2 mountinfo enhancement) ---
log.info("\n[Proc] stealth")
mountinfo = adb("cat /proc/self/mountinfo 2>/dev/null | grep -i titan")
if mountinfo:
    gap("proc", f"Titan bind-mounts visible in mountinfo: {mountinfo[:100]}")
else:
    log.info("  PASS mountinfo clean (no titan traces)")

mounts = adb("cat /proc/mounts 2>/dev/null | grep -i titan")
if mounts:
    gap("proc", f"Titan traces in /proc/mounts: {mounts[:100]}")
else:
    log.info("  PASS /proc/mounts clean")

cmdline = adb("cat /proc/cmdline 2>/dev/null")
for suspect in ["vsoc", "cuttlefish", "virtio", "goldfish"]:
    if suspect in cmdline.lower():
        gap("proc", f"/proc/cmdline contains '{suspect}'")
log.info(f"  cmdline check done")

# --- 7h. Device identity coherence ---
log.info("\n[Identity] coherence")
brand = adb("getprop ro.product.brand")
device = adb("getprop ro.product.device")
fingerprint = adb("getprop ro.build.fingerprint")
log.info(f"  brand={brand} device={device}")
log.info(f"  fingerprint={fingerprint}")
if "cuttlefish" in (brand + device + fingerprint).lower():
    gap("identity", "Cuttlefish identity not patched")
if "vsoc" in (brand + device + fingerprint).lower():
    gap("identity", "vsoc identity leak")

serial = adb("getprop ro.serialno")
log.info(f"  serial={serial}")
if not serial or serial == "CUTTLEFISHCVD011":
    gap("identity", f"Default Cuttlefish serial: {serial}")

# --- 7i. SELinux ---
selinux = adb("getenforce 2>/dev/null")
log.info(f"  SELinux: {selinux}")
if selinux.lower() != "enforcing":
    gap("selinux", f"SELinux not enforcing: {selinux}")

# --- 7j. Sensor presence ---
log.info("\n[Sensors]")
sensors = adb("dumpsys sensorservice 2>/dev/null | grep -c 'active'")
log.info(f"  Active sensors: {sensors}")

# --- 7k. Call log burst distribution (R5 Poisson clustering) ---
log.info("\n[Behavioral] Poisson burst analysis")
call_dates = adb("content query --uri content://call_log/calls --projection date --sort 'date ASC' 2>/dev/null | head -50")
date_matches = re.findall(r'date=(\d+)', call_dates)
if len(date_matches) >= 10:
    timestamps = [int(d) for d in date_matches]
    intervals = [(timestamps[i+1] - timestamps[i]) / 1000 for i in range(len(timestamps)-1)]
    short_gaps = sum(1 for i in intervals if i < 300)  # < 5 min
    burst_pct = short_gaps / len(intervals) * 100 if intervals else 0
    log.info(f"  Call intervals: {len(intervals)}, burst(<5min): {short_gaps} ({burst_pct:.0f}%)")
    if burst_pct < 5:
        warn("No Poisson burst clustering detected in call logs")
else:
    warn(f"Too few call logs ({len(date_matches)}) for burst analysis")

# --- 7l. Storage encryption (Phase 19) ---
log.info("\n[Storage] encryption masking")
crypto_state = adb("getprop ro.crypto.state")
log.info(f"  {'PASS' if crypto_state == 'encrypted' else 'FAIL'} ro.crypto.state={crypto_state}")
if crypto_state != "encrypted":
    gap("patch", "ro.crypto.state not encrypted (emulator detection)")

# --- 7m. Process stealth (Phase 20) ---
log.info("\n[Process] stealth")
cf_procs = adb("ps -eo args 2>/dev/null | grep -iE 'cuttlefish|cvd_internal' | grep -v grep | grep -vF '['")
if cf_procs.strip():
    gap("proc", f"Cuttlefish processes visible: {cf_procs.strip()[:80]}")
else:
    log.info("  PASS no cuttlefish/cvd processes visible")

# --- 7n. Audio subsystem (Phase 21) ---
log.info("\n[Audio] subsystem scrub")
asound = adb("cat /proc/asound/cards 2>/dev/null")
if "virtio" in asound.lower():
    gap("patch", "virtio_snd visible in /proc/asound/cards")
else:
    log.info("  PASS /proc/asound/cards clean")

# --- 7o. Input behavior (Phase 22) ---
log.info("\n[Input] kinematic behavior")
typing_delay = adb("getprop persist.sys.input.typing_delay")
touch_jitter = adb("getprop persist.sys.input.touch_jitter")
log.info(f"  typing_delay={typing_delay} touch_jitter={touch_jitter}")
if not typing_delay:
    warn("persist.sys.input.typing_delay not set")
if not touch_jitter:
    warn("persist.sys.input.touch_jitter not set")

# --- 7p. Kernel hardening (Phase 23) ---
log.info("\n[Kernel] execution hardening")
perf_paranoid = adb("cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null").strip()
log.info(f"  perf_event_paranoid={perf_paranoid}")
try:
    if int(perf_paranoid) < 3:
        warn(f"perf_event_paranoid={perf_paranoid} (want >=3)")
except ValueError:
    warn(f"Cannot read perf_event_paranoid: {perf_paranoid}")

debugfs_mounted = adb("mount | grep debugfs 2>/dev/null").strip()
if debugfs_mounted:
    warn("debugfs still mounted (detection surface)")
else:
    log.info("  PASS debugfs unmounted")

# --- 7q. IPv6 disable ---
log.info("\n[Network] IPv6 hardening")
ip6_policy = adb("ip6tables -L INPUT 2>/dev/null | head -1")
if "DROP" in ip6_policy:
    log.info("  PASS IPv6 INPUT policy DROP")
else:
    warn("IPv6 not fully disabled (ip6tables INPUT not DROP)")

# --- 7r. Patch persistence ---
log.info("\n[Persistence] patch hook")
recovery_sh = adb("cat /system/bin/install-recovery.sh 2>/dev/null")
service_d = adb("ls /data/adb/service.d/99-titan-patch.sh 2>/dev/null")
if "99-titan-patch" in recovery_sh:
    log.info("  PASS install-recovery.sh hook present")
elif service_d.strip():
    log.info("  PASS /data/adb/service.d/99-titan-patch.sh present (erofs fallback)")
else:
    warn("No patch persistence hook found (install-recovery.sh or service.d)")

# --- 7s. GSF MD5 alignment ---
log.info("\n[GSF] identity alignment")
android_id = adb("settings get secure android_id").strip()
checkin_xml = adb("cat /data/data/com.google.android.gms/shared_prefs/CheckinService.xml 2>/dev/null")
if android_id and "deviceId" in checkin_xml:
    expected_gsf = hashlib.md5(android_id.encode()).hexdigest()[:16]
    if expected_gsf in checkin_xml:
        log.info(f"  PASS GSF deviceId=md5(android_id)={expected_gsf}")
    else:
        warn(f"GSF deviceId not MD5 of android_id ({expected_gsf})")
else:
    warn("Cannot verify GSF alignment (missing data)")


# ═══════════════════════════════════════════════════════════════════
# FINAL GAP REPORT
# ═══════════════════════════════════════════════════════════════════
section("FINAL GAP REPORT")

# Categorize
critical = [(c, d) for c, d in gaps if c in ("forge", "inject", "patch", "audit_fail", "proc", "identity", "selinux")]
moderate = [(c, d) for c, d in gaps if c in ("gpay", "gpay_prefs", "playstore", "chrome", "wallet", "wallet_verify", "account", "trust_check")]
cosmetic = [(c, d) for c, d in gaps if c not in dict(critical + moderate)]

log.info(f"\n  Trust Score: {trust_score}/100 ({trust_grade})")
log.info(f"  Total Gaps: {len(gaps)}")
log.info(f"    Critical: {len(critical)}")
log.info(f"    Moderate: {len(moderate)}")
log.info(f"    Cosmetic: {len(cosmetic)}")
log.info(f"  Warnings: {len(warnings)}")

if critical:
    log.info(f"\n--- CRITICAL ({len(critical)}) ---")
    for i, (c, d) in enumerate(critical, 1):
        log.info(f"  {i}. [{c}] {d}")

if moderate:
    log.info(f"\n--- MODERATE ({len(moderate)}) ---")
    for i, (c, d) in enumerate(moderate, 1):
        log.info(f"  {i}. [{c}] {d}")

if cosmetic:
    log.info(f"\n--- COSMETIC ({len(cosmetic)}) ---")
    for i, (c, d) in enumerate(cosmetic, 1):
        log.info(f"  {i}. [{c}] {d}")

if warnings:
    log.info(f"\n--- WARNINGS ({len(warnings)}) ---")
    for i, w in enumerate(warnings, 1):
        log.info(f"  {i}. {w}")

if not gaps:
    log.info("\n  ZERO GAPS — ALL CHECKS PASSED")

log.info(f"\n{'='*65}")
log.info(f"  E2E COMPLETE — {len(gaps)} gaps found")
log.info(f"{'='*65}")
