#!/usr/bin/env python3
"""Titan V11.3 — Phase 2 test suite: SmartForge + Purchase History bridges."""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
os.environ["TITAN_V11_CORE"] = "/root/titan-v11-release/core"

errors = []

def test(name, fn):
    try:
        fn()
        print("  PASS  " + name)
    except Exception as e:
        print("  FAIL  " + name + ": " + str(e))
        errors.append(name)

# === Test 1: SmartForge Bridge ===
print("=== Test 1: SmartForge Bridge ===")

def t_sf_import():
    from smartforge_bridge import smartforge_for_android, get_occupations, get_countries
    assert len(get_occupations()) >= 10
    assert len(get_countries()) >= 15

def t_sf_generate():
    from smartforge_bridge import smartforge_for_android
    config = smartforge_for_android(
        occupation="software_engineer", country="US", age=32,
        age_days=180, use_ai=False,
    )
    assert config["persona_name"], "No persona_name"
    assert config["persona_email"], "No persona_email"
    assert config["persona_phone"], "No persona_phone"
    assert config["age_days"] == 180
    assert config["country"] == "US"
    assert config["smartforge"] == True
    assert len(config["browsing_sites"]) > 5
    assert len(config["cookie_sites"]) > 3
    assert config["card_data"] is not None, "No card generated"
    pn = config["persona_name"]
    dm = config["device_model"]
    cr = config["carrier"]
    cd = config["card_data"]["number"][-4:]
    bs = len(config["browsing_sites"])
    cs = len(config["cookie_sites"])
    print("         persona: " + pn)
    print("         device: " + dm)
    print("         carrier: " + cr)
    print("         card: ****" + cd)
    print("         sites: " + str(bs) + " browsing, " + str(cs) + " cookies")

def t_sf_override():
    from smartforge_bridge import smartforge_for_android
    config = smartforge_for_android(
        occupation="doctor", country="GB", age=45,
        identity_override={"name": "Dr. James Watson", "email": "jwatson@nhs.uk"},
    )
    assert "Watson" in config["persona_name"]
    assert "jwatson" in config["persona_email"]

test("import", t_sf_import)
test("generate_profile", t_sf_generate)
test("identity_override", t_sf_override)

# === Test 2: Purchase History Bridge ===
print("\n=== Test 2: Purchase History Bridge ===")

def t_ph_import():
    from purchase_history_bridge import generate_android_purchase_history, get_available_merchants
    merchants = get_available_merchants()
    assert len(merchants) >= 6

def t_ph_generate():
    from purchase_history_bridge import generate_android_purchase_history
    ph = generate_android_purchase_history(
        persona_name="Alex Mercer",
        persona_email="alex.mercer42@gmail.com",
        country="US",
        age_days=120,
        card_last4="4242",
    )
    assert len(ph["purchases"]) >= 3
    assert len(ph["chrome_history"]) >= 9
    assert len(ph["chrome_cookies"]) >= 4
    assert len(ph["notifications"]) >= 3
    assert len(ph["email_receipts"]) >= 3
    s = ph["purchase_summary"]
    tp = s["total_purchases"]
    ts = s["total_spent"]
    um = s["unique_merchants"]
    he = s["chrome_history_entries"]
    cc = s["chrome_cookies"]
    print("         purchases: " + str(tp) + ", spent: $" + str(round(ts, 2)))
    print("         merchants: " + str(um))
    print("         chrome: " + str(he) + " history, " + str(cc) + " cookies")

test("import", t_ph_import)
test("generate_history", t_ph_generate)

# === Test 3: Full SmartForge + Forge Pipeline ===
print("\n=== Test 3: Full SmartForge + Forge Pipeline ===")

def t_full_pipeline():
    from smartforge_bridge import smartforge_for_android
    from android_profile_forge import AndroidProfileForge

    sf = smartforge_for_android(
        occupation="university_student", country="US", age=22,
        age_days=60, use_ai=False,
    )

    forge = AndroidProfileForge()
    profile = forge.forge(
        persona_name=sf["persona_name"],
        persona_email=sf["persona_email"],
        persona_phone=sf["persona_phone"],
        country=sf["country"],
        archetype=sf["archetype"],
        age_days=sf["age_days"],
        carrier=sf["carrier"],
        location=sf["location"],
        device_model=sf["device_model"],
    )

    profile["smartforge_config"] = sf.get("smartforge_config", {})
    profile["purchase_categories"] = sf.get("purchase_categories", [])

    pid = profile["id"]
    assert pid
    s = profile["stats"]
    assert s["contacts"] > 0
    assert s["play_purchases"] > 0
    print("         profile: " + pid[:20] + "...")
    print("         contacts=" + str(s["contacts"]) + " calls=" + str(s["call_logs"]) + " sms=" + str(s["sms"]))
    print("         cookies=" + str(s["cookies"]) + " history=" + str(s["history"]) + " gallery=" + str(s["gallery"]))
    print("         purchases=" + str(s["play_purchases"]) + " usage=" + str(s["app_usage"]))

test("full_pipeline", t_full_pipeline)

# === Test 4: API Server Import ===
print("\n=== Test 4: API Server Import ===")

def t_api():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "titan_api",
        os.path.join(os.path.dirname(__file__), "..", "server", "titan_api.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "genesis_smartforge"), "No smartforge endpoint"
    assert hasattr(mod, "genesis_occupations"), "No occupations endpoint"
    assert hasattr(mod, "genesis_countries"), "No countries endpoint"
    assert hasattr(mod, "genesis_trust_score"), "No trust-score endpoint"

test("api_import", t_api)

# === Summary ===
print("\n" + "=" * 50)
if errors:
    print("  FAILED: " + str(len(errors)) + " — " + str(errors))
    sys.exit(1)
else:
    print("  ALL TESTS PASSED")
    sys.exit(0)
