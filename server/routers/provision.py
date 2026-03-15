"""
Titan V11.3 — Provision Router
/api/genesis/* — Inject, full-provision, age-device, job status
Split from genesis.py to reduce file size and separate concerns.
"""

import asyncio
import functools
import json
import logging
import os
import threading
import time as _time_mod
import uuid as _uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from device_manager import DeviceManager
from job_manager import inject_jobs as _inject_mgr, provision_jobs as _provision_mgr
from profile_injector import ProfileInjector

router = APIRouter(prefix="/api/genesis", tags=["genesis"])
logger = logging.getLogger("titan.provision")

dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


def _profiles_dir() -> Path:
    d = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _attach_gallery(profile_data: dict):
    """Attach gallery stub paths to profile data if available."""
    gallery_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "forge_gallery"
    if gallery_dir.exists():
        profile_data["gallery_paths"] = [str(p) for p in sorted(gallery_dir.glob("*.jpg"))[:25]]


def _build_card_data(body, persona_name: str = "") -> Optional[dict]:
    """Build card_data dict from request body if cc_number is provided."""
    if not body.cc_number:
        return None
    return {
        "number": body.cc_number,
        "exp_month": body.cc_exp_month,
        "exp_year": body.cc_exp_year,
        "cvv": body.cc_cvv,
        "cardholder": body.cc_cardholder or persona_name,
    }


# ═══════════════════════════════════════════════════════════════════════
# INJECT
# ═══════════════════════════════════════════════════════════════════════

class GenesisInjectBody(BaseModel):
    profile_id: str = ""
    cc_number: str = ""
    cc_exp_month: int = 0
    cc_exp_year: int = 0
    cc_cvv: str = ""
    cc_cardholder: str = ""


def _run_inject_job(job_id: str, adb_target: str, profile_data: dict,
                    card_data: dict, device_id: str, profile_id: str):
    """Background worker for profile injection (ADB path)."""
    try:
        injector = ProfileInjector(adb_target=adb_target)
        result = injector.inject_full_profile(profile_data, card_data=card_data)
        _inject_mgr.update(job_id, {
            "status": "completed", "trust_score": result.trust_score,
            "result": result.to_dict(), "completed_at": _time_mod.time(),
        })
        logger.info(f"Inject job {job_id} completed: trust={result.trust_score}")
    except Exception as e:
        _inject_mgr.update(job_id, {"status": "failed", "error": str(e), "completed_at": _time_mod.time()})
        logger.exception(f"Inject job {job_id} failed")


@router.post("/inject/{device_id}")
async def genesis_inject(device_id: str, body: GenesisInjectBody):
    """Inject forged profile into Android device via ADB (runs in background)."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    pf = _profiles_dir() / f"{body.profile_id}.json"
    if not pf.exists():
        raise HTTPException(404, f"Profile not found: {body.profile_id}")

    profile_data = json.loads(pf.read_text())
    _attach_gallery(profile_data)
    card_data = _build_card_data(body, profile_data.get("persona_name", ""))

    job_id = str(_uuid.uuid4())[:8]
    _inject_mgr.create(job_id, {
        "status": "running", "device_id": device_id,
        "profile_id": body.profile_id, "started_at": _time_mod.time(),
    })

    t = threading.Thread(
        target=_run_inject_job,
        args=(job_id, dev.adb_target, profile_data, card_data, device_id, body.profile_id),
        daemon=True,
    )
    t.start()

    return {
        "status": "inject_started", "job_id": job_id,
        "device_id": device_id, "profile_id": body.profile_id,
        "poll_url": f"/api/genesis/inject-status/{job_id}",
    }


@router.get("/inject-status/{job_id}")
async def genesis_inject_status(job_id: str):
    """Poll injection job status."""
    job = _inject_mgr.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


# ═══════════════════════════════════════════════════════════════════════
# FULL PROVISION
# ═══════════════════════════════════════════════════════════════════════

class FullProvisionBody(BaseModel):
    profile_id: str
    cc_number: str = ""
    cc_exp_month: int = 0
    cc_exp_year: int = 0
    cc_cvv: str = ""
    cc_cardholder: str = ""
    preset: str = ""       # optional override; defaults to profile's device_model
    lockdown: bool = False


def _run_provision_job(job_id: str, adb_target: str, profile_data: dict,
                       card_data: Optional[dict], preset: str, lockdown: bool):
    """Background worker: inject profile -> full_patch (26 phases) -> GSM verify -> trust score."""
    from adb_utils import adb_shell

    try:
        # -- Step 1: Profile injection
        _provision_mgr.update(job_id, {"step": "inject", "step_n": 1})
        injector = ProfileInjector(adb_target=adb_target)
        inj_result = injector.inject_full_profile(profile_data, card_data=card_data)
        _provision_mgr.update(job_id, {"inject_trust": inj_result.trust_score})

        # -- Step 2: Full patch (26 phases, 103+ vectors)
        _provision_mgr.update(job_id, {"step": "patch", "step_n": 2})
        from anomaly_patcher import AnomalyPatcher
        carrier  = profile_data.get("carrier",      "tmobile_us")
        location = profile_data.get("location",     "nyc")
        model    = preset or profile_data.get("device_model", "samsung_s25_ultra")
        patcher  = AnomalyPatcher(adb_target=adb_target)
        report   = patcher.full_patch(model, carrier, location, lockdown=lockdown)
        _provision_mgr.update(job_id, {
            "patch_score": report.score, "phases_passed": report.passed,
            "phases_total": report.total, "patch_results": report.results[:40],
        })

        # -- Step 3: GSM verify
        _provision_mgr.update(job_id, {"step": "gsm_verify", "step_n": 3})
        gsm_state    = adb_shell(adb_target, "getprop gsm.sim.state")
        gsm_operator = adb_shell(adb_target, "getprop gsm.sim.operator.alpha")
        gsm_mcc_mnc  = adb_shell(adb_target, "getprop gsm.sim.operator.numeric")
        gsm_ok = (
            gsm_state.strip() == "READY" and
            len(gsm_operator.strip()) > 0 and
            len(gsm_mcc_mnc.strip()) >= 5
        )
        _provision_mgr.update(job_id, {"gsm": {
            "ok": gsm_ok,
            "state": gsm_state.strip(),
            "operator": gsm_operator.strip(),
            "mcc_mnc": gsm_mcc_mnc.strip(),
            "expected_carrier": carrier,
        }})

        # -- Step 4: Trust score (canonical 14-check scorer)
        _provision_mgr.update(job_id, {"step": "trust_score", "step_n": 4})
        from trust_scorer import compute_trust_score
        trust_result = compute_trust_score(adb_target)
        trust_score = trust_result["trust_score"]

        _provision_mgr.update(job_id, {
            "status": "completed",
            "step": "done",
            "step_n": 4,
            "trust_score": trust_score,
            "trust_checks": trust_result["checks"],
            "completed_at": _time_mod.time(),
        })
        logger.info(f"Provision job {job_id} done: patch={report.score} trust={trust_score} gsm={'OK' if gsm_ok else 'FAIL'}")

    except Exception as e:
        _provision_mgr.update(job_id, {"status": "failed", "error": str(e), "completed_at": _time_mod.time()})
        logger.exception(f"Provision job {job_id} failed")


@router.post("/full-provision/{device_id}")
async def genesis_full_provision(device_id: str, body: FullProvisionBody):
    """One-shot endpoint: inject genesis profile + full_patch (26 phases) + GSM verify.
    Returns a job_id; poll /provision-status/{job_id} for progress."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    pf = _profiles_dir() / f"{body.profile_id}.json"
    if not pf.exists():
        raise HTTPException(404, f"Profile not found: {body.profile_id}")

    profile_data = json.loads(pf.read_text())
    _attach_gallery(profile_data)
    card_data = _build_card_data(body, profile_data.get("persona_name", ""))

    job_id = str(_uuid.uuid4())[:8]
    _provision_mgr.create(job_id, {
        "status": "running",
        "device_id": device_id,
        "profile_id": body.profile_id,
        "step": "inject",
        "step_n": 1,
        "started_at": _time_mod.time(),
        "patch_score": None,
        "trust_score": None,
        "gsm": None,
    })

    t = threading.Thread(
        target=_run_provision_job,
        args=(job_id, dev.adb_target, profile_data, card_data,
              body.preset, body.lockdown),
        daemon=True,
    )
    t.start()

    return {
        "status": "started",
        "job_id": job_id,
        "device_id": device_id,
        "profile_id": body.profile_id,
        "poll_url": f"/api/genesis/provision-status/{job_id}",
    }


@router.get("/provision-status/{job_id}")
async def genesis_provision_status(job_id: str):
    """Poll full-provision job status."""
    job = _provision_mgr.get(job_id)
    if not job:
        raise HTTPException(404, "Provision job not found")
    return job


# ═══════════════════════════════════════════════════════════════════════
# AGE DEVICE
# ═══════════════════════════════════════════════════════════════════════

class AgeDeviceBody(BaseModel):
    device_id: str
    preset: str = "pixel_9_pro"
    carrier: str = "tmobile_us"
    location: str = "nyc"
    age_days: int = 90
    persona: str = ""


@router.post("/age-device/{device_id}")
async def genesis_age_device(device_id: str, body: AgeDeviceBody):
    """Run anomaly-patching phases on the device. Routes by device_type."""
    dev = dm.get_device(device_id) if dm else None

    try:
        from anomaly_patcher import AnomalyPatcher
        adb_target = "127.0.0.1:6520"
        if dev:
            adb_target = dev.adb_target

        patcher = AnomalyPatcher(adb_target=adb_target)
        loop = asyncio.get_event_loop()
        fn = functools.partial(
            patcher.full_patch,
            preset_name=body.preset,
            carrier_name=body.carrier,
            location_name=body.location,
        )
        report = await asyncio.wait_for(loop.run_in_executor(None, fn), timeout=120.0)
        return {"status": "complete", "device_id": device_id, "phases": len(report.results), "report": report.__dict__}
    except asyncio.TimeoutError:
        return {"status": "timeout", "device_id": device_id}
    except (ImportError, Exception) as e:
        logger.error("age-device error: %s", e)
        return {"status": "error", "error": str(e), "device_id": device_id}
