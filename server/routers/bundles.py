"""
Titan V11.3 — Bundles Router
/api/bundles/* — App bundle installation
"""

from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from device_manager import DeviceManager
from app_bundles import get_bundles_for_country, list_all_bundles

router = APIRouter(prefix="/api/bundles", tags=["bundles"])

dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


class InstallAppsBody(BaseModel):
    bundle: str = ""
    packages: List[str] = []


@router.get("")
async def get_bundles():
    return {"bundles": list_all_bundles()}


@router.get("/{country}")
async def get_country_bundles(country: str):
    return {"bundles": get_bundles_for_country(country.upper())}


@router.post("/{device_id}/install")
async def install_bundle(device_id: str, body: InstallAppsBody):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    return {"status": "install_queued", "device": device_id, "bundle": body.bundle}
