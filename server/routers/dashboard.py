"""
Titan V11.3 — Dashboard Router
/api/dashboard/* — Live ops feed, summary
"""

from fastapi import APIRouter

from device_manager import DeviceManager

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


@router.get("/summary")
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
