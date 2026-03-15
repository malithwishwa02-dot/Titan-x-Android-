"""
Titan V11.3 — Genesis Router
/api/genesis/* — Profile forge, inject, smartforge, trust score
"""

import json
import logging
import os
import time as _time_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from device_manager import DeviceManager
from android_profile_forge import AndroidProfileForge
from profile_injector import ProfileInjector

router = APIRouter(prefix="/api/genesis", tags=["genesis"])
logger = logging.getLogger("titan.genesis")

dm: DeviceManager = None
_forge = AndroidProfileForge()


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


class GenesisCreateBody(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    country: str = "US"
    archetype: str = "professional"
    age_days: int = 90
    carrier: str = "tmobile_us"
    location: str = "nyc"
    device_model: str = "samsung_s25_ultra"
    cc_number: str = ""
    cc_exp_month: int = 0
    cc_exp_year: int = 0
    cc_cvv: str = ""
    cc_cardholder: str = ""
    install_wallets: bool = True
    pre_login: bool = True


class GenesisInjectBody(BaseModel):
    profile_id: str = ""
    cc_number: str = ""
    cc_exp_month: int = 0
    cc_exp_year: int = 0
    cc_cvv: str = ""
    cc_cardholder: str = ""


class SmartForgeBody(BaseModel):
    occupation: str = "software_engineer"
    country: str = "US"
    age: int = 30
    gender: str = "auto"
    target_site: str = "amazon.com"
    use_ai: bool = False
    age_days: int = 0
    name: str = ""
    email: str = ""
    phone: str = ""
    dob: str = ""
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    card_number: str = ""
    card_exp: str = ""
    card_cvv: str = ""


def _profiles_dir() -> Path:
    d = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/create")
async def genesis_create(body: GenesisCreateBody):
    """Forge a complete Android device profile. All fields derived from persona inputs."""
    try:
        # Build persona address from user inputs
        persona_address = None
        if body.cc_cardholder:  # If cardholder provided, user gave full identity
            pass
        # Build address dict if street provided
        if hasattr(body, 'street') and body.cc_cardholder:  # use fields from SmartForge path
            pass

        profile = _forge.forge(
            persona_name=body.name, persona_email=body.email, persona_phone=body.phone,
            country=body.country, archetype=body.archetype, age_days=body.age_days,
            carrier=body.carrier, location=body.location, device_model=body.device_model,
        )
        pf = _profiles_dir() / f"{profile['id']}.json"
        pf.write_text(json.dumps(profile))
        return {
            "profile_id": profile["id"],
            "stats": profile["stats"],
            "persona": {"name": profile["persona_name"], "email": profile["persona_email"], "phone": profile["persona_phone"]},
        }
    except Exception as e:
        logger.exception("Genesis forge failed")
        raise HTTPException(500, str(e))


@router.get("/profiles")
async def genesis_list():
    """List all forged profiles."""
    profiles = []
    for f in sorted(_profiles_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text())
            profiles.append({
                "id": data.get("id", f.stem), "persona_name": data.get("persona_name", ""),
                "persona_email": data.get("persona_email", ""), "country": data.get("country", ""),
                "archetype": data.get("archetype", ""), "age_days": data.get("age_days", 0),
                "device_model": data.get("device_model", ""), "created_at": data.get("created_at", ""),
                "stats": data.get("stats", {}),
            })
        except Exception:
            pass
    return {"profiles": profiles, "count": len(profiles)}


@router.get("/profiles/{profile_id}")
async def genesis_get(profile_id: str):
    pf = _profiles_dir() / f"{profile_id}.json"
    if not pf.exists():
        raise HTTPException(404, "Profile not found")
    return json.loads(pf.read_text())


@router.delete("/profiles/{profile_id}")
async def genesis_delete(profile_id: str):
    pf = _profiles_dir() / f"{profile_id}.json"
    if pf.exists():
        pf.unlink()
    return {"deleted": profile_id}


import asyncio
import threading
import time as _time
import uuid as _uuid

_inject_jobs: Dict[str, dict] = {}


def _run_inject_job(job_id: str, adb_target: str, profile_data: dict,
                    card_data: dict, device_id: str, profile_id: str):
    """Background worker for profile injection (ADB path)."""
    job = _inject_jobs[job_id]
    try:
        injector = ProfileInjector(adb_target=adb_target)
        result = injector.inject_full_profile(profile_data, card_data=card_data)
        job.update({
            "status": "completed", "trust_score": result.trust_score,
            "result": result.to_dict(), "completed_at": _time.time(),
        })
        logger.info(f"Inject job {job_id} completed: trust={result.trust_score}")
    except Exception as e:
        job.update({"status": "failed", "error": str(e), "completed_at": _time.time()})
        logger.exception(f"Inject job {job_id} failed")


@router.post("/inject/{device_id}")
async def genesis_inject(device_id: str, body: GenesisInjectBody):
    """Inject forged profile into Android device via ADB (runs in background)."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    pf = _profiles_dir() / f"{body.profile_id}.json"
    if not pf.exists():
        raise HTTPException(404, f"Profile not found: {body.profile_id}")

    profile_data = json.loads(pf.read_text())

    gallery_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "forge_gallery"
    if gallery_dir.exists():
        profile_data["gallery_paths"] = [str(p) for p in sorted(gallery_dir.glob("*.jpg"))[:25]]

    card_data = None
    if body.cc_number:
        card_data = {
            "number": body.cc_number, "exp_month": body.cc_exp_month,
            "exp_year": body.cc_exp_year, "cvv": body.cc_cvv,
            "cardholder": body.cc_cardholder or profile_data.get("persona_name", ""),
        }

    job_id = str(_uuid.uuid4())[:8]
    _inject_jobs[job_id] = {
        "status": "running", "device_id": device_id,
        "profile_id": body.profile_id, "started_at": _time.time(),
    }

    # All devices use ADB injection (Cuttlefish backend)
    t = threading.Thread(
        target=_run_inject_job,
        args=(job_id, dev.adb_target, profile_data, card_data, device_id, body.profile_id),
        daemon=True,
    )
    t.start()

    return {
        "status": "inject_started", "job_id": job_id,
        "device_id": device_id, "profile_id": body.profile_id,
        "poll_url": f"/api/genesis/inject-status/{job_id}",
    }


@router.get("/inject-status/{job_id}")
async def genesis_inject_status(job_id: str):
    """Poll injection job status."""
    job = _inject_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/trust-score/{device_id}")
async def genesis_trust_score(device_id: str):
    """Compute trust score for a device based on injected data presence."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    # ── ADB path (Cuttlefish) ─────────────────────────────────────
    from device_manager import _adb_shell as dm_shell
    t = dev.adb_target
    checks = {}
    score = 0

    # 1. Google account present
    has_google = bool(dm_shell(t, "ls /data/system_ce/0/accounts_ce.db 2>/dev/null"))
    checks["google_account"] = {"present": has_google, "weight": 15}
    if has_google: score += 15

    # 2. Contacts populated
    contacts_count = dm_shell(t, "content query --uri content://contacts/phones --projection _id | wc -l")
    try: contacts_n = int(contacts_count.strip()) if contacts_count.strip().isdigit() else 0
    except ValueError: contacts_n = 0
    checks["contacts"] = {"count": contacts_n, "weight": 8}
    if contacts_n >= 5: score += 8

    # 3. Chrome cookies exist
    has_cookies = bool(dm_shell(t, "ls /data/data/com.android.chrome/app_chrome/Default/Cookies 2>/dev/null"))
    checks["chrome_cookies"] = {"present": has_cookies, "weight": 8}
    if has_cookies: score += 8

    # 4. Chrome history exists
    has_history = bool(dm_shell(t, "ls /data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null"))
    checks["chrome_history"] = {"present": has_history, "weight": 8}
    if has_history: score += 8

    # 5. Gallery has photos
    gallery_count = dm_shell(t, "ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l")
    try: gallery_n = int(gallery_count.strip()) if gallery_count.strip().isdigit() else 0
    except ValueError: gallery_n = 0
    checks["gallery"] = {"count": gallery_n, "weight": 5}
    if gallery_n >= 3: score += 5

    # 6. Google Pay wallet data — deep check (schema + token count)
    tapandpay_path = "/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db"
    has_wallet = bool(dm_shell(t, f"ls {tapandpay_path} 2>/dev/null"))
    wallet_tokens = 0
    if has_wallet:
        token_raw = dm_shell(t, f"sqlite3 {tapandpay_path} 'SELECT COUNT(*) FROM tokens' 2>/dev/null")
        try: wallet_tokens = int(token_raw.strip()) if token_raw and token_raw.strip().isdigit() else 0
        except ValueError: wallet_tokens = 0
    wallet_valid = has_wallet and wallet_tokens > 0
    checks["google_pay"] = {"present": has_wallet, "tokens": wallet_tokens, "valid": wallet_valid, "weight": 12}
    if wallet_valid: score += 12

    # 6b. NFC prefs (tap-and-pay ready)
    nfc_prefs = dm_shell(t, "cat /data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml 2>/dev/null")
    has_nfc = "nfc_enabled" in (nfc_prefs or "")
    checks["nfc_tap_pay"] = {"present": has_nfc, "weight": 0}

    # 6c. GMS billing state
    gms_wallet = dm_shell(t, "cat /data/data/com.google.android.gms/shared_prefs/wallet_instrument_prefs.xml 2>/dev/null")
    has_gms_billing = "wallet_setup_complete" in (gms_wallet or "")
    checks["gms_billing_sync"] = {"present": has_gms_billing, "weight": 0}

    # 6d. Keybox loaded
    keybox_prop = dm_shell(t, "getprop persist.titan.keybox.loaded")
    has_keybox = keybox_prop.strip() == "1" if keybox_prop else False
    checks["keybox"] = {"present": has_keybox, "loaded": has_keybox, "weight": 0}

    # 7. Play Store library
    has_library = bool(dm_shell(t, "ls /data/data/com.android.vending/databases/library.db 2>/dev/null"))
    checks["play_store_library"] = {"present": has_library, "weight": 8}
    if has_library: score += 8

    # 8. WiFi networks saved
    has_wifi = bool(dm_shell(t, "ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null"))
    checks["wifi_networks"] = {"present": has_wifi, "weight": 4}
    if has_wifi: score += 4

    # 9. SMS present (sqlite3 fallback — content provider can freeze on Cuttlefish)
    sms_count = dm_shell(t, "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db 'SELECT COUNT(*) FROM sms' 2>/dev/null")
    try: sms_n = int(sms_count.strip()) if sms_count and sms_count.strip().isdigit() else 0
    except ValueError: sms_n = 0
    checks["sms"] = {"count": sms_n, "weight": 7}
    if sms_n >= 5: score += 7

    # 10. Call logs present (sqlite3 fallback)
    calls_count = dm_shell(t, "sqlite3 /data/data/com.android.providers.contacts/databases/calllog.db 'SELECT COUNT(*) FROM calls' 2>/dev/null")
    if not calls_count or not calls_count.strip().isdigit():
        calls_count = dm_shell(t, "content query --uri content://call_log/calls --projection _id 2>/dev/null | wc -l")
    try: calls_n = int(calls_count.strip()) if calls_count and calls_count.strip().isdigit() else 0
    except ValueError: calls_n = 0
    checks["call_logs"] = {"count": calls_n, "weight": 7}
    if calls_n >= 10: score += 7

    # 11. App SharedPrefs populated
    has_app_prefs = bool(dm_shell(t, "ls /data/data/com.instagram.android/shared_prefs/ 2>/dev/null"))
    checks["app_data"] = {"present": has_app_prefs, "weight": 8}
    if has_app_prefs: score += 8

    # 12. Chrome signed in
    has_chrome_prefs = bool(dm_shell(t, "ls /data/data/com.android.chrome/app_chrome/Default/Preferences 2>/dev/null"))
    checks["chrome_signin"] = {"present": has_chrome_prefs, "weight": 5}
    if has_chrome_prefs: score += 5

    # 13. Autofill data
    has_autofill = bool(dm_shell(t, "ls '/data/data/com.android.chrome/app_chrome/Default/Web Data' 2>/dev/null"))
    checks["autofill"] = {"present": has_autofill, "weight": 5}
    if has_autofill: score += 5

    # 14. GSM / SIM alignment (set by AnomalyPatcher Phase 2)
    gsm_state    = dm_shell(t, "getprop gsm.sim.state")
    gsm_operator = dm_shell(t, "getprop gsm.sim.operator.alpha")
    gsm_mcc_mnc  = dm_shell(t, "getprop gsm.sim.operator.numeric")
    gsm_ok = (
        (gsm_state or "").strip() == "READY" and
        len((gsm_operator or "").strip()) > 0 and
        len((gsm_mcc_mnc or "").strip()) >= 5
    )
    checks["gsm_sim"] = {
        "state": (gsm_state or "").strip(),
        "operator": (gsm_operator or "").strip(),
        "mcc_mnc": (gsm_mcc_mnc or "").strip(),
        "ok": gsm_ok, "weight": 8,
    }
    if gsm_ok: score += 8

    max_score = 108  # 100 base + 8 GSM
    normalized = min(100, round(score / max_score * 100))
    return {
        "device_id": device_id, "trust_score": normalized, "raw_score": score, "max_score": max_score,
        "grade": "A+" if normalized >= 90 else "A" if normalized >= 80 else "B" if normalized >= 65 else "C" if normalized >= 50 else "D" if normalized >= 30 else "F",
        "checks": checks,
    }


@router.post("/smartforge")
async def genesis_smartforge(body: SmartForgeBody):
    """AI-powered SmartForge: persona-driven forge with ALL fields from user inputs."""
    try:
        from smartforge_bridge import smartforge_for_android

        override = {}
        for field_name in ["name", "email", "phone", "dob", "street", "city", "state", "zip", "card_number", "card_exp", "card_cvv"]:
            val = getattr(body, field_name, "")
            if val:
                override[field_name] = val

        android_config = smartforge_for_android(
            occupation=body.occupation, country=body.country, age=body.age,
            gender=body.gender, target_site=body.target_site, use_ai=body.use_ai,
            identity_override=override if override else None, age_days=body.age_days,
        )

        # Build persona_address from resolved SmartForge config
        persona_address = None
        if android_config.get("street"):
            persona_address = {
                "address": android_config["street"],
                "city": android_config.get("city", ""),
                "state": android_config.get("state", ""),
                "zip": android_config.get("zip", ""),
                "country": android_config.get("country", "US"),
            }

        profile = _forge.forge(
            persona_name=android_config["persona_name"], persona_email=android_config["persona_email"],
            persona_phone=android_config["persona_phone"], country=android_config["country"],
            archetype=android_config["archetype"], age_days=android_config["age_days"],
            carrier=android_config["carrier"], location=android_config["location"],
            device_model=android_config["device_model"],
            persona_address=persona_address,
            persona_area_code=android_config.get("persona_area_code", ""),
            city_area_codes=android_config.get("city_area_codes", []),
        )

        profile["smartforge_config"] = android_config.get("smartforge_config", {})
        profile["browsing_sites"] = android_config.get("browsing_sites", [])
        profile["cookie_sites"] = android_config.get("cookie_sites", [])
        profile["purchase_categories"] = android_config.get("purchase_categories", [])
        profile["social_platforms"] = android_config.get("social_platforms", [])

        return {
            "profile_id": profile["id"], "stats": profile["stats"],
            "persona": {
                "name": android_config["persona_name"], "email": android_config["persona_email"],
                "phone": android_config["persona_phone"], "occupation": android_config["occupation"],
                "age": android_config["age"], "country": android_config["country"],
                "device_model": android_config["device_model"],
            },
            "smartforge": {
                "ai_enriched": android_config.get("ai_enriched", False),
                "osint_enriched": android_config.get("osint_enriched", False),
                "age_days": android_config["age_days"],
                "has_card": android_config.get("card_data") is not None,
                "carrier": android_config["carrier"],
                "locale": android_config.get("locale", ""),
                "timezone": android_config.get("timezone", ""),
            },
            "card_data": android_config.get("card_data"),
        }
    except Exception as e:
        logger.exception("SmartForge failed")
        raise HTTPException(500, str(e))


@router.get("/occupations")
async def genesis_occupations():
    from smartforge_bridge import get_occupations
    return {"occupations": get_occupations()}


@router.get("/countries")
async def genesis_countries():
    from smartforge_bridge import get_countries
    return {"countries": get_countries()}


class AgeDeviceBody(BaseModel):
    device_id: str
    preset: str = "pixel_9_pro"
    carrier: str = "tmobile_us"
    location: str = "nyc"
    age_days: int = 90
    persona: str = ""


# ── Full Provision: inject + full_patch in one atomic background job ─────────

class FullProvisionBody(BaseModel):
    profile_id: str
    cc_number: str = ""
    cc_exp_month: int = 0
    cc_exp_year: int = 0
    cc_cvv: str = ""
    cc_cardholder: str = ""
    preset: str = ""       # optional override; defaults to profile's device_model
    lockdown: bool = False


_provision_jobs: Dict[str, dict] = {}


def _run_provision_job(job_id: str, adb_target: str, profile_data: dict,
                       card_data: Optional[dict], preset: str, lockdown: bool):
    """Background worker: inject profile → full_patch (26 phases) → GSM verify → trust score."""
    import subprocess as _sp
    job = _provision_jobs[job_id]

    def _adb(cmd, timeout=15):
        try:
            r = _sp.run(["adb", "-s", adb_target, "shell", cmd],
                        capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip()
        except Exception:
            return ""

    try:
        # ── Step 1: Profile injection ────────────────────────────────
        job.update({"step": "inject", "step_n": 1})
        injector = ProfileInjector(adb_target=adb_target)
        inj_result = injector.inject_full_profile(profile_data, card_data=card_data)
        job["inject_trust"] = inj_result.trust_score

        # ── Step 2: Full patch (26 phases, 103+ vectors) ─────────────
        job.update({"step": "patch", "step_n": 2})
        from anomaly_patcher import AnomalyPatcher
        carrier  = profile_data.get("carrier",      "tmobile_us")
        location = profile_data.get("location",     "nyc")
        model    = preset or profile_data.get("device_model", "samsung_s25_ultra")
        patcher  = AnomalyPatcher(adb_target=adb_target)
        report   = patcher.full_patch(model, carrier, location, lockdown=lockdown)
        job["patch_score"]    = report.score
        job["phases_passed"]  = report.passed
        job["phases_total"]   = report.total
        job["patch_results"]  = report.results[:40]  # first 40 for payload size

        # ── Step 3: GSM verify ────────────────────────────────────────
        job.update({"step": "gsm_verify", "step_n": 3})
        gsm_state    = _adb("getprop gsm.sim.state")
        gsm_operator = _adb("getprop gsm.sim.operator.alpha")
        gsm_mcc_mnc  = _adb("getprop gsm.sim.operator.numeric")
        gsm_ok = (
            gsm_state.strip() == "READY" and
            len(gsm_operator.strip()) > 0 and
            len(gsm_mcc_mnc.strip()) >= 5
        )
        job["gsm"] = {
            "ok": gsm_ok,
            "state": gsm_state.strip(),
            "operator": gsm_operator.strip(),
            "mcc_mnc": gsm_mcc_mnc.strip(),
            "expected_carrier": carrier,
        }

        # ── Step 4: Trust score ───────────────────────────────────────
        job.update({"step": "trust_score", "step_n": 4})
        trust_raw = 0
        trust_checks: dict = {}
        # contacts
        c = _adb("content query --uri content://contacts/phones --projection _id | wc -l")
        cn = int(c.strip()) if c.strip().isdigit() else 0
        trust_checks["contacts"] = cn >= 5; trust_raw += 8 if cn >= 5 else 0
        # chrome cookies
        ok = bool(_adb("ls /data/data/com.android.chrome/app_chrome/Default/Cookies 2>/dev/null"))
        trust_checks["chrome_cookies"] = ok; trust_raw += 8 if ok else 0
        # chrome history
        ok = bool(_adb("ls /data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null"))
        trust_checks["chrome_history"] = ok; trust_raw += 8 if ok else 0
        # wallet
        tw = _adb("sqlite3 /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 'SELECT COUNT(*) FROM tokens' 2>/dev/null")
        wt = int(tw.strip()) if tw and tw.strip().isdigit() else 0
        trust_checks["google_pay"] = wt > 0; trust_raw += 12 if wt > 0 else 0
        # sms
        s = _adb("sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db 'SELECT COUNT(*) FROM sms' 2>/dev/null")
        sn = int(s.strip()) if s and s.strip().isdigit() else 0
        trust_checks["sms"] = sn >= 5; trust_raw += 7 if sn >= 5 else 0
        # call logs
        cl = _adb("sqlite3 /data/data/com.android.providers.contacts/databases/calllog.db 'SELECT COUNT(*) FROM calls' 2>/dev/null")
        cln = int(cl.strip()) if cl and cl.strip().isdigit() else 0
        trust_checks["call_logs"] = cln >= 10; trust_raw += 7 if cln >= 10 else 0
        # wifi
        ok = bool(_adb("ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null"))
        trust_checks["wifi"] = ok; trust_raw += 4 if ok else 0
        # gsm
        trust_checks["gsm_sim"] = gsm_ok; trust_raw += 8 if gsm_ok else 0
        trust_score = min(100, round(trust_raw / 62 * 100))  # 62 = max from above checks

        job.update({
            "status": "completed",
            "step": "done",
            "step_n": 4,
            "trust_score": trust_score,
            "trust_checks": trust_checks,
            "completed_at": _time_mod.time(),
        })
        logger.info(f"Provision job {job_id} done: patch={report.score} trust={trust_score} gsm={'OK' if gsm_ok else 'FAIL'}")

    except Exception as e:
        job.update({"status": "failed", "error": str(e), "completed_at": _time_mod.time()})
        logger.exception(f"Provision job {job_id} failed")


@router.post("/full-provision/{device_id}")
async def genesis_full_provision(device_id: str, body: FullProvisionBody):
    """One-shot endpoint: inject genesis profile + full_patch (26 phases) + GSM verify.
    Returns a job_id; poll /provision-status/{job_id} for progress."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    pf = _profiles_dir() / f"{body.profile_id}.json"
    if not pf.exists():
        raise HTTPException(404, f"Profile not found: {body.profile_id}")

    profile_data = json.loads(pf.read_text())

    # Attach gallery stubs if available
    gallery_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "forge_gallery"
    if gallery_dir.exists():
        profile_data["gallery_paths"] = [str(p) for p in sorted(gallery_dir.glob("*.jpg"))[:25]]

    card_data = None
    if body.cc_number:
        card_data = {
            "number": body.cc_number,
            "exp_month": body.cc_exp_month,
            "exp_year": body.cc_exp_year,
            "cvv": body.cc_cvv,
            "cardholder": body.cc_cardholder or profile_data.get("persona_name", ""),
        }

    job_id = str(_uuid.uuid4())[:8]
    _provision_jobs[job_id] = {
        "status": "running",
        "device_id": device_id,
        "profile_id": body.profile_id,
        "step": "inject",
        "step_n": 1,
        "started_at": _time_mod.time(),
        "patch_score": None,
        "trust_score": None,
        "gsm": None,
    }

    t = threading.Thread(
        target=_run_provision_job,
        args=(job_id, dev.adb_target, profile_data, card_data,
              body.preset, body.lockdown),
        daemon=True,
    )
    t.start()

    return {
        "status": "started",
        "job_id": job_id,
        "device_id": device_id,
        "profile_id": body.profile_id,
        "poll_url": f"/api/genesis/provision-status/{job_id}",
    }


@router.get("/provision-status/{job_id}")
async def genesis_provision_status(job_id: str):
    """Poll full-provision job status."""
    job = _provision_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Provision job not found")
    return job


@router.post("/age-device/{device_id}")
async def genesis_age_device(device_id: str, body: AgeDeviceBody):
    """Run anomaly-patching phases on the device. Routes by device_type."""
    import functools

    dev = dm.get_device(device_id) if dm else None

    # ── ADB path (Cuttlefish) ─────────────────────────────────────
    try:
        from anomaly_patcher import AnomalyPatcher
        adb_target = "127.0.0.1:6520"
        if dev:
            adb_target = dev.adb_target

        patcher = AnomalyPatcher(adb_target=adb_target)
        loop = asyncio.get_event_loop()
        fn = functools.partial(
            patcher.full_patch,
            preset_name=body.preset,
            carrier_name=body.carrier,
            location_name=body.location,
        )
        report = await asyncio.wait_for(loop.run_in_executor(None, fn), timeout=120.0)
        return {"status": "complete", "device_id": device_id, "phases": len(report.results), "report": report.__dict__}
    except asyncio.TimeoutError:
        return {"status": "timeout", "device_id": device_id}
    except (ImportError, Exception) as e:
        logger.error("age-device error: %s", e)
        return {"status": "error", "error": str(e), "device_id": device_id}



