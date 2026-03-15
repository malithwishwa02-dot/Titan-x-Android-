"""
Titan V11.3 — Shared FastAPI Dependencies
Provides DeviceManager and other singletons via Depends().
"""

from device_manager import DeviceManager

_dm: DeviceManager = None


def set_device_manager(device_manager: DeviceManager):
    """Called once at startup to set the singleton."""
    global _dm
    _dm = device_manager


def get_dm() -> DeviceManager:
    """FastAPI dependency: inject the DeviceManager singleton."""
    if _dm is None:
        raise RuntimeError("DeviceManager not initialized")
    return _dm
