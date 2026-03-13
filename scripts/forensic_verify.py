#!/usr/bin/env python3
"""
Deep Forensic Verification — Jovany Owens Device
Checks timestamp aging, wallet CC consistency, account coherence, and anomalies.
"""
import json, subprocess, time, re, os

ADB = "127.0.0.1:5555"

def sh(cmd, timeout=15):
    try:
        r = subprocess.run(["adb", "-s", ADB, "shell", cmd],
                          capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except:
        return ""

def sql(db, query):
    return sh(f'sqlite3 {db} "{query}"')

now_ms = int(time.time() * 1000)
now_s = int(time.time())
CHROME_EPOCH = 11644473600000000  # Chrome epoch offset in microseconds

print("=" * 65)
print("  DEEP FORENSIC VERIFICATION -- Jovany Owens Device")
print("=" * 65)

anomalies = []
checks_pass = 0
checks_total = 0

def check(name, passed, detail=""):
    global checks_pass, checks_total
    checks_total += 1
    if passed:
        checks_pass += 1
        print(f"  [PASS] {name}: {detail}")
    else:
        anomalies.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")

# ══════════════════════════════════════════════════════════════
# A. TIMESTAMP AGING ANALYSIS
# ══════════════════════════════════════════════════════════════
print("\n== A. TIMESTAMP AGING ANALYSIS ==")

# Call logs
call_range = sh("content query --uri content://call_log/calls --projection date --sort 'date ASC' 2>/dev/null | head -1")
call_oldest_match = re.search(r'date=(\d+)', call_range)
call_newest = sh("content query --uri content://call_log/calls --projection date --sort 'date DESC' 2>/dev/null | head -1")
call_newest_match = re.search(r'date=(\d+)', call_newest)

if call_oldest_match and call_newest_match:
    oldest_ms = int(call_oldest_match.group(1))
    newest_ms = int(call_newest_match.group(1))
    span_days = (newest_ms - oldest_ms) / (86400 * 1000)
    age_days = (now_ms - oldest_ms) / (86400 * 1000)
    check("Call log span", span_days > 30, f"{span_days:.0f} days span, oldest {age_days:.0f}d ago")
else:
    check("Call log span", False, "Could not parse dates")

# SMS
sms_oldest = sh("content query --uri content://sms --projection date --sort 'date ASC' 2>/dev/null | head -1")
sms_newest = sh("content query --uri content://sms --projection date --sort 'date DESC' 2>/dev/null | head -1")
sms_old_match = re.search(r'date=(\d+)', sms_oldest)
sms_new_match = re.search(r'date=(\d+)', sms_newest)
if sms_old_match and sms_new_match:
    sms_span = (int(sms_new_match.group(1)) - int(sms_old_match.group(1))) / (86400*1000)
    sms_age = (now_ms - int(sms_old_match.group(1))) / (86400*1000)
    check("SMS span", sms_span > 5, f"{sms_span:.0f} days span, oldest {sms_age:.0f}d ago")
else:
    check("SMS span", False, "Could not parse")

# Chrome cookies
cookie_range = sql("/data/data/com.android.chrome/app_chrome/Default/Cookies",
                   "SELECT MIN(creation_utc), MAX(creation_utc) FROM cookies")
if cookie_range and "|" in cookie_range:
    parts = cookie_range.split("|")
    min_ck = int(parts[0])
    max_ck = int(parts[1])
    min_unix = (min_ck - CHROME_EPOCH) / 1000000
    max_unix = (max_ck - CHROME_EPOCH) / 1000000
    cookie_span = (max_unix - min_unix) / 86400
    cookie_age = (now_s - min_unix) / 86400
    check("Cookie span", cookie_span > 30, f"{cookie_span:.0f} days span, oldest {cookie_age:.0f}d ago")
else:
    check("Cookie span", False, f"raw: {cookie_range}")

# Chrome history
hist_range = sql("/data/data/com.android.chrome/app_chrome/Default/History",
                 "SELECT MIN(last_visit_time), MAX(last_visit_time) FROM urls")
if hist_range and "|" in hist_range:
    parts = hist_range.split("|")
    min_h = int(parts[0])
    max_h = int(parts[1])
    min_unix = (min_h - CHROME_EPOCH) / 1000000
    max_unix = (max_h - CHROME_EPOCH) / 1000000
    hist_span = (max_unix - min_unix) / 86400
    hist_age = (now_s - min_unix) / 86400
    check("History span", hist_span > 30, f"{hist_span:.0f} days span, oldest {hist_age:.0f}d ago")
else:
    check("History span", False, f"raw: {hist_range}")

# Gallery EXIF dates (check file modified times)
gallery_oldest = sh("stat -c %Y /sdcard/DCIM/Camera/*.jpg 2>/dev/null | sort -n | head -1")
gallery_newest = sh("stat -c %Y /sdcard/DCIM/Camera/*.jpg 2>/dev/null | sort -n | tail -1")
if gallery_oldest and gallery_newest:
    gal_span = (int(gallery_newest) - int(gallery_oldest)) / 86400
    gal_age = (now_s - int(gallery_oldest)) / 86400
    check("Gallery age", gal_span > 10, f"{gal_span:.0f} days span, oldest {gal_age:.0f}d ago")
else:
    check("Gallery age", False, "Could not stat")

# ══════════════════════════════════════════════════════════════
# B. WALLET CC VISIBILITY & CONSISTENCY
# ══════════════════════════════════════════════════════════════
print("\n== B. WALLET CC VISIBILITY & CONSISTENCY ==")

# Google Pay
gpay_tokens = sql("/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db",
                  "SELECT card_description, issuer_name, dpan_last4, is_default FROM tokens")
gpay_count = sql("/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db",
                 "SELECT COUNT(*) FROM tokens")
tc = int(gpay_count) if gpay_count.isdigit() else 0
check("Google Pay tokens", tc > 0, f"{tc} token(s): {gpay_tokens}")

# Play Store
coin_xml = sh("cat /data/data/com.android.vending/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml 2>/dev/null")
has_payment = "has_payment_method" in coin_xml and "true" in coin_xml
last4_match = re.search(r'last4.*?value="(\d+)"', coin_xml)
play_last4 = last4_match.group(1) if last4_match else "?"
check("Play Store billing", has_payment, f"last4={play_last4}")

# Chrome credit card
chrome_cc = sql("'/data/data/com.android.chrome/app_chrome/Default/Web Data'",
                "SELECT name_on_card, expiration_month, expiration_year, nickname FROM credit_cards")
check("Chrome credit card", bool(chrome_cc), chrome_cc)

# Chrome autofill profile
autofill_count = sql("'/data/data/com.android.chrome/app_chrome/Default/Web Data'",
                     "SELECT COUNT(*) FROM autofill_profiles")
autofill_names = sql("'/data/data/com.android.chrome/app_chrome/Default/Web Data'",
                     "SELECT full_name FROM autofill_profile_names")
apc = int(autofill_count) if autofill_count.isdigit() else 0
check("Chrome autofill profiles", apc > 0, f"{apc} profile(s): {autofill_names}")

# token_metadata view
tm_count = sql("/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db",
               "SELECT COUNT(*) FROM token_metadata")
tmc = int(tm_count) if tm_count.isdigit() else 0
check("token_metadata view", tmc > 0, f"{tmc} entries")

# NFC prefs
nfc_prefs = sh("cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml 2>/dev/null")
check("NFC prefs", "nfc_setup_done" in nfc_prefs, "nfc_on_prefs.xml present")

# Google Pay default settings
gpay_prefs = sh("cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/default_settings.xml 2>/dev/null")
for key in ["wallet_setup_complete", "nfc_enabled", "tap_and_pay_setup_complete", "default_payment_instrument_id"]:
    check(f"GPay pref: {key}", key in gpay_prefs, "present" if key in gpay_prefs else "MISSING")

# ══════════════════════════════════════════════════════════════
# C. ACCOUNT COHERENCE
# ══════════════════════════════════════════════════════════════
print("\n== C. ACCOUNT COHERENCE ==")

accounts = sql("/data/system_ce/0/accounts_ce.db", "SELECT name, type FROM accounts")
check("Google accounts", "com.google" in accounts, accounts.replace("\n", " | "))

gpay_user_match = re.search(r'user_account">(.*?)<', gpay_prefs)
gpay_user = gpay_user_match.group(1) if gpay_user_match else "?"
billing_match = re.search(r'billing_account">(.*?)<', coin_xml)
billing_user = billing_match.group(1) if billing_match else "?"
print(f"  Google Pay user: {gpay_user}")
print(f"  Play Store billing: {billing_user}")
print(f"  Chrome autofill: {autofill_names}")
check("Billing matches an account", billing_user in accounts, f"{billing_user}")

# ══════════════════════════════════════════════════════════════
# D. DATA VOLUME CHECKS
# ══════════════════════════════════════════════════════════════
print("\n== D. DATA VOLUME & REALISM ==")

contacts_n = sh("content query --uri content://contacts/phones --projection _id | wc -l")
cn = int(contacts_n) if contacts_n.strip().isdigit() else 0
check("Contacts volume", cn >= 10, f"{cn} contacts")

calls_n = sh("content query --uri content://call_log/calls --projection _id | wc -l")
cln = int(calls_n) if calls_n.strip().isdigit() else 0
check("Call logs volume", cln >= 50, f"{cln} call logs")

sms_n = sh("content query --uri content://sms --projection _id | wc -l")
sn = int(sms_n) if sms_n.strip().isdigit() else 0
check("SMS volume", sn >= 5, f"{sn} messages")

cookies_n = sql("/data/data/com.android.chrome/app_chrome/Default/Cookies", "SELECT COUNT(*) FROM cookies")
ckn = int(cookies_n) if cookies_n.isdigit() else 0
check("Cookie volume", ckn >= 20, f"{ckn} cookies")

history_n = sql("/data/data/com.android.chrome/app_chrome/Default/History", "SELECT COUNT(*) FROM urls")
hn = int(history_n) if history_n.isdigit() else 0
check("History volume", hn >= 100, f"{hn} URLs")

gallery_n = sh("ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l")
gn = int(gallery_n) if gallery_n.strip().isdigit() else 0
check("Gallery volume", gn >= 10, f"{gn} photos")

wifi = sh("cat /data/misc/wifi/WifiConfigStore.xml 2>/dev/null")
wifi_ssids = re.findall(r'SSID">&quot;(.*?)&quot;', wifi)
check("WiFi networks", len(wifi_ssids) >= 2, f"{len(wifi_ssids)} SSIDs: {', '.join(wifi_ssids)}")

# Play Store library
lib_count = sql("/data/data/com.android.vending/databases/library.db", "SELECT COUNT(*) FROM ownership")
lc = int(lib_count) if lib_count.isdigit() else 0
check("Play Store library", lc >= 5, f"{lc} apps purchased")

# App SharedPrefs
for pkg, name in [("com.instagram.android", "Instagram"), ("com.whatsapp", "WhatsApp"),
                   ("com.squareup.cash", "Cash App"), ("com.venmo", "Venmo")]:
    p = sh(f"ls /data/data/{pkg}/shared_prefs/ 2>/dev/null")
    check(f"App data: {name}", bool(p), "prefs present" if p else "MISSING")

# ══════════════════════════════════════════════════════════════
# E. DUPLICATE / ANOMALY DETECTION
# ══════════════════════════════════════════════════════════════
print("\n== E. ANOMALY DETECTION ==")

# Check for duplicate contacts
dup_contacts = sh("content query --uri content://contacts/phones --projection display_name 2>/dev/null | sort | uniq -c | sort -rn | head -5")
print(f"  Top contact duplicates:\n{dup_contacts}")

# Check for suspicious cookie domains
suspicious_cookies = sql("/data/data/com.android.chrome/app_chrome/Default/Cookies",
                         "SELECT DISTINCT host_key FROM cookies WHERE host_key LIKE '%test%' OR host_key LIKE '%fake%' OR host_key LIKE '%titan%'")
check("No suspicious cookies", not suspicious_cookies, suspicious_cookies if suspicious_cookies else "clean")

# Check for future-dated timestamps
future_calls = sh("content query --uri content://call_log/calls --projection date --sort 'date DESC' 2>/dev/null | head -1")
future_match = re.search(r'date=(\d+)', future_calls)
if future_match:
    newest_call = int(future_match.group(1))
    diff = newest_call - now_ms
    check("No future-dated calls", diff < 86400000, f"newest call {diff/1000:.0f}s from now")

# Check browsing history for suspicious patterns
test_urls = sql("/data/data/com.android.chrome/app_chrome/Default/History",
                "SELECT COUNT(*) FROM urls WHERE url LIKE '%test%' OR url LIKE '%fake%' OR url LIKE '%titan%'")
tn = int(test_urls) if test_urls.isdigit() else 0
check("No test/fake URLs in history", tn == 0, f"{tn} suspicious URLs")

# ══════════════════════════════════════════════════════════════
# FINAL REPORT
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 65)
print("FORENSIC VERIFICATION REPORT")
print("=" * 65)
print(f"  Device: dev-us1 (Samsung S25 Ultra, T-Mobile US)")
print(f"  Checks Passed: {checks_pass}/{checks_total}")
print(f"  Anomalies: {len(anomalies)}")
if anomalies:
    for i, a in enumerate(anomalies, 1):
        print(f"    {i}. {a}")
else:
    print("  [OK] ZERO ANOMALIES -- DEVICE IS REAL-WORLD OPERATIONAL")

# Build summary for AI audit
summary = {
    "device": "Samsung S25 Ultra, T-Mobile US, Android 14",
    "accounts": accounts,
    "contacts": cn, "call_logs": cln, "sms": sn,
    "cookies": ckn, "history_urls": hn, "gallery": gn,
    "wifi_ssids": wifi_ssids,
    "google_pay": gpay_tokens,
    "play_store_billing": f"Visa ****{play_last4}",
    "chrome_cc": chrome_cc,
    "autofill": autofill_names,
    "play_library": lc,
    "checks_passed": f"{checks_pass}/{checks_total}",
    "anomalies": anomalies,
}
# Save for AI audit
with open("/tmp/device_summary.json", "w") as f:
    json.dump(summary, f, indent=2)
print(f"\n  Summary saved to /tmp/device_summary.json for AI audit")
print("=" * 65)
