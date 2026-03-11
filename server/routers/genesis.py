"""
Titan V11.3 — Genesis Router
/api/genesis/* — Profile forge, inject, smartforge, trust score
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List

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


import threading
import time as _time
import uuid as _uuid

_inject_jobs: Dict[str, dict] = {}


def _run_inject_job(job_id: str, adb_target: str, profile_data: dict,
                    card_data: dict, device_id: str, profile_id: str):
    """Background worker for profile injection."""
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

    # 6. Google Pay wallet data
    has_wallet = bool(dm_shell(t, "ls /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 2>/dev/null"))
    checks["google_pay"] = {"present": has_wallet, "weight": 12}
    if has_wallet: score += 12

    # 7. Play Store library
    has_library = bool(dm_shell(t, "ls /data/data/com.android.vending/databases/library.db 2>/dev/null"))
    checks["play_store_library"] = {"present": has_library, "weight": 8}
    if has_library: score += 8

    # 8. WiFi networks saved
    has_wifi = bool(dm_shell(t, "ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null"))
    checks["wifi_networks"] = {"present": has_wifi, "weight": 4}
    if has_wifi: score += 4

    # 9. SMS present
    sms_count = dm_shell(t, "content query --uri content://sms --projection _id | wc -l")
    try: sms_n = int(sms_count.strip()) if sms_count.strip().isdigit() else 0
    except ValueError: sms_n = 0
    checks["sms"] = {"count": sms_n, "weight": 7}
    if sms_n >= 5: score += 7

    # 10. Call logs present
    calls_count = dm_shell(t, "content query --uri content://call_log/calls --projection _id | wc -l")
    try: calls_n = int(calls_count.strip()) if calls_count.strip().isdigit() else 0
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

    return {
        "device_id": device_id, "trust_score": score, "max_score": 100,
        "grade": "A+" if score >= 90 else "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D" if score >= 30 else "F",
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
