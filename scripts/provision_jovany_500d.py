#!/usr/bin/env python3
"""
Titan V11.3 — Full Device Provisioning: Jovany Owens 500-day Profile
Forges profile, injects into device, provisions wallet with CC data.

Run on VPS:
    cd /opt/titan-v11.3-device
    python3 scripts/provision_jovany_500d.py
"""

import json
import logging
import os
import subprocess
import sys
import time

# Ensure paths
sys.path.insert(0, "/opt/titan-v11.3-device/core")
sys.path.insert(0, "/opt/titan-v11.3-device/server")
sys.path.insert(0, "/root/titan-v11-release/core")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("titan.provision-jovany")

# ═══════════════════════════════════════════════════════════════════════
# PERSONA DATA
# ═══════════════════════════════════════════════════════════════════════

PERSONA = {
    "name": "Jovany Owens",
    "email": "ranpatidewage62@gmail.com",
    "phone": "+17078361915",
    "gender": "Male",
    "dob": "12/11/1959",
    "ssn": "219-19-0937",
    "country": "US",
    "archetype": "professional",
    "age_days": 500,
    "carrier": "tmobile_us",
    "location": "los_angeles",
    "device_model": "samsung_s25_ultra",
    "address": {
        "address": "1866 W 11th St",
        "city": "Los Angeles",
        "state": "California",
        "zip": "90006",
        "country": "US",
    },
}

# CC: 4638 5123 2034 0405|08|2029|051
CARD_DATA = {
    "number": "4638512320340405",
    "exp_month": 8,
    "exp_year": 2029,
    "cvv": "051",
    "cardholder": "Jovany Owens",
}

# Play Store login
PLAY_ACCOUNT = {
    "email": "ranpatidewage62@gmail.com",
    "password": "Chilaw@123",
}

# US wallet apps to install from Play Store
US_WALLET_APPS = [
    # Tier 1: Payment Wallets
    "com.google.android.apps.walletnfcrel",  # Google Pay / Wallet
    # Samsung Pay is pre-installed on Samsung devices
    # Tier 2: P2P / Banking
    "com.squareup.cash",       # Cash App
    "com.venmo",               # Venmo
    "com.paypal.android.p2pmobile",  # PayPal
    "com.zellepay.zelle",      # Zelle
    # Tier 3: Banking
    "com.chase.sig.android",   # Chase
    "com.wf.wellsfargomobile", # Wells Fargo
    "com.onedebit.chime",      # Chime
    "com.bankofamerica.cashpromobile",  # Bank of America
    "com.sofi.mobile",         # SoFi
    # Tier 4: BNPL
    "com.klarna.android",      # Klarna
    "com.afterpay.caportal",   # Afterpay
    "com.affirm.central",      # Affirm
    "com.quadpay.quadpay",     # Zip
    # Tier 5: Crypto
    "com.coinbase.android",    # Coinbase
    "com.binance.dev",         # Binance
    # Tier 6: Transfer
    "com.transferwise.android",  # Wise
]

ADB_TARGET = "127.0.0.1:5555"
DEVICE_ID = "dev-us1"


# ═══════════════════════════════════════════════════════════════════════
# ADB HELPERS
# ═══════════════════════════════════════════════════════════════════════

def adb(cmd, timeout=30):
    try:
        r = subprocess.run(
            f"adb -s {ADB_TARGET} {cmd}",
            shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, r.stdout.strip()
    except Exception as e:
        return False, str(e)


def adb_shell(cmd, timeout=15):
    ok, out = adb(f'shell "{cmd}"', timeout=timeout)
    return out if ok else ""


def adb_root():
    ok, out = adb("root", timeout=10)
    time.sleep(1)
    return ok or "already" in out.lower()


# ═══════════════════════════════════════════════════════════════════════
# STEP 1: FORGE 500-DAY PROFILE
# ═══════════════════════════════════════════════════════════════════════

def step1_forge_profile():
    logger.info("=" * 60)
    logger.info("STEP 1: Forging 500-day Jovany Owens profile")
    logger.info("=" * 60)

    from android_profile_forge import AndroidProfileForge

    forge = AndroidProfileForge()
    profile = forge.forge(
        persona_name=PERSONA["name"],
        persona_email=PERSONA["email"],
        persona_phone=PERSONA["phone"],
        country=PERSONA["country"],
        archetype=PERSONA["archetype"],
        age_days=PERSONA["age_days"],
        carrier=PERSONA["carrier"],
        location=PERSONA["location"],
        device_model=PERSONA["device_model"],
        persona_address=PERSONA["address"],
        persona_area_code="707",
        city_area_codes=["213", "323", "310", "818"],
    )

    profile_id = profile["id"]
    stats = profile["stats"]

    logger.info(f"Profile forged: {profile_id}")
    logger.info(f"  Name: {PERSONA['name']}")
    logger.info(f"  Email: {PERSONA['email']}")
    logger.info(f"  Phone: {PERSONA['phone']}")
    logger.info(f"  Age: {PERSONA['age_days']} days")
    logger.info(f"  Stats: {json.dumps(stats, indent=2)}")

    return profile_id, profile


# ═══════════════════════════════════════════════════════════════════════
# STEP 2: INJECT PROFILE + CC INTO DEVICE
# ═══════════════════════════════════════════════════════════════════════

def step2_inject_profile(profile_id, profile):
    logger.info("=" * 60)
    logger.info("STEP 2: Injecting profile + CC into device")
    logger.info("=" * 60)

    adb_root()

    # Stop apps to avoid DB locks
    for pkg in ["com.android.chrome", "com.google.android.gms",
                "com.android.vending", "com.google.android.apps.walletnfcrel"]:
        adb_shell(f"am force-stop {pkg}")
    time.sleep(1)

    from profile_injector import ProfileInjector

    injector = ProfileInjector(adb_target=ADB_TARGET)
    result = injector.inject_full_profile(profile, card_data=CARD_DATA)

    logger.info(f"Injection result: {json.dumps(result.to_dict(), indent=2)}")
    logger.info(f"Trust score: {result.trust_score}/100")

    return result


# ═══════════════════════════════════════════════════════════════════════
# STEP 3: GOOGLE ACCOUNT LOGIN VIA ADB (for Play Store)
# ═══════════════════════════════════════════════════════════════════════

def step3_login_google_account():
    logger.info("=" * 60)
    logger.info("STEP 3: Injecting Google account for Play Store access")
    logger.info("=" * 60)

    adb_root()

    from google_account_injector import GoogleAccountInjector

    injector = GoogleAccountInjector(adb_target=ADB_TARGET)
    result = injector.inject_account(
        email=PLAY_ACCOUNT["email"],
        display_name="Jovany Owens",
    )

    logger.info(f"Google account injection: {result.success_count}/8 targets")
    if result.errors:
        for e in result.errors:
            logger.warning(f"  Error: {e}")

    # Set the account as default in GMS
    adb_shell("am broadcast -a com.google.android.gms.INITIALIZE")
    time.sleep(2)

    return result


# ═══════════════════════════════════════════════════════════════════════
# STEP 4: INSTALL WALLET APPS VIA ADB (Play Store cmdline)
# ═══════════════════════════════════════════════════════════════════════

def step4_install_wallet_apps():
    logger.info("=" * 60)
    logger.info("STEP 4: Installing US wallet/banking apps")
    logger.info("=" * 60)

    installed = []
    failed = []

    for pkg in US_WALLET_APPS:
        # Check if already installed
        check = adb_shell(f"pm path {pkg}")
        if check and "package:" in check:
            logger.info(f"  Already installed: {pkg}")
            installed.append(pkg)
            continue

        # Try to install via Play Store intent (market://)
        logger.info(f"  Triggering Play Store install: {pkg}")
        adb_shell(
            f"am start -a android.intent.action.VIEW "
            f"-d 'market://details?id={pkg}' "
            f"com.android.vending"
        )
        time.sleep(3)

        # Try clicking the Install button via UI automation
        # Use input tap at typical "Install" button position
        adb_shell("input tap 540 1650")  # Install button area
        time.sleep(2)

        # Accept permissions if prompted
        adb_shell("input tap 540 1450")  # Accept button
        time.sleep(1)

        installed.append(pkg)
        logger.info(f"  Install triggered: {pkg}")

    # Also try batch install via pm install-existing for system apps
    system_apps = [
        "com.google.android.apps.walletnfcrel",
        "com.android.chrome",
    ]
    for pkg in system_apps:
        adb_shell(f"pm install-existing {pkg}")

    logger.info(f"\nInstall summary: {len(installed)} triggered, {len(failed)} failed")
    return installed, failed


# ═══════════════════════════════════════════════════════════════════════
# STEP 5: WALLET PROVISIONING (CC into Google Pay + Chrome + Play Store)
# ═══════════════════════════════════════════════════════════════════════

def step5_provision_wallet():
    logger.info("=" * 60)
    logger.info("STEP 5: Provisioning CC into wallets")
    logger.info("=" * 60)

    adb_root()

    from wallet_provisioner import WalletProvisioner

    prov = WalletProvisioner(adb_target=ADB_TARGET)
    result = prov.provision_card(
        card_number=CARD_DATA["number"],
        exp_month=CARD_DATA["exp_month"],
        exp_year=CARD_DATA["exp_year"],
        cardholder=CARD_DATA["cardholder"],
        cvv=CARD_DATA["cvv"],
        persona_email=PERSONA["email"],
        persona_name=PERSONA["name"],
    )

    logger.info(f"Wallet provisioning: {result.success_count}/3 targets")
    logger.info(f"  Google Pay: {'OK' if result.google_pay_ok else 'FAIL'}")
    logger.info(f"  Play Store: {'OK' if result.play_store_ok else 'FAIL'}")
    logger.info(f"  Chrome Autofill: {'OK' if result.chrome_autofill_ok else 'FAIL'}")
    if result.errors:
        for e in result.errors:
            logger.warning(f"  Error: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════
# STEP 6: VERIFY TRUST SCORE
# ═══════════════════════════════════════════════════════════════════════

def step6_verify():
    logger.info("=" * 60)
    logger.info("STEP 6: Verifying device state")
    logger.info("=" * 60)

    checks = {}

    # Google account
    out = adb_shell("ls /data/system_ce/0/accounts_ce.db 2>/dev/null")
    checks["google_account"] = bool(out)

    # Contacts
    out = adb_shell("content query --uri content://contacts/phones --projection _id 2>/dev/null | wc -l")
    try:
        checks["contacts"] = int(out.strip())
    except:
        checks["contacts"] = 0

    # Chrome cookies
    out = adb_shell("ls /data/data/com.android.chrome/app_chrome/Default/Cookies 2>/dev/null")
    checks["chrome_cookies"] = bool(out)

    # Chrome history
    out = adb_shell("ls /data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null")
    checks["chrome_history"] = bool(out)

    # Gallery
    out = adb_shell("ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l")
    try:
        checks["gallery"] = int(out.strip())
    except:
        checks["gallery"] = 0

    # Google Pay wallet
    out = adb_shell("ls /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 2>/dev/null")
    checks["google_pay"] = bool(out)

    # SMS count
    out = adb_shell("content query --uri content://sms --projection _id 2>/dev/null | wc -l")
    try:
        checks["sms"] = int(out.strip())
    except:
        checks["sms"] = 0

    # Call logs
    out = adb_shell("content query --uri content://call_log/calls --projection _id 2>/dev/null | wc -l")
    try:
        checks["call_logs"] = int(out.strip())
    except:
        checks["call_logs"] = 0

    # Chrome autofill (Web Data)
    out = adb_shell("ls '/data/data/com.android.chrome/app_chrome/Default/Web Data' 2>/dev/null")
    checks["chrome_autofill"] = bool(out)

    # Chrome signed in
    out = adb_shell("ls /data/data/com.android.chrome/app_chrome/Default/Preferences 2>/dev/null")
    checks["chrome_signin"] = bool(out)

    # Compute score
    score = 0
    if checks["google_account"]: score += 15
    if checks["contacts"] >= 5: score += 8
    if checks["chrome_cookies"]: score += 8
    if checks["chrome_history"]: score += 8
    if checks["gallery"] >= 3: score += 5
    if checks["google_pay"]: score += 12
    if checks["sms"] >= 5: score += 7
    if checks["call_logs"] >= 10: score += 7
    if checks["chrome_autofill"]: score += 5
    if checks["chrome_signin"]: score += 5

    grade = "A+" if score >= 90 else "A" if score >= 80 else "B" if score >= 65 else "C"

    logger.info(f"\n{'=' * 60}")
    logger.info(f"FINAL TRUST SCORE: {score}/100  Grade: {grade}")
    logger.info(f"{'=' * 60}")
    for k, v in checks.items():
        status = "✓" if (v if isinstance(v, bool) else v > 0) else "✗"
        logger.info(f"  {status} {k}: {v}")

    return score, grade, checks


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║  TITAN V11.3 — FULL DEVICE PROVISIONING                ║")
    logger.info("║  Persona: Jovany Owens (500-day aged profile)          ║")
    logger.info("║  CC: Visa ****0405 | 08/2029                           ║")
    logger.info("║  Device: dev-us1 (Samsung S25 Ultra, Android 14)       ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")

    # Verify ADB connection
    ok, out = adb("shell getprop ro.product.model")
    if not ok:
        logger.error(f"ADB not connected to {ADB_TARGET}. Trying to connect...")
        adb(f"connect {ADB_TARGET}")
        time.sleep(2)
        ok, out = adb("shell getprop ro.product.model")
        if not ok:
            logger.error("Cannot connect to device. Exiting.")
            sys.exit(1)
    logger.info(f"Device connected: {out}")

    # Execute all steps
    profile_id, profile = step1_forge_profile()
    inject_result = step2_inject_profile(profile_id, profile)
    acct_result = step3_login_google_account()
    step4_install_wallet_apps()
    wallet_result = step5_provision_wallet()
    score, grade, checks = step6_verify()

    # Final summary
    logger.info("\n" + "=" * 60)
    logger.info("PROVISIONING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Profile ID: {profile_id}")
    logger.info(f"  Persona: {PERSONA['name']} ({PERSONA['email']})")
    logger.info(f"  Age: {PERSONA['age_days']} days")
    logger.info(f"  CC: Visa ****0405 → Google Pay + Play Store + Chrome")
    logger.info(f"  Trust Score: {score}/100 ({grade})")
    logger.info(f"  Wallet: {wallet_result.success_count}/3 targets")
    logger.info(f"  Google Account: {acct_result.success_count}/8 targets")
    logger.info(f"  Profile Injection Trust: {inject_result.trust_score}/100")

    return 0


if __name__ == "__main__":
    sys.exit(main())
