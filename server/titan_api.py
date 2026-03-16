"""
Titan V11.3 — Unified API Server (Restructured)
FastAPI backend serving all 12 app sections (62 tabs) + device management.
Split into router modules for maintainability and performance.
"""

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

# Add core to path — project core, /opt/titan/core, then any PYTHONPATH entries
CORE_DIR = Path(__file__).parent.parent / "core"
OPT_TITAN_CORE = Path("/opt/titan/core")
for _p in [str(CORE_DIR), str(OPT_TITAN_CORE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
V11_CORE = os.environ.get("PYTHONPATH", "").split(":")
for p in V11_CORE:
    if p and p not in sys.path:
        sys.path.insert(0, p)

from device_manager import DeviceManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("titan.api")

# ═══════════════════════════════════════════════════════════════════════
# APP INIT
# ═══════════════════════════════════════════════════════════════════════

app = FastAPI(title="Titan V11.3 Antidetect Device Platform (Cuttlefish)", version="11.3.2")

CONSOLE_DIR = Path(__file__).parent.parent / "console"

# ─── Middleware ────────────────────────────────────────────────────────
from middleware.auth import AuthMiddleware
from middleware.rate_limit import RateLimitMiddleware
from middleware.cpu_governor import cpu_governor

app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static console files
if CONSOLE_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(CONSOLE_DIR)), name="static")

# Device manager singleton
dm = DeviceManager()

# Register DM with FastAPI Depends system
from deps import set_device_manager
set_device_manager(dm)

# ─── Register Routers ─────────────────────────────────────────────────
from routers import devices, stealth, genesis, provision, agent, intel, network
from routers import cerberus, targets, kyc, admin, dashboard, settings
from routers import bundles, ai, ws, training

# Initialize routers that need the device manager (legacy pattern, kept for compat)
for mod in [devices, stealth, genesis, provision, agent, kyc, admin, dashboard, bundles, ws, ai, training]:
    mod.init(dm)

# Include all routers
for r in [devices, stealth, genesis, provision, agent, intel, network, cerberus,
          targets, kyc, admin, dashboard, settings, bundles, ai, ws, training]:
    app.include_router(r.router)


# ═══════════════════════════════════════════════════════════════════════
# CONSOLE — Serves the SPA
# ═══════════════════════════════════════════════════════════════════════

@app.get("/ready")
async def readiness_check():
    """Kubernetes-style readiness probe - is the app ready to serve traffic?"""
    try:
        # Check if at least one device is available
        devs = dm.list_devices()
        has_device = any(d.get("status") == "online" for d in devs)
        return {"ready": True, "devices": len(devs), "online": has_device}
    except Exception as e:
        return {"ready": False, "error": str(e)}


@app.get("/live")
async def liveness_check():
    """Kubernetes-style liveness probe - is the app alive?"""
    return {"alive": True, "version": "11.3.2"}


@app.get("/health")
async def health_check():
    """System health check: ADB, Ollama, disk, memory."""
    import shutil, subprocess as _sp
    import time
    start = time.time()
    health = {"status": "ok", "checks": {}, "timestamp": int(start)}
    # ADB
    try:
        devs = dm.list_devices()
        adb_targets = [d.get("adb_target", "") for d in devs if d.get("status") == "online"]
        adb_ok = False
        for t in adb_targets[:1]:
            r = _sp.run(["adb", "-s", t, "shell", "echo ok"], capture_output=True, text=True, timeout=5)
            adb_ok = "ok" in r.stdout
        health["checks"]["adb"] = {"ok": adb_ok, "devices": len(devs)}
    except Exception as e:
        health["checks"]["adb"] = {"ok": False, "error": str(e)}
    # Ollama
    try:
        import httpx
        r = httpx.get(os.environ.get("TITAN_GPU_OLLAMA", "http://127.0.0.1:11435") + "/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        health["checks"]["ollama"] = {"ok": True, "models": len(models)}
    except Exception:
        health["checks"]["ollama"] = {"ok": False, "models": 0}
    # Disk
    try:
        usage = shutil.disk_usage("/")
        free_gb = round(usage.free / (1024**3), 1)
        health["checks"]["disk"] = {"ok": free_gb > 5, "free_gb": free_gb}
    except Exception:
        health["checks"]["disk"] = {"ok": False}
    # Memory
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem = {l.split(":")[0].strip(): int(l.split(":")[1].strip().split()[0]) for l in lines[:3]}
        avail_gb = round(mem.get("MemAvailable", 0) / (1024**2), 1)
        health["checks"]["memory"] = {"ok": avail_gb > 1, "available_gb": avail_gb}
    except Exception:
        health["checks"]["memory"] = {"ok": False}
    if not all(c.get("ok") for c in health["checks"].values()):
        health["status"] = "degraded"
    return health


@app.get("/api/capabilities")
async def capabilities():
    """Report which optional modules are actually available vs stub."""
    caps = {}
    # Network modules
    for name, imp in [
        ("mullvad_vpn", "mullvad_vpn"),
        ("forensic_monitor", "forensic_monitor"),
        ("network_shield", "network_shield"),
        ("proxy_scorer", "proxy_quality_scorer"),
    ]:
        try:
            __import__(imp)
            caps[name] = True
        except ImportError:
            caps[name] = False
    # Intel modules
    for name, imp in [
        ("ai_intelligence", "ai_intelligence"),
        ("target_intelligence", "target_intelligence"),
        ("osint_orchestrator", "osint_orchestrator"),
        ("three_ds_strategy", "three_ds_strategy"),
        ("onion_search", "onion_search"),
    ]:
        try:
            __import__(imp)
            caps[name] = True
        except ImportError:
            caps[name] = False
    # Cerberus modules
    for name, imp in [
        ("cerberus_engine", "cerberus_core"),
        ("bin_database", "bin_database"),
        ("bin_scanner", "bin_scanner"),
    ]:
        try:
            __import__(imp)
            caps[name] = True
        except ImportError:
            caps[name] = False
    # Targets modules
    for name, imp in [
        ("web_check", "web_check_engine"),
        ("waf_detector", "waf_detector"),
        ("dns_intel", "dns_intel"),
        ("target_profiler", "target_profiler"),
    ]:
        try:
            __import__(imp)
            caps[name] = True
        except ImportError:
            caps[name] = False
    # KYC modules
    for name, imp in [
        ("gpu_reenact", "gpu_reenact_client"),
        ("kyc_controller", "kyc_core"),
        ("kyc_voice", "kyc_voice"),
    ]:
        try:
            __import__(imp)
            caps[name] = True
        except ImportError:
            caps[name] = False
    available = sum(1 for v in caps.values() if v)
    return {
        "total": len(caps),
        "available": available,
        "stub": len(caps) - available,
        "modules": caps,
    }


@app.get("/", response_class=HTMLResponse)
async def console_root():
    index = CONSOLE_DIR / "index.html"
    content = index.read_text() if index.exists() else "<h1>Titan V11.3 — Console not found. Deploy console/index.html</h1>"
    resp = HTMLResponse(content)
    # Inject API auth token as cookie so console JS can read it
    secret = os.environ.get("TITAN_API_SECRET", "").strip()
    if secret and secret != "change-me-to-a-secure-random-string":
        resp.set_cookie("titan_token", secret, httponly=False, samesite="strict", path="/")
    return resp

@app.get("/mobile", response_class=HTMLResponse)
async def console_mobile():
    mobile = CONSOLE_DIR / "mobile.html"
    if mobile.exists():
        return HTMLResponse(mobile.read_text())
    return HTMLResponse("<h1>Mobile view not found</h1>")

@app.get("/favicon.ico")
async def favicon():
    # Inline 1x1 transparent ICO to suppress 404s
    ico = CONSOLE_DIR / "favicon.ico"
    if ico.exists():
        return Response(content=ico.read_bytes(), media_type="image/x-icon")
    # Minimal 16x16 ICO header (transparent)
    import struct
    bmp = b'\x28\x00\x00\x00\x10\x00\x00\x00\x20\x00\x00\x00\x01\x00\x20\x00\x00\x00\x00\x00\x00\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    pixels = b'\x00\xd4\xff\xff' * 256  # 16x16 cyan pixels
    mask = b'\x00' * 64
    img_data = bmp + pixels + mask
    header = struct.pack('<HHH', 0, 1, 1)
    entry = struct.pack('<BBBBHHII', 16, 16, 0, 0, 1, 32, len(img_data), 22)
    return Response(content=header + entry + img_data, media_type="image/x-icon")


# ═══════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    logger.info("Titan V11.3 API Server starting")
    logger.info(f"Devices loaded: {len(dm.list_devices())}")
    logger.info(f"Console dir: {CONSOLE_DIR}")
    logger.info(f"Core dir: {CORE_DIR}")
    await cpu_governor.start()
    
    # Start ADB connection watchdog for all online devices
    try:
        from adb_utils import start_connection_watchdog
        targets = [d.get("adb_target") for d in dm.list_devices() if d.get("status") == "online"]
        if targets:
            start_connection_watchdog(targets, check_interval=30)
    except Exception as e:
        logger.warning(f"ADB watchdog init failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    """Graceful shutdown - drain in-flight requests and cleanup."""
    logger.info("Titan V11.3 API Server shutting down gracefully")
    
    # Stop CPU governor
    try:
        await cpu_governor.stop()
    except Exception:
        pass
    
    # Allow in-flight requests to complete (up to 10 seconds)
    import asyncio
    await asyncio.sleep(2)
    
    logger.info("Shutdown complete")

