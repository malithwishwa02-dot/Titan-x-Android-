#!/usr/bin/env python3
"""
Build a 500-day aged, fully-patched device for Jovany Owens.
Runs all 5 phases: stealth patch → forge → inject → age → audit.
"""
import sys, os, json, time, logging

# Add paths
sys.path.insert(0, "/opt/titan-v11.3-device/core")
sys.path.insert(0, "/opt/titan-v11.3-device/server")
sys.path.insert(0, "/opt/titan/core")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build")

ADB_TARGET = "127.0.0.1:5555"
CONTAINER = "titan-dev-us1"

# ── Persona ──────────────────────────────────────────────
PERSONA = {
    "name": "Jovany Owens",
    "email": "jovany.owens59@gmail.com",
    "phone": "+17078361915",
    "gender": "male",
    "dob": "1959-12-11",
    "ssn": "219-19-0937",
    "address": "1866 W 11th St",
    "city": "Los Angeles",
    "state": "California",
    "zip": "90006",
    "country": "US",
}

CC = {
    "number": "4638512320340405",
    "exp_month": 8,
    "exp_year": 2029,
    "cvv": "051",
    "cardholder": "Jovany Owens",
}

AGE_DAYS = 500
PRESET = "samsung_s25_ultra"
CARRIER = "tmobile_us"
LOCATION = "la"

# ═══════════════════════════════════════════════════════════
# PHASE 1: STEALTH PATCH (53+ vectors)
# ═══════════════════════════════════════════════════════════
def phase1_stealth():
    log.info("=" * 60)
    log.info("PHASE 1: STEALTH PATCH — Samsung S25 Ultra / T-Mobile / LA")
    log.info("=" * 60)
    from anomaly_patcher import AnomalyPatcher
    patcher = AnomalyPatcher(adb_target=ADB_TARGET, container=CONTAINER)
    result = patcher.full_patch(PRESET, CARRIER, LOCATION)
    log.info(f"  Stealth score: {result.score}/100")
    log.info(f"  Vectors patched: {result.patched}/{result.total}")
    if result.errors:
        for e in result.errors[:5]:
            log.warning(f"  Error: {e}")
    return result

# ═══════════════════════════════════════════════════════════
# PHASE 2: FORGE PROFILE (500-day history)
# ═══════════════════════════════════════════════════════════
def phase2_forge():
    log.info("=" * 60)
    log.info("PHASE 2: FORGE PROFILE — Jovany Owens, 500 days, US/CA")
    log.info("=" * 60)
    from android_profile_forge import AndroidProfileForge
    forge = AndroidProfileForge()
    profile = forge.forge(
        persona_name=PERSONA["name"],
        persona_email=PERSONA["email"],
        persona_phone=PERSONA["phone"],
        country=PERSONA["country"],
        archetype="professional",
        age_days=AGE_DAYS,
        carrier=CARRIER,
        location=LOCATION,
        device_model=PRESET,
    )
    stats = profile.get("stats", {})
    log.info(f"  Profile ID: {profile['id']}")
    log.info(f"  Contacts: {stats.get('contacts', 0)}")
    log.info(f"  Call logs: {stats.get('call_logs', 0)}")
    log.info(f"  SMS: {stats.get('sms', 0)}")
    log.info(f"  Browser history: {stats.get('history', 0)}")
    log.info(f"  Cookies: {stats.get('cookies', 0)}")
    log.info(f"  Gallery images: {stats.get('gallery', 0)}")

    # Enrich profile with extra persona data
    profile["persona_gender"] = PERSONA["gender"]
    profile["persona_dob"] = PERSONA["dob"]
    profile["persona_ssn"] = PERSONA["ssn"]
    profile["persona_address"] = PERSONA["address"]
    profile["persona_city"] = PERSONA["city"]
    profile["persona_state"] = PERSONA["state"]
    profile["persona_zip"] = PERSONA["zip"]

    # Save enriched profile
    data_dir = "/opt/titan/data/profiles"
    os.makedirs(data_dir, exist_ok=True)
    pf = os.path.join(data_dir, f"{profile['id']}.json")
    with open(pf, "w") as f:
        json.dump(profile, f, indent=2, default=str)
    log.info(f"  Saved: {pf}")
    return profile

# ═══════════════════════════════════════════════════════════
# PHASE 3: INJECT PROFILE + CC INTO DEVICE
# ═══════════════════════════════════════════════════════════
def phase3_inject(profile):
    log.info("=" * 60)
    log.info("PHASE 3: INJECT PROFILE + WALLET INTO DEVICE")
    log.info("=" * 60)
    from profile_injector import ProfileInjector

    # Add gallery paths if available
    gallery_dir = "/opt/titan/data/forge_gallery"
    if os.path.isdir(gallery_dir):
        profile["gallery_paths"] = sorted(
            [os.path.join(gallery_dir, f) for f in os.listdir(gallery_dir) if f.endswith(".jpg")]
        )[:25]

    injector = ProfileInjector(adb_target=ADB_TARGET)
    result = injector.inject_full_profile(profile, card_data=CC)
    log.info(f"  Trust score: {result.trust_score}/100")
    log.info(f"  Phases OK: {result.phases_ok}/{result.phases_total}")
    rd = result.to_dict()
    for k, v in rd.items():
        if isinstance(v, bool):
            log.info(f"    {k}: {'✓' if v else '✗'}")
    return result

# ═══════════════════════════════════════════════════════════
# PHASE 4: DEVICE AGING (500 days)
# ═══════════════════════════════════════════════════════════
def phase4_aging(profile):
    log.info("=" * 60)
    log.info(f"PHASE 4: DEVICE AGING — {AGE_DAYS} days")
    log.info("=" * 60)
    from device_ager import DeviceAger
    ager = DeviceAger(adb_target=ADB_TARGET, container=CONTAINER)
    result = ager.age_device(
        age_days=AGE_DAYS,
        persona_name=PERSONA["name"],
        persona_email=PERSONA["email"],
        country=PERSONA["country"],
        app_installs=profile.get("stats", {}).get("app_installs", []),
        app_usage=profile.get("stats", {}).get("app_usage", []),
    )
    log.info(f"  Aging score: {result.phases_ok}/{result.phases_total} phases")
    return result

# ═══════════════════════════════════════════════════════════
# PHASE 5: FULL AUDIT
# ═══════════════════════════════════════════════════════════
def phase5_audit():
    log.info("=" * 60)
    log.info("PHASE 5: FULL DEVICE AUDIT")
    log.info("=" * 60)
    from device_audit import DeviceRealismAuditor
    auditor = DeviceRealismAuditor(adb_target=ADB_TARGET)
    result = auditor.audit(expected_age_days=AGE_DAYS)
    log.info(f"  Audit score: {result.score}/{result.max_score}")
    log.info(f"  Checks passed: {result.passed}/{result.total}")
    for check in result.checks:
        status = "✓" if check.passed else "✗"
        log.info(f"    [{status}] {check.name}: {check.detail}")
    return result


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    t0 = time.time()
    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║  TITAN V11.3 — FULL DEVICE BUILD                       ║")
    log.info("║  Persona: Jovany Owens | Age: 500 days | Region: US/CA ║")
    log.info("╚══════════════════════════════════════════════════════════╝")

    results = {}

    # Phase 1: Stealth
    try:
        r1 = phase1_stealth()
        results["stealth"] = {"score": r1.score, "patched": r1.patched, "total": r1.total}
    except Exception as e:
        log.error(f"Phase 1 FAILED: {e}")
        results["stealth"] = {"error": str(e)}

    # Phase 2: Forge
    try:
        profile = phase2_forge()
        results["forge"] = {"profile_id": profile["id"], "stats": profile.get("stats", {})}
    except Exception as e:
        log.error(f"Phase 2 FAILED: {e}")
        results["forge"] = {"error": str(e)}
        profile = {}

    # Phase 3: Inject
    if profile:
        try:
            r3 = phase3_inject(profile)
            results["inject"] = {"trust_score": r3.trust_score, "phases_ok": r3.phases_ok}
        except Exception as e:
            log.error(f"Phase 3 FAILED: {e}")
            results["inject"] = {"error": str(e)}

    # Phase 4: Aging
    if profile:
        try:
            r4 = phase4_aging(profile)
            results["aging"] = {"phases_ok": r4.phases_ok, "phases_total": r4.phases_total}
        except Exception as e:
            log.error(f"Phase 4 FAILED: {e}")
            results["aging"] = {"error": str(e)}

    # Phase 5: Audit
    try:
        r5 = phase5_audit()
        results["audit"] = {"score": r5.score, "max": r5.max_score, "passed": r5.passed, "total": r5.total}
    except Exception as e:
        log.error(f"Phase 5 FAILED: {e}")
        results["audit"] = {"error": str(e)}

    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("FINAL BUILD REPORT")
    log.info("=" * 60)
    log.info(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    log.info(f"  Results: {json.dumps(results, indent=2, default=str)}")
    log.info("=" * 60)

    # Save report
    report_path = "/opt/titan/data/build_report_jovany.json"
    with open(report_path, "w") as f:
        json.dump({"persona": PERSONA, "cc_last4": CC["number"][-4:], "results": results, "elapsed_seconds": elapsed}, f, indent=2, default=str)
    log.info(f"Report saved: {report_path}")
