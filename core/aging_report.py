"""
Titan V11.3 — Device Aging Report
===================================
Generates comprehensive verification reports for aged devices,
combining trust score, patch results, app installation status,
wallet state, injection results, and agent task history.

Usage:
    reporter = AgingReporter(device_manager=dm)
    report = await reporter.generate(device_id="dev-abc123")
    # Returns full JSON report with all checks
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.aging-report")

PROFILES_DIR = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "profiles"
TRAJECTORY_DIR = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "trajectories"


@dataclass
class AgingReport:
    """Complete device aging report."""
    device_id: str = ""
    report_time: str = ""
    # Persona
    persona: Dict[str, str] = field(default_factory=dict)
    profile_id: str = ""
    profile_age_days: int = 0
    # Scores
    trust_score: Dict[str, Any] = field(default_factory=dict)
    patch_score: Dict[str, Any] = field(default_factory=dict)
    verify_score: Dict[str, Any] = field(default_factory=dict)
    # App state
    apps_installed: List[Dict[str, Any]] = field(default_factory=list)
    apps_signed_in: List[Dict[str, Any]] = field(default_factory=list)
    # Wallet
    wallet: Dict[str, Any] = field(default_factory=dict)
    # Injection results
    injection_results: Dict[str, Any] = field(default_factory=dict)
    # Agent tasks
    agent_tasks: List[Dict[str, Any]] = field(default_factory=list)
    # Overall
    overall_grade: str = ""
    overall_score: float = 0.0
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class AgingReporter:
    """Generates comprehensive aging reports for devices."""

    def __init__(self, bridge=None, device_manager=None):
        self._bridge = bridge  # legacy — unused for Cuttlefish
        self.dm = device_manager

    async def generate(self, device_id: str) -> AgingReport:
        """Generate a full aging report for a device."""
        report = AgingReport(
            device_id=device_id,
            report_time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

        dev = self.dm.get_device(device_id) if self.dm else None
        adb_target = dev.adb_target if dev else "127.0.0.1:6520"

        # 1. Load persona from profile
        report.persona, report.profile_id, report.profile_age_days = (
            self._load_profile_info(device_id)
        )

        # 2. Trust score (if endpoint available)
        report.trust_score = await self._get_trust_score(device_id)

        # 3. Patch score
        report.patch_score = await self._get_patch_score(device_id)

        # 4. Task verification
        if dev:
            from task_verifier import TaskVerifier
            verifier = TaskVerifier(adb_target=adb_target)

            # Check expected apps
            expected_apps = self._get_expected_apps(device_id)
            verify = await verifier.full_verify(
                device_id=device_id,
                expected_apps=expected_apps,
            )
            report.verify_score = verify.to_dict()

            # Detailed app status
            for pkg in expected_apps:
                result = await verifier.verify_app_installed(pkg)
                signin = await verifier.verify_app_signed_in(pkg)
                report.apps_installed.append({
                    "package": pkg,
                    "installed": result.passed,
                })
                if signin.passed:
                    report.apps_signed_in.append({
                        "package": pkg,
                        "signed_in": True,
                    })

            # Wallet check
            wallet_check = await verifier.verify_wallet_active()
            report.wallet = {
                "active": wallet_check.passed,
                "detail": wallet_check.detail,
            }

        # 5. Injection results from profile
        report.injection_results = self._load_injection_results(device_id)

        # 6. Agent task history from trajectories
        report.agent_tasks = self._load_agent_tasks(device_id)

        # 7. Calculate overall grade
        report.overall_score, report.overall_grade = self._calculate_grade(report)
        report.recommendations = self._generate_recommendations(report)

        logger.info(f"Aging report for {device_id}: {report.overall_grade} "
                     f"({report.overall_score:.0f}/100)")
        return report

    def _load_profile_info(self, device_id: str) -> tuple:
        """Load persona info from saved profile."""
        persona = {}
        profile_id = ""
        age_days = 0

        if not PROFILES_DIR.exists():
            return persona, profile_id, age_days

        # Find profile for this device
        for f in PROFILES_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("device_id") == device_id or device_id in f.name:
                    persona = {
                        "name": data.get("persona_name", ""),
                        "email": data.get("persona_email", ""),
                        "phone": data.get("persona_phone", ""),
                        "country": data.get("country", ""),
                    }
                    profile_id = data.get("profile_id", f.stem)
                    age_days = data.get("age_days", 0)
                    break
            except Exception:
                continue

        return persona, profile_id, age_days

    async def _get_trust_score(self, device_id: str) -> Dict:
        """Fetch trust score from API (internal call)."""
        def _fetch():
            import urllib.request
            api_port = os.environ.get("TITAN_API_PORT", "8080")
            url = f"http://127.0.0.1:{api_port}/api/genesis/trust-score/{device_id}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        try:
            return await asyncio.to_thread(_fetch)
        except Exception:
            return {"score": 0, "grade": "N/A", "error": "Could not fetch trust score"}

    async def _get_patch_score(self, device_id: str) -> Dict:
        """Fetch latest patch/audit results."""
        def _fetch():
            import urllib.request
            api_port = os.environ.get("TITAN_API_PORT", "8080")
            url = f"http://127.0.0.1:{api_port}/api/stealth/{device_id}/audit"
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        try:
            return await asyncio.to_thread(_fetch)
        except Exception:
            return {"score": 0, "phases": "N/A"}

    def _get_expected_apps(self, device_id: str) -> List[str]:
        """Get list of apps expected to be installed on this device."""
        try:
            from app_bundles import APP_BUNDLES, COUNTRY_BUNDLES
            # Default to US bundle
            bundles = COUNTRY_BUNDLES.get("US", ["us_banking", "social"])
            pkgs = []
            for bkey in bundles:
                bundle = APP_BUNDLES.get(bkey, {})
                for app in bundle.get("apps", []):
                    pkgs.append(app["pkg"])
            return pkgs[:20]  # Cap at 20 to avoid timeout
        except Exception:
            return []

    def _load_injection_results(self, device_id: str) -> Dict:
        """Load injection results from stored profile data."""
        results = {
            "contacts": 0, "sms": 0, "call_logs": 0,
            "chrome_history": False, "chrome_cookies": False,
            "gallery_photos": 0, "wallet": False,
        }
        if not PROFILES_DIR.exists():
            return results

        for f in PROFILES_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("device_id") == device_id or device_id in f.name:
                    results["contacts"] = len(data.get("contacts", []))
                    results["sms"] = len(data.get("sms", []))
                    results["call_logs"] = len(data.get("call_logs", []))
                    results["chrome_history"] = len(data.get("history", [])) > 0
                    results["chrome_cookies"] = len(data.get("cookies", [])) > 0
                    results["gallery_photos"] = len(data.get("gallery_paths", []))
                    results["wallet"] = bool(data.get("wallet_provisioned"))
                    break
            except Exception:
                continue
        return results

    def _load_agent_tasks(self, device_id: str) -> List[Dict]:
        """Load agent task history from trajectory metadata."""
        tasks = []
        if not TRAJECTORY_DIR.exists():
            return tasks

        for d in sorted(TRAJECTORY_DIR.iterdir(), reverse=True):
            meta_file = d / "metadata.json"
            if not meta_file.exists():
                continue
            try:
                meta = json.loads(meta_file.read_text())
                if meta.get("device_id") == device_id or device_id in meta.get("device_id", ""):
                    tasks.append({
                        "task_id": meta.get("task_id"),
                        "prompt": meta.get("prompt", "")[:80],
                        "category": meta.get("task_category"),
                        "status": meta.get("status"),
                        "steps": meta.get("total_steps", 0),
                        "duration": f"{meta.get('duration', 0):.0f}s",
                        "model": meta.get("model"),
                        "is_demo": meta.get("is_demo", False),
                    })
            except Exception:
                continue

        return tasks[:20]  # Last 20 tasks

    def _calculate_grade(self, report: AgingReport) -> tuple:
        """Calculate overall aging score and letter grade."""
        score = 0.0
        weights = {
            "trust": 30,
            "patch": 20,
            "verify": 25,
            "apps": 15,
            "wallet": 10,
        }

        # Trust score component
        ts = report.trust_score.get("score", 0)
        if isinstance(ts, (int, float)):
            score += (ts / 100) * weights["trust"]

        # Patch score component
        ps = report.patch_score.get("score", 0)
        if isinstance(ps, (int, float)):
            score += (ps / 100) * weights["patch"]

        # Verify score component
        vs = report.verify_score.get("score", 0)
        if isinstance(vs, (int, float)):
            score += (vs / 100) * weights["verify"]

        # App installation rate
        if report.apps_installed:
            installed = sum(1 for a in report.apps_installed if a.get("installed"))
            rate = installed / len(report.apps_installed)
            score += rate * weights["apps"]

        # Wallet
        if report.wallet.get("active"):
            score += weights["wallet"]

        # Grade
        if score >= 90:
            grade = "A+"
        elif score >= 80:
            grade = "A"
        elif score >= 70:
            grade = "B"
        elif score >= 60:
            grade = "C"
        elif score >= 50:
            grade = "D"
        else:
            grade = "F"

        return round(score, 1), grade

    def _generate_recommendations(self, report: AgingReport) -> List[str]:
        """Generate actionable recommendations based on report gaps."""
        recs = []

        ts = report.trust_score.get("score", 0)
        if isinstance(ts, (int, float)) and ts < 80:
            recs.append("Trust score below 80 — re-inject profile data or add missing data types")

        if not report.wallet.get("active"):
            recs.append("Wallet not active — inject tapandpay.db with card data")

        installed_count = sum(1 for a in report.apps_installed if a.get("installed"))
        total_expected = len(report.apps_installed)
        if total_expected > 0 and installed_count < total_expected * 0.7:
            missing = total_expected - installed_count
            recs.append(f"{missing} expected apps not installed — run app bundle install agent")

        signed_in = len(report.apps_signed_in)
        if installed_count > 0 and signed_in < installed_count * 0.3:
            recs.append("Low app sign-in rate — run sign-in agent for installed apps")

        if not report.agent_tasks:
            recs.append("No warmup tasks recorded — run warmup_device and warmup_youtube scenarios")

        if not recs:
            recs.append("Device aging looks complete — monitor for anomaly detection")

        return recs
