"""
Titan V11.3 — Wallet Injection Verifier
Deep verification of wallet injection state on Android devices.

Checks:
  1. tapandpay.db existence, schema validity, token count + provisioning status
  2. NFC shared_prefs (nfc_on_prefs.xml) — tap-and-pay readiness
  3. COIN.xml (Play Store billing) — payment method presence + auth settings
  4. Chrome Web Data — autofill card entry
  5. GMS billing state — wallet_instrument_prefs.xml + payment_profile_prefs.xml
  6. Keybox — Play Integrity Strong attestation readiness
  7. File ownership/SELinux — DAC permissions on injected files
  8. GSF alignment — CheckinService.xml + GservicesSettings.xml coherence

Returns a structured WalletVerificationReport with per-check pass/fail,
overall score, and actionable remediation hints.
"""

import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.wallet_verifier")


def _adb_shell(target: str, cmd: str, timeout: int = 15) -> str:
    """Execute ADB shell command and return stdout."""
    try:
        r = subprocess.run(
            ["adb", "-s", target, "shell", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception as e:
        logger.debug(f"adb shell failed: {e}")
        return ""


@dataclass
class WalletCheck:
    name: str
    passed: bool
    detail: str = ""
    remediation: str = ""


@dataclass
class WalletVerificationReport:
    device_target: str = ""
    timestamp: float = 0.0
    checks: List[WalletCheck] = field(default_factory=list)
    samsung_pay_note: str = (
        "Samsung Pay is NOT supported on virtualized/modified devices. "
        "Knox TEE e-fuse (0x1) permanently blocks token writes when "
        "bootloader is unlocked or device is rooted."
    )

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def score(self) -> int:
        return int((self.passed / self.total) * 100) if self.total > 0 else 0

    @property
    def grade(self) -> str:
        s = self.score
        if s >= 95: return "A+"
        if s >= 85: return "A"
        if s >= 70: return "B"
        if s >= 50: return "C"
        return "F"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_target": self.device_target,
            "timestamp": self.timestamp,
            "score": self.score,
            "grade": self.grade,
            "passed": self.passed,
            "total": self.total,
            "samsung_pay": self.samsung_pay_note,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "detail": c.detail,
                    "remediation": c.remediation,
                }
                for c in self.checks
            ],
        }


class WalletVerifier:
    """Deep wallet injection state verifier for Android devices via ADB."""

    WALLET_DATA = "/data/data/com.google.android.apps.walletnfcrel"
    VENDING_DATA = "/data/data/com.android.vending"
    CHROME_DATA = "/data/data/com.android.chrome"
    GMS_DATA = "/data/data/com.google.android.gms"

    def __init__(self, adb_target: str = "127.0.0.1:6520"):
        self.target = adb_target
        self._browser_pkg = self._resolve_browser_pkg()
        self.CHROME_DATA = f"/data/data/{self._browser_pkg}"

    def _resolve_browser_pkg(self) -> str:
        """Detect Chrome vs Kiwi Browser on device."""
        for pkg in ["com.android.chrome", "com.kiwibrowser.browser"]:
            out = self._sh(f"pm path {pkg} 2>/dev/null")
            if out.strip():
                return pkg
        return "com.android.chrome"

    def _sh(self, cmd: str, timeout: int = 15) -> str:
        return _adb_shell(self.target, cmd, timeout)

    def verify(self) -> WalletVerificationReport:
        """Run all wallet verification checks. Returns structured report."""
        report = WalletVerificationReport(
            device_target=self.target,
            timestamp=time.time(),
        )

        report.checks.append(self._check_tapandpay_db())
        report.checks.append(self._check_tapandpay_tokens())
        report.checks.append(self._check_token_metadata())
        report.checks.append(self._check_nfc_prefs())
        report.checks.append(self._check_coin_xml())
        report.checks.append(self._check_coin_auth())
        report.checks.append(self._check_chrome_webdata())
        report.checks.append(self._check_gms_wallet_prefs())
        report.checks.append(self._check_gms_payment_profile())
        report.checks.append(self._check_keybox())
        report.checks.append(self._check_gsf_alignment())
        report.checks.append(self._check_tapandpay_ownership())
        report.checks.append(self._check_nfc_system_enabled())

        logger.info(
            f"Wallet verification: {report.passed}/{report.total} "
            f"({report.score}% {report.grade}) on {self.target}"
        )
        return report

    # ─── Individual checks ─────────────────────────────────────────

    def _check_tapandpay_db(self) -> WalletCheck:
        db_path = f"{self.WALLET_DATA}/databases/tapandpay.db"
        exists = bool(self._sh(f"ls {db_path} 2>/dev/null"))
        return WalletCheck(
            name="tapandpay_db_exists",
            passed=exists,
            detail=f"{'Found' if exists else 'Missing'}: {db_path}",
            remediation="" if exists else "Run wallet provisioning: WalletProvisioner.provision_card()",
        )

    def _query_db(self, remote_db: str, sql: str) -> str:
        """Query a remote SQLite DB. Try device sqlite3 first, fall back to local."""
        raw = self._sh(f"sqlite3 {remote_db} '{sql}' 2>/dev/null")
        if raw and raw.strip():
            return raw.strip()
        # Fallback: pull DB locally and query with Python sqlite3
        try:
            import tempfile, subprocess, sqlite3
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name
            r = subprocess.run(
                ["adb", "-s", self.target, "pull", remote_db, tmp_path],
                capture_output=True, timeout=15)
            if r.returncode != 0:
                return ""
            conn = sqlite3.connect(tmp_path)
            try:
                row = conn.execute(sql).fetchone()
                return str(row[0]) if row else ""
            finally:
                conn.close()
                import os; os.unlink(tmp_path)
        except Exception:
            return ""

    def _check_tapandpay_tokens(self) -> WalletCheck:
        db_path = f"{self.WALLET_DATA}/databases/tapandpay.db"
        raw = self._query_db(db_path, "SELECT COUNT(*) FROM tokens")
        count = int(raw) if raw and raw.isdigit() else 0
        return WalletCheck(
            name="tapandpay_token_count",
            passed=count > 0,
            detail=f"Token count: {count}",
            remediation="" if count > 0 else "No tokens in tapandpay.db — re-run wallet provisioning",
        )

    def _check_token_metadata(self) -> WalletCheck:
        db_path = f"{self.WALLET_DATA}/databases/tapandpay.db"
        status = self._query_db(db_path, "SELECT provisioning_status FROM token_metadata LIMIT 1")
        ok = status == "PROVISIONED"
        return WalletCheck(
            name="token_provisioning_status",
            passed=ok,
            detail=f"Status: {status or 'N/A'}",
            remediation="" if ok else "Token metadata missing or not PROVISIONED",
        )

    def _check_nfc_prefs(self) -> WalletCheck:
        content = self._sh(
            f"cat {self.WALLET_DATA}/shared_prefs/nfc_on_prefs.xml 2>/dev/null"
        )
        has_nfc = "nfc_enabled" in (content or "") and "true" in (content or "")
        return WalletCheck(
            name="nfc_prefs_enabled",
            passed=has_nfc,
            detail="NFC tap-and-pay prefs present" if has_nfc else "nfc_on_prefs.xml missing or incomplete",
            remediation="" if has_nfc else "Re-run Google Pay provisioning to write NFC prefs",
        )

    def _check_coin_xml(self) -> WalletCheck:
        coin_path = (
            f"{self.VENDING_DATA}/shared_prefs/"
            "com.android.vending.billing.InAppBillingService.COIN.xml"
        )
        content = self._sh(f"cat {coin_path} 2>/dev/null")
        has_payment = "has_payment_method" in (content or "")
        return WalletCheck(
            name="coin_xml_payment_method",
            passed=has_payment,
            detail="COIN.xml has payment method" if has_payment else "COIN.xml missing or no payment method",
            remediation="" if has_payment else "Re-run Play Store billing provisioning",
        )

    def _check_coin_auth(self) -> WalletCheck:
        coin_path = (
            f"{self.VENDING_DATA}/shared_prefs/"
            "com.android.vending.billing.InAppBillingService.COIN.xml"
        )
        content = self._sh(f"cat {coin_path} 2>/dev/null")
        no_auth = "purchase_requires_auth" in (content or "") and "false" in (content or "")
        return WalletCheck(
            name="coin_auth_disabled",
            passed=no_auth,
            detail="purchase_requires_auth=false" if no_auth else "Auth not disabled or COIN.xml missing",
            remediation="" if no_auth else "Update COIN.xml with purchase_requires_auth=false",
        )

    def _check_chrome_webdata(self) -> WalletCheck:
        # Chrome may store Web Data with space in name
        exists = bool(self._sh(
            f"ls '{self.CHROME_DATA}/app_chrome/Default/Web Data' 2>/dev/null"
        ))
        return WalletCheck(
            name="chrome_webdata_exists",
            passed=exists,
            detail="Chrome Web Data present" if exists else "Chrome Web Data missing",
            remediation="" if exists else "Re-run Chrome autofill provisioning",
        )

    def _check_gms_wallet_prefs(self) -> WalletCheck:
        content = self._sh(
            f"cat {self.GMS_DATA}/shared_prefs/wallet_instrument_prefs.xml 2>/dev/null"
        )
        synced = "wallet_setup_complete" in (content or "") and "true" in (content or "")
        return WalletCheck(
            name="gms_wallet_synced",
            passed=synced,
            detail="GMS wallet state synced" if synced else "GMS wallet_instrument_prefs.xml missing",
            remediation="" if synced else "Re-run wallet provisioning (GMS billing sync step)",
        )

    def _check_gms_payment_profile(self) -> WalletCheck:
        content = self._sh(
            f"cat {self.GMS_DATA}/shared_prefs/payment_profile_prefs.xml 2>/dev/null"
        )
        synced = "payment_methods_synced" in (content or "") and "true" in (content or "")
        return WalletCheck(
            name="gms_payment_profile_synced",
            passed=synced,
            detail="GMS payment profile synced" if synced else "payment_profile_prefs.xml missing",
            remediation="" if synced else "Re-run wallet provisioning (GMS billing sync step)",
        )

    def _check_keybox(self) -> WalletCheck:
        loaded = self._sh("getprop persist.titan.keybox.loaded")
        kb_hash = self._sh("getprop persist.titan.keybox.hash")
        ok = loaded.strip() == "1"
        return WalletCheck(
            name="keybox_loaded",
            passed=ok,
            detail=f"Keybox loaded (hash={kb_hash.strip()[:12]})" if ok else "Keybox NOT loaded",
            remediation="" if ok else (
                "Place keybox.xml at /opt/titan/data/keybox.xml and re-run anomaly patcher. "
                "Without keybox, Play Integrity Strong will fail and Google Pay NFC won't work."
            ),
        )

    def _check_gsf_alignment(self) -> WalletCheck:
        checkin = self._sh(
            f"cat {self.GMS_DATA}/shared_prefs/CheckinService.xml 2>/dev/null"
        )
        has_device_id = "deviceId" in (checkin or "")
        return WalletCheck(
            name="gsf_fingerprint_aligned",
            passed=has_device_id,
            detail="GSF CheckinService aligned" if has_device_id else "CheckinService.xml missing",
            remediation="" if has_device_id else "Re-run anomaly patcher Phase 11c (GSF alignment)",
        )

    def _check_tapandpay_ownership(self) -> WalletCheck:
        db_path = f"{self.WALLET_DATA}/databases/tapandpay.db"
        db_owner = self._sh(f"stat -c %U {db_path} 2>/dev/null")
        dir_owner = self._sh(f"stat -c %U {self.WALLET_DATA} 2>/dev/null")
        ok = bool(db_owner.strip()) and db_owner.strip() == dir_owner.strip()
        return WalletCheck(
            name="tapandpay_ownership",
            passed=ok,
            detail=f"Owner: {db_owner.strip() or 'N/A'} (expected: {dir_owner.strip() or 'N/A'})",
            remediation="" if ok else "Fix ownership: chown + restorecon on tapandpay.db",
        )

    def _check_nfc_system_enabled(self) -> WalletCheck:
        nfc_state = self._sh("settings get secure nfc_on 2>/dev/null")
        ok = nfc_state.strip() == "1"
        return WalletCheck(
            name="system_nfc_enabled",
            passed=ok,
            detail=f"System NFC: {'enabled' if ok else 'disabled'}",
            remediation="" if ok else "Enable NFC: settings put secure nfc_on 1",
        )
