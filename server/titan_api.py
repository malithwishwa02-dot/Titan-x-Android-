"""
Titan V11.3 — Unified API Server
FastAPI backend serving all 10 app sections (62 tabs) + device management.
Replaces all PyQt6 desktop apps with REST + WebSocket APIs.

Sections:
  /api/devices/*     — Device CRUD, streaming, screenshots
  /api/stealth/*     — Anomaly patcher, audit, presets
  /api/genesis/*     — Profile forge, inject, warm, export
  /api/intel/*       — AI copilot, 3DS, detection, recon, dark web
  /api/network/*     — VPN, shield, forensic, proxy
  /api/cerberus/*    — Card validation, batch, routing, BIN
  /api/targets/*     — OSINT analyzer, WAF, SSL, DNS, scoring
  /api/kyc/*         — Camera inject, deepfake, liveness, voice
  /api/admin/*       — Services, tools, automation, diagnostics
  /api/ai/*          — AI task routing, metrics, providers
  /api/dashboard/*   — Live ops feed, heatmap, decline waterfall
  /api/settings/*    — VPN, AI, services, API keys, proxy config
"""

import asyncio
import io
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add core to path
CORE_DIR = Path(__file__).parent.parent / "core"
V11_CORE = os.environ.get("PYTHONPATH", "").split(":")
sys.path.insert(0, str(CORE_DIR))
for p in V11_CORE:
    if p and p not in sys.path:
        sys.path.insert(0, p)

from device_manager import DeviceManager, CreateDeviceRequest, DeviceInstance
from anomaly_patcher import AnomalyPatcher
from device_presets import (
    DEVICE_PRESETS, CARRIERS, LOCATIONS, COUNTRY_DEFAULTS,
    list_preset_names,
)
from app_bundles import (
    APP_BUNDLES, VIRTUAL_NUMBER_APPS, COUNTRY_BUNDLES,
    get_bundles_for_country, list_all_bundles,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("titan.api")

# ═══════════════════════════════════════════════════════════════════════
# APP INIT
# ═══════════════════════════════════════════════════════════════════════

app = FastAPI(title="Titan V11.3 Antidetect Device Platform", version="11.3.0")

CONSOLE_DIR = Path(__file__).parent.parent / "console"

# Serve static console files
if CONSOLE_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(CONSOLE_DIR)), name="static")

# Device manager singleton
dm = DeviceManager()


# ═══════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════════════

class CreateDeviceBody(BaseModel):
    model: str = "samsung_s25_ultra"
    country: str = "US"
    carrier: str = "tmobile_us"
    location: str = "nyc"
    phone_number: str = ""
    android_version: str = "14"

class PatchDeviceBody(BaseModel):
    preset: str = ""
    carrier: str = ""
    location: str = ""

class InstallAppsBody(BaseModel):
    bundle: str = ""
    packages: List[str] = []


# ═══════════════════════════════════════════════════════════════════════
# CONSOLE — Serves the SPA
# ═══════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def console_root():
    index = CONSOLE_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text())
    return HTMLResponse("<h1>Titan V11.3 — Console not found. Deploy console/index.html</h1>")

@app.get("/mobile", response_class=HTMLResponse)
async def console_mobile():
    mobile = CONSOLE_DIR / "mobile.html"
    if mobile.exists():
        return HTMLResponse(mobile.read_text())
    return HTMLResponse("<h1>Mobile view not found</h1>")


# ═══════════════════════════════════════════════════════════════════════
# SECTION 1: DEVICES — /api/devices/*
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/devices")
async def list_devices():
    devices = dm.list_devices()
    return {"devices": [d.to_dict() for d in devices]}

@app.get("/api/devices/{device_id}")
async def get_device(device_id: str):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    return dev.to_dict()

@app.get("/api/devices/{device_id}/info")
async def get_device_info(device_id: str):
    info = dm.get_device_info(device_id)
    if not info:
        raise HTTPException(404, "Device not found or not ready")
    return info

@app.post("/api/devices")
async def create_device(body: CreateDeviceBody):
    try:
        req = CreateDeviceRequest(
            model=body.model,
            country=body.country,
            carrier=body.carrier,
            phone_number=body.phone_number,
            android_version=body.android_version,
        )
        dev = await dm.create_device(req)

        # Auto-patch with matching preset + carrier + location
        location = body.location
        if not location:
            defaults = COUNTRY_DEFAULTS.get(body.country, {})
            location = defaults.get("location", "nyc")

        patcher = AnomalyPatcher(adb_target=dev.adb_target, container=dev.container)
        patch_result = patcher.full_patch(body.model, body.carrier, location)
        dev.patch_result = patch_result.to_dict()
        dev.stealth_score = patch_result.score
        dev.state = "patched"

        return {"device": dev.to_dict(), "patch": patch_result.to_dict()}
    except Exception as e:
        logger.exception("Create device failed")
        raise HTTPException(500, str(e))

@app.delete("/api/devices/{device_id}")
async def destroy_device(device_id: str):
    ok = await dm.destroy_device(device_id)
    if not ok:
        raise HTTPException(404, "Device not found")
    return {"ok": True}

@app.post("/api/devices/{device_id}/restart")
async def restart_device(device_id: str):
    ok = await dm.restart_device(device_id)
    if not ok:
        raise HTTPException(404, "Device not found")
    return {"ok": True}

@app.get("/api/devices/{device_id}/screenshot")
async def device_screenshot(device_id: str):
    data = await dm.screenshot(device_id)
    if not data:
        raise HTTPException(404, "Screenshot failed")
    return StreamingResponse(io.BytesIO(data), media_type="image/jpeg")


class InputBody(BaseModel):
    type: str = "tap"
    x: float = 0.0
    y: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    duration: int = 300
    keycode: str = ""
    text: str = ""

@app.post("/api/devices/{device_id}/input")
async def device_input(device_id: str, body: InputBody):
    """Send touch/key input to device via ADB."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    from device_manager import _adb
    t = dev.adb_target

    # Get screen resolution for coordinate mapping
    info = _adb(t, 'shell "wm size"')
    width, height = 1080, 2400
    if info["ok"] and "x" in info["stdout"]:
        try:
            parts = info["stdout"].split(":")[-1].strip().split("x")
            width, height = int(parts[0]), int(parts[1])
        except Exception:
            pass

    if body.type == "tap":
        px, py = int(body.x * width), int(body.y * height)
        _adb(t, f'shell "input tap {px} {py}"')
        return {"ok": True, "action": "tap", "px": px, "py": py}

    elif body.type == "swipe":
        px1, py1 = int(body.x1 * width), int(body.y1 * height)
        px2, py2 = int(body.x2 * width), int(body.y2 * height)
        dur = max(100, min(body.duration, 2000))
        _adb(t, f'shell "input swipe {px1} {py1} {px2} {py2} {dur}"')
        return {"ok": True, "action": "swipe"}

    elif body.type == "key":
        _adb(t, f'shell "input keyevent {body.keycode}"')
        return {"ok": True, "action": "key", "keycode": body.keycode}

    elif body.type == "text":
        # Escape text for ADB shell
        escaped = body.text.replace(" ", "%s").replace("'", "\\'")
        escaped = escaped.replace('"', '\\"').replace("&", "\\&")
        escaped = escaped.replace("(", "\\(").replace(")", "\\)")
        escaped = escaped.replace(";", "\\;").replace("|", "\\|")
        _adb(t, f"shell \"input text '{escaped}'\"")
        return {"ok": True, "action": "text", "length": len(body.text)}

    return {"ok": False, "error": "unknown input type"}


# ═══════════════════════════════════════════════════════════════════════
# SECTION 2: STEALTH — /api/stealth/*
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/stealth/presets")
async def list_presets():
    return {"presets": list_preset_names()}

@app.get("/api/stealth/carriers")
async def list_carriers():
    return {"carriers": {k: {"name": v.name, "mcc": v.mcc, "mnc": v.mnc, "country": v.country}
                         for k, v in CARRIERS.items()}}

@app.get("/api/stealth/locations")
async def list_locations():
    return {"locations": LOCATIONS}

@app.post("/api/stealth/{device_id}/patch")
async def patch_device(device_id: str, body: PatchDeviceBody):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    preset = body.preset or dev.config.get("model", "samsung_s25_ultra")
    carrier = body.carrier or dev.config.get("carrier", "tmobile_us")
    location = body.location or "nyc"

    patcher = AnomalyPatcher(adb_target=dev.adb_target)
    report = patcher.full_patch(preset, carrier, location)
    dev.patch_result = report.to_dict()
    dev.stealth_score = report.score
    return report.to_dict()

@app.get("/api/stealth/{device_id}/audit")
async def audit_device(device_id: str):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    patcher = AnomalyPatcher(adb_target=dev.adb_target)
    return patcher.audit()


# ═══════════════════════════════════════════════════════════════════════
# SECTION 3: GENESIS — /api/genesis/*
# Full Android device profile forging + injection via ADB
# ═══════════════════════════════════════════════════════════════════════

from android_profile_forge import AndroidProfileForge
from profile_injector import ProfileInjector

_forge = AndroidProfileForge()

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
    # Wallet / CC fields
    cc_number: str = ""
    cc_exp_month: int = 0
    cc_exp_year: int = 0
    cc_cvv: str = ""
    cc_cardholder: str = ""
    # Pre-login / trust options
    install_wallets: bool = True
    pre_login: bool = True

@app.post("/api/genesis/create")
async def genesis_create(body: GenesisCreateBody):
    """Forge a complete Android device profile (contacts, calls, SMS, cookies, history, gallery)."""
    try:
        # Auto-generate persona if name empty
        if not body.name:
            import random as _r
            first = _r.choice(["James", "Michael", "Robert", "Sarah", "Emily", "Jessica"])
            last = _r.choice(["Smith", "Johnson", "Williams", "Brown", "Davis", "Wilson"])
            body.name = f"{first} {last}"
        if not body.email:
            body.email = f"{body.name.lower().replace(' ', '.')}{_r.randint(10,99)}@gmail.com"
        if not body.phone:
            area = {"US": "212", "GB": "020", "DE": "030", "FR": "01"}.get(body.country, "212")
            body.phone = f"+1{area}{''.join([str(_r.randint(0,9)) for _ in range(7)])}"

        profile = _forge.forge(
            persona_name=body.name,
            persona_email=body.email,
            persona_phone=body.phone,
            country=body.country,
            archetype=body.archetype,
            age_days=body.age_days,
            carrier=body.carrier,
            location=body.location,
            device_model=body.device_model,
        )
        return {
            "profile_id": profile["id"],
            "stats": profile["stats"],
            "persona": {
                "name": profile["persona_name"],
                "email": profile["persona_email"],
                "phone": profile["persona_phone"],
            },
        }
    except Exception as e:
        logger.exception("Genesis forge failed")
        raise HTTPException(500, str(e))

@app.get("/api/genesis/profiles")
async def genesis_list():
    """List all forged profiles."""
    profiles_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profiles = []
    for f in sorted(profiles_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text())
            profiles.append({
                "id": data.get("id", f.stem),
                "persona_name": data.get("persona_name", ""),
                "persona_email": data.get("persona_email", ""),
                "country": data.get("country", ""),
                "archetype": data.get("archetype", ""),
                "age_days": data.get("age_days", 0),
                "device_model": data.get("device_model", ""),
                "created_at": data.get("created_at", ""),
                "stats": data.get("stats", {}),
            })
        except Exception:
            pass
    return {"profiles": profiles, "count": len(profiles)}

@app.get("/api/genesis/profiles/{profile_id}")
async def genesis_get(profile_id: str):
    """Get full profile data by ID."""
    profiles_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
    pf = profiles_dir / f"{profile_id}.json"
    if not pf.exists():
        raise HTTPException(404, "Profile not found")
    return json.loads(pf.read_text())

@app.delete("/api/genesis/profiles/{profile_id}")
async def genesis_delete(profile_id: str):
    """Delete a forged profile."""
    profiles_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
    pf = profiles_dir / f"{profile_id}.json"
    if pf.exists():
        pf.unlink()
    return {"deleted": profile_id}

class GenesisInjectBody(BaseModel):
    profile_id: str = ""
    # Optional CC data for wallet provisioning during injection
    cc_number: str = ""
    cc_exp_month: int = 0
    cc_exp_year: int = 0
    cc_cvv: str = ""
    cc_cardholder: str = ""

@app.post("/api/genesis/inject/{device_id}")
async def genesis_inject(device_id: str, body: GenesisInjectBody):
    """Inject forged profile into Android device via ADB.
    Includes: contacts, calls, SMS, cookies, history, gallery,
    Google account, wallet/CC, per-app data, Play Store purchases, trust score."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    # Load profile
    profiles_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
    pf = profiles_dir / f"{body.profile_id}.json"
    if not pf.exists():
        raise HTTPException(404, f"Profile not found: {body.profile_id}")

    profile_data = json.loads(pf.read_text())

    # Restore gallery_paths from forge_gallery dir
    gallery_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "forge_gallery"
    if gallery_dir.exists():
        profile_data["gallery_paths"] = [str(p) for p in sorted(gallery_dir.glob("*.jpg"))[:25]]

    # Build card_data dict if CC provided
    card_data = None
    if body.cc_number:
        card_data = {
            "number": body.cc_number,
            "exp_month": body.cc_exp_month,
            "exp_year": body.cc_exp_year,
            "cvv": body.cc_cvv,
            "cardholder": body.cc_cardholder or profile_data.get("persona_name", ""),
        }

    # Inject via ADB
    try:
        injector = ProfileInjector(adb_target=dev.adb_target)
        result = injector.inject_full_profile(profile_data, card_data=card_data)
        return {
            "status": "injected",
            "device_id": device_id,
            "profile_id": body.profile_id,
            "trust_score": result.trust_score,
            "result": result.to_dict(),
        }
    except Exception as e:
        logger.exception("Inject failed")
        raise HTTPException(500, str(e))


@app.get("/api/genesis/trust-score/{device_id}")
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
    acct = dm_shell(t, "content query --uri content://com.android.contacts/profile --projection display_name 2>/dev/null")
    has_google = bool(dm_shell(t, "ls /data/system_ce/0/accounts_ce.db 2>/dev/null"))
    checks["google_account"] = {"present": has_google, "weight": 15}
    if has_google:
        score += 15

    # 2. Contacts populated
    contacts_count = dm_shell(t, "content query --uri content://contacts/phones --projection _id | wc -l")
    try:
        contacts_n = int(contacts_count.strip()) if contacts_count.strip().isdigit() else 0
    except ValueError:
        contacts_n = 0
    checks["contacts"] = {"count": contacts_n, "weight": 8}
    if contacts_n >= 5:
        score += 8

    # 3. Chrome cookies exist
    has_cookies = bool(dm_shell(t, "ls /data/data/com.android.chrome/app_chrome/Default/Cookies 2>/dev/null"))
    checks["chrome_cookies"] = {"present": has_cookies, "weight": 8}
    if has_cookies:
        score += 8

    # 4. Chrome history exists
    has_history = bool(dm_shell(t, "ls /data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null"))
    checks["chrome_history"] = {"present": has_history, "weight": 8}
    if has_history:
        score += 8

    # 5. Gallery has photos
    gallery_count = dm_shell(t, "ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l")
    try:
        gallery_n = int(gallery_count.strip()) if gallery_count.strip().isdigit() else 0
    except ValueError:
        gallery_n = 0
    checks["gallery"] = {"count": gallery_n, "weight": 5}
    if gallery_n >= 3:
        score += 5

    # 6. Google Pay wallet data
    has_wallet = bool(dm_shell(t, "ls /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 2>/dev/null"))
    checks["google_pay"] = {"present": has_wallet, "weight": 12}
    if has_wallet:
        score += 12

    # 7. Play Store library
    has_library = bool(dm_shell(t, "ls /data/data/com.android.vending/databases/library.db 2>/dev/null"))
    checks["play_store_library"] = {"present": has_library, "weight": 8}
    if has_library:
        score += 8

    # 8. WiFi networks saved
    has_wifi = bool(dm_shell(t, "ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null"))
    checks["wifi_networks"] = {"present": has_wifi, "weight": 4}
    if has_wifi:
        score += 4

    # 9. SMS present
    sms_count = dm_shell(t, "content query --uri content://sms --projection _id | wc -l")
    try:
        sms_n = int(sms_count.strip()) if sms_count.strip().isdigit() else 0
    except ValueError:
        sms_n = 0
    checks["sms"] = {"count": sms_n, "weight": 7}
    if sms_n >= 5:
        score += 7

    # 10. Call logs present
    calls_count = dm_shell(t, "content query --uri content://call_log/calls --projection _id | wc -l")
    try:
        calls_n = int(calls_count.strip()) if calls_count.strip().isdigit() else 0
    except ValueError:
        calls_n = 0
    checks["call_logs"] = {"count": calls_n, "weight": 7}
    if calls_n >= 10:
        score += 7

    # 11. App SharedPrefs populated
    has_app_prefs = bool(dm_shell(t, "ls /data/data/com.instagram.android/shared_prefs/ 2>/dev/null"))
    checks["app_data"] = {"present": has_app_prefs, "weight": 8}
    if has_app_prefs:
        score += 8

    # 12. Chrome signed in
    has_chrome_prefs = bool(dm_shell(t, "ls /data/data/com.android.chrome/app_chrome/Default/Preferences 2>/dev/null"))
    checks["chrome_signin"] = {"present": has_chrome_prefs, "weight": 5}
    if has_chrome_prefs:
        score += 5

    # 13. Autofill data
    has_autofill = bool(dm_shell(t, "ls '/data/data/com.android.chrome/app_chrome/Default/Web Data' 2>/dev/null"))
    checks["autofill"] = {"present": has_autofill, "weight": 5}
    if has_autofill:
        score += 5

    return {
        "device_id": device_id,
        "trust_score": score,
        "max_score": 100,
        "grade": "A+" if score >= 90 else "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D" if score >= 30 else "F",
        "checks": checks,
    }


# ─── SMARTFORGE ENDPOINTS ──────────────────────────────────────────

from smartforge_bridge import smartforge_for_android, get_occupations, get_countries

class SmartForgeBody(BaseModel):
    occupation: str = "software_engineer"
    country: str = "US"
    age: int = 30
    gender: str = "auto"
    target_site: str = "amazon.com"
    use_ai: bool = False
    age_days: int = 0
    # Identity override (optional — real data)
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

@app.post("/api/genesis/smartforge")
async def genesis_smartforge(body: SmartForgeBody):
    """AI-powered SmartForge: generate a full persona + forge + ready-to-inject profile.
    Combines v11-release SmartForge engine with Android genesis pipeline."""
    try:
        # Build identity override dict from provided fields
        override = {}
        for field in ["name", "email", "phone", "dob", "street", "city",
                      "state", "zip", "card_number", "card_exp", "card_cvv"]:
            val = getattr(body, field, "")
            if val:
                override[field] = val

        # Generate SmartForge profile adapted for Android
        android_config = smartforge_for_android(
            occupation=body.occupation,
            country=body.country,
            age=body.age,
            gender=body.gender,
            target_site=body.target_site,
            use_ai=body.use_ai,
            identity_override=override if override else None,
            age_days=body.age_days,
        )

        # Forge the Android profile using the SmartForge config
        profile = _forge.forge(
            persona_name=android_config["persona_name"],
            persona_email=android_config["persona_email"],
            persona_phone=android_config["persona_phone"],
            country=android_config["country"],
            archetype=android_config["archetype"],
            age_days=android_config["age_days"],
            carrier=android_config["carrier"],
            location=android_config["location"],
            device_model=android_config["device_model"],
        )

        # Attach SmartForge metadata to profile for injection enrichment
        profile["smartforge_config"] = android_config.get("smartforge_config", {})
        profile["browsing_sites"] = android_config.get("browsing_sites", [])
        profile["cookie_sites"] = android_config.get("cookie_sites", [])
        profile["purchase_categories"] = android_config.get("purchase_categories", [])
        profile["social_platforms"] = android_config.get("social_platforms", [])

        return {
            "profile_id": profile["id"],
            "stats": profile["stats"],
            "persona": {
                "name": android_config["persona_name"],
                "email": android_config["persona_email"],
                "phone": android_config["persona_phone"],
                "occupation": android_config["occupation"],
                "age": android_config["age"],
                "country": android_config["country"],
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


@app.get("/api/genesis/occupations")
async def genesis_occupations():
    """List available occupation archetypes for SmartForge."""
    return {"occupations": get_occupations()}


@app.get("/api/genesis/countries")
async def genesis_countries():
    """List available countries for SmartForge."""
    return {"countries": get_countries()}


# ═══════════════════════════════════════════════════════════════════════
# SECTION 3.5: AI AGENT — /api/agent/*
# Autonomous device control via GPU LLM see→think→act loop
# ═══════════════════════════════════════════════════════════════════════

from device_agent import DeviceAgent, TASK_TEMPLATES

# Cache agents per device
_agents: Dict[str, DeviceAgent] = {}

def _get_agent(device_id: str) -> DeviceAgent:
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    if device_id not in _agents:
        if dev.device_type == "vmos_cloud" and dev.vmos_pad_code:
            # Use VMOS Cloud API adapter for screenshot + touch
            bridge = _get_vmos()
            if bridge:
                from vmos_agent_adapter import VMOSScreenAdapter, VMOSTouchAdapter
                agent = DeviceAgent(adb_target=dev.adb_target or "vmos-api")
                agent.analyzer = VMOSScreenAdapter(bridge=bridge, pad_code=dev.vmos_pad_code)
                agent.touch = VMOSTouchAdapter(bridge=bridge, pad_code=dev.vmos_pad_code)
                _agents[device_id] = agent
                logger.info(f"VMOS agent created for {device_id} (pad={dev.vmos_pad_code})")
            else:
                _agents[device_id] = DeviceAgent(adb_target=dev.adb_target)
        else:
            _agents[device_id] = DeviceAgent(adb_target=dev.adb_target)
    return _agents[device_id]


class AgentTaskBody(BaseModel):
    prompt: str = ""
    template: str = ""          # browse_url, create_account, install_app, etc.
    template_params: Dict[str, str] = {}
    model: str = "hermes3:8b"
    max_steps: int = 30
    persona: Dict[str, str] = {}  # name, email, phone, password for form filling


@app.post("/api/agent/task/{device_id}")
async def agent_start_task(device_id: str, body: AgentTaskBody):
    """Start an autonomous AI task on an Android device.
    The agent will see the screen, decide actions, and execute them via ADB."""
    agent = _get_agent(device_id)

    if body.model:
        agent.model = body.model

    task_id = agent.start_task(
        prompt=body.prompt,
        persona=body.persona if body.persona else None,
        template=body.template if body.template else None,
        template_params=body.template_params if body.template_params else None,
        max_steps=body.max_steps,
    )
    return {"task_id": task_id, "device_id": device_id, "status": "started"}


@app.get("/api/agent/task/{device_id}/{task_id}")
async def agent_task_status(device_id: str, task_id: str):
    """Get status of a running or completed agent task."""
    agent = _get_agent(device_id)
    task = agent.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task.to_dict()


@app.post("/api/agent/stop/{device_id}/{task_id}")
async def agent_stop_task(device_id: str, task_id: str):
    """Stop a running agent task."""
    agent = _get_agent(device_id)
    ok = agent.stop_task(task_id)
    return {"stopped": ok, "task_id": task_id}


@app.get("/api/agent/tasks/{device_id}")
async def agent_list_tasks(device_id: str):
    """List all tasks for a device."""
    agent = _get_agent(device_id)
    return {"tasks": agent.list_tasks()}


@app.get("/api/agent/screen/{device_id}")
async def agent_analyze_screen(device_id: str):
    """One-shot screen analysis — capture screenshot + detect UI elements."""
    agent = _get_agent(device_id)
    return agent.analyze_screen()


@app.get("/api/agent/templates")
async def agent_templates():
    """List available task templates."""
    return {"templates": {k: {"params": v["params"], "prompt": v["prompt"]}
                          for k, v in TASK_TEMPLATES.items()}}


@app.get("/api/agent/models")
async def agent_models():
    """List available AI models on GPU Ollama."""
    import urllib.request
    gpu_url = os.environ.get("TITAN_GPU_OLLAMA", "http://127.0.0.1:11435")
    try:
        req = urllib.request.Request(f"{gpu_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1)}
                      for m in data.get("models", [])]
            return {"models": models, "gpu_url": gpu_url, "status": "connected"}
    except Exception as e:
        return {"models": [], "gpu_url": gpu_url, "status": "disconnected", "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# SECTION 4: INTELLIGENCE — /api/intel/*
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/intel/copilot")
async def intel_copilot(request: Request):
    body = await request.json()
    query = body.get("query", "")
    try:
        from ai_intelligence_engine import recon_target
        result = recon_target(query)
        return {"result": result}
    except ImportError:
        return {"result": f"AI copilot stub response for: {query}", "stub": True}

@app.post("/api/intel/recon")
async def intel_recon(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from target_intelligence import TargetProfiler
        profiler = TargetProfiler()
        result = profiler.profile(domain)
        return {"result": result}
    except ImportError:
        return {"domain": domain, "stub": True}


# ═══════════════════════════════════════════════════════════════════════
# SECTION 5: NETWORK — /api/network/*
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/network/status")
async def network_status():
    try:
        from mullvad_vpn import get_mullvad_status
        return get_mullvad_status()
    except ImportError:
        return {"vpn": "not_connected", "stub": True}

@app.post("/api/network/vpn/connect")
async def vpn_connect(request: Request):
    return {"status": "vpn_connect_queued", "stub": True}


# ═══════════════════════════════════════════════════════════════════════
# SECTION 6: CERBERUS — /api/cerberus/*
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/cerberus/validate")
async def cerberus_validate(request: Request):
    body = await request.json()
    try:
        from cerberus_core import CerberusEngine
        engine = CerberusEngine()
        result = engine.validate_card(body)
        return result
    except ImportError:
        return {"result": "cerberus_stub", "stub": True}


# ═══════════════════════════════════════════════════════════════════════
# SECTION 7: TARGETS — /api/targets/*
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/targets/analyze")
async def target_analyze(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from webcheck_engine import WebCheckEngine
        engine = WebCheckEngine()
        result = engine.full_scan(domain)
        return result
    except ImportError:
        return {"domain": domain, "stub": True}


# ═══════════════════════════════════════════════════════════════════════
# SECTION 8: KYC / DEEPFAKE — /api/kyc/*
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/kyc/{device_id}/upload_face")
async def kyc_upload_face(device_id: str, request: Request):
    """Upload target face image for deepfake pipeline."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    # Stub — wires to gpu_reenact_client
    return {"status": "face_uploaded", "device": device_id}

@app.post("/api/kyc/{device_id}/start_deepfake")
async def kyc_start_deepfake(device_id: str):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    return {"status": "deepfake_started", "device": device_id}

@app.post("/api/kyc/{device_id}/stop_deepfake")
async def kyc_stop_deepfake(device_id: str):
    return {"status": "deepfake_stopped", "device": device_id}


# ═══════════════════════════════════════════════════════════════════════
# SECTION 9: ADMIN — /api/admin/*
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/admin/services")
async def admin_services():
    """Get status of all system services."""
    import subprocess
    services = ["titan-api", "ws-scrcpy", "nginx"]
    result = {}
    for svc in services:
        try:
            r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, timeout=5)
            result[svc] = r.stdout.strip()
        except Exception:
            result[svc] = "unknown"
    return {"services": result}

@app.get("/api/admin/health")
async def admin_health():
    devices = dm.list_devices()
    return {
        "status": "ok",
        "devices": len(devices),
        "devices_ready": sum(1 for d in devices if d.state in ("ready", "patched")),
        "uptime": time.time(),
    }


# ═══════════════════════════════════════════════════════════════════════
# SECTION 10: AI TASKS — /api/ai/*
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/ai/status")
async def ai_status():
    try:
        from ai_task_router import AITaskRouter
        router = AITaskRouter()
        return {"providers": router.get_provider_status()}
    except ImportError:
        return {"providers": {}, "stub": True}


# ═══════════════════════════════════════════════════════════════════════
# SECTION 11: DASHBOARD — /api/dashboard/*
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/dashboard/summary")
async def dashboard_summary():
    devices = dm.list_devices()
    return {
        "total_devices": len(devices),
        "active_devices": sum(1 for d in devices if d.state in ("ready", "patched")),
        "avg_stealth_score": (
            sum(d.stealth_score for d in devices) // max(len(devices), 1)
        ),
        "devices": [
            {"id": d.id, "model": d.config.get("model", ""), "state": d.state,
             "score": d.stealth_score, "carrier": d.config.get("carrier", "")}
            for d in devices
        ],
    }


# ═══════════════════════════════════════════════════════════════════════
# SECTION 12: SETTINGS — /api/settings/*
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/settings")
async def get_settings():
    config_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    settings_file = config_dir / "settings.json"
    if settings_file.exists():
        return json.loads(settings_file.read_text())
    return {"gpu_url": os.environ.get("TITAN_GPU_URL", ""), "stub": True}

@app.post("/api/settings")
async def save_settings(request: Request):
    body = await request.json()
    config_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.json").write_text(json.dumps(body, indent=2))
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════
# APP BUNDLES — /api/bundles/*
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/bundles")
async def get_bundles():
    return {"bundles": list_all_bundles()}

@app.get("/api/bundles/{country}")
async def get_country_bundles(country: str):
    return {"bundles": get_bundles_for_country(country.upper())}

@app.post("/api/bundles/{device_id}/install")
async def install_bundle(device_id: str, body: InstallAppsBody):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    # Stub — real implementation installs APKs via ADB
    return {"status": "install_queued", "device": device_id, "bundle": body.bundle}


# ═══════════════════════════════════════════════════════════════════════
# WEBSOCKET — Live device screen stream
# ═══════════════════════════════════════════════════════════════════════

@app.websocket("/ws/screen/{device_id}")
async def ws_screen(websocket: WebSocket, device_id: str):
    await websocket.accept()
    dev = dm.get_device(device_id)
    if not dev:
        await websocket.close(1008, "Device not found")
        return

    try:
        while True:
            data = await dm.screenshot(device_id)
            if data:
                await websocket.send_bytes(data)
            await asyncio.sleep(0.25)  # ~4 FPS screencap
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS screen error: {e}")


@app.websocket("/ws/logs/{device_id}")
async def ws_logs(websocket: WebSocket, device_id: str):
    """Stream device logcat over WebSocket."""
    await websocket.accept()
    dev = dm.get_device(device_id)
    if not dev:
        await websocket.close(1008, "Device not found")
        return

    try:
        proc = await asyncio.create_subprocess_exec(
            "adb", "-s", dev.adb_target, "logcat", "-v", "time",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode("utf-8", errors="replace"))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS logs error: {e}")
    finally:
        try:
            proc.kill()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# VMOS CLOUD — Bridge API endpoints for hybrid device management
# ═══════════════════════════════════════════════════════════════════════

_vmos_bridge = None

def _get_vmos():
    global _vmos_bridge
    if _vmos_bridge is None:
        try:
            from vmos_cloud_bridge import VMOSCloudBridge
            key = os.environ.get("VMOS_API_KEY", "")
            secret = os.environ.get("VMOS_API_SECRET", "")
            if key and secret:
                _vmos_bridge = VMOSCloudBridge(api_key=key, api_secret=secret)
                logger.info("VMOS Cloud bridge initialized")
            else:
                logger.info("VMOS Cloud not configured (no VMOS_API_KEY)")
        except Exception as e:
            logger.warning(f"VMOS Cloud bridge init failed: {e}")
    return _vmos_bridge


class VMOSRegisterBody(BaseModel):
    pad_code: str
    device_id: str = ""
    model: str = "samsung_s25_ultra"
    country: str = "US"


class VMOSPatchBody(BaseModel):
    brand: str = "samsung"
    model: str = "SM-S928U"
    device: str = "e3q"
    fingerprint: str = ""
    android_version: str = "15"
    imei: str = ""
    iccid: str = ""
    imsi: str = ""
    phone_number: str = ""
    lat: float = 40.7128
    lon: float = -74.0060
    wifi_ssid: str = "NETGEAR72-5G"


class VMOSInjectBody(BaseModel):
    contacts: List[Dict[str, str]] = []
    call_logs: List[Dict[str, Any]] = []
    sms: List[Dict[str, str]] = []
    chrome_commands: List[str] = []
    wallet_commands: List[str] = []


class VMOSShellBody(BaseModel):
    command: str


class VMOSTouchBody(BaseModel):
    x: int = 0
    y: int = 0
    action: str = "tap"       # tap, swipe
    x2: int = 0
    y2: int = 0
    duration: int = 300


class VMOSProxyBody(BaseModel):
    ip: str
    port: int
    username: str = ""
    password: str = ""
    proxy_type: str = "socks5"


@app.get("/api/vmos/status")
async def vmos_status():
    """Check VMOS Cloud bridge connectivity."""
    bridge = _get_vmos()
    if not bridge:
        return {"status": "not_configured", "message": "Set VMOS_API_KEY and VMOS_API_SECRET env vars"}
    try:
        instances = await bridge.list_instances(page=1, rows=5)
        return {
            "status": "connected",
            "instances": len(instances),
            "devices": [i.to_dict() for i in instances],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/vmos/register")
async def vmos_register_device(body: VMOSRegisterBody):
    """Register a VMOS Cloud instance as a Titan device."""
    bridge = _get_vmos()
    if not bridge:
        raise HTTPException(503, "VMOS Cloud not configured")

    dev_id = body.device_id or f"vmos-{body.pad_code[:8].lower()}"

    # Check if already registered
    existing = dm.get_device(dev_id)
    if existing:
        return {"device": existing.to_dict(), "message": "Already registered"}

    # Try to get ADB access via SSH tunnel
    adb_info = await bridge.open_adb(body.pad_code)
    adb_target = ""
    if adb_info:
        adb_target = adb_info.get("adb_connect", "").replace("adb connect ", "")

    from device_manager import DeviceInstance, DEVICES_DIR
    from datetime import datetime, timezone

    dev = DeviceInstance(
        id=dev_id,
        container=f"vmos-{body.pad_code}",
        adb_port=0,
        adb_target=adb_target,
        config={
            "model": body.model,
            "country": body.country,
            "carrier": "",
            "pad_code": body.pad_code,
        },
        state="ready",
        created_at=datetime.now(timezone.utc).isoformat(),
        device_type="vmos_cloud",
        vmos_pad_code=body.pad_code,
    )

    dm._devices[dev_id] = dev
    dm._save_state()

    return {
        "device": dev.to_dict(),
        "adb_info": adb_info,
        "message": f"VMOS device {body.pad_code} registered as {dev_id}",
    }


@app.get("/api/vmos/instances")
async def vmos_list_instances():
    """List all VMOS Cloud instances from the API."""
    bridge = _get_vmos()
    if not bridge:
        raise HTTPException(503, "VMOS Cloud not configured")
    instances = await bridge.list_instances()
    return {"instances": [i.to_dict() for i in instances]}


@app.get("/api/vmos/{device_id}/properties")
async def vmos_get_properties(device_id: str):
    """Get all properties for a VMOS device."""
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")
    props = await bridge.get_instance_properties(dev.vmos_pad_code)
    return {"device_id": device_id, "properties": props}


@app.post("/api/vmos/{device_id}/patch")
async def vmos_patch_device(device_id: str, body: VMOSPatchBody):
    """Apply full stealth patch to VMOS Cloud device using native APIs."""
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")

    result = await bridge.full_stealth_patch(
        dev.vmos_pad_code,
        preset={
            "brand": body.brand, "model": body.model, "device": body.device,
            "fingerprint": body.fingerprint, "android_version": body.android_version,
        },
        carrier={
            "imei": body.imei, "iccid": body.iccid, "imsi": body.imsi,
            "phone_number": body.phone_number,
        },
        location={"lat": body.lat, "lon": body.lon},
        wifi={"ssid": body.wifi_ssid},
    )
    dev.patch_result = result
    dm._save_state()
    return {"device_id": device_id, "result": result}


@app.post("/api/vmos/{device_id}/inject")
async def vmos_inject_profile(device_id: str, body: VMOSInjectBody):
    """Inject profile data into VMOS Cloud device."""
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")

    result = await bridge.full_profile_inject(
        dev.vmos_pad_code,
        contacts=body.contacts or None,
        call_logs=body.call_logs or None,
        sms_messages=body.sms or None,
        chrome_commands=body.chrome_commands or None,
        wallet_commands=body.wallet_commands or None,
    )
    return {"device_id": device_id, "result": result}


@app.post("/api/vmos/{device_id}/shell")
async def vmos_shell(device_id: str, body: VMOSShellBody):
    """Execute shell command on VMOS Cloud device."""
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")

    result = await bridge.exec_shell(dev.vmos_pad_code, body.command)
    return {"device_id": device_id, "result": result.to_dict()}


@app.post("/api/vmos/{device_id}/touch")
async def vmos_touch(device_id: str, body: VMOSTouchBody):
    """Simulate touch on VMOS Cloud device."""
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")

    if body.action == "swipe":
        result = await bridge.swipe(dev.vmos_pad_code, body.x, body.y, body.x2, body.y2, body.duration)
    else:
        result = await bridge.tap(dev.vmos_pad_code, body.x, body.y)
    return {"device_id": device_id, "result": result.to_dict()}


@app.get("/api/vmos/{device_id}/screenshot")
async def vmos_screenshot(device_id: str):
    """Get screenshot URL from VMOS Cloud device."""
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")

    url = await bridge.screenshot(dev.vmos_pad_code)
    if url:
        return {"device_id": device_id, "screenshot_url": url}
    raise HTTPException(500, "Screenshot failed")


@app.post("/api/vmos/{device_id}/proxy")
async def vmos_set_proxy(device_id: str, body: VMOSProxyBody):
    """Set network proxy on VMOS Cloud device."""
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")

    result = await bridge.set_proxy(
        dev.vmos_pad_code, body.ip, body.port,
        username=body.username, password=body.password,
        proxy_type=body.proxy_type,
    )
    return {"device_id": device_id, "result": result.to_dict()}


@app.get("/api/vmos/{device_id}/apps")
async def vmos_list_apps(device_id: str):
    """List installed apps on VMOS Cloud device."""
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")

    apps = await bridge.list_apps(dev.vmos_pad_code)
    return {"device_id": device_id, "apps": apps}


@app.post("/api/vmos/{device_id}/adb")
async def vmos_open_adb(device_id: str):
    """Open ADB-over-SSH tunnel to VMOS Cloud device."""
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")

    info = await bridge.open_adb(dev.vmos_pad_code)
    if info:
        # Update adb_target in device state
        adb_connect = info.get("adb_connect", "").replace("adb connect ", "")
        if adb_connect:
            dev.adb_target = adb_connect
            dm._save_state()
        return {"device_id": device_id, "adb": info}
    raise HTTPException(500, "Failed to open ADB access")


# ═══════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    logger.info("Titan V11.3 API Server starting")
    logger.info(f"Devices loaded: {len(dm.list_devices())}")
    logger.info(f"Console dir: {CONSOLE_DIR}")
    logger.info(f"Core dir: {CORE_DIR}")
