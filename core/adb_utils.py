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


# ═══════════════════════════════════════════════════════════════════════
# ADB CONNECTION WATCHDOG
# ═══════════════════════════════════════════════════════════════════════

_connection_status: dict = {}


def is_device_connected(target: str) -> bool:
    """Check if device is currently connected and responsive."""
    try:
        result = subprocess.run(
            ["adb", "-s", target, "shell", "echo", "ok"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and "ok" in result.stdout
    except Exception:
        return False


def reconnect_device(target: str, max_retries: int = 3, retry_delay: float = 2.0) -> bool:
    """
    Attempt to reconnect to a disconnected device.
    
    Args:
        target: ADB target (e.g., "127.0.0.1:5555")
        max_retries: Maximum reconnection attempts
        retry_delay: Delay between retries in seconds
        
    Returns:
        True if reconnection successful, False otherwise
    """
    logger.info(f"Attempting to reconnect to {target}")
    
    for attempt in range(max_retries):
        try:
            # Disconnect first (clean state)
            subprocess.run(
                ["adb", "disconnect", target],
                capture_output=True, timeout=5
            )
            time.sleep(0.5)
            
            # Reconnect
            result = subprocess.run(
                ["adb", "connect", target],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0 and "connected" in result.stdout.lower():
                # Verify connection
                time.sleep(1)
                if is_device_connected(target):
                    logger.info(f"Reconnected to {target} on attempt {attempt + 1}")
                    _connection_status[target] = {"connected": True, "last_check": time.time()}
                    return True
            
            logger.warning(f"Reconnect attempt {attempt + 1} failed: {result.stdout}")
            time.sleep(retry_delay)
            
        except Exception as e:
            logger.error(f"Reconnect attempt {attempt + 1} error: {e}")
            time.sleep(retry_delay)
    
    _connection_status[target] = {"connected": False, "last_check": time.time()}
    return False


def adb_with_retry(target: str, cmd: str, timeout: int = 15, 
                   max_retries: int = 2) -> Tuple[bool, str]:
    """
    Run ADB command with automatic reconnection on failure.
    
    If the command fails due to connection issues, attempts to reconnect
    and retry the command.
    """
    # First attempt
    ok, out = adb(target, cmd, timeout)
    if ok:
        return True, out
    
    # Check if it's a connection issue
    connection_errors = ["device offline", "no devices", "connection refused", 
                        "device not found", "error: closed"]
    is_connection_error = any(err in out.lower() for err in connection_errors)
    
    if not is_connection_error:
        return False, out  # Not a connection issue, don't retry
    
    logger.warning(f"ADB connection issue detected: {out}")
    
    # Attempt reconnection
    if reconnect_device(target, max_retries=max_retries):
        # Retry command after reconnection
        logger.info(f"Retrying command after reconnection: {cmd[:50]}...")
        return adb(target, cmd, timeout)
    
    return False, "reconnection_failed"


def adb_shell_with_retry(target: str, cmd: str, timeout: int = 15) -> str:
    """Run ADB shell command with automatic reconnection."""
    ok, out = adb_with_retry(target, f'shell "{cmd}"', timeout=timeout)
    return out if ok else ""


def start_connection_watchdog(targets: list, check_interval: int = 30):
    """
    Start background thread that monitors ADB connections.
    
    Args:
        targets: List of ADB targets to monitor
        check_interval: Seconds between connection checks
    """
    import threading
    
    def watchdog_loop():
        while True:
            for target in targets:
                if not is_device_connected(target):
                    logger.warning(f"Device {target} disconnected, attempting reconnect...")
                    reconnect_device(target)
                else:
                    _connection_status[target] = {"connected": True, "last_check": time.time()}
            time.sleep(check_interval)
    
    thread = threading.Thread(target=watchdog_loop, daemon=True, name="adb-watchdog")
    thread.start()
    logger.info(f"ADB connection watchdog started for {len(targets)} targets")
    return thread


def get_connection_status() -> dict:
    """Get current connection status for all monitored devices."""
    return dict(_connection_status)
