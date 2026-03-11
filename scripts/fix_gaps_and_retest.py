#!/usr/bin/env python3
"""
Fix all 3 wallet gaps found by the console test, then re-verify.
1. Re-provision Play Store billing COIN.xml with full payment fields
2. Add token_metadata alias view in tapandpay.db for app compatibility
3. Add nfc_on_prefs.xml symlink for apps that check that path
Then re-run full wallet probe with corrected checks.
"""
import json, logging, os, sqlite3, subprocess, sys, tempfile, time

sys.path.insert(0, '/opt/titan-v11.3-device/core')
sys.path.insert(0, '/opt/titan-v11.3-device/server')
sys.path.insert(0, '/root/titan-v11-release/core')
os.environ['TITAN_DATA'] = '/opt/titan/data'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('gapfix')

ADB_TARGET = "127.0.0.1:5555"

def adb_cmd(args, timeout=15):
    r = subprocess.run(["adb", "-s", ADB_TARGET] + args,
                      capture_output=True, text=True, timeout=timeout)
    return r.returncode == 0, r.stdout.strip()

def adb_shell(cmd, timeout=15):
    return adb_cmd(["shell", cmd], timeout)

def adb_push(local, remote):
    return adb_cmd(["push", local, remote])

# Ensure root
adb_shell("echo root")
subprocess.run(["adb", "-s", ADB_TARGET, "root"], capture_output=True, timeout=10)
time.sleep(1)

# ═══════════════════════════════════════════════════════════════════
# FIX 1: Play Store billing COIN.xml — write full payment prefs
# ═══════════════════════════════════════════════════════════════════
log.info("═══ FIX 1: Play Store billing COIN.xml ═══")

billing_xml = """<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="billing_client_version">6.1.0</string>
    <boolean name="has_payment_method" value="true" />
    <string name="default_payment_method_type">Visa</string>
    <string name="default_payment_method_last4">0405</string>
    <string name="default_payment_method_description">Visa ····0405</string>
    <string name="billing_account">ranpatidewage62@gmail.com</string>
    <string name="default_instrument_id">instrument_visa_0405</string>
    <boolean name="purchase_requires_auth" value="false" />
</map>"""

with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as f:
    f.write(billing_xml)
    tmp_billing = f.name

remote_billing = "/data/data/com.android.vending/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml"
adb_shell("am force-stop com.android.vending")
ok, out = adb_push(tmp_billing, remote_billing)
if ok:
    # Fix ownership
    _, uid = adb_shell("stat -c %U /data/data/com.android.vending 2>/dev/null")
    if uid:
        adb_shell(f"chown {uid}:{uid} {remote_billing}")
    adb_shell(f"chmod 660 {remote_billing}")
    log.info("  COIN.xml written with full payment method fields")
else:
    log.error(f"  Failed to push COIN.xml: {out}")
os.unlink(tmp_billing)

# ═══════════════════════════════════════════════════════════════════
# FIX 2: Google Pay — add token_metadata VIEW for app compat
# ═══════════════════════════════════════════════════════════════════
log.info("═══ FIX 2: Google Pay tapandpay.db — add token_metadata view ═══")

tap_db = "/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db"
tmp_db = tempfile.mktemp(suffix=".db")
ok, _ = adb_cmd(["pull", tap_db, tmp_db])
if ok:
    conn = sqlite3.connect(tmp_db)
    c = conn.cursor()
    # Check existing tables
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' OR type='view'").fetchall()]
    log.info(f"  Existing: {tables}")

    # Add token_metadata as a view aliasing tokens (some Google Pay versions use this name)
    if "token_metadata" not in tables:
        try:
            c.execute("CREATE VIEW IF NOT EXISTS token_metadata AS SELECT * FROM tokens")
            conn.commit()
            log.info("  Created token_metadata VIEW → tokens")
        except Exception as e:
            log.warning(f"  Could not create view: {e}")
    else:
        log.info("  token_metadata already exists")

    # Verify card data
    rows = c.execute("SELECT dpan, fpan_last4, card_description, is_default, status FROM tokens").fetchall()
    log.info(f"  Tokens: {len(rows)}")
    for r in rows:
        log.info(f"    DPAN=****{r[0][-4:]}, last4={r[1]}, desc={r[2]}, default={r[3]}, status={r[4]}")
    conn.close()

    # Push back
    adb_shell("am force-stop com.google.android.apps.walletnfcrel")
    ok, _ = adb_push(tmp_db, tap_db)
    if ok:
        _, uid = adb_shell("stat -c %U /data/data/com.google.android.apps.walletnfcrel 2>/dev/null")
        if uid:
            adb_shell(f"chown {uid}:{uid} {tap_db}")
        adb_shell(f"chmod 660 {tap_db}")
        log.info("  tapandpay.db updated and pushed")
    os.unlink(tmp_db)
else:
    log.warning("  Could not pull tapandpay.db")

# ═══════════════════════════════════════════════════════════════════
# FIX 3: Google Pay — add nfc_on_prefs.xml for compat
# ═══════════════════════════════════════════════════════════════════
log.info("═══ FIX 3: Google Pay nfc_on_prefs.xml ═══")

nfc_xml = """<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="nfc_setup_done" value="true" />
    <boolean name="nfc_enabled" value="true" />
    <boolean name="tap_and_pay_enabled" value="true" />
    <boolean name="contactless_payments_enabled" value="true" />
    <string name="default_payment_app">com.google.android.apps.walletnfcrel</string>
</map>"""

with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as f:
    f.write(nfc_xml)
    tmp_nfc = f.name

remote_nfc = "/data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml"
ok, _ = adb_push(tmp_nfc, remote_nfc)
if ok:
    _, uid = adb_shell("stat -c %U /data/data/com.google.android.apps.walletnfcrel 2>/dev/null")
    if uid:
        adb_shell(f"chown {uid}:{uid} {remote_nfc}")
    adb_shell(f"chmod 660 {remote_nfc}")
    log.info("  nfc_on_prefs.xml written")
else:
    log.error(f"  Failed to push nfc_on_prefs.xml")
os.unlink(tmp_nfc)


# ═══════════════════════════════════════════════════════════════════
# RE-VERIFY: Full wallet probe with corrected checks
# ═══════════════════════════════════════════════════════════════════
log.info("")
log.info("═" * 65)
log.info("RE-VERIFICATION: Full Wallet Probe")
log.info("═" * 65)

gaps = []

# 1. Google Pay tapandpay.db
log.info("[1] Google Pay tapandpay.db")
_, tables_out = adb_shell("sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db \".tables\"")
log.info(f"    Tables: {tables_out}")
_, tokens_out = adb_shell("sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db \"SELECT COUNT(*) FROM tokens\"")
token_count = int(tokens_out.strip()) if tokens_out.strip().isdigit() else 0
if token_count > 0:
    log.info(f"    ✓ Tokens: {token_count}")
else:
    gaps.append("google_pay: no tokens in tapandpay.db")
    log.warning(f"    ✗ No tokens found")

# 2. Google Pay token_metadata (compat view)
_, tm_out = adb_shell("sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db \"SELECT COUNT(*) FROM token_metadata\"")
tm_count = int(tm_out.strip()) if tm_out.strip().isdigit() else 0
if tm_count > 0:
    log.info(f"    ✓ token_metadata view: {tm_count} rows")
else:
    gaps.append("google_pay: token_metadata view missing or empty")

# 3. Google Pay default_settings.xml
_, ds_out = adb_shell("cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/default_settings.xml 2>/dev/null")
if "wallet_setup_complete" in ds_out and "nfc_enabled" in ds_out:
    log.info("    ✓ default_settings.xml: wallet setup + NFC")
else:
    gaps.append("google_pay: default_settings.xml incomplete")

# 4. Google Pay nfc_on_prefs.xml
_, nfc_out = adb_shell("cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml 2>/dev/null")
if "nfc_setup_done" in nfc_out:
    log.info("    ✓ nfc_on_prefs.xml: NFC setup done")
else:
    gaps.append("google_pay: nfc_on_prefs.xml missing")

# 5. Play Store billing COIN.xml
log.info("[2] Play Store billing")
_, coin_out = adb_shell("cat /data/data/com.android.vending/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml 2>/dev/null")
if "has_payment_method" in coin_out and "default_payment_method_last4" in coin_out:
    log.info("    ✓ COIN.xml: payment method + last4")
else:
    gaps.append("play_store: COIN.xml missing payment method fields")
    log.warning(f"    ✗ COIN.xml incomplete")

# 6. Play Store library.db
_, lib_out = adb_shell("ls /data/data/com.android.vending/databases/library.db 2>/dev/null")
if lib_out:
    log.info("    ✓ library.db exists")
else:
    gaps.append("play_store: library.db missing")

# 7. Chrome Web Data (credit cards)
log.info("[3] Chrome autofill")
_, cc_out = adb_shell("sqlite3 '/data/data/com.android.chrome/app_chrome/Default/Web Data' \"SELECT COUNT(*) FROM credit_cards\" 2>/dev/null")
cc_count = int(cc_out.strip()) if cc_out.strip().isdigit() else 0
if cc_count > 0:
    log.info(f"    ✓ credit_cards: {cc_count}")
else:
    gaps.append("chrome: no credit_cards")

# 8. Chrome autofill profiles
_, ap_out = adb_shell("sqlite3 '/data/data/com.android.chrome/app_chrome/Default/Web Data' \"SELECT COUNT(*) FROM autofill_profiles\" 2>/dev/null")
ap_count = int(ap_out.strip()) if ap_out.strip().isdigit() else 0
log.info(f"    {'✓' if ap_count > 0 else '◌'} autofill_profiles: {ap_count}")
if ap_count == 0:
    gaps.append("chrome: no autofill_profiles (address not saved)")

# 9. Chrome Cookies
log.info("[4] Chrome browser data")
_, cookies_out = adb_shell("sqlite3 /data/data/com.android.chrome/app_chrome/Default/Cookies \"SELECT COUNT(*) FROM cookies\" 2>/dev/null")
cookie_count = int(cookies_out.strip()) if cookies_out.strip().isdigit() else 0
if cookie_count > 0:
    log.info(f"    ✓ Cookies: {cookie_count}")
else:
    gaps.append("chrome: no cookies")

# 10. Chrome History
_, hist_out = adb_shell("sqlite3 /data/data/com.android.chrome/app_chrome/Default/History \"SELECT COUNT(*) FROM urls\" 2>/dev/null")
hist_count = int(hist_out.strip()) if hist_out.strip().isdigit() else 0
if hist_count > 0:
    log.info(f"    ✓ History: {hist_count} URLs")
else:
    gaps.append("chrome: no history")

# 11. Google Account
log.info("[5] Google Account")
_, acct_out = adb_shell("sqlite3 /data/system_ce/0/accounts_ce.db \"SELECT name, type FROM accounts\" 2>/dev/null")
if "com.google" in acct_out:
    log.info(f"    ✓ Accounts: {acct_out}")
else:
    gaps.append("google_account: no com.google accounts")

# 12. SMS
log.info("[6] Content providers")
_, sms_out = adb_shell("content query --uri content://sms --projection _id | wc -l")
sms_n = int(sms_out.strip()) if sms_out.strip().isdigit() else 0
log.info(f"    {'✓' if sms_n >= 5 else '✗'} SMS: {sms_n}")
if sms_n < 5:
    gaps.append(f"sms: only {sms_n} (need >=5)")

# 13. Contacts
_, contacts_out = adb_shell("content query --uri content://contacts/phones --projection _id | wc -l")
contacts_n = int(contacts_out.strip()) if contacts_out.strip().isdigit() else 0
log.info(f"    ✓ Contacts: {contacts_n}")

# 14. Call logs
_, calls_out = adb_shell("content query --uri content://call_log/calls --projection _id | wc -l")
calls_n = int(calls_out.strip()) if calls_out.strip().isdigit() else 0
log.info(f"    ✓ Call logs: {calls_n}")

# 15. Gallery
_, gallery_out = adb_shell("ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l")
gallery_n = int(gallery_out.strip()) if gallery_out.strip().isdigit() else 0
log.info(f"    ✓ Gallery: {gallery_n} photos")

# 16. WiFi
_, wifi_out = adb_shell("ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null")
log.info(f"    {'✓' if wifi_out else '✗'} WiFi: {'EXISTS' if wifi_out else 'MISSING'}")
if not wifi_out:
    gaps.append("wifi: missing")

# 17. App data
log.info("[7] App SharedPrefs")
for pkg, name in [
    ("com.instagram.android", "Instagram"),
    ("com.whatsapp", "WhatsApp"),
    ("com.squareup.cash", "Cash App"),
]:
    _, p = adb_shell(f"ls /data/data/{pkg}/shared_prefs/ 2>/dev/null")
    log.info(f"    {'✓' if p else '◌'} {name}: {'OK' if p else 'not present'}")

# ═══════════════════════════════════════════════════════════════════
# Trust Score
# ═══════════════════════════════════════════════════════════════════
log.info("")
log.info("[8] Trust Score (via API)")
import urllib.request
try:
    req = urllib.request.Request("http://127.0.0.1:8080/api/genesis/trust-score/dev-us1")
    with urllib.request.urlopen(req, timeout=10) as r:
        ts = json.loads(r.read())
    log.info(f"    Trust Score: {ts['trust_score']}/100 ({ts['grade']})")
except Exception as e:
    log.error(f"    Trust score API error: {e}")

# ═══════════════════════════════════════════════════════════════════
# FINAL REPORT
# ═══════════════════════════════════════════════════════════════════
log.info("")
log.info("═" * 65)
log.info("FINAL GAP REPORT")
log.info("═" * 65)
if gaps:
    log.info(f"  Remaining gaps: {len(gaps)}")
    for i, g in enumerate(gaps, 1):
        log.info(f"    {i}. {g}")
else:
    log.info("  ✓ ZERO GAPS — All wallet targets verified!")
log.info("═" * 65)
