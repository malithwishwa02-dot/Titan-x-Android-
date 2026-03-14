"""
Titan V11.3 — Training Data Router
/api/training/* — Demo recording, trajectory management, training data export
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from device_manager import DeviceManager

router = APIRouter(prefix="/api/training", tags=["training"])
logger = logging.getLogger("titan.training")

dm: DeviceManager = None
_recorder = None
_exporter = None
_scenario_runner = None


def init(device_manager: DeviceManager):
    global dm, _recorder, _exporter, _scenario_runner
    dm = device_manager
    from demo_recorder import DemoRecorder
    from trajectory_logger import TrainingDataExporter
    from scenario_runner import ScenarioRunner
    _recorder = DemoRecorder()
    _exporter = TrainingDataExporter()
    _scenario_runner = ScenarioRunner(device_manager=dm)


# ═══════════════════════════════════════════════════════════════════════
# DEMO RECORDING
# ═══════════════════════════════════════════════════════════════════════

class DemoStartBody(BaseModel):
    prompt: str = ""
    task_category: str = ""
    app_context: str = ""


class DemoActionBody(BaseModel):
    action: str = "tap"
    x: int = 0
    y: int = 0
    text: str = ""
    reason: str = ""
    capture_screen: bool = True


@router.post("/demo/start/{device_id}")
async def demo_start(device_id: str, body: DemoStartBody):
    """Start a human demonstration recording session."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    session = _recorder.start_session(
        device_id=device_id,
        pad_code=dev.vmos_pad_code or "",
        prompt=body.prompt,
        task_category=body.task_category,
        app_context=body.app_context,
    )
    return {
        "session_id": session.session_id,
        "device_id": device_id,
        "status": "recording",
    }


@router.post("/demo/action/{session_id}")
async def demo_action(session_id: str, body: DemoActionBody):
    """Record a single human action. Optionally captures screenshot first."""
    session = _recorder.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    screen_b64 = ""
    screen_context = ""
    if body.capture_screen:
        screen_b64 = await _recorder.capture_screen_for_session(session_id)

    params = {}
    if body.x or body.y:
        params["x"] = body.x
        params["y"] = body.y
    if body.text:
        params["text"] = body.text

    result = await _recorder.record_action(
        session_id=session_id,
        action_type=body.action,
        params=params,
        reason=body.reason,
        screen_b64=screen_b64,
        screen_context=screen_context,
    )

    # Also execute the action on the device
    dev = dm.get_device(session.device_id)
    if dev and dev.vmos_pad_code:
        try:
            from vmos_agent_adapter import VMOSTouchAdapter
            touch = VMOSTouchAdapter(pad_code=dev.vmos_pad_code)
            if body.action == "tap":
                touch.tap(body.x, body.y)
            elif body.action == "type":
                touch.type_text(body.text)
            elif body.action == "back":
                touch.back()
            elif body.action == "home":
                touch.home()
            elif body.action == "enter":
                touch.enter()
            elif body.action == "scroll_down":
                touch.scroll_down()
            elif body.action == "scroll_up":
                touch.scroll_up()
        except Exception as e:
            result["exec_error"] = str(e)

    return result


@router.post("/demo/stop/{session_id}")
async def demo_stop(session_id: str):
    """Stop recording and finalize the trajectory."""
    return _recorder.stop_session(session_id)


@router.get("/demo/sessions")
async def demo_list():
    """List all demo recording sessions."""
    return {"sessions": _recorder.list_sessions()}


@router.get("/demo/screen/{session_id}")
async def demo_screen(session_id: str):
    """Get current device screenshot for a recording session."""
    b64 = await _recorder.capture_screen_for_session(session_id)
    if not b64:
        raise HTTPException(500, "Screenshot failed")
    return {"screenshot_b64": b64[:100] + "...", "length": len(b64)}


# ═══════════════════════════════════════════════════════════════════════
# TRAJECTORY MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

@router.get("/trajectories")
async def list_trajectories(status: str = "", category: str = ""):
    """List all collected trajectories with metadata."""
    trajs = _exporter.list_trajectories(status=status, category=category)
    return {
        "trajectories": trajs,
        "count": len(trajs),
    }


@router.get("/trajectories/stats")
async def trajectory_stats():
    """Get trajectory collection statistics."""
    return _exporter.stats()


@router.post("/export/action")
async def export_action_data(min_success_rate: float = 0.5):
    """Export action model training data as JSONL."""
    count = _exporter.export_action_training(min_success_rate=min_success_rate)
    return {"exported": count, "format": "jsonl", "type": "action"}


@router.post("/export/vision")
async def export_vision_data():
    """Export vision model training data as JSONL."""
    count = _exporter.export_vision_training()
    return {"exported": count, "format": "jsonl", "type": "vision"}


# ═══════════════════════════════════════════════════════════════════════
# SCENARIO RUNNER
# ═══════════════════════════════════════════════════════════════════════

class ScenarioRunBody(BaseModel):
    device_ids: List[str] = []
    templates: List[str] = []
    params_sets: List[Dict[str, str]] = []
    preset: str = ""
    max_steps: int = 30
    retries: int = 0
    persona: Dict[str, str] = {}


@router.post("/scenarios/run")
async def scenario_run(body: ScenarioRunBody):
    """Create and run a batch of scenario tasks for training data."""
    if not body.device_ids:
        raise HTTPException(400, "device_ids required")

    batch = _scenario_runner.create_batch(
        device_ids=body.device_ids,
        templates=body.templates or None,
        params_sets=body.params_sets or None,
        preset=body.preset,
        max_steps=body.max_steps,
        retries=body.retries,
    )
    _scenario_runner.run_batch(batch.batch_id, persona=body.persona)
    return {
        "batch_id": batch.batch_id,
        "total_tasks": len(batch.tasks),
        "status": "running",
    }


@router.get("/scenarios/status/{batch_id}")
async def scenario_status(batch_id: str):
    """Get status of a scenario batch."""
    batch = _scenario_runner.get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    return batch.to_dict()


@router.get("/scenarios/batches")
async def scenario_list():
    """List all scenario batches."""
    return {"batches": _scenario_runner.list_batches()}


@router.get("/scenarios/presets")
async def scenario_presets():
    """List available scenario presets."""
    return {"presets": _scenario_runner.list_presets()}


# ═══════════════════════════════════════════════════════════════════════
# VERIFICATION & AGING REPORTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/report/{device_id}")
async def aging_report(device_id: str):
    """Generate comprehensive aging report for a device."""
    from aging_report import AgingReporter
    reporter = AgingReporter(device_manager=dm)
    report = await reporter.generate(device_id=device_id)
    return report.to_dict()


class VerifyBody(BaseModel):
    expected_apps: List[str] = []
    expect_wallet: bool = True
    expect_google: bool = True


@router.post("/verify/{device_id}")
async def verify_device(device_id: str, body: VerifyBody):
    """Run task verification checks on a device."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    if not dev.vmos_pad_code:
        raise HTTPException(400, "Only VMOS Cloud devices supported for verify")

    from task_verifier import TaskVerifier
    verifier = TaskVerifier(pad_code=dev.vmos_pad_code)
    verify_report = await verifier.full_verify(
        device_id=device_id,
        expected_apps=body.expected_apps,
        expect_wallet=body.expect_wallet,
        expect_google=body.expect_google,
    )
    return verify_report.to_dict()


# ═══════════════════════════════════════════════════════════════════════
# WORKFLOW ENGINE
# ═══════════════════════════════════════════════════════════════════════

_workflow_engine = None


def _get_workflow_engine():
    global _workflow_engine
    if _workflow_engine is None:
        from workflow_engine import WorkflowEngine
        _workflow_engine = WorkflowEngine(device_manager=dm)
    return _workflow_engine


class WorkflowStartBody(BaseModel):
    persona: Dict[str, str] = {}
    bundles: List[str] = ["us_banking", "social"]
    card_data: Dict[str, Any] = {}
    country: str = "US"
    aging_level: str = "medium"
    skip_forge: bool = False
    skip_patch: bool = False
    profile_id: str = ""


@router.post("/workflow/start/{device_id}")
async def workflow_start(device_id: str, body: WorkflowStartBody):
    """Start a complete device aging workflow."""
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")

    engine = _get_workflow_engine()
    job = await engine.start_workflow(
        device_id=device_id,
        persona=body.persona,
        bundles=body.bundles,
        card_data=body.card_data,
        country=body.country,
        aging_level=body.aging_level,
        skip_forge=body.skip_forge,
        skip_patch=body.skip_patch,
        profile_id=body.profile_id,
    )
    return {
        "job_id": job.job_id,
        "device_id": device_id,
        "stages": len(job.stages),
        "status": "running",
    }


@router.get("/workflow/status/{job_id}")
async def workflow_status(job_id: str):
    """Get workflow job status."""
    engine = _get_workflow_engine()
    job = engine.get_status(job_id)
    if not job:
        raise HTTPException(404, "Workflow job not found")
    return job.to_dict()


@router.get("/workflow/jobs")
async def workflow_list():
    """List all workflow jobs."""
    engine = _get_workflow_engine()
    return {"jobs": engine.list_jobs()}
