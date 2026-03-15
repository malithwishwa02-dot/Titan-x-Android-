"""
Titan V11.3 — Trust Scorer
Canonical trust score computation for device profile completeness.
Single implementation used by genesis trust-score endpoint and provision jobs.
"""

import logging
from typing import Any, Dict

from adb_utils import adb_shell

logger = logging.getLogger("titan.trust-scorer")


def _safe_int(raw: str) -> int:
    """Parse ADB output to int, returning 0 on failure."""
    s = (raw or "").strip()
    return int(s) if s.isdigit() else 0


def compute_trust_score(adb_target: str) -> Dict[str, Any]:
    """Compute trust score for a device. Returns full report dict.

    Runs 14 weighted checks via ADB and returns:
        trust_score (0-100 normalized), raw_score, max_score,
        grade (A+ to F), and per-check details.
    """
    t = adb_target
    checks = {}
    score = 0

    # 1. Google account present (weight: 15)
    has_google = bool(adb_shell(t, "ls /data/system_ce/0/accounts_ce.db 2>/dev/null"))
    checks["google_account"] = {"present": has_google, "weight": 15}
    if has_google:
        score += 15

    # 2. Contacts populated (weight: 8)
    contacts_n = _safe_int(adb_shell(t, "content query --uri content://contacts/phones --projection _id | wc -l"))
    checks["contacts"] = {"count": contacts_n, "weight": 8}
    if contacts_n >= 5:
        score += 8

    # 3. Chrome cookies exist (weight: 8)
    has_cookies = bool(adb_shell(t, "ls /data/data/com.android.chrome/app_chrome/Default/Cookies 2>/dev/null"))
    checks["chrome_cookies"] = {"present": has_cookies, "weight": 8}
    if has_cookies:
        score += 8

    # 4. Chrome history exists (weight: 8)
    has_history = bool(adb_shell(t, "ls /data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null"))
    checks["chrome_history"] = {"present": has_history, "weight": 8}
    if has_history:
        score += 8

    # 5. Gallery has photos (weight: 5)
    gallery_n = _safe_int(adb_shell(t, "ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l"))
    checks["gallery"] = {"count": gallery_n, "weight": 5}
    if gallery_n >= 3:
        score += 5

    # 6. Google Pay wallet data — deep check (weight: 12)
    tapandpay_path = "/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db"
    has_wallet = bool(adb_shell(t, f"ls {tapandpay_path} 2>/dev/null"))
    wallet_tokens = 0
    if has_wallet:
        wallet_tokens = _safe_int(adb_shell(t, f"sqlite3 {tapandpay_path} 'SELECT COUNT(*) FROM tokens' 2>/dev/null"))
    wallet_valid = has_wallet and wallet_tokens > 0
    checks["google_pay"] = {"present": has_wallet, "tokens": wallet_tokens, "valid": wallet_valid, "weight": 12}
    if wallet_valid:
        score += 12

    # 6b. NFC prefs (informational, weight: 0)
    nfc_prefs = adb_shell(t, "cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml 2>/dev/null")
    checks["nfc_tap_pay"] = {"present": "nfc_enabled" in (nfc_prefs or ""), "weight": 0}

    # 6c. GMS billing state (informational, weight: 0)
    gms_wallet = adb_shell(t, "cat /data/data/com.google.android.gms/shared_prefs/wallet_instrument_prefs.xml 2>/dev/null")
    checks["gms_billing_sync"] = {"present": "wallet_setup_complete" in (gms_wallet or ""), "weight": 0}

    # 6d. Keybox loaded (informational, weight: 0)
    keybox_prop = adb_shell(t, "getprop persist.titan.keybox.loaded")
    has_keybox = keybox_prop.strip() == "1" if keybox_prop else False
    checks["keybox"] = {"present": has_keybox, "loaded": has_keybox, "weight": 0}

    # 7. Play Store library (weight: 8)
    has_library = bool(adb_shell(t, "ls /data/data/com.android.vending/databases/library.db 2>/dev/null"))
    checks["play_store_library"] = {"present": has_library, "weight": 8}
    if has_library:
        score += 8

    # 8. WiFi networks saved (weight: 4)
    has_wifi = bool(adb_shell(t, "ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null"))
    checks["wifi_networks"] = {"present": has_wifi, "weight": 4}
    if has_wifi:
        score += 4

    # 9. SMS present (weight: 7)
    sms_n = _safe_int(adb_shell(t, "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db 'SELECT COUNT(*) FROM sms' 2>/dev/null"))
    checks["sms"] = {"count": sms_n, "weight": 7}
    if sms_n >= 5:
        score += 7

    # 10. Call logs present (weight: 7)
    calls_raw = adb_shell(t, "sqlite3 /data/data/com.android.providers.contacts/databases/calllog.db 'SELECT COUNT(*) FROM calls' 2>/dev/null")
    calls_n = _safe_int(calls_raw)
    if calls_n == 0:
        calls_n = _safe_int(adb_shell(t, "content query --uri content://call_log/calls --projection _id 2>/dev/null | wc -l"))
    checks["call_logs"] = {"count": calls_n, "weight": 7}
    if calls_n >= 10:
        score += 7

    # 11. App SharedPrefs populated (weight: 8)
    has_app_prefs = bool(adb_shell(t, "ls /data/data/com.instagram.android/shared_prefs/ 2>/dev/null"))
    checks["app_data"] = {"present": has_app_prefs, "weight": 8}
    if has_app_prefs:
        score += 8

    # 12. Chrome signed in (weight: 5)
    has_chrome_prefs = bool(adb_shell(t, "ls /data/data/com.android.chrome/app_chrome/Default/Preferences 2>/dev/null"))
    checks["chrome_signin"] = {"present": has_chrome_prefs, "weight": 5}
    if has_chrome_prefs:
        score += 5

    # 13. Autofill data (weight: 5)
    has_autofill = bool(adb_shell(t, "ls '/data/data/com.android.chrome/app_chrome/Default/Web Data' 2>/dev/null"))
    checks["autofill"] = {"present": has_autofill, "weight": 5}
    if has_autofill:
        score += 5

    # 14. GSM / SIM alignment (weight: 8)
    gsm_state = adb_shell(t, "getprop gsm.sim.state")
    gsm_operator = adb_shell(t, "getprop gsm.sim.operator.alpha")
    gsm_mcc_mnc = adb_shell(t, "getprop gsm.sim.operator.numeric")
    gsm_ok = (
        (gsm_state or "").strip() == "READY"
        and len((gsm_operator or "").strip()) > 0
        and len((gsm_mcc_mnc or "").strip()) >= 5
    )
    checks["gsm_sim"] = {
        "state": (gsm_state or "").strip(),
        "operator": (gsm_operator or "").strip(),
        "mcc_mnc": (gsm_mcc_mnc or "").strip(),
        "ok": gsm_ok,
        "weight": 8,
    }
    if gsm_ok:
        score += 8

    max_score = 108
    normalized = min(100, round(score / max_score * 100))

    if normalized >= 90:
        grade = "A+"
    elif normalized >= 80:
        grade = "A"
    elif normalized >= 65:
        grade = "B"
    elif normalized >= 50:
        grade = "C"
    elif normalized >= 30:
        grade = "D"
    else:
        grade = "F"

    return {
        "trust_score": normalized,
        "raw_score": score,
        "max_score": max_score,
        "grade": grade,
        "checks": checks,
    }
