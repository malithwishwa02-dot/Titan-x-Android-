"""Titan V11.3 — Device Aging Workflow Engine (Cuttlefish)
========================================================
High-level orchestrator that chains multiple operations into a complete
device aging pipeline driven by user inputs.

Workflow stages:
  1. Forge Genesis profile (contacts, SMS, call logs, Chrome data)
  2. Inject profile into device
  3. Patch device for stealth (Cuttlefish artifact masking)
  4. Install app bundles via AI agent
  5. Sign into apps via AI agent (using persona credentials)
  6. Set up wallet (data injection via ADB)
  7. Run warmup browsing/YouTube sessions
  8. Generate verification report

Each stage decides the optimal method (data injection vs AI agent)
based on the app/task type.

Usage:
    engine = WorkflowEngine(device_manager=dm)
    job = await engine.start_workflow(
        device_id="dev-abc123",
        persona={"name": "James Mitchell", "email": "jm@gmail.com", ...},
        bundles=["us_banking", "social"],
        card_data={"number": "4532...", "exp_month": 12, ...},
        country="US",
        aging_level="medium",  # light=30d, medium=90d, heavy=365d
    )
    status = engine.get_status(job.job_id)
"""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.workflow-engine")

AGING_LEVELS = {
    "light": {"age_days": 30, "warmup_tasks": 2, "browse_queries": 3},
    "medium": {"age_days": 90, "warmup_tasks": 4, "browse_queries": 6},
    "heavy": {"age_days": 365, "warmup_tasks": 8, "browse_queries": 12},
}


@dataclass
class WorkflowStage:
    """Single stage in a workflow."""
    name: str = ""
    status: str = "pending"  # pending | running | completed | failed | skipped
    method: str = ""         # inject | agent | patch | forge
    detail: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""


@dataclass
class WorkflowJob:
    """Complete workflow job."""
    job_id: str = ""
    device_id: str = ""
    status: str = "pending"
    stages: List[WorkflowStage] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    completed_at: float = 0.0
    report: Dict[str, Any] = field(default_factory=dict)

    @property
    def completed_stages(self) -> int:
        return sum(1 for s in self.stages if s.status == "completed")

    @property
    def progress(self) -> float:
        return self.completed_stages / max(len(self.stages), 1)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "device_id": self.device_id,
            "status": self.status,
            "progress": round(self.progress * 100, 1),
            "stages": [asdict(s) for s in self.stages],
            "config": self.config,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "report": self.report,
        }


class WorkflowEngine:
    """Orchestrates complete device aging workflows."""

    def __init__(self, device_manager=None):
        self.dm = device_manager
        self._jobs: Dict[str, WorkflowJob] = {}
        self._threads: Dict[str, threading.Thread] = {}

    async def start_workflow(self, device_id: str,
                             persona: Dict[str, str] = None,
                             bundles: List[str] = None,
                             card_data: Dict[str, Any] = None,
                             country: str = "US",
                             aging_level: str = "medium",
                             skip_forge: bool = False,
                             skip_patch: bool = False,
                             profile_id: str = "",
                             disable_adb: bool = False) -> WorkflowJob:
        """Start a complete device aging workflow."""
        job_id = f"wf-{uuid.uuid4().hex[:8]}"
        aging = AGING_LEVELS.get(aging_level, AGING_LEVELS["medium"])

        job = WorkflowJob(
            job_id=job_id,
            device_id=device_id,
            status="pending",
            created_at=time.time(),
            config={
                "persona": persona or {},
                "bundles": bundles or ["us_banking", "social"],
                "card_data": {k: v for k, v in (card_data or {}).items() if k != "number"},
                "country": country,
                "aging_level": aging_level,
                "aging_config": aging,
                "profile_id": profile_id,
            },
        )

        # Build stage list — ORDER MATTERS:
        #   0. bootstrap_gapps  — install GMS/Play Store/Chrome/GPay (skip if present)
        #   1. forge_profile    — generate persona data
        #   2. install_apps     — via AI agent + Play Store (needs Play Store!)
        #   3. inject_profile   — push data into apps that now exist
        #   4. setup_wallet     — needs Google Pay APK installed
        #   5. patch_device     — stealth masking LAST (bind-mounts /proc)
        #   6. warmup           — natural usage after all data is in place
        #   7. verify           — audit + trust + wallet checks
        job.stages.append(WorkflowStage(name="bootstrap_gapps", method="inject"))
        if not skip_forge and not profile_id:
            job.stages.append(WorkflowStage(name="forge_profile", method="forge"))
        job.stages.append(WorkflowStage(name="install_apps", method="agent"))
        job.stages.append(WorkflowStage(name="inject_profile", method="inject"))
        job.stages.append(WorkflowStage(name="setup_wallet", method="inject"))
        if not skip_patch:
            job.stages.append(WorkflowStage(name="patch_device", method="patch"))
        job.stages.append(WorkflowStage(name="warmup_browse", method="agent"))
        job.stages.append(WorkflowStage(name="warmup_youtube", method="agent"))
        job.stages.append(WorkflowStage(name="verify_report", method="inject"))
        if disable_adb:
            job.stages.append(WorkflowStage(name="lockdown_device", method="inject"))

        self._jobs[job_id] = job

        job.config["disable_adb"] = disable_adb

        # Run in background thread
        thread = threading.Thread(
            target=self._run_workflow, args=(job_id, persona or {},
                                             bundles or ["us_banking", "social"],
                                             card_data or {}, country, aging),
            daemon=True,
        )
        self._threads[job_id] = thread
        job.status = "running"
        thread.start()

        logger.info(f"Workflow {job_id} started: {len(job.stages)} stages for {device_id}")
        return job

    def _check_adb_connectivity(self, job: WorkflowJob) -> bool:
        """Verify ADB connection to device before starting stages."""
        import subprocess
        dev = self.dm.get_device(job.device_id) if self.dm else None
        target = dev.adb_target if dev else "127.0.0.1:6520"
        try:
            r = subprocess.run(
                ["adb", "-s", target, "shell", "echo", "ok"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0 and "ok" in r.stdout:
                logger.info(f"ADB connectivity OK: {target}")
                return True
            # Try reconnecting once
            subprocess.run(["adb", "connect", target],
                           capture_output=True, timeout=10)
            time.sleep(2)
            r = subprocess.run(
                ["adb", "-s", target, "shell", "echo", "ok"],
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0 and "ok" in r.stdout
        except Exception as e:
            logger.error(f"ADB connectivity check failed: {e}")
            return False

    def _run_workflow(self, job_id: str, persona: Dict, bundles: List[str],
                      card_data: Dict, country: str, aging: Dict):
        """Execute workflow stages sequentially."""
        job = self._jobs[job_id]

        try:
            # Pre-flight: verify ADB connectivity
            if not self._check_adb_connectivity(job):
                job.status = "failed"
                job.completed_at = time.time()
                logger.error(f"Workflow {job_id} aborted: ADB unreachable")
                return

            asyncio.run(self._run_stages(job, persona, bundles, card_data, country, aging))

            job.status = "completed"
        except Exception as e:
            job.status = "failed"
            logger.exception(f"Workflow {job_id} failed: {e}")

        job.completed_at = time.time()
        duration = job.completed_at - job.created_at
        logger.info(f"Workflow {job_id} finished: {job.status} "
                     f"({job.completed_stages}/{len(job.stages)} stages, {duration:.0f}s)")

    async def _run_stages(self, job: 'WorkflowJob', persona: Dict,
                          bundles: List[str], card_data: Dict,
                          country: str, aging: Dict):
        """Execute all workflow stages in order."""
        stage_map = {
            "bootstrap_gapps": lambda: self._stage_bootstrap_gapps(job),
            "forge_profile": lambda: self._stage_forge(job, persona, country, aging),
            "inject_profile": lambda: self._stage_inject(job, persona, card_data),
            "patch_device": lambda: self._stage_patch(job, country),
            "install_apps": lambda: self._stage_install_apps(job, bundles),
            "setup_wallet": lambda: self._stage_wallet(job, card_data),
            "warmup_browse": lambda: self._stage_warmup(job, "browse", aging),
            "warmup_youtube": lambda: self._stage_warmup(job, "youtube", aging),
            "verify_report": lambda: self._stage_verify(job),
            "lockdown_device": lambda: self._stage_lockdown(job),
        }

        ABORT_ON_FAILURE = {"bootstrap_gapps", "forge_profile"}

        for idx, stage in enumerate(job.stages):
            stage.status = "running"
            stage.started_at = time.time()

            try:
                handler = stage_map.get(stage.name)
                if handler:
                    await handler()
                stage.status = "completed"
            except Exception as e:
                stage.status = "failed"
                stage.error = str(e)
                logger.warning(f"Stage {stage.name} failed: {e}")
                # Abort remaining stages if a critical stage fails
                if stage.name in ABORT_ON_FAILURE:
                    stage.completed_at = time.time()
                    for remaining in job.stages[idx + 1:]:
                        remaining.status = "skipped"
                        remaining.error = f"Skipped: critical stage '{stage.name}' failed"
                    raise RuntimeError(f"Aborting workflow: critical stage '{stage.name}' failed: {e}")

            stage.completed_at = time.time()

    # ─── STAGE IMPLEMENTATIONS ───────────────────────────────────────

    async def _stage_bootstrap_gapps(self, job: WorkflowJob):
        """Stage 0: Install GMS, Play Store, Chrome, Google Pay if missing."""
        dev = self.dm.get_device(job.device_id) if self.dm else None
        if not dev:
            raise RuntimeError(f"Device {job.device_id} not found")

        from gapps_bootstrap import GAppsBootstrap
        bs = GAppsBootstrap(adb_target=dev.adb_target)

        # Quick check — skip if already bootstrapped
        status = bs.check_status()
        if not status["needs_bootstrap"]:
            logger.info("GApps already installed — skipping bootstrap")
            return

        result = bs.run(skip_optional=False)
        if result.missing_apks:
            logger.warning(f"Missing APKs (place in /opt/titan/data/gapps/): "
                           f"{result.missing_apks}")
        if not result.gms_ready or not result.play_store_ready:
            raise RuntimeError(
                f"GApps bootstrap incomplete: GMS={result.gms_ready} "
                f"PlayStore={result.play_store_ready}. "
                f"Place APKs in /opt/titan/data/gapps/ and retry.")
        logger.info(f"GApps bootstrap: {len(result.installed)} installed, "
                     f"{len(result.already_installed)} already present")

    async def _stage_forge(self, job: WorkflowJob, persona: Dict,
                           country: str, aging: Dict):
        """Stage: Forge Genesis profile (direct call, no HTTP back-loop)."""
        from android_profile_forge import AndroidProfileForge

        forge = AndroidProfileForge()
        profile = forge.forge(
            persona_name=persona.get("name", ""),
            persona_email=persona.get("email", ""),
            persona_phone=persona.get("phone", ""),
            country=country,
            age_days=aging["age_days"],
        )

        # Persist profile to disk (same path as genesis router)
        profiles_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile_id = profile.get("id", f"TITAN-{uuid.uuid4().hex[:8].upper()}")
        profile["id"] = profile_id
        (profiles_dir / f"{profile_id}.json").write_text(json.dumps(profile, indent=2))

        job.config["profile_id"] = profile_id
        logger.info(f"Profile forged: {profile_id}")

    async def _stage_inject(self, job: WorkflowJob, persona: Dict,
                            card_data: Dict):
        """Stage: Inject profile into device."""
        import urllib.request
        api = f"http://127.0.0.1:{os.environ.get('TITAN_API_PORT', '8080')}"
        profile_id = job.config.get("profile_id", "")
        body = json.dumps({
            "profile_id": profile_id,
            "cc_number": card_data.get("number", ""),
            "cc_exp_month": card_data.get("exp_month", 0),
            "cc_exp_year": card_data.get("exp_year", 0),
            "cc_cvv": card_data.get("cvv", ""),
            "cc_cardholder": card_data.get("cardholder", persona.get("name", "")),
        }).encode()
        req = urllib.request.Request(
            f"{api}/api/genesis/inject/{job.device_id}",
            data=body, headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            inject_job_id = data.get("job_id", "")
            logger.info(f"Inject started: {inject_job_id}")

        # Poll for completion
        for _ in range(120):
            await asyncio.sleep(5)
            try:
                req = urllib.request.Request(
                    f"{api}/api/genesis/inject-status/{inject_job_id}")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = json.loads(resp.read().decode())
                    if status.get("status") in ("completed", "done"):
                        return
                    if status.get("status") == "failed":
                        raise RuntimeError(f"Inject failed: {status.get('error')}")
            except urllib.error.URLError:
                continue
        raise RuntimeError("Inject timed out after 10 minutes")

    async def _stage_patch(self, job: WorkflowJob, country: str):
        """Stage: Apply stealth patches via AnomalyPatcher."""
        dev = self.dm.get_device(job.device_id) if self.dm else None
        if not dev:
            raise RuntimeError(f"Device {job.device_id} not found")

        from anomaly_patcher import AnomalyPatcher
        from device_presets import COUNTRY_DEFAULTS
        from pathlib import Path as _Path

        defaults = COUNTRY_DEFAULTS.get(country, COUNTRY_DEFAULTS.get("US", {}))
        carrier  = defaults.get("carrier", "att_us")
        location = defaults.get("location", "la")
        model    = dev.config.get("model", "samsung_s25_ultra")

        # Override with genesis profile values so GSM props match the persona's carrier
        profile_id = job.config.get("profile_id", "")
        if profile_id:
            _pf = _Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles" / f"{profile_id}.json"
            if _pf.exists():
                try:
                    _pd = json.loads(_pf.read_text())
                    carrier  = _pd.get("carrier",      carrier)
                    location = _pd.get("location",     location)
                    model    = _pd.get("device_model", model)
                    logger.info(f"Patch using profile values: preset={model} carrier={carrier} location={location}")
                except Exception as _e:
                    logger.warning(f"Could not load profile for patch params: {_e}")

        patcher = AnomalyPatcher(adb_target=dev.adb_target)
        report = patcher.full_patch(model, carrier, location)
        dev.patch_result = report.to_dict()
        dev.stealth_score = report.score
        dev.state = "patched"
        logger.info(f"Patch complete: score={report.score}")

    async def _stage_install_apps(self, job: WorkflowJob, bundles: List[str]):
        """Stage: Install apps via AI agent in batches of 3."""
        from app_bundles import APP_BUNDLES
        apps = []
        for bkey in bundles:
            bundle = APP_BUNDLES.get(bkey, {})
            for app in bundle.get("apps", []):
                apps.append(app["name"])

        if not apps:
            return

        import urllib.request
        api = f"http://127.0.0.1:{os.environ.get('TITAN_API_PORT', '8080')}"
        batch_size = 3
        batches = [apps[i:i + batch_size] for i in range(0, min(len(apps), 12), batch_size)]

        for batch_idx, batch in enumerate(batches):
            app_list = ", ".join(batch)
            steps_per_app = 25
            body = json.dumps({
                "prompt": (f"Open Google Play Store and install these apps one by one: "
                           f"{app_list}. For each: search by name, tap Install, wait for "
                           f"it to complete, then search for the next. Skip any requiring payment."),
                "max_steps": steps_per_app * len(batch),
            }).encode()
            req = urllib.request.Request(
                f"{api}/api/agent/task/{job.device_id}",
                data=body, headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                    task_id = data.get("task_id", "")
            except Exception as e:
                logger.warning(f"App install batch {batch_idx} failed to start: {e}")
                continue

            # Poll for completion (up to 10 min per batch)
            for _ in range(120):
                await asyncio.sleep(5)
                try:
                    req = urllib.request.Request(
                        f"{api}/api/agent/task/{job.device_id}/{task_id}")
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        status = json.loads(resp.read().decode())
                        if status.get("status") in ("completed", "failed", "stopped"):
                            logger.info(f"App install batch {batch_idx+1}/{len(batches)}: "
                                         f"{status.get('status')} ({status.get('steps_taken', 0)} steps)")
                            break
                except Exception:
                    continue

            await asyncio.sleep(3)  # Brief pause between batches

    async def _stage_wallet(self, job: WorkflowJob, card_data: Dict):
        """Stage: Set up wallet via ADB data injection."""
        if not card_data.get("number"):
            logger.info("No card data — skipping wallet stage")
            return

        dev = self.dm.get_device(job.device_id) if self.dm else None
        if not dev:
            raise RuntimeError(f"Device {job.device_id} not found")

        from wallet_provisioner import WalletProvisioner
        prov = WalletProvisioner(adb_target=dev.adb_target)
        result = prov.provision_card(
            card_number=card_data["number"],
            exp_month=card_data.get("exp_month", 12),
            exp_year=card_data.get("exp_year", 2027),
            cardholder=card_data.get("cardholder", ""),
            cvv=card_data.get("cvv", ""),
            persona_email=job.config.get("persona", {}).get("email", ""),
        )
        if not result.success:
            raise RuntimeError(f"Wallet injection failed: {result.error}")
        logger.info(f"Wallet provisioned: {result.card_network} ...{result.last4}")

    async def _stage_warmup(self, job: WorkflowJob, warmup_type: str,
                            aging: Dict):
        """Stage: Run warmup browsing/YouTube sessions."""
        import urllib.request
        api = f"http://127.0.0.1:{os.environ.get('TITAN_API_PORT', '8080')}"

        if warmup_type == "browse":
            prompt = ("Open the web browser and browse naturally. Visit Google, search for "
                      "'best restaurants near me', click a result, scroll through it. "
                      "Then search for 'weather forecast', view results. Visit 2 more "
                      "websites naturally.")
        else:
            prompt = ("Open YouTube. Browse the home feed, watch a video for 30 seconds, "
                      "scroll the feed, watch another video. Like one video.")

        body = json.dumps({
            "prompt": prompt,
            "max_steps": 25,
        }).encode()
        req = urllib.request.Request(
            f"{api}/api/agent/task/{job.device_id}",
            data=body, headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            task_id = data.get("task_id", "")

        # Poll (up to 15 min)
        for _ in range(180):
            await asyncio.sleep(5)
            try:
                req = urllib.request.Request(
                    f"{api}/api/agent/task/{job.device_id}/{task_id}")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = json.loads(resp.read().decode())
                    if status.get("status") in ("completed", "failed", "stopped"):
                        return
            except Exception:
                continue

    async def _stage_verify(self, job: WorkflowJob):
        """Stage: Generate verification report + deep wallet verification."""
        from aging_report import AgingReporter
        reporter = AgingReporter(device_manager=self.dm)
        report = await reporter.generate(device_id=job.device_id)
        job.report = report.to_dict()
        logger.info(f"Verify report: {report.overall_grade} ({report.overall_score}/100)")

        # Deep wallet verification (13-check)
        try:
            from wallet_verifier import WalletVerifier
            dev = self.dm.get_device(job.device_id) if self.dm else None
            target = dev.adb_target if dev else "127.0.0.1:6520"
            wv = WalletVerifier(adb_target=target)
            wallet_report = wv.verify()
            job.report["wallet_verification"] = wallet_report.to_dict()
            logger.info(f"Wallet verify: {wallet_report.passed}/{wallet_report.total} ({wallet_report.grade})")
        except Exception as e:
            logger.warning(f"Wallet verification failed: {e}")

    async def _stage_lockdown(self, job: WorkflowJob):
        """Stage: Production lockdown — disable ADB and developer options.

        Only called when disable_adb=True was passed to start_workflow.
        Disables ADB to remove the biggest forensic indicator that a device
        is under automated control. Device becomes unmanageable via ADB
        after this — only use in production deployments.
        """
        import subprocess
        dev = self.dm.get_device(job.device_id) if self.dm else None
        target = dev.adb_target if dev else "127.0.0.1:6520"
        logger.info(f"Lockdown: disabling ADB on {target}")
        try:
            cmds = [
                "settings put global adb_enabled 0",
                "settings put global development_settings_enabled 0",
                "settings put secure adb_notify 0",
                "setprop service.adb.tcp.port -1",
                "setprop persist.sys.usb.config mtp",
            ]
            subprocess.run(
                ["adb", "-s", target, "shell", ";".join(cmds)],
                capture_output=True, text=True, timeout=15,
            )
            logger.info("Lockdown complete — ADB disabled")
        except Exception as e:
            logger.warning(f"Lockdown failed: {e}")

    # ─── PUBLIC API ──────────────────────────────────────────────────

    def get_status(self, job_id: str) -> Optional[WorkflowJob]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> List[Dict]:
        return [j.to_dict() for j in self._jobs.values()]
