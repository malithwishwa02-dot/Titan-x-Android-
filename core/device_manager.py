"""
Titan V11.3 — Device Manager (Cuttlefish KVM Backend)
Creates, destroys, patches, and manages Cuttlefish Android virtual machines.
Each device gets: unique ADB port, KVM instance, identity preset, anomaly patching.

Cuttlefish uses launch_cvd / stop_cvd binaries to manage full Android VMs
running under KVM with near-native performance.

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
CVD_HOME_BASE = Path(os.environ.get("CVD_HOME_BASE", "/opt/titan/cuttlefish"))
CVD_BIN_DIR = Path(os.environ.get("CVD_BIN_DIR", "/opt/android-cuttlefish/bin"))
CVD_IMAGES_DIR = Path(os.environ.get("CVD_IMAGES_DIR", "/opt/titan/cuttlefish/images"))
BASE_ADB_PORT = 6520
BASE_VNC_PORT = 6444
MAX_DEVICES = 8
INSTANCE_PREFIX = "titan-cvd-"


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
    memory_mb: int = 4096
    cpus: int = 4
    numa_node: int = -1          # -1 = auto-detect, 0+ = pin to specific NUMA node
    cpu_governor: str = "schedutil"  # schedutil|performance|powersave
    gpu_mode: str = "guest_swiftshader"  # guest_swiftshader|drm_virgl|gfxstream


@dataclass
class DeviceInstance:
    id: str = ""
    container: str = ""               # legacy compat — maps to instance name
    adb_port: int = 6520
    adb_target: str = "127.0.0.1:6520"
    config: Dict[str, Any] = field(default_factory=dict)
    state: str = "created"
    created_at: str = ""
    error: str = ""
    patch_result: Dict[str, Any] = field(default_factory=dict)
    installed_apps: List[str] = field(default_factory=list)
    stealth_score: int = 0
    device_type: str = "cuttlefish"    # "cuttlefish" (KVM-based Android VM)
    instance_num: int = 1              # Cuttlefish --base_instance_num
    cvd_home: str = ""                 # Cuttlefish HOME directory for this instance
    vnc_port: int = 6444               # VNC display port

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════
# SHELL HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _run(cmd: str, timeout: int = 60, env: Dict[str, str] = None) -> Dict[str, Any]:
    try:
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, env=run_env)
        return {"ok": r.returncode == 0, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e)}


def _adb(target: str, cmd: str, timeout: int = 15) -> Dict[str, Any]:
    return _run(f"adb -s {target} {cmd}", timeout=timeout)


def _adb_shell(target: str, cmd: str, timeout: int = 15) -> str:
    from adb_utils import adb_shell
    return adb_shell(target, cmd, timeout=timeout)


# ═══════════════════════════════════════════════════════════════════════
# DEVICE MANAGER
# ═══════════════════════════════════════════════════════════════════════

class DeviceManager:
    """Manages multiple Cuttlefish Android virtual machines via launch_cvd/stop_cvd."""

    # Required kernel modules for Cuttlefish KVM operation
    REQUIRED_MODULES = ["kvm", "vhost_vsock", "vhost_net"]
    OPTIONAL_MODULES = ["binder_linux", "ashmem_linux", "v4l2loopback"]

    def __init__(self):
        DEVICES_DIR.mkdir(parents=True, exist_ok=True)
        CVD_HOME_BASE.mkdir(parents=True, exist_ok=True)
        self._devices: Dict[str, DeviceInstance] = {}
        self._numa_topology: Optional[Dict] = None
        self._load_state()

    # ─── NUMA / CPU AFFINITY ──────────────────────────────────────────

    def _detect_numa_topology(self) -> Dict[str, Any]:
        """Detect NUMA topology for CPU pinning optimization.

        On multi-socket servers (e.g., AMD EPYC), pinning Cuttlefish VMs
        to a specific NUMA node prevents cross-socket memory access latency
        and reduces performance jitter that can be detected by timing-based
        RASP analysis.
        """
        if self._numa_topology:
            return self._numa_topology

        topology = {"nodes": [], "total_cpus": 0, "numa_available": False}

        r = _run("lscpu --parse=CPU,NODE 2>/dev/null | grep -v '^#'", timeout=5)
        if r["ok"] and r["stdout"]:
            nodes: Dict[int, List[int]] = {}
            for line in r["stdout"].strip().split("\n"):
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    try:
                        cpu_id, node_id = int(parts[0]), int(parts[1])
                        nodes.setdefault(node_id, []).append(cpu_id)
                    except ValueError:
                        continue

            for node_id in sorted(nodes.keys()):
                topology["nodes"].append({
                    "id": node_id,
                    "cpus": sorted(nodes[node_id]),
                    "cpu_count": len(nodes[node_id]),
                })
            topology["total_cpus"] = sum(len(n) for n in nodes.values())
            topology["numa_available"] = len(nodes) > 1

        self._numa_topology = topology
        return topology

    def _select_numa_cpus(self, req: CreateDeviceRequest) -> Optional[str]:
        """Select CPUs for NUMA-aware pinning. Returns taskset CPU list or None."""
        topo = self._detect_numa_topology()
        if not topo["numa_available"]:
            return None

        node_id = req.numa_node
        if node_id == -1:
            # Auto-select: pick the NUMA node with the most free CPUs
            # (approximation: pick node with most CPUs)
            best = max(topo["nodes"], key=lambda n: n["cpu_count"])
            node_id = best["id"]

        # Find the requested NUMA node
        target_node = None
        for node in topo["nodes"]:
            if node["id"] == node_id:
                target_node = node
                break

        if not target_node or len(target_node["cpus"]) < req.cpus:
            logger.warning(f"NUMA node {node_id} has insufficient CPUs "
                           f"({len(target_node['cpus'] if target_node else [])} < {req.cpus})")
            return None

        # Select the first N CPUs from this node
        selected = target_node["cpus"][:req.cpus]
        cpu_list = ",".join(str(c) for c in selected)
        logger.info(f"NUMA pinning: node={node_id}, cpus={cpu_list}")
        return cpu_list

    def _ensure_kernel_modules(self):
        """Verify and load required kernel modules for Cuttlefish."""
        for mod in self.REQUIRED_MODULES:
            r = _run(f"lsmod | grep -q '^{mod}' || modprobe {mod} 2>/dev/null", timeout=10)
            if not r["ok"]:
                logger.warning(f"Kernel module '{mod}' not available — Cuttlefish may fail")

        for mod in self.OPTIONAL_MODULES:
            _run(f"lsmod | grep -q '^{mod}' || modprobe {mod} 2>/dev/null", timeout=5)

    def _set_cpu_governor(self, governor: str = "schedutil"):
        """Set CPU frequency governor for consistent VM performance."""
        valid = {"schedutil", "performance", "powersave", "ondemand", "conservative"}
        if governor not in valid:
            governor = "schedutil"
        _run(f"for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; "
             f"do echo {governor} > $f 2>/dev/null; done", timeout=5)

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

    def _next_instance_num(self) -> int:
        used = {d.instance_num for d in self._devices.values()}
        for num in range(1, MAX_DEVICES + 5):
            if num not in used:
                return num
        raise RuntimeError("No available Cuttlefish instance numbers")

    def _instance_adb_port(self, instance_num: int) -> int:
        return BASE_ADB_PORT + instance_num - 1

    def _instance_vnc_port(self, instance_num: int) -> int:
        return BASE_VNC_PORT + instance_num - 1

    def _generate_cvd_config(self, req: CreateDeviceRequest,
                              preset=None) -> Dict[str, Any]:
        """Generate Cuttlefish JSON config for launch_cvd."""
        # Build extra_bootconfig_args with device identity props
        boot_props = [
            "androidboot.verifiedbootstate=green",
            "androidboot.vbmeta.device_state=locked",
            "sys.use_memfd=true",
        ]
        if preset:
            boot_props.extend([
                f"androidboot.hardware={preset.hardware}",
                f"ro.product.brand={preset.brand}",
                f"ro.product.manufacturer={preset.manufacturer}",
                f"ro.product.model={preset.model}",
                f"ro.product.device={preset.device}",
                f"ro.product.name={preset.product}",
                f"ro.build.fingerprint={preset.fingerprint}",
                f"ro.build.display.id={preset.build_id}",
                f"ro.build.version.release={preset.android_version}",
                f"ro.build.version.sdk={preset.sdk_version}",
                f"ro.build.version.security_patch={preset.security_patch}",
                f"ro.build.type={preset.build_type}",
                f"ro.build.tags={preset.build_tags}",
                f"ro.board.platform={preset.board}",
                f"ro.bootloader={preset.bootloader}",
                f"ro.baseband={preset.baseband}",
                f"ro.sf.lcd_density={preset.lcd_density}",
                f"ro.boot.flash.locked=1",
                f"ro.build.selinux=1",
                f"ro.allow.mock.location=0",
                f"ro.kernel.qemu=0",
                f"ro.hardware.virtual=0",
                f"ro.boot.qemu=0",
            ])

        config = {
            "instances": [{
                "vm": {
                    "memory_mb": req.memory_mb,
                    "cpus": req.cpus,
                },
                "graphics": {
                    "displays": [{
                        "width": req.screen_width,
                        "height": req.screen_height,
                        "dpi": req.dpi,
                    }]
                },
                "boot": {
                    "extra_bootconfig_args": " ".join(boot_props),
                },
            }]
        }
        return config

    async def create_device(self, req: CreateDeviceRequest) -> DeviceInstance:
        if len(self._devices) >= MAX_DEVICES:
            raise RuntimeError(f"Max {MAX_DEVICES} devices reached")

        # Pre-flight: ensure kernel modules and CPU governor
        self._ensure_kernel_modules()
        if req.cpu_governor != "schedutil":
            self._set_cpu_governor(req.cpu_governor)

        dev_id = f"dev-{secrets.token_hex(3)}"
        instance_num = self._next_instance_num()
        adb_port = self._instance_adb_port(instance_num)
        vnc_port = self._instance_vnc_port(instance_num)
        instance_name = f"{INSTANCE_PREFIX}{dev_id}"

        # Create per-instance home directory for Cuttlefish
        cvd_home = CVD_HOME_BASE / dev_id
        cvd_home.mkdir(parents=True, exist_ok=True)

        # Also create device data dir for Titan metadata
        data_dir = DEVICES_DIR / dev_id
        data_dir.mkdir(parents=True, exist_ok=True)

        dev = DeviceInstance(
            id=dev_id,
            container=instance_name,
            adb_port=adb_port,
            adb_target=f"127.0.0.1:{adb_port}",
            config=asdict(req) if hasattr(req, '__dataclass_fields__') else req.__dict__,
            state="creating",
            created_at=datetime.now(timezone.utc).isoformat(),
            device_type="cuttlefish",
            instance_num=instance_num,
            cvd_home=str(cvd_home),
            vnc_port=vnc_port,
        )
        self._devices[dev_id] = dev
        self._save_state()

        # Resolve device preset for identity props
        from device_presets import DEVICE_PRESETS
        preset = DEVICE_PRESETS.get(req.model)

        # Generate Cuttlefish JSON config with device identity baked in
        cvd_config = self._generate_cvd_config(req, preset)
        config_path = cvd_home / "cvd_config.json"
        config_path.write_text(json.dumps(cvd_config, indent=2))
        logger.info(f"Wrote CVD config: {config_path}")

        # Determine launch_cvd binary path
        launch_cvd = CVD_BIN_DIR / "launch_cvd"
        if not launch_cvd.exists():
            # Fallback: check if it's on PATH
            launch_cvd = Path(shutil.which("launch_cvd") or "launch_cvd")

        # Build launch_cvd command
        cvd_cmd = (
            f"{launch_cvd} "
            f"--config_file={config_path} "
            f"--base_instance_num={instance_num} "
            f"--daemon "
            f"--gpu_mode={req.gpu_mode} "
            f"--report_anonymous_usage_stats=n "
        )

        # Add image directory if configured
        if CVD_IMAGES_DIR.exists():
            system_img = CVD_IMAGES_DIR / "system.img"
            if system_img.exists():
                cvd_cmd += f"--system_image_dir={CVD_IMAGES_DIR} "

        # NUMA-aware CPU pinning: wrap launch_cvd with taskset if on multi-socket
        numa_cpus = self._select_numa_cpus(req)
        if numa_cpus:
            cvd_cmd = f"taskset -c {numa_cpus} {cvd_cmd}"
            logger.info(f"NUMA pinning active: CPUs {numa_cpus}")

        logger.info(f"Creating Cuttlefish device {dev_id} (instance {instance_num})")
        result = _run(cvd_cmd, timeout=180, env={"HOME": str(cvd_home)})

        if not result["ok"]:
            dev.state = "error"
            dev.error = result["stderr"]
            self._save_state()
            raise RuntimeError(f"launch_cvd failed: {result['stderr']}")

        dev.state = "booting"
        self._save_state()

        # Wait for ADB
        await self._wait_for_adb(dev)

        dev.state = "ready"
        self._save_state()
        logger.info(f"Device {dev_id} ready on {dev.adb_target} (CVD instance {instance_num})")
        return dev

    async def _wait_for_adb(self, dev: DeviceInstance, timeout: int = 120):
        """Poll until ADB connects and Cuttlefish VM boots."""
        target = dev.adb_target
        start = time.time()

        # Connect ADB — Cuttlefish exposes ADB on 0.0.0.0:<port>
        while time.time() - start < timeout:
            r = _adb(target, "connect " + target)
            stdout = r.get("stdout", "").lower()
            if "connected" in stdout or "already" in stdout:
                break
            await asyncio.sleep(3)

        # Wait for boot_completed
        while time.time() - start < timeout:
            val = _adb_shell(target, "getprop sys.boot_completed")
            if val.strip() == "1":
                return
            await asyncio.sleep(3)

        dev.state = "error"
        dev.error = "ADB boot timeout"
        self._save_state()
        raise RuntimeError(f"ADB boot timeout for device {dev.id} after {timeout}s")

    async def destroy_device(self, device_id: str) -> bool:
        dev = self._devices.get(device_id)
        if not dev:
            return False

        logger.info(f"Destroying device {device_id}")

        # Stop Cuttlefish VM
        stop_cvd = CVD_BIN_DIR / "stop_cvd"
        if not stop_cvd.exists():
            stop_cvd = Path(shutil.which("stop_cvd") or "stop_cvd")
        cvd_home = dev.cvd_home or str(CVD_HOME_BASE / device_id)
        _run(f"{stop_cvd} --base_instance_num={dev.instance_num}",
             timeout=30, env={"HOME": cvd_home})

        # Disconnect ADB
        _run(f"adb disconnect {dev.adb_target}", timeout=5)

        # Remove instance home directory
        cvd_path = Path(cvd_home)
        if cvd_path.exists():
            shutil.rmtree(cvd_path, ignore_errors=True)

        # Remove device data
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

        # Restart Cuttlefish: stop then re-launch with same config
        stop_cvd = CVD_BIN_DIR / "stop_cvd"
        if not stop_cvd.exists():
            stop_cvd = Path(shutil.which("stop_cvd") or "stop_cvd")
        cvd_home = dev.cvd_home or str(CVD_HOME_BASE / device_id)
        _run(f"{stop_cvd} --base_instance_num={dev.instance_num}",
             timeout=30, env={"HOME": cvd_home})

        await asyncio.sleep(2)

        # Re-launch with existing config
        config_path = Path(cvd_home) / "cvd_config.json"
        launch_cvd = CVD_BIN_DIR / "launch_cvd"
        if not launch_cvd.exists():
            launch_cvd = Path(shutil.which("launch_cvd") or "launch_cvd")

        cvd_cmd = (
            f"{launch_cvd} "
            f"--config_file={config_path} "
            f"--base_instance_num={dev.instance_num} "
            f"--daemon "
            f"--report_anonymous_usage_stats=n "
        )
        if CVD_IMAGES_DIR.exists() and (CVD_IMAGES_DIR / "system.img").exists():
            cvd_cmd += f"--system_image_dir={CVD_IMAGES_DIR} "

        _run(cvd_cmd, timeout=180, env={"HOME": cvd_home})

        dev.state = "booting"
        self._save_state()

        await self._wait_for_adb(dev)
        dev.state = "ready"
        self._save_state()
        return True

    def get_device_info(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get live device info via ADB."""
        dev = self._devices.get(device_id)
        if not dev or dev.state not in ("ready", "patched", "running"):
            return None

        t = dev.adb_target
        return {
            "id": dev.id,
            "device_type": dev.device_type,
            "instance_num": dev.instance_num,
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
        if not dev or dev.state not in ("ready", "patched", "running"):
            return None

        for attempt in range(2):
            try:
                # Use raw binary mode — text mode corrupts PNG data
                proc = subprocess.run(
                    ["adb", "-s", dev.adb_target, "exec-out", "screencap", "-p"],
                    capture_output=True, timeout=10,
                )
                if proc.returncode != 0 or len(proc.stdout) < 100:
                    if attempt == 0:
                        # Try ADB reconnect before giving up
                        subprocess.run(
                            ["adb", "connect", dev.adb_target],
                            capture_output=True, timeout=5,
                        )
                        continue
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
                if attempt == 0:
                    try:
                        subprocess.run(
                            ["adb", "connect", dev.adb_target],
                            capture_output=True, timeout=5,
                        )
                    except Exception:
                        pass
                    continue
                return None
        return None
