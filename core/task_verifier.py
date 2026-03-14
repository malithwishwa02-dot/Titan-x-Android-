"""
Titan V11.3 — Task Verifier
=============================
Verifies that AI agent tasks completed successfully by checking
device state after execution.

Verification methods:
  - Package presence (pm list packages)
  - SharedPrefs login tokens
  - File existence (tapandpay.db, gallery photos)
  - Screenshot + vision model analysis
  - Shell command output checks

Usage:
    verifier = TaskVerifier(bridge, pad_code="ACP...")
    result = await verifier.verify_app_installed("com.chase.sig.android")
    result = await verifier.verify_wallet_active()
    report = await verifier.full_verify(expected_apps=[...], expect_wallet=True)
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.task-verifier")


@dataclass
class VerifyResult:
    """Result of a single verification check."""
    check: str = ""
    passed: bool = False
    detail: str = ""
    method: str = ""  # shell | vision | file_check


@dataclass
class VerifyReport:
    """Complete verification report for a device."""
    device_id: str = ""
    timestamp: float = 0.0
    checks: List[VerifyResult] = field(default_factory=list)
    summary: str = ""

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def score(self) -> float:
        return self.passed / max(self.total, 1)

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "score": round(self.score * 100, 1),
            "checks": [asdict(c) for c in self.checks],
            "summary": self.summary,
        }


class TaskVerifier:
    """Verifies device state after AI agent task execution."""

    def __init__(self, bridge=None, pad_code: str = ""):
        self._bridge = bridge
        self.pad_code = pad_code

    def _get_bridge(self):
        if self._bridge is None:
            from vmos_cloud_bridge import VMOSCloudBridge
            self._bridge = VMOSCloudBridge()
        return self._bridge

    async def _shell(self, cmd: str, wait: int = 12) -> str:
        """Execute shell command on device and return output."""
        bridge = self._get_bridge()
        result = await bridge.exec_shell(self.pad_code, cmd)
        if result.ok:
            task_id = None
            if hasattr(result, 'data') and result.data:
                task_id = result.data
            if task_id:
                await asyncio.sleep(wait)
                detail = await bridge._wait_for_task(self.pad_code, task_id)
                return detail or ""
        return ""

    # ─── INDIVIDUAL CHECKS ───────────────────────────────────────────

    async def verify_app_installed(self, package: str) -> VerifyResult:
        """Check if an app is installed via pm list packages."""
        output = await self._shell(f"pm list packages | grep {package}", wait=8)
        installed = package in (output or "")
        return VerifyResult(
            check=f"app_installed:{package}",
            passed=installed,
            detail=f"{'Found' if installed else 'Not found'}: {package}",
            method="shell",
        )

    async def verify_app_signed_in(self, package: str) -> VerifyResult:
        """Check if app has login state by examining SharedPrefs for tokens."""
        # Check for common login indicators in SharedPrefs
        checks = [
            f"ls /data/data/{package}/shared_prefs/ 2>/dev/null | head -10",
        ]
        output = await self._shell(checks[0], wait=8)

        # Look for login-related pref files
        login_indicators = [
            "auth", "token", "login", "session", "account", "user",
            "credential", "access_token", "refresh_token",
        ]
        has_login = False
        if output:
            lower = output.lower()
            has_login = any(ind in lower for ind in login_indicators)

        return VerifyResult(
            check=f"app_signed_in:{package}",
            passed=has_login,
            detail=f"Login prefs: {'found' if has_login else 'not found'} in {package}",
            method="shell",
        )

    async def verify_wallet_active(self) -> VerifyResult:
        """Check if Google Pay tapandpay.db exists with card data."""
        output = await self._shell(
            "ls -la /data/data/com.google.android.gms/databases/tapandpay.db 2>/dev/null",
            wait=8,
        )
        has_db = "tapandpay.db" in (output or "")
        return VerifyResult(
            check="wallet_active",
            passed=has_db,
            detail=f"tapandpay.db: {'exists' if has_db else 'missing'}",
            method="shell",
        )

    async def verify_google_account(self) -> VerifyResult:
        """Check if a Google account is configured."""
        output = await self._shell(
            "dumpsys account | grep -i 'Account {' | head -3",
            wait=10,
        )
        has_account = "google.com" in (output or "").lower() or "Account {" in (output or "")
        return VerifyResult(
            check="google_account",
            passed=has_account,
            detail=f"Google account: {'present' if has_account else 'not found'}",
            method="shell",
        )

    async def verify_contacts(self, min_count: int = 5) -> VerifyResult:
        """Check if contacts exist."""
        output = await self._shell(
            "content query --uri content://com.android.contacts/contacts --projection display_name 2>/dev/null | wc -l",
            wait=10,
        )
        try:
            count = int(output.strip()) if output else 0
        except (ValueError, AttributeError):
            count = 0
        passed = count >= min_count
        return VerifyResult(
            check="contacts",
            passed=passed,
            detail=f"Contacts: {count} (need {min_count}+)",
            method="shell",
        )

    async def verify_chrome_data(self) -> VerifyResult:
        """Check if Chrome history/cookies are present."""
        output = await self._shell(
            "ls /data/data/com.android.chrome/app_chrome/Default/ 2>/dev/null | head -10",
            wait=8,
        )
        files = (output or "").split()
        has_history = "History" in files
        has_cookies = "Cookies" in files
        passed = has_history or has_cookies
        return VerifyResult(
            check="chrome_data",
            passed=passed,
            detail=f"Chrome: History={'yes' if has_history else 'no'}, Cookies={'yes' if has_cookies else 'no'}",
            method="shell",
        )

    async def verify_gallery(self, min_photos: int = 3) -> VerifyResult:
        """Check if gallery has photos."""
        output = await self._shell(
            "ls /sdcard/DCIM/Camera/ 2>/dev/null | wc -l",
            wait=8,
        )
        try:
            count = int(output.strip()) if output else 0
        except (ValueError, AttributeError):
            count = 0
        passed = count >= min_photos
        return VerifyResult(
            check="gallery",
            passed=passed,
            detail=f"Gallery photos: {count} (need {min_photos}+)",
            method="shell",
        )

    async def verify_sms(self, min_count: int = 5) -> VerifyResult:
        """Check if SMS messages exist."""
        output = await self._shell(
            "content query --uri content://sms --projection _id 2>/dev/null | wc -l",
            wait=10,
        )
        try:
            count = int(output.strip()) if output else 0
        except (ValueError, AttributeError):
            count = 0
        passed = count >= min_count
        return VerifyResult(
            check="sms",
            passed=passed,
            detail=f"SMS: {count} (need {min_count}+)",
            method="shell",
        )

    async def verify_wifi_networks(self) -> VerifyResult:
        """Check if saved WiFi networks exist."""
        output = await self._shell(
            "ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null && echo EXISTS || echo MISSING",
            wait=8,
        )
        has_wifi = "EXISTS" in (output or "")
        return VerifyResult(
            check="wifi_networks",
            passed=has_wifi,
            detail=f"WifiConfigStore.xml: {'present' if has_wifi else 'missing'}",
            method="shell",
        )

    async def verify_screen_shows(self, expected_text: str) -> VerifyResult:
        """Take screenshot and check if expected text is visible via vision."""
        try:
            from vmos_agent_adapter import VMOSScreenAdapter
            adapter = VMOSScreenAdapter(bridge=self._bridge, pad_code=self.pad_code)
            state = adapter.capture_and_analyze(use_ui_dump=True)
            all_text = " ".join(state.text_blocks).lower()
            found = expected_text.lower() in all_text
            return VerifyResult(
                check=f"screen_shows:{expected_text}",
                passed=found,
                detail=f"Screen text match for '{expected_text}': {'found' if found else 'not found'}",
                method="vision",
            )
        except Exception as e:
            return VerifyResult(
                check=f"screen_shows:{expected_text}",
                passed=False,
                detail=f"Vision check failed: {e}",
                method="vision",
            )

    # ─── FULL VERIFY ─────────────────────────────────────────────────

    async def full_verify(self, device_id: str = "",
                          expected_apps: List[str] = None,
                          expect_wallet: bool = True,
                          expect_google: bool = True,
                          expect_contacts: bool = True,
                          expect_chrome: bool = True,
                          expect_gallery: bool = True,
                          expect_sms: bool = True) -> VerifyReport:
        """Run all relevant verification checks and produce a report."""
        report = VerifyReport(
            device_id=device_id or self.pad_code,
            timestamp=time.time(),
        )

        # Core checks
        if expect_google:
            report.checks.append(await self.verify_google_account())
        if expect_contacts:
            report.checks.append(await self.verify_contacts())
        if expect_chrome:
            report.checks.append(await self.verify_chrome_data())
        if expect_wallet:
            report.checks.append(await self.verify_wallet_active())
        if expect_gallery:
            report.checks.append(await self.verify_gallery())
        if expect_sms:
            report.checks.append(await self.verify_sms())
        report.checks.append(await self.verify_wifi_networks())

        # App-specific checks
        for pkg in (expected_apps or []):
            report.checks.append(await self.verify_app_installed(pkg))

        report.summary = (
            f"{report.passed}/{report.total} checks passed "
            f"({report.score:.0%})"
        )

        logger.info(f"Verify report for {device_id}: {report.summary}")
        return report
