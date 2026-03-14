#!/usr/bin/env python3
"""
Titan V11.3 — Full US Bundle Injection Test
Tests the complete injection pipeline:
  1. AndroidProfileForge → generate US profile
  2. ProfileInjector → inject all data into Cuttlefish Android VM
  3. WalletProvisioner → inject CC into Google Pay / Play / Chrome
  4. GoogleAccountInjector → inject Google account
  5. AppDataForger → inject per-app SharedPrefs
  6. Verify injected data on device via ADB
"""

import json
import logging
import os
import sys
import time
import traceback

# Add core to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("test-us-injection")

ADB_TARGET = "127.0.0.1:5555"

# ═══════════════════════════════════════════════════════════════════════
# TEST PARAMETERS — US Bundle
# ═══════════════════════════════════════════════════════════════════════

US_PERSONA = {
    "name": "Marcus Thompson",
    "email": "marcus.thompson.ny@gmail.com",
    "phone": "+12125559847",
    "country": "US",
    "archetype": "professional",
    "age_days": 120,
    "carrier": "tmobile_us",
    "location": "nyc",
    "device_model": "samsung_s25_ultra",
}

US_CARD_DATA = {
    "card_number": "4532015112830366",
    "cardholder": "MARCUS THOMPSON",
    "expiry_month": 11,
    "expiry_year": 2027,
    "billing_address": {
        "address": "1847 Oak St",
        "city": "New York",
        "state": "NY",
        "zip": "10019",
        "country": "US",
    },
}

# ═══════════════════════════════════════════════════════════════════════
# RESULTS TRACKER
# ═══════════════════════════════════════════════════════════════════════

class TestResults:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []
        self.crash_log = []

    def ok(self, name, detail=""):
        self.passed.append((name, detail))
        logger.info(f"  ✓ {name}: {detail}" if detail else f"  ✓ {name}")

    def fail(self, name, detail=""):
        self.failed.append((name, detail))
        logger.error(f"  ✗ {name}: {detail}" if detail else f"  ✗ {name}")

    def warn(self, name, detail=""):
        self.warnings.append((name, detail))
        logger.warning(f"  ⚠ {name}: {detail}" if detail else f"  ⚠ {name}")

    def crash(self, phase, error):
        self.crash_log.append((phase, str(error)))
        logger.critical(f"  CRASH in {phase}: {error}")

    def summary(self):
        total = len(self.passed) + len(self.failed)
        print("\n" + "=" * 70)
        print(f"TEST RESULTS: {len(self.passed)}/{total} passed, "
              f"{len(self.failed)} failed, {len(self.warnings)} warnings, "
              f"{len(self.crash_log)} crashes")
        print("=" * 70)
        if self.failed:
            print("\nFAILED:")
            for name, detail in self.failed:
                print(f"  ✗ {name}: {detail}")
        if self.crash_log:
            print("\nCRASHES:")
            for phase, err in self.crash_log:
                print(f"  💥 {phase}: {err}")
        if self.warnings:
            print("\nWARNINGS:")
            for name, detail in self.warnings:
                print(f"  ⚠ {name}: {detail}")
        print()
        return len(self.failed) == 0 and len(self.crash_log) == 0


results = TestResults()


# ═══════════════════════════════════════════════════════════════════════
# PHASE 1: Import all modules
# ═══════════════════════════════════════════════════════════════════════

def test_imports():
    logger.info("Phase 1: Testing imports...")
    modules = {}

    try:
        from android_profile_forge import AndroidProfileForge
        modules["AndroidProfileForge"] = AndroidProfileForge
        results.ok("Import AndroidProfileForge")
    except Exception as e:
        results.crash("Import AndroidProfileForge", e)

    try:
        from profile_injector import ProfileInjector
        modules["ProfileInjector"] = ProfileInjector
        results.ok("Import ProfileInjector")
    except Exception as e:
        results.crash("Import ProfileInjector", e)

    try:
        from wallet_provisioner import WalletProvisioner, detect_network, generate_dpan
        modules["WalletProvisioner"] = WalletProvisioner
        modules["detect_network"] = detect_network
        modules["generate_dpan"] = generate_dpan
        results.ok("Import WalletProvisioner")
    except Exception as e:
        results.crash("Import WalletProvisioner", e)

    try:
        from google_account_injector import GoogleAccountInjector
        modules["GoogleAccountInjector"] = GoogleAccountInjector
        results.ok("Import GoogleAccountInjector")
    except Exception as e:
        results.crash("Import GoogleAccountInjector", e)

    try:
        from app_data_forger import AppDataForger
        modules["AppDataForger"] = AppDataForger
        results.ok("Import AppDataForger")
    except Exception as e:
        results.crash("Import AppDataForger", e)

    try:
        from app_bundles import APP_BUNDLES, COUNTRY_BUNDLES, get_bundles_for_country
        modules["APP_BUNDLES"] = APP_BUNDLES
        modules["get_bundles_for_country"] = get_bundles_for_country
        results.ok("Import app_bundles")
    except Exception as e:
        results.crash("Import app_bundles", e)

    try:
        from apk_data_map import APK_DATA_MAP, get_app_map, get_payment_apps
        modules["APK_DATA_MAP"] = APK_DATA_MAP
        modules["get_payment_apps"] = get_payment_apps
        results.ok("Import apk_data_map")
    except Exception as e:
        results.crash("Import apk_data_map", e)

    return modules


# ═══════════════════════════════════════════════════════════════════════
# PHASE 2: Forge US Profile
# ═══════════════════════════════════════════════════════════════════════

def test_forge_profile(modules):
    logger.info("\nPhase 2: Forging US profile...")
    profile = None

    try:
        forge = modules["AndroidProfileForge"]()
        profile = forge.forge(
            persona_name=US_PERSONA["name"],
            persona_email=US_PERSONA["email"],
            persona_phone=US_PERSONA["phone"],
            country=US_PERSONA["country"],
            archetype=US_PERSONA["archetype"],
            age_days=US_PERSONA["age_days"],
            carrier=US_PERSONA["carrier"],
            location=US_PERSONA["location"],
            device_model=US_PERSONA["device_model"],
        )
        results.ok("Profile forged", f"ID: {profile.get('id', 'N/A')}")
    except Exception as e:
        results.crash("Profile forge", f"{e}\n{traceback.format_exc()}")
        return None

    # Validate profile data completeness
    required_keys = [
        "contacts", "call_logs", "sms", "cookies", "history",
        "gallery_paths", "autofill", "app_installs", "play_purchases",
        "app_usage", "notifications", "email_receipts",
    ]
    for key in required_keys:
        val = profile.get(key)
        if val is None:
            results.fail(f"Profile missing key: {key}")
        elif isinstance(val, list) and len(val) == 0:
            results.warn(f"Profile key empty: {key}")
        elif isinstance(val, dict) and len(val) == 0 and key != "local_storage":
            results.warn(f"Profile key empty dict: {key}")
        else:
            count = len(val) if isinstance(val, (list, dict)) else "present"
            results.ok(f"Profile.{key}", f"count={count}")

    # Validate US-specific data
    if profile:
        stats = profile.get("stats", {})
        if stats.get("contacts", 0) < 10:
            results.warn("Low contact count", str(stats.get("contacts")))
        if stats.get("call_logs", 0) < 20:
            results.warn("Low call log count", str(stats.get("call_logs")))
        if stats.get("cookies", 0) < 10:
            results.warn("Low cookie count", str(stats.get("cookies")))
        if stats.get("history", 0) < 100:
            results.warn("Low history count", str(stats.get("history")))

        # Check US phone numbers in contacts
        contacts = profile.get("contacts", [])
        us_phones = sum(1 for c in contacts if c.get("phone", "").startswith("+1"))
        if us_phones < 5:
            results.warn("Few US phone numbers in contacts", f"{us_phones}/{len(contacts)}")
        else:
            results.ok("US phone numbers in contacts", f"{us_phones}/{len(contacts)}")

        # Check autofill address is US
        autofill = profile.get("autofill", {})
        addr = autofill.get("address", {})
        if addr.get("country") != "US":
            results.fail("Autofill address not US", str(addr))
        else:
            results.ok("Autofill address is US", f"{addr.get('city')}, {addr.get('state')}")

    return profile


# ═══════════════════════════════════════════════════════════════════════
# PHASE 3: Wallet / DPAN Tests
# ═══════════════════════════════════════════════════════════════════════

def test_wallet_functions(modules):
    logger.info("\nPhase 3: Testing wallet functions...")

    # Test card network detection
    try:
        network = modules["detect_network"](US_CARD_DATA["card_number"])
        results.ok("Card network detection", f"Network: {network}")
    except Exception as e:
        results.crash("Card network detection", e)

    # Test DPAN generation
    try:
        dpan = modules["generate_dpan"](US_CARD_DATA["card_number"])
        results.ok("DPAN generation", f"DPAN: {dpan[:6]}...{dpan[-4:]}")

        # Validate DPAN
        orig = US_CARD_DATA["card_number"].replace(" ", "")
        if dpan[:6] != orig[:6]:
            results.fail("DPAN BIN mismatch", f"Expected {orig[:6]}, got {dpan[:6]}")
        else:
            results.ok("DPAN BIN prefix preserved")

        if len(dpan) != len(orig):
            results.fail("DPAN length mismatch", f"Expected {len(orig)}, got {len(dpan)}")
        else:
            results.ok("DPAN length matches")

        # Luhn check
        if _luhn_check(dpan):
            results.ok("DPAN Luhn check valid")
        else:
            results.fail("DPAN Luhn check INVALID")

    except Exception as e:
        results.crash("DPAN generation", e)


def _luhn_check(number):
    digits = [int(d) for d in str(number)]
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


# ═══════════════════════════════════════════════════════════════════════
# PHASE 4: US Bundle Apps Check
# ═══════════════════════════════════════════════════════════════════════

def test_us_bundle(modules):
    logger.info("\nPhase 4: Testing US bundle apps...")

    try:
        get_bundles = modules["get_bundles_for_country"]
        bundles = get_bundles("US")
        us_pkgs = []
        for bundle in bundles:
            if isinstance(bundle, dict):
                apps = bundle.get("apps", [])
                for app in apps:
                    pkg = app.get("pkg", "") if isinstance(app, dict) else str(app)
                    if pkg and pkg not in us_pkgs:
                        us_pkgs.append(pkg)
            elif isinstance(bundle, str):
                us_pkgs.append(bundle)
        results.ok("US bundle packages", f"{len(us_pkgs)} packages from {len(bundles)} bundles")

        # Verify wallet apps in bundle
        wallet_pkgs = [
            "com.google.android.apps.walletnfcrel",
            "com.paypal.android.p2pmobile",
            "com.venmo",
            "com.squareup.cash",
        ]
        for pkg in wallet_pkgs:
            if pkg in us_pkgs:
                results.ok(f"Wallet app in US bundle: {pkg}")
            else:
                results.warn(f"Wallet app missing from US bundle: {pkg}")

        # Check APK_DATA_MAP coverage for US bundle
        apk_map = modules["APK_DATA_MAP"]
        mapped = sum(1 for p in us_pkgs if p in apk_map)
        results.ok(f"APK_DATA_MAP coverage", f"{mapped}/{len(us_pkgs)} US apps mapped")

        unmapped = [p for p in us_pkgs if p not in apk_map]
        if unmapped:
            results.warn("Unmapped US apps", ", ".join(unmapped[:5]))

        return us_pkgs

    except Exception as e:
        results.crash("US bundle check", e)
        return []


# ═══════════════════════════════════════════════════════════════════════
# PHASE 5: Full Injection into Device
# ═══════════════════════════════════════════════════════════════════════

def test_full_injection(modules, profile):
    logger.info("\nPhase 5: Running full injection into device...")

    if not profile:
        results.fail("Skipping injection — no profile")
        return None

    try:
        ProfileInjector = modules["ProfileInjector"]
        injector = ProfileInjector(adb_target=ADB_TARGET)

        inject_result = injector.inject_full_profile(
            profile=profile,
            card_data=US_CARD_DATA,
        )

        results.ok("Injection completed", f"Trust score: {inject_result.trust_score}")

        # Check individual injection results
        r = inject_result.to_dict()
        for key, val in r.items():
            if key in ("profile_id", "trust_score", "errors"):
                continue
            if isinstance(val, bool):
                if val:
                    results.ok(f"Injection.{key}")
                else:
                    results.fail(f"Injection.{key}", "returned False")
            elif isinstance(val, dict):
                for subkey, subval in val.items():
                    if isinstance(subval, bool):
                        if subval:
                            results.ok(f"Injection.{key}.{subkey}")
                        else:
                            results.fail(f"Injection.{key}.{subkey}", "returned False")

        # Log injection errors
        errors = r.get("errors", [])
        if errors:
            for err in errors[:10]:
                results.warn("Injection error", err)
        else:
            results.ok("No injection errors")

        return inject_result

    except Exception as e:
        results.crash("Full injection", f"{e}\n{traceback.format_exc()}")
        return None


# ═══════════════════════════════════════════════════════════════════════
# PHASE 6: Verify Injected Data on Device
# ═══════════════════════════════════════════════════════════════════════

def test_verify_device(profile):
    logger.info("\nPhase 6: Verifying injected data on device...")

    import subprocess

    def adb_shell(cmd):
        try:
            r = subprocess.run(
                f"adb -s {ADB_TARGET} shell \"{cmd}\"",
                shell=True, capture_output=True, text=True, timeout=15,
            )
            return r.stdout.strip()
        except Exception:
            return ""

    # 6a. Check Chrome cookies DB exists
    cookie_db = adb_shell("ls -la /data/data/com.android.chrome/app_chrome/Default/Cookies 2>/dev/null")
    if "Cookies" in cookie_db:
        results.ok("Chrome Cookies DB exists on device")
    else:
        results.warn("Chrome Cookies DB not found")

    # 6b. Check Chrome history DB
    history_db = adb_shell("ls -la /data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null")
    if "History" in history_db:
        results.ok("Chrome History DB exists on device")
    else:
        results.warn("Chrome History DB not found")

    # 6c. Check Chrome autofill / Web Data
    webdata_db = adb_shell("ls -la /data/data/com.android.chrome/app_chrome/Default/'Web Data' 2>/dev/null")
    if "Web Data" in webdata_db or "Web" in webdata_db:
        results.ok("Chrome Web Data (autofill) exists")
    else:
        results.warn("Chrome Web Data not found")

    # 6d. Check Google account injection (accounts_ce.db)
    acc_ce = adb_shell("ls -la /data/system_ce/0/accounts_ce.db 2>/dev/null")
    if "accounts_ce" in acc_ce:
        results.ok("accounts_ce.db exists on device")
        # Try to read email from it
        email_check = adb_shell("sqlite3 /data/system_ce/0/accounts_ce.db 'SELECT name FROM accounts LIMIT 1' 2>/dev/null")
        if US_PERSONA["email"] in email_check:
            results.ok("Google account email verified in accounts_ce.db")
        elif email_check:
            results.warn("accounts_ce.db has different email", email_check)
        else:
            results.warn("Could not read accounts_ce.db (sqlite3 not available?)")
    else:
        results.warn("accounts_ce.db not found")

    # 6e. Check Google Pay / tapandpay.db
    gpay_db = adb_shell("ls -la /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 2>/dev/null")
    if "tapandpay" in gpay_db:
        results.ok("Google Pay tapandpay.db exists")
    else:
        results.warn("Google Pay tapandpay.db not found")

    # 6f. Check Google Pay SharedPrefs
    gpay_prefs = adb_shell("ls /data/data/com.google.android.apps.walletnfcrel/shared_prefs/ 2>/dev/null")
    if gpay_prefs:
        results.ok("Google Pay SharedPrefs exist", gpay_prefs[:80])
    else:
        results.warn("Google Pay SharedPrefs not found")

    # 6g. Check Play Store finsky.xml
    finsky = adb_shell("cat /data/data/com.android.vending/shared_prefs/finsky.xml 2>/dev/null | head -5")
    if "finsky" in finsky or "xml" in finsky:
        results.ok("Play Store finsky.xml exists")
    else:
        results.warn("Play Store finsky.xml not found")

    # 6h. Check Play Store library.db
    lib_db = adb_shell("ls -la /data/data/com.android.vending/databases/library.db 2>/dev/null")
    if "library" in lib_db:
        results.ok("Play Store library.db exists")
    else:
        results.warn("Play Store library.db not found")

    # 6i. Check contacts
    contacts_count = adb_shell("content query --uri content://contacts/phones --projection display_name 2>/dev/null | wc -l")
    try:
        cnt = int(contacts_count.strip())
        if cnt > 0:
            results.ok("Contacts injected", f"{cnt} contacts")
        else:
            results.warn("No contacts found on device")
    except:
        results.warn("Could not query contacts", contacts_count[:60])

    # 6j. Check SMS
    sms_count = adb_shell("content query --uri content://sms --projection body 2>/dev/null | wc -l")
    try:
        cnt = int(sms_count.strip())
        if cnt > 0:
            results.ok("SMS injected", f"{cnt} messages")
        else:
            results.warn("No SMS found on device")
    except:
        results.warn("Could not query SMS", sms_count[:60])

    # 6k. Check call logs
    calls_count = adb_shell("content query --uri content://call_log/calls --projection number 2>/dev/null | wc -l")
    try:
        cnt = int(calls_count.strip())
        if cnt > 0:
            results.ok("Call logs injected", f"{cnt} entries")
        else:
            results.warn("No call logs found on device")
    except:
        results.warn("Could not query call logs", calls_count[:60])

    # 6l. Check GMS prefs
    gms_prefs = adb_shell("ls /data/data/com.google.android.gms/shared_prefs/ 2>/dev/null")
    if gms_prefs:
        results.ok("GMS SharedPrefs exist")
    else:
        results.warn("GMS SharedPrefs not found")

    # 6m. Check Chrome sign-in Preferences
    chrome_prefs = adb_shell("cat /data/data/com.android.chrome/app_chrome/Default/Preferences 2>/dev/null | head -3")
    if chrome_prefs and ("account_info" in chrome_prefs or "{" in chrome_prefs):
        results.ok("Chrome Preferences exists")
    else:
        results.warn("Chrome Preferences not found")

    # 6n. Check wallet apps SharedPrefs (Venmo, CashApp, PayPal)
    for pkg, name in [
        ("com.venmo", "Venmo"),
        ("com.squareup.cash", "Cash App"),
        ("com.paypal.android.p2pmobile", "PayPal"),
        ("com.chase.sig.android", "Chase"),
    ]:
        prefs = adb_shell(f"ls /data/data/{pkg}/shared_prefs/ 2>/dev/null")
        if prefs:
            results.ok(f"{name} SharedPrefs exist")
        else:
            results.warn(f"{name} SharedPrefs not found (app may not be installed)")


# ═══════════════════════════════════════════════════════════════════════
# PHASE 7: Standalone Wallet Provisioner Test
# ═══════════════════════════════════════════════════════════════════════

def test_wallet_provisioner_standalone(modules):
    logger.info("\nPhase 7: Testing WalletProvisioner standalone...")

    try:
        WalletProvisioner = modules["WalletProvisioner"]
        provisioner = WalletProvisioner(adb_target=ADB_TARGET)

        provision_result = provisioner.provision_card(
            card_number=US_CARD_DATA["card_number"],
            cardholder=US_CARD_DATA["cardholder"],
            exp_month=US_CARD_DATA["expiry_month"],
            exp_year=US_CARD_DATA["expiry_year"],
        )

        r = provision_result.to_dict()
        results.ok("WalletProvisioner.provision completed")

        for key in ["google_pay", "play_store", "chrome_autofill"]:
            if r.get(key):
                results.ok(f"Wallet standalone: {key}")
            else:
                results.fail(f"Wallet standalone: {key}")

        dpan = r.get("dpan", "")
        if dpan:
            results.ok("DPAN generated during provisioning", f"...{dpan[-4:]}")
        else:
            results.warn("No DPAN in provision result")

        errors = r.get("errors", [])
        if errors:
            for err in errors[:5]:
                results.warn("Wallet provision error", err)

    except Exception as e:
        results.crash("WalletProvisioner standalone", f"{e}\n{traceback.format_exc()}")


# ═══════════════════════════════════════════════════════════════════════
# PHASE 8: Google Account Injector Standalone
# ═══════════════════════════════════════════════════════════════════════

def test_google_account_standalone(modules):
    logger.info("\nPhase 8: Testing GoogleAccountInjector standalone...")

    try:
        GoogleAccountInjector = modules["GoogleAccountInjector"]
        injector = GoogleAccountInjector(adb_target=ADB_TARGET)

        result = injector.inject_account(
            email=US_PERSONA["email"],
            display_name=US_PERSONA["name"],
        )

        r = result.to_dict()
        results.ok("GoogleAccountInjector completed", f"{r['success_count']}/8 targets")

        for key in ["accounts_ce", "accounts_de", "gms_prefs", "chrome_signin",
                     "play_store", "gmail", "youtube", "maps"]:
            if r.get(key):
                results.ok(f"GoogleAccount.{key}")
            else:
                results.fail(f"GoogleAccount.{key}", "injection failed")

        errors = r.get("errors", [])
        if errors:
            for err in errors[:5]:
                results.warn("Google account error", err)

    except Exception as e:
        results.crash("GoogleAccountInjector standalone", f"{e}\n{traceback.format_exc()}")


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("Titan V11.3 — Full US Bundle Injection Test")
    print(f"ADB Target: {ADB_TARGET}")
    print(f"Persona: {US_PERSONA['name']} ({US_PERSONA['email']})")
    print(f"Card: ...{US_CARD_DATA['card_number'][-4:]}")
    print("=" * 70)

    # Phase 1: Imports
    modules = test_imports()
    if not modules:
        results.summary()
        return 1

    # Phase 2: Forge profile
    profile = test_forge_profile(modules)

    # Phase 3: Wallet functions (unit tests, no device needed)
    test_wallet_functions(modules)

    # Phase 4: US bundle check
    us_pkgs = test_us_bundle(modules)

    # Phase 5: Full injection (requires device)
    inject_result = test_full_injection(modules, profile)

    # Phase 6: Verify on device
    test_verify_device(profile)

    # Phase 7: Standalone wallet test
    test_wallet_provisioner_standalone(modules)

    # Phase 8: Standalone Google account test
    test_google_account_standalone(modules)

    # Summary
    success = results.summary()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
