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

@app.post("/api/genesis/inject/{device_id}")
async def genesis_inject(device_id: str, body: GenesisInjectBody):
    """Inject forged profile into Android device via ADB — contacts, calls, SMS, cookies, history, gallery."""
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

    # Inject via ADB
    try:
        injector = ProfileInjector(adb_target=dev.adb_target)
        result = injector.inject_full_profile(profile_data)
        return {
            "status": "injected",
            "device_id": device_id,
            "profile_id": body.profile_id,
            "result": result.to_dict(),
        }
    except Exception as e:
        logger.exception("Inject failed")
        raise HTTPException(500, str(e))


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
            await asyncio.sleep(1.0)  # ~1 FPS screencap
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
# STARTUP
# ═══════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    logger.info("Titan V11.3 API Server starting")
    logger.info(f"Devices loaded: {len(dm.list_devices())}")
    logger.info(f"Console dir: {CONSOLE_DIR}")
    logger.info(f"Core dir: {CORE_DIR}")
