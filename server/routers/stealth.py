"""
Titan V11.3 — Stealth Router
/api/stealth/* — Presets, carriers, locations, patch, audit
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from device_manager import DeviceManager
from anomaly_patcher import AnomalyPatcher
from device_presets import CARRIERS, LOCATIONS, list_preset_names

router = APIRouter(prefix="/api/stealth", tags=["stealth"])

dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


class PatchDeviceBody(BaseModel):
    preset: str = ""
    carrier: str = ""
    location: str = ""


@router.get("/presets")
async def list_presets():
    return {"presets": list_preset_names()}


@router.get("/carriers")
async def list_carriers():
    return {"carriers": {k: {"name": v.name, "mcc": v.mcc, "mnc": v.mnc, "country": v.country}
                         for k, v in CARRIERS.items()}}


@router.get("/locations")
async def list_locations():
    return {"locations": LOCATIONS}


@router.post("/{device_id}/patch")
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


@router.get("/{device_id}/audit")
async def audit_device(device_id: str):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    patcher = AnomalyPatcher(adb_target=dev.adb_target)
    return patcher.audit()
