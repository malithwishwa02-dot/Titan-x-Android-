"""
Titan V11.3 — Stealth Router
/api/stealth/* — Presets, carriers, locations, patch, audit
"""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from device_manager import DeviceManager
from anomaly_patcher import AnomalyPatcher
from device_presets import CARRIERS, LOCATIONS, list_preset_names
from wallet_verifier import WalletVerifier

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


def _run_patch(adb_target: str, preset: str, carrier: str, location: str):
    """Blocking helper — runs in thread to avoid blocking event loop."""
    patcher = AnomalyPatcher(adb_target=adb_target)
    return patcher.full_patch(preset, carrier, location)


@router.post("/{device_id}/patch")
async def patch_device(device_id: str, body: PatchDeviceBody):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    preset = body.preset or dev.config.get("model", "samsung_s25_ultra")
    carrier = body.carrier or dev.config.get("carrier", "tmobile_us")
    location = body.location or "nyc"

    report = await asyncio.to_thread(_run_patch, dev.adb_target, preset, carrier, location)
    dev.patch_result = report.to_dict()
    dev.stealth_score = report.score
    return report.to_dict()


def _run_audit(adb_target: str):
    """Blocking helper — runs in thread to avoid blocking event loop."""
    patcher = AnomalyPatcher(adb_target=adb_target)
    return patcher.audit()


@router.get("/{device_id}/audit")
async def audit_device(device_id: str):
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    return await asyncio.to_thread(_run_audit, dev.adb_target)


def _run_wallet_verify(adb_target: str):
    """Blocking helper — runs in thread to avoid blocking event loop."""
    verifier = WalletVerifier(adb_target=adb_target)
    return verifier.verify()


@router.get("/{device_id}/wallet-verify")
async def wallet_verify(device_id: str):
    """Deep wallet injection verification — 13 checks across Google Pay,
    Play Store, Chrome, GMS, keybox, GSF alignment, and file ownership."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    report = await asyncio.to_thread(_run_wallet_verify, dev.adb_target)
    return report.to_dict()


# ═══════════════════════════════════════════════════════════════════════
# GAPPS BOOTSTRAP
# ═══════════════════════════════════════════════════════════════════════

def _run_bootstrap(adb_target: str, skip_optional: bool):
    """Blocking helper — runs in thread."""
    from gapps_bootstrap import GAppsBootstrap
    bs = GAppsBootstrap(adb_target=adb_target)
    return bs.run(skip_optional=skip_optional)


def _check_gapps_status(adb_target: str):
    """Blocking helper — runs in thread."""
    from gapps_bootstrap import GAppsBootstrap
    bs = GAppsBootstrap(adb_target=adb_target)
    return bs.check_status()


class BootstrapBody(BaseModel):
    skip_optional: bool = False


@router.post("/{device_id}/bootstrap-gapps")
async def bootstrap_gapps(device_id: str, body: BootstrapBody = BootstrapBody()):
    """Install GMS, Play Store, Chrome, Google Pay on vanilla AOSP Cuttlefish.
    APKs must be in /opt/titan/data/gapps/. Must run BEFORE aging pipeline."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    result = await asyncio.to_thread(_run_bootstrap, dev.adb_target, body.skip_optional)
    return result.to_dict()


@router.get("/{device_id}/gapps-status")
async def gapps_status(device_id: str):
    """Check which Google apps are installed on the device."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    return await asyncio.to_thread(_check_gapps_status, dev.adb_target)
