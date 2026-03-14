"""
Titan V11.3 — VMOS Cloud Router
/api/vmos/* — VMOS Cloud bridge API endpoints
"""

import logging
import os
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from device_manager import DeviceManager, DeviceInstance, DEVICES_DIR

router = APIRouter(prefix="/api/vmos", tags=["vmos"])
logger = logging.getLogger("titan.vmos")

dm: DeviceManager = None
_vmos_bridge = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


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
    carrier: str = "att_us"
    location: str = "la"
    preset: str = "oneplus_ace3"
    lockdown: bool = True


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
    action: str = "tap"
    x2: int = 0
    y2: int = 0
    duration: int = 300


class VMOSProxyBody(BaseModel):
    ip: str
    port: int
    username: str = ""
    password: str = ""
    proxy_type: str = "socks5"


@router.get("/status")
async def vmos_status():
    bridge = _get_vmos()
    if not bridge:
        return {"status": "not_configured", "message": "Set VMOS_API_KEY and VMOS_API_SECRET env vars"}
    try:
        instances = await bridge.list_instances(page=1, rows=5)
        return {"status": "connected", "instances": len(instances), "devices": [i.to_dict() for i in instances]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/register")
async def vmos_register_device(body: VMOSRegisterBody):
    bridge = _get_vmos()
    if not bridge:
        raise HTTPException(503, "VMOS Cloud not configured")

    dev_id = body.device_id or f"vmos-{body.pad_code[:8].lower()}"
    existing = dm.get_device(dev_id)
    if existing:
        return {"device": existing.to_dict(), "message": "Already registered"}

    adb_info = await bridge.open_adb(body.pad_code)
    adb_target = ""
    if adb_info:
        adb_target = adb_info.get("adb_connect", "").replace("adb connect ", "")

    from datetime import datetime, timezone
    dev = DeviceInstance(
        id=dev_id, container=f"vmos-{body.pad_code}", adb_port=0, adb_target=adb_target,
        config={"model": body.model, "country": body.country, "carrier": "", "pad_code": body.pad_code},
        state="ready", created_at=datetime.now(timezone.utc).isoformat(),
        device_type="vmos_cloud", vmos_pad_code=body.pad_code,
    )
    dm._devices[dev_id] = dev
    dm._save_state()
    return {"device": dev.to_dict(), "adb_info": adb_info, "message": f"VMOS device {body.pad_code} registered as {dev_id}"}


@router.get("/instances")
async def vmos_list_instances():
    bridge = _get_vmos()
    if not bridge:
        raise HTTPException(503, "VMOS Cloud not configured")
    instances = await bridge.list_instances()
    return {"instances": [i.to_dict() for i in instances]}


@router.get("/{device_id}/properties")
async def vmos_get_properties(device_id: str):
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")
    props = await bridge.get_instance_properties(dev.vmos_pad_code)
    return {"device_id": device_id, "properties": props}


@router.post("/{device_id}/patch")
async def vmos_patch_device(device_id: str, body: VMOSPatchBody):
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")
    from vmos_cloud_patcher import VMOSCloudPatcher
    patcher = VMOSCloudPatcher(bridge, dev.vmos_pad_code)
    report = await patcher.full_patch(
        carrier=body.carrier,
        location=body.location,
        preset=body.preset,
        lockdown=body.lockdown,
    )
    dev.patch_result = report.to_dict()
    dm._save_state()
    return {"device_id": device_id, "result": report.to_dict()}


@router.post("/{device_id}/inject")
async def vmos_inject_profile(device_id: str, body: VMOSInjectBody):
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")
    result = await bridge.full_profile_inject(
        dev.vmos_pad_code, contacts=body.contacts or None, call_logs=body.call_logs or None,
        sms_messages=body.sms or None, chrome_commands=body.chrome_commands or None,
        wallet_commands=body.wallet_commands or None,
    )
    return {"device_id": device_id, "result": result}


@router.post("/{device_id}/shell")
async def vmos_shell(device_id: str, body: VMOSShellBody):
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")
    result = await bridge.exec_shell(dev.vmos_pad_code, body.command)
    return {"device_id": device_id, "result": result.to_dict()}


@router.post("/{device_id}/touch")
async def vmos_touch(device_id: str, body: VMOSTouchBody):
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")
    if body.action == "swipe":
        result = await bridge.swipe(dev.vmos_pad_code, body.x, body.y, body.x2, body.y2, body.duration)
    else:
        result = await bridge.tap(dev.vmos_pad_code, body.x, body.y)
    return {"device_id": device_id, "result": result.to_dict()}


@router.get("/{device_id}/screenshot")
async def vmos_screenshot(device_id: str):
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")
    url = await bridge.screenshot(dev.vmos_pad_code)
    if url:
        return {"device_id": device_id, "screenshot_url": url}
    raise HTTPException(500, "Screenshot failed")


@router.post("/{device_id}/proxy")
async def vmos_set_proxy(device_id: str, body: VMOSProxyBody):
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")
    result = await bridge.set_proxy(
        dev.vmos_pad_code, body.ip, body.port,
        username=body.username, password=body.password, proxy_type=body.proxy_type,
    )
    return {"device_id": device_id, "result": result.to_dict()}


@router.get("/{device_id}/apps")
async def vmos_list_apps(device_id: str):
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")
    apps = await bridge.list_apps(dev.vmos_pad_code)
    return {"device_id": device_id, "apps": apps}


@router.post("/{device_id}/adb")
async def vmos_open_adb(device_id: str):
    bridge = _get_vmos()
    dev = dm.get_device(device_id)
    if not bridge or not dev or dev.device_type != "vmos_cloud":
        raise HTTPException(404, "VMOS device not found")
    info = await bridge.open_adb(dev.vmos_pad_code)
    if info:
        adb_connect = info.get("adb_connect", "").replace("adb connect ", "")
        if adb_connect:
            dev.adb_target = adb_connect
            dm._save_state()
        return {"device_id": device_id, "adb": info}
    raise HTTPException(500, "Failed to open ADB access")
