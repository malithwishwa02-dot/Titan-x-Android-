"""
Titan V11.3 — Admin Router
/api/admin/* — Services, health, CPU monitoring
"""

import subprocess
import time

from fastapi import APIRouter

from device_manager import DeviceManager
from middleware.cpu_governor import cpu_governor

router = APIRouter(prefix="/api/admin", tags=["admin"])

dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


@router.get("/services")
async def admin_services():
    """Get status of all system services."""
    services = ["titan-api", "ws-scrcpy", "nginx"]
    result = {}
    for svc in services:
        try:
            r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, timeout=5)
            result[svc] = r.stdout.strip()
        except Exception:
            result[svc] = "unknown"
    return {"services": result}


@router.get("/health")
async def admin_health():
    devices = dm.list_devices()
    return {
        "status": "ok",
        "devices": len(devices),
        "devices_ready": sum(1 for d in devices if d.state in ("ready", "patched")),
        "uptime": time.time(),
        "cpu": cpu_governor.get_status(),
    }


@router.get("/cpu")
async def admin_cpu():
    """Get detailed CPU monitoring data."""
    return cpu_governor.get_status()
