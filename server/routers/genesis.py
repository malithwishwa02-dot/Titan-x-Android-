"""
Titan V11.3 — Genesis Router
/api/genesis/* — Profile forge, smartforge, profiles CRUD, trust score
Provision/inject/age-device endpoints are in provision.py.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import get_dm
from device_manager import DeviceManager
from android_profile_forge import AndroidProfileForge

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
        except Exception as e:
            logger.warning(f"Failed to read profile {f.name}: {e}")
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


@router.get("/trust-score/{device_id}")
async def genesis_trust_score(device_id: str, device_mgr: DeviceManager = Depends(get_dm)):
    """Compute trust score for a device based on injected data presence."""
    dev = device_mgr.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    from trust_scorer import compute_trust_score
    result = compute_trust_score(dev.adb_target)
    result["device_id"] = device_id
    return result


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




