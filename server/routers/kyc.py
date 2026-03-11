"""
Titan V11.3 — KYC Router
/api/kyc/* — Camera inject, deepfake, liveness
"""

from fastapi import APIRouter, HTTPException, Request

from device_manager import DeviceManager

router = APIRouter(prefix="/api/kyc", tags=["kyc"])

dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


@router.post("/{device_id}/upload_face")
async def kyc_upload_face(device_id: str, request: Request):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    return {"status": "face_uploaded", "device": device_id}


@router.post("/{device_id}/start_deepfake")
async def kyc_start_deepfake(device_id: str):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    return {"status": "deepfake_started", "device": device_id}


@router.post("/{device_id}/stop_deepfake")
async def kyc_stop_deepfake(device_id: str):
    return {"status": "deepfake_stopped", "device": device_id}
