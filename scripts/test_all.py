#!/usr/bin/env python3
"""Titan V11.3 — Full test suite for all new modules."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

errors = []

def test(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        errors.append(name)


# ── Test 1: Imports ──
print("=== Test 1: Module Imports ===")

def t_apk_data_map():
    from apk_data_map import APK_DATA_MAP, get_payment_apps, get_google_apps, get_total_trust_weight
    assert len(APK_DATA_MAP) >= 30, f"Only {len(APK_DATA_MAP)} packages"
    assert get_total_trust_weight() > 100
    assert len(get_payment_apps()) >= 10
    assert len(get_google_apps()) >= 5

def t_app_bundles():
    from app_bundles import APP_BUNDLES, get_bundles_for_country
    assert len(APP_BUNDLES) >= 11
    us = get_bundles_for_country("US")
    assert len(us) >= 8
    bundle_names = [b["name"] for b in us]
    assert "Payment Wallets" in bundle_names

def t_google_account():
    from google_account_injector import GoogleAccountInjector, AccountInjectionResult
    r = AccountInjectionResult(email="test@test.com")
    assert r.success_count == 0
    d = r.to_dict()
    assert "email" in d
    assert "success_count" in d

def t_wallet_prov():
    from wallet_provisioner import WalletProvisioner, detect_network, detect_issuer, generate_dpan, WalletProvisionResult
    r = WalletProvisionResult()
    assert r.success_count == 0

def t_app_data():
    from app_data_forger import AppDataForger, AppDataForgeResult
    r = AppDataForgeResult()
    assert r.apps_processed == 0

def t_profile_forge():
    from android_profile_forge import AndroidProfileForge
    assert callable(getattr(AndroidProfileForge, "forge", None))

def t_profile_inject():
    from profile_injector import ProfileInjector, InjectionResult
    r = InjectionResult()
    d = r.to_dict()
    for field in ["google_account", "wallet", "app_data", "play_purchases", "app_usage", "trust_score"]:
        assert field in d, f"Missing field: {field}"

test("apk_data_map", t_apk_data_map)
test("app_bundles", t_app_bundles)
test("google_account_injector", t_google_account)
test("wallet_provisioner", t_wallet_prov)
test("app_data_forger", t_app_data)
test("android_profile_forge", t_profile_forge)
test("profile_injector", t_profile_inject)

# ── Test 2: Wallet DPAN & Detection ──
print("\n=== Test 2: Wallet DPAN & Card Detection ===")

def luhn_ok(num):
    digits = [int(d) for d in num]
    odd = sum(digits[-1::-2])
    even = sum(d * 2 - 9 if d * 2 > 9 else d * 2 for d in digits[-2::-2])
    return (odd + even) % 10 == 0

def t_visa():
    from wallet_provisioner import detect_network
    n = detect_network("4532015112830366")
    assert n["network"] == "visa"

def t_mc():
    from wallet_provisioner import detect_network
    n = detect_network("5425233430109903")
    assert n["network"] == "mastercard"

def t_amex():
    from wallet_provisioner import detect_network
    n = detect_network("378282246310005")
    assert n["network"] == "amex"

def t_dpan_luhn():
    from wallet_provisioner import generate_dpan
    for _ in range(10):
        dpan = generate_dpan("4532015112830366")
        assert dpan[:6] == "453201", f"BIN mismatch: {dpan[:6]}"
        assert len(dpan) == 16, f"Length wrong: {len(dpan)}"
        assert luhn_ok(dpan), f"Luhn fail: {dpan}"

def t_issuer():
    from wallet_provisioner import detect_issuer
    assert detect_issuer("4532015112830366") == "Chase"

test("visa_detect", t_visa)
test("mastercard_detect", t_mc)
test("amex_detect", t_amex)
test("dpan_luhn_x10", t_dpan_luhn)
test("issuer_detect", t_issuer)

# ── Test 3: Full Profile Forge ──
print("\n=== Test 3: AndroidProfileForge (full forge) ===")

def t_full_forge():
    from android_profile_forge import AndroidProfileForge
    forge = AndroidProfileForge()
    profile = forge.forge(
        persona_name="Alex Mercer",
        persona_email="alex.mercer42@gmail.com",
        persona_phone="+12125559876",
        country="US",
        archetype="professional",
        age_days=60,
        carrier="tmobile_us",
        location="nyc",
        device_model="samsung_s25_ultra",
    )

    # Check all new fields
    for field in ["play_purchases", "app_usage", "notifications", "email_receipts"]:
        assert field in profile, f"Missing: {field}"
        assert field in profile["stats"], f"Missing stats.{field}"

    s = profile["stats"]
    assert s["contacts"] > 0
    assert s["call_logs"] > 0
    assert s["sms"] > 0
    assert s["cookies"] > 0
    assert s["history"] > 0
    assert s["apps"] > 0
    assert s["play_purchases"] > 0
    assert s["app_usage"] > 0
    assert s["notifications"] > 0
    assert s["email_receipts"] > 0

    # Validate purchase structure
    pp = profile["play_purchases"]
    assert any(p["offer_type"] > 1 for p in pp), "No paid purchases"
    assert all("doc_id" in p and "purchase_time" in p for p in pp)

    # Validate app usage
    au = profile["app_usage"]
    assert all("package" in a and "total_minutes" in a for a in au)

    # Validate notifications
    assert all("package" in n and "title" in n for n in profile["notifications"])

    # Validate email receipts
    er = profile["email_receipts"]
    assert all("merchant" in r and "amount" in r for r in er)

    print(f"         stats: contacts={s['contacts']} calls={s['call_logs']} sms={s['sms']}")
    print(f"         cookies={s['cookies']} history={s['history']} gallery={s['gallery']}")
    print(f"         apps={s['apps']} wifi={s['wifi']}")
    print(f"         purchases={s['play_purchases']} usage={s['app_usage']} notifs={s['notifications']} receipts={s['email_receipts']}")

test("full_forge", t_full_forge)

# ── Test 4: XML generation ──
print("\n=== Test 4: SharedPrefs XML Generation ===")

def t_xml_gen():
    from app_data_forger import AppDataForger
    forger = AppDataForger(adb_target="127.0.0.1:9999")
    xml = forger._build_prefs_xml({
        "is_logged_in": "true",
        "email": "test@gmail.com",
        "count": "42",
        "token": "abc123xyz",
    })
    assert "<?xml" in xml
    assert "is_logged_in" in xml
    assert "true" in xml
    assert "test@gmail.com" in xml
    assert "42" in xml

def t_xml_google():
    from google_account_injector import GoogleAccountInjector
    inj = GoogleAccountInjector(adb_target="127.0.0.1:9999")
    xml = inj._build_shared_prefs_xml({"key": "val", "flag": "false", "num": "999"})
    assert "<map>" in xml
    assert "val" in xml
    assert "false" in xml

test("app_data_xml", t_xml_gen)
test("google_acct_xml", t_xml_google)

# ── Test 5: API Server ──
print("\n=== Test 5: API Server Module ===")

def t_api_import():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "titan_api",
        os.path.join(os.path.dirname(__file__), "..", "server", "titan_api.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "app"), "No FastAPI app"
    assert hasattr(mod, "genesis_create"), "No genesis_create"
    assert hasattr(mod, "genesis_inject"), "No genesis_inject"
    assert hasattr(mod, "genesis_trust_score"), "No genesis_trust_score"

test("api_import", t_api_import)

# ── Summary ──
print("\n" + "=" * 55)
if errors:
    print(f"  FAILED: {len(errors)} tests — {errors}")
    sys.exit(1)
else:
    total = 5 + 5 + 1 + 2 + 1  # count of test() calls
    print(f"  ALL {total} TESTS PASSED")
    sys.exit(0)
