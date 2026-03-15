"""
Titan V11.3 — Admin Router (Cuttlefish-aware)
/api/admin/* — Services, health, CPU monitoring, CVD management, kernel modules
"""

import os
import subprocess
import time

from fastapi import APIRouter

from device_manager import DeviceManager, CVD_BIN_DIR, CVD_HOME_BASE, CVD_IMAGES_DIR, MAX_DEVICES
from middleware.cpu_governor import cpu_governor

router = APIRouter(prefix="/api/admin", tags=["admin"])

dm: DeviceManager = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


@router.get("/services")
async def admin_services():
    """Get status of all system services including Cuttlefish-related ones."""
    services = ["titan-api", "ws-scrcpy", "nginx", "cvd-stream", "cftunnel",
                 "titan-gpu-tunnel", "titan-oracle-tunnel"]
    result = {}
    for svc in services:
        try:
            r = subprocess.run(["systemctl", "is-active", svc],
                               capture_output=True, text=True, timeout=5)
            result[svc] = r.stdout.strip()
        except Exception:
            result[svc] = "unknown"
    return {"services": result}


@router.get("/health")
async def admin_health():
    devices = dm.list_devices()
    cvd_devices = [d for d in devices if d.device_type == "cuttlefish"]
    return {
        "status": "ok",
        "devices": len(devices),
        "devices_ready": sum(1 for d in devices if d.state in ("ready", "patched")),
        "cvd_count": len(cvd_devices),
        "cvd_ready": sum(1 for d in cvd_devices if d.state in ("ready", "patched")),
        "uptime": time.time(),
        "cpu": cpu_governor.get_status(),
    }


@router.get("/cpu")
async def admin_cpu():
    """Get detailed CPU monitoring data."""
    return cpu_governor.get_status()


@router.get("/cvd-status")
async def admin_cvd_status():
    """Get Cuttlefish environment status and paths."""
    devices = dm.list_devices()
    cvd_devices = [d for d in devices if d.device_type == "cuttlefish"]

    # Check if launch_cvd binary exists
    launch_cvd = CVD_BIN_DIR / "launch_cvd"
    bin_exists = launch_cvd.exists()

    # Check images
    images_exist = CVD_IMAGES_DIR.exists() and (CVD_IMAGES_DIR / "system.img").exists()

    return {
        "bin_dir": str(CVD_BIN_DIR),
        "home_base": str(CVD_HOME_BASE),
        "images_dir": str(CVD_IMAGES_DIR),
        "max_devices": MAX_DEVICES,
        "launch_cvd_exists": bin_exists,
        "images_exist": images_exist,
        "active_cvds": len(cvd_devices),
        "cvd_instances": [
            {
                "id": d.id,
                "instance_num": d.instance_num,
                "adb_target": d.adb_target,
                "vnc_port": d.vnc_port,
                "state": d.state,
                "cvd_home": d.cvd_home,
            }
            for d in cvd_devices
        ],
    }


@router.get("/kernel-modules")
async def admin_kernel_modules():
    """Check status of kernel modules required for Cuttlefish KVM."""
    required = ["kvm", "vhost_vsock", "vhost_net"]
    optional = ["binder_linux", "ashmem_linux", "v4l2loopback"]
    all_modules = required + optional

    modules = []
    for mod in all_modules:
        try:
            r = subprocess.run(
                f"lsmod | grep -q '^{mod}'",
                shell=True, capture_output=True, timeout=5,
            )
            loaded = r.returncode == 0
        except Exception:
            loaded = False
        modules.append({
            "name": mod,
            "loaded": loaded,
            "required": mod in required,
        })

    return {"modules": modules}
