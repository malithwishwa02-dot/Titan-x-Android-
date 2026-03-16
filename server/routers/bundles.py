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
    # Resolve app names from bundle or use explicit packages
    apps = list(body.packages) if body.packages else []
    if not apps and body.bundle:
        from app_bundles import APP_BUNDLES
        bundle = APP_BUNDLES.get(body.bundle, {})
        apps = [a["name"] for a in bundle.get("apps", [])]
    if not apps:
        return {"status": "no_apps", "device": device_id, "bundle": body.bundle}
    # Start AI agent task to install via Play Store
    try:
        from routers.agent import _get_agent
        agent = _get_agent(device_id)
        app_list = ", ".join(apps[:6])
        task_id = agent.start_task(
            prompt=f"Open Google Play Store and install these apps one by one: {app_list}. "
                   f"For each: search by name, tap Install, wait for it to complete, then search for the next.",
            max_steps=len(apps) * 25,
        )
        return {"status": "install_started", "device": device_id, "task_id": task_id, "apps": apps[:6]}
    except Exception as e:
        raise HTTPException(500, f"Failed to start install: {e}")
