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
from fastapi.responses import HTMLResponse
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

app = FastAPI(title="Titan V11.3 Antidetect Device Platform", version="11.3.1")

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

# ─── Register Routers ─────────────────────────────────────────────────
from routers import devices, stealth, genesis, agent, intel, network
from routers import cerberus, targets, kyc, admin, dashboard, settings
from routers import bundles, ai, ws, vmos, training

# Initialize routers that need the device manager
for mod in [devices, stealth, genesis, agent, kyc, admin, dashboard, bundles, ws, vmos, ai, training]:
    mod.init(dm)

# Include all routers
for r in [devices, stealth, genesis, agent, intel, network, cerberus,
          targets, kyc, admin, dashboard, settings, bundles, ai, ws, vmos, training]:
    app.include_router(r.router)


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
# STARTUP
# ═══════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    logger.info("Titan V11.3 API Server starting")
    logger.info(f"Devices loaded: {len(dm.list_devices())}")
    logger.info(f"Console dir: {CONSOLE_DIR}")
    logger.info(f"Core dir: {CORE_DIR}")
    await cpu_governor.start()

