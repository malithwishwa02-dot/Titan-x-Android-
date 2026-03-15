"""
Titan V11.3 — Devices Router (Cuttlefish)
/api/devices/* — Device CRUD, streaming, screenshots, input
"""

import io
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from device_manager import DeviceManager, CreateDeviceRequest
from anomaly_patcher import AnomalyPatcher
from device_presets import COUNTRY_DEFAULTS

router = APIRouter(prefix="/api/devices", tags=["devices"])

# Shared device manager singleton — set by main app
dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


class CreateDeviceBody(BaseModel):
    model: str = "samsung_s25_ultra"
    country: str = "US"
    carrier: str = "tmobile_us"
    location: str = "nyc"
    phone_number: str = ""
    android_version: str = "14"


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


@router.get("")
async def list_devices():
    devices = dm.list_devices()
    return {"devices": [d.to_dict() for d in devices]}


@router.get("/{device_id}")
async def get_device(device_id: str):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    return dev.to_dict()


@router.get("/{device_id}/info")
async def get_device_info(device_id: str):
    info = dm.get_device_info(device_id)
    if not info:
        raise HTTPException(404, "Device not found or not ready")
    return info


@router.post("")
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

        patcher = AnomalyPatcher(adb_target=dev.adb_target)
        patch_result = patcher.full_patch(body.model, body.carrier, location)
        dev.patch_result = patch_result.to_dict()
        dev.stealth_score = patch_result.score
        dev.state = "patched"

        return {"device": dev.to_dict(), "patch": patch_result.to_dict()}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/{device_id}")
async def destroy_device(device_id: str):
    ok = await dm.destroy_device(device_id)
    if not ok:
        raise HTTPException(404, "Device not found")
    return {"ok": True}


@router.post("/{device_id}/restart")
async def restart_device(device_id: str):
    ok = await dm.restart_device(device_id)
    if not ok:
        raise HTTPException(404, "Device not found")
    return {"ok": True}


@router.get("/{device_id}/screenshot")
async def device_screenshot(device_id: str):
    data = await dm.screenshot(device_id)
    if not data:
        raise HTTPException(404, "Screenshot failed")
    return StreamingResponse(io.BytesIO(data), media_type="image/jpeg")


@router.post("/{device_id}/input")
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
        except Exception as e:
            logger.debug(f"Screen resolution parse failed: {e}")

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
