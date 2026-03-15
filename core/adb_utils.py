"""
Titan V11.3 — Shared ADB Utilities
Canonical ADB helper functions used across all core modules.
Eliminates duplication of _adb(), _adb_shell(), _adb_push(), _ensure_adb_root().
"""

import logging
import subprocess
import time
from typing import Tuple

logger = logging.getLogger("titan.adb")


def adb(target: str, cmd: str, timeout: int = 15) -> Tuple[bool, str]:
    """Run an ADB command and return (success, stdout)."""
    try:
        r = subprocess.run(
            f"adb -s {target} {cmd}",
            shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def adb_raw(target: str, cmd: str, timeout: int = 15) -> Tuple[bool, bytes]:
    """Run an ADB command and return (success, raw_bytes)."""
    try:
        r = subprocess.run(
            f"adb -s {target} {cmd}",
            shell=True, capture_output=True, timeout=timeout,
        )
        return r.returncode == 0, r.stdout
    except Exception as e:
        return False, b""


def adb_shell(target: str, cmd: str, timeout: int = 15) -> str:
    """Run an ADB shell command and return stdout (empty string on failure)."""
    ok, out = adb(target, f'shell "{cmd}"', timeout=timeout)
    return out if ok else ""


def adb_push(target: str, local: str, remote: str, timeout: int = 30) -> bool:
    """Push a local file to the device. Returns True on success."""
    ok, _ = adb(target, f"push {local} '{remote}'", timeout=timeout)
    return ok


def ensure_adb_root(target: str) -> bool:
    """Ensure ADB is running as root. Returns True if root is active."""
    ok, out = adb(target, "root", timeout=10)
    if ok or "already running as root" in out.lower():
        time.sleep(1)
        return True
    return False
