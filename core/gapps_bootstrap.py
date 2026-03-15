"""
Titan V11.3 — GApps Bootstrap for Vanilla AOSP Cuttlefish
==========================================================
Installs GMS, Play Store, Chrome, Google Pay onto vanilla AOSP.
MUST run BEFORE the aging pipeline.

Usage:
    bootstrap = GAppsBootstrap(adb_target="127.0.0.1:6520")
    result = bootstrap.run()
"""

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("titan.gapps-bootstrap")

GAPPS_DIR = Path(os.environ.get("TITAN_GAPPS_DIR", "/opt/titan/data/gapps"))

# Install order matters: GSF → GMS → Play Store → apps
ESSENTIAL_APKS = [
    {"pkg": "com.google.android.gsf", "name": "Google Services Framework",
     "required": True, "priority": 1,
     "globs": ["GoogleServicesFramework*.apk", "gsf*.apk", "GSF*.apk"]},
    {"pkg": "com.google.android.gms", "name": "Google Play Services",
     "required": True, "priority": 2,
     "globs": ["GmsCore*.apk", "GooglePlayServices*.apk", "gms*.apk",
               "com.google.android.gms*.apk", "PlayServices*.apk"]},
    {"pkg": "com.android.vending", "name": "Google Play Store",
     "required": True, "priority": 3,
     "globs": ["Phonesky*.apk", "PlayStore*.apk", "vending*.apk",
               "com.android.vending*.apk", "GooglePlayStore*.apk"]},
    {"pkg": "com.android.chrome", "name": "Google Chrome",
     "required": True, "priority": 4,
     "globs": ["Chrome*.apk", "chrome*.apk", "com.android.chrome*.apk"],
     "alt_pkg": "com.kiwibrowser.browser",
     "alt_globs": ["Chrome_standalone*.apk", "Kiwi*.apk", "kiwi*.apk"]},
    {"pkg": "com.google.android.apps.walletnfcrel", "name": "Google Pay / Wallet",
     "required": True, "priority": 5,
     "globs": ["GooglePay*.apk", "Wallet*.apk", "GPay*.apk",
               "com.google.android.apps.walletnfcrel*.apk"]},
    {"pkg": "com.google.android.youtube", "name": "YouTube",
     "required": False, "priority": 6,
     "globs": ["YouTube*.apk", "youtube*.apk"]},
    {"pkg": "com.google.android.gm", "name": "Gmail",
     "required": False, "priority": 7,
     "globs": ["Gmail*.apk", "gmail*.apk"]},
    {"pkg": "com.google.android.apps.maps", "name": "Google Maps",
     "required": False, "priority": 8,
     "globs": ["Maps*.apk", "GoogleMaps*.apk"]},
    {"pkg": "com.google.android.apps.photos", "name": "Google Photos",
     "required": False, "priority": 9,
     "globs": ["Photos*.apk", "GooglePhotos*.apk"]},
]


@dataclass
class BootstrapResult:
    success: bool = False
    installed: List[str] = field(default_factory=list)
    already_installed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    missing_apks: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    total_packages_before: int = 0
    total_packages_after: int = 0
    gms_ready: bool = False
    play_store_ready: bool = False
    chrome_ready: bool = False
    wallet_ready: bool = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class GAppsBootstrap:
    """Installs GApps on a vanilla AOSP Cuttlefish device."""

    def __init__(self, adb_target: str = "127.0.0.1:6520", gapps_dir: str = ""):
        self.target = adb_target
        self.gapps_dir = Path(gapps_dir) if gapps_dir else GAPPS_DIR
        self._adb_cmd(["root"], timeout=10)
        time.sleep(1)

    def _adb_cmd(self, args: List[str], timeout: int = 30) -> Tuple[bool, str]:
        cmd = ["adb", "-s", self.target] + args
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0, r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as e:
            return False, str(e)

    def _shell(self, cmd: str, timeout: int = 15) -> str:
        ok, out = self._adb_cmd(["shell", cmd], timeout=timeout)
        return out.strip()

    def _is_installed(self, pkg: str) -> bool:
        out = self._shell(f"pm list packages {pkg} 2>/dev/null")
        return f"package:{pkg}" in out

    def _get_installed_packages(self) -> List[str]:
        out = self._shell("pm list packages 2>/dev/null")
        return [l.replace("package:", "").strip()
                for l in out.split("\n") if l.startswith("package:")]

    def _find_apk(self, entry: Dict) -> Optional[Path]:
        if not self.gapps_dir.exists():
            return None
        for pattern in entry["globs"]:
            matches = list(self.gapps_dir.glob(pattern))
            if matches:
                return max(matches, key=lambda p: p.stat().st_size)
        exact = self.gapps_dir / f"{entry['pkg']}.apk"
        return exact if exact.exists() else None

    def _install_apk(self, apk_path: Path) -> Tuple[bool, str]:
        cmd = ["install", "-r", "-d", "-g", str(apk_path)]
        logger.info(f"  Installing {apk_path.name} ({apk_path.stat().st_size // 1024}KB)...")
        ok, out = self._adb_cmd(cmd, timeout=120)
        if not ok and "INSTALL_FAILED_MISSING_SPLIT" in out:
            # Try XAPK bundle (zip with split APKs inside)
            return self._install_xapk(apk_path)
        if not ok and "INSTALL_FAILED_MISSING_SHARED_LIBRARY" in out:
            # Chrome needs TrichromeLibrary — skip, use alt browser
            logger.warning(f"  {apk_path.name} needs shared library — trying alt")
        return ok, out

    def _install_xapk(self, xapk_path: Path) -> Tuple[bool, str]:
        """Extract XAPK bundle and install via install-multiple."""
        import tempfile, zipfile
        xapk_file = xapk_path.with_suffix(".xapk")
        if not xapk_file.exists():
            # The .apk might itself be an XAPK — check for embedded APKs
            try:
                with zipfile.ZipFile(xapk_path) as zf:
                    apk_names = [n for n in zf.namelist() if n.endswith(".apk")]
                    if not apk_names:
                        return False, "Not an XAPK bundle"
                    xapk_file = xapk_path  # It IS an XAPK
            except zipfile.BadZipFile:
                return False, "Not a valid zip/XAPK"
        else:
            try:
                with zipfile.ZipFile(xapk_file) as zf:
                    apk_names = [n for n in zf.namelist() if n.endswith(".apk")]
            except zipfile.BadZipFile:
                return False, "Bad XAPK file"

        with tempfile.TemporaryDirectory() as tmpdir:
            logger.info(f"  Extracting XAPK: {len(apk_names)} splits")
            with zipfile.ZipFile(xapk_file) as zf:
                for name in apk_names:
                    zf.extract(name, tmpdir)
            splits = [str(Path(tmpdir) / n) for n in apk_names]
            cmd = ["install-multiple", "-r", "-d", "-g"] + splits
            return self._adb_cmd(cmd, timeout=180)

    def check_status(self) -> Dict:
        """Check current GApps status without making changes."""
        pkgs = self._get_installed_packages()
        gms = self._is_installed("com.google.android.gms")
        ps = self._is_installed("com.android.vending")
        ch = self._is_installed("com.android.chrome") or self._is_installed("com.kiwibrowser.browser")
        wl = self._is_installed("com.google.android.apps.walletnfcrel")
        return {
            "gms_installed": gms, "play_store_installed": ps,
            "chrome_installed": ch, "wallet_installed": wl,
            "youtube_installed": self._is_installed("com.google.android.youtube"),
            "gmail_installed": self._is_installed("com.google.android.gm"),
            "total_packages": len(pkgs),
            "total_google_packages": sum(1 for p in pkgs if "google" in p or p == "com.android.vending"),
            "needs_bootstrap": not (gms and ps and ch and wl),
            "apk_dir": str(self.gapps_dir),
            "apks_available": len(list(self.gapps_dir.glob("*.apk"))) if self.gapps_dir.exists() else 0,
        }

    def run(self, skip_optional: bool = False) -> BootstrapResult:
        """Run the full GApps bootstrap."""
        result = BootstrapResult()
        logger.info("=" * 60)
        logger.info("GApps Bootstrap — Installing Google services on Cuttlefish")
        logger.info("=" * 60)

        result.total_packages_before = len(self._get_installed_packages())
        logger.info(f"Packages before: {result.total_packages_before}")

        self.gapps_dir.mkdir(parents=True, exist_ok=True)
        available = list(self.gapps_dir.glob("*.apk"))
        logger.info(f"APKs in {self.gapps_dir}: {len(available)}")
        for apk in sorted(available):
            logger.info(f"  {apk.name} ({apk.stat().st_size // 1024}KB)")

        entries = [e for e in ESSENTIAL_APKS if not skip_optional or e["required"]]
        for entry in sorted(entries, key=lambda e: e["priority"]):
            pkg, name = entry["pkg"], entry["name"]

            if self._is_installed(pkg):
                logger.info(f"  SKIP {name} ({pkg}) — already installed")
                result.already_installed.append(pkg)
                continue

            apk_path = self._find_apk(entry)
            # If primary APK not found or fails, try alternative package
            alt_pkg = entry.get("alt_pkg")
            if not apk_path and alt_pkg and self._is_installed(alt_pkg):
                logger.info(f"  SKIP {name} — alt {alt_pkg} already installed")
                result.already_installed.append(alt_pkg)
                continue
            if not apk_path and alt_pkg:
                # Try finding alt APK
                alt_entry = {"globs": entry.get("alt_globs", []), "pkg": alt_pkg}
                apk_path = self._find_apk(alt_entry)
            if not apk_path:
                msg = f"{name} ({pkg}) — APK not found"
                if entry["required"]:
                    logger.error(f"  MISSING {msg}")
                    result.missing_apks.append(pkg)
                else:
                    logger.info(f"  SKIP {msg} (optional)")
                continue

            ok, out = self._install_apk(apk_path)
            if ok and "Success" in out:
                logger.info(f"  OK {name} ({pkg})")
                result.installed.append(pkg)
            else:
                err = out.strip().split("\n")[-1] if out else "unknown"
                logger.error(f"  FAIL {name} ({pkg}) — {err}")
                result.failed.append(pkg)
                result.errors.append(f"{pkg}: {err}")
            time.sleep(1)

        # Post-install: grant GMS permissions
        if self._is_installed("com.google.android.gms"):
            for perm in ["ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION",
                         "READ_PHONE_STATE", "GET_ACCOUNTS", "READ_CONTACTS",
                         "WRITE_CONTACTS", "READ_EXTERNAL_STORAGE",
                         "WRITE_EXTERNAL_STORAGE", "RECEIVE_SMS"]:
                self._shell(f"pm grant com.google.android.gms android.permission.{perm} 2>/dev/null")

        # Post-install: disable GMS setup wizard nag
        self._shell("settings put secure user_setup_complete 1")
        self._shell("settings put global device_provisioned 1")
        self._shell("am broadcast -a com.google.android.checkin.CHECKIN_COMPLETE 2>/dev/null")

        # Verify
        result.total_packages_after = len(self._get_installed_packages())
        result.gms_ready = self._is_installed("com.google.android.gms")
        result.play_store_ready = self._is_installed("com.android.vending")
        result.chrome_ready = self._is_installed("com.android.chrome")
        result.wallet_ready = self._is_installed("com.google.android.apps.walletnfcrel")
        result.success = result.gms_ready and result.play_store_ready and not result.missing_apks

        logger.info("=" * 60)
        logger.info(f"Bootstrap complete: {len(result.installed)} installed, "
                     f"{len(result.already_installed)} skipped, "
                     f"{len(result.failed)} failed, "
                     f"{len(result.missing_apks)} missing")
        logger.info(f"  GMS={result.gms_ready} PlayStore={result.play_store_ready} "
                     f"Chrome={result.chrome_ready} Wallet={result.wallet_ready}")
        logger.info("=" * 60)
        return result
