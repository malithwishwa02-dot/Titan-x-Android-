"""
Titan V11.3 — Device Manager
Creates, destroys, patches, and manages Redroid Android containers.
Each device gets: unique ADB port, data volume, identity preset, anomaly patching.

Usage:
    mgr = DeviceManager()
    dev = await mgr.create_device(CreateDeviceRequest(
        model="samsung_s25_ultra", country="US", carrier="tmobile_us"
    ))
    await mgr.patch_device(dev.id)
    await mgr.destroy_device(dev.id)
"""

import asyncio
import json
import logging
import os
import secrets
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.device-manager")

TITAN_DATA = Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))
DEVICES_DIR = TITAN_DATA / "devices"
REDROID_IMAGE = os.environ.get("REDROID_IMAGE", "redroid/redroid:14.0.0-latest")
BASE_ADB_PORT = 5555
MAX_DEVICES = 8
CONTAINER_PREFIX = "titan-dev-"


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CreateDeviceRequest:
    model: str = "samsung_s25_ultra"
    country: str = "US"
    carrier: str = "tmobile_us"
    phone_number: str = ""
    android_version: str = "14"
    screen_width: int = 1080
    screen_height: int = 2400
    dpi: int = 420


@dataclass
class DeviceInstance:
    id: str = ""
    container: str = ""
    adb_port: int = 5555
    adb_target: str = "127.0.0.1:5555"
    config: Dict[str, Any] = field(default_factory=dict)
    state: str = "created"
    created_at: str = ""
    error: str = ""
    patch_result: Dict[str, Any] = field(default_factory=dict)
    installed_apps: List[str] = field(default_factory=list)
    stealth_score: int = 0
    device_type: str = "redroid"       # "redroid" | "vmos_cloud" | "emulator"
    vmos_pad_code: str = ""            # VMOS Cloud instance code (e.g. "ACP250331GLMP7YX")

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════
# SHELL HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _run(cmd: str, timeout: int = 60) -> Dict[str, Any]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"ok": r.returncode == 0, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e)}


def _adb(target: str, cmd: str, timeout: int = 15) -> Dict[str, Any]:
    return _run(f"adb -s {target} {cmd}", timeout=timeout)


def _adb_shell(target: str, cmd: str, timeout: int = 15) -> str:
    r = _adb(target, f'shell "{cmd}"', timeout=timeout)
    return r.get("stdout", "")


# ═══════════════════════════════════════════════════════════════════════
# DEVICE MANAGER
# ═══════════════════════════════════════════════════════════════════════

class DeviceManager:
    """Manages multiple Redroid device containers."""

    def __init__(self):
        DEVICES_DIR.mkdir(parents=True, exist_ok=True)
        self._devices: Dict[str, DeviceInstance] = {}
        self._load_state()

    # ─── STATE PERSISTENCE ────────────────────────────────────────────

    def _state_file(self) -> Path:
        return DEVICES_DIR / "devices.json"

    def _load_state(self):
        sf = self._state_file()
        if sf.exists():
            try:
                data = json.loads(sf.read_text())
                for d in data:
                    dev = DeviceInstance(**d)
                    self._devices[dev.id] = dev
                logger.info(f"Loaded {len(self._devices)} devices from state")
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")

    def _save_state(self):
        sf = self._state_file()
        data = [d.to_dict() for d in self._devices.values()]
        sf.write_text(json.dumps(data, indent=2))

    # ─── DEVICE CRUD ──────────────────────────────────────────────────

    def list_devices(self) -> List[DeviceInstance]:
        return list(self._devices.values())

    def get_device(self, device_id: str) -> Optional[DeviceInstance]:
        return self._devices.get(device_id)

    def _next_port(self) -> int:
        used = {d.adb_port for d in self._devices.values()}
        for port in range(BASE_ADB_PORT, BASE_ADB_PORT + MAX_DEVICES + 5):
            if port not in used:
                return port
        raise RuntimeError("No available ADB ports")

    async def create_device(self, req: CreateDeviceRequest) -> DeviceInstance:
        if len(self._devices) >= MAX_DEVICES:
            raise RuntimeError(f"Max {MAX_DEVICES} devices reached")

        dev_id = f"dev-{secrets.token_hex(3)}"
        port = self._next_port()
        container = f"{CONTAINER_PREFIX}{dev_id}"
        data_dir = DEVICES_DIR / dev_id / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        dev = DeviceInstance(
            id=dev_id,
            container=container,
            adb_port=port,
            adb_target=f"127.0.0.1:{port}",
            config=asdict(req) if hasattr(req, '__dataclass_fields__') else req.__dict__,
            state="creating",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._devices[dev_id] = dev
        self._save_state()

        # Resolve device preset for Docker identity props
        from device_presets import DEVICE_PRESETS
        preset = DEVICE_PRESETS.get(req.model)

        # Build Docker launch command with full device identity baked in
        identity_args = ""
        if preset:
            identity_args = (
                f"ro.product.brand={preset.brand} "
                f"ro.product.manufacturer={preset.manufacturer} "
                f"ro.product.model={preset.model} "
                f"ro.product.device={preset.device} "
                f"ro.product.name={preset.product} "
                f"ro.build.fingerprint={preset.fingerprint} "
                f"ro.build.display.id={preset.build_id} "
                f"ro.build.version.release={preset.android_version} "
                f"ro.build.version.sdk={preset.sdk_version} "
                f"ro.build.version.security_patch={preset.security_patch} "
                f"ro.build.type={preset.build_type} "
                f"ro.build.tags={preset.build_tags} "
                f"ro.hardware={preset.hardware} "
                f"ro.board.platform={preset.board} "
                f"ro.bootloader={preset.bootloader} "
                f"ro.baseband={preset.baseband} "
                f"ro.sf.lcd_density={preset.lcd_density} "
                f"ro.boot.verifiedbootstate=green "
                f"ro.boot.vbmeta.device_state=locked "
                f"ro.boot.flash.locked=1 "
                f"ro.build.selinux=1 "
                f"ro.allow.mock.location=0 "
                f"ro.kernel.qemu=0 "
                f"ro.hardware.virtual=0 "
                f"ro.boot.qemu=0 "
            )

        docker_cmd = (
            f"docker run -d --privileged "
            f"--name {container} "
            f"-v {data_dir}:/data "
            f"-v /dev/binderfs:/dev/binderfs "
            f"-p 127.0.0.1:{port}:5555 "
            f"--memory=3g --cpus=2 "
            f"{REDROID_IMAGE} "
            f"androidboot.redroid_width={req.screen_width} "
            f"androidboot.redroid_height={req.screen_height} "
            f"androidboot.redroid_dpi={req.dpi} "
            f"androidboot.redroid_fps=60 "
            f"androidboot.redroid_gpu_mode=guest "
            f"androidboot.redroid_net_ndns=2 "
            f"androidboot.redroid_net_dns1=8.8.8.8 "
            f"androidboot.redroid_net_dns2=8.8.4.4 "
            f"{identity_args}"
        )

        logger.info(f"Creating device {dev_id} on port {port}")
        result = _run(docker_cmd, timeout=120)

        if not result["ok"]:
            dev.state = "error"
            dev.error = result["stderr"]
            self._save_state()
            raise RuntimeError(f"Docker create failed: {result['stderr']}")

        dev.state = "booting"
        self._save_state()

        # Inject host ADB key into container for authorization
        await asyncio.sleep(3)  # Let container init start
        adb_key_path = Path.home() / ".android" / "adbkey.pub"
        if adb_key_path.exists():
            key_data = adb_key_path.read_text().strip()
            _run(f"docker exec {container} mkdir -p /data/misc/adb", timeout=10)
            _run(f"docker exec {container} sh -c 'echo \"{key_data}\" > /data/misc/adb/adb_keys'", timeout=10)
            _run(f"docker exec {container} chmod 640 /data/misc/adb/adb_keys", timeout=10)
            logger.info(f"Injected ADB key into {container}")

        # Disconnect phantom emulator devices
        _run("adb disconnect emulator-5554 2>/dev/null", timeout=5)
        _run("adb disconnect emulator-5556 2>/dev/null", timeout=5)

        # Wait for ADB
        await self._wait_for_adb(dev)

        dev.state = "ready"
        self._save_state()
        logger.info(f"Device {dev_id} ready on {dev.adb_target}")
        return dev

    async def _wait_for_adb(self, dev: DeviceInstance, timeout: int = 90):
        """Poll until ADB connects and device boots."""
        target = dev.adb_target
        start = time.time()

        # Connect ADB
        while time.time() - start < timeout:
            r = _adb(target, "connect " + target)
            if "connected" in r.get("stdout", "").lower() or "already" in r.get("stdout", "").lower():
                break
            await asyncio.sleep(2)

        # Wait for boot_completed
        while time.time() - start < timeout:
            val = _adb_shell(target, "getprop sys.boot_completed")
            if val.strip() == "1":
                return
            await asyncio.sleep(3)

        dev.state = "error"
        dev.error = "ADB boot timeout"
        self._save_state()

    async def destroy_device(self, device_id: str) -> bool:
        dev = self._devices.get(device_id)
        if not dev:
            return False

        logger.info(f"Destroying device {device_id}")

        # Stop and remove container
        _run(f"docker rm -f {dev.container}", timeout=30)

        # Remove data volume
        data_dir = DEVICES_DIR / device_id
        if data_dir.exists():
            shutil.rmtree(data_dir, ignore_errors=True)

        del self._devices[device_id]
        self._save_state()
        return True

    async def restart_device(self, device_id: str) -> bool:
        dev = self._devices.get(device_id)
        if not dev:
            return False

        _run(f"docker restart {dev.container}", timeout=60)
        dev.state = "booting"
        self._save_state()

        await self._wait_for_adb(dev)
        dev.state = "ready"
        self._save_state()
        return True

    def get_device_info(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get live device info via ADB."""
        dev = self._devices.get(device_id)
        if not dev or dev.state != "ready":
            return None

        t = dev.adb_target
        return {
            "id": dev.id,
            "model": _adb_shell(t, "getprop ro.product.model"),
            "brand": _adb_shell(t, "getprop ro.product.brand"),
            "android": _adb_shell(t, "getprop ro.build.version.release"),
            "sdk": _adb_shell(t, "getprop ro.build.version.sdk"),
            "fingerprint": _adb_shell(t, "getprop ro.build.fingerprint"),
            "serial": _adb_shell(t, "getprop ro.serialno"),
            "imei": _adb_shell(t, "service call iphonesubinfo 1 | grep -oP \"[0-9a-f]{8}\" | head -4"),
            "carrier": _adb_shell(t, "getprop gsm.sim.operator.alpha"),
            "sim_state": _adb_shell(t, "getprop gsm.sim.state"),
            "battery": _adb_shell(t, "dumpsys battery | grep level"),
            "boot_completed": _adb_shell(t, "getprop sys.boot_completed"),
            "uptime": _adb_shell(t, "uptime"),
        }

    async def screenshot(self, device_id: str) -> Optional[bytes]:
        """Capture device screenshot as JPEG bytes."""
        dev = self._devices.get(device_id)
        if not dev or dev.state != "ready":
            return None

        try:
            # Use raw binary mode — text mode corrupts PNG data
            proc = subprocess.run(
                ["adb", "-s", dev.adb_target, "exec-out", "screencap", "-p"],
                capture_output=True, timeout=10,
            )
            if proc.returncode != 0 or len(proc.stdout) < 100:
                return None

            png_bytes = proc.stdout

            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(png_bytes))
                img = img.convert("RGB")
                w, h = img.size
                img = img.resize((w // 2, h // 2))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70)
                return buf.getvalue()
            except Exception:
                # If PIL fails, return raw PNG
                return png_bytes
        except Exception:
            return None
