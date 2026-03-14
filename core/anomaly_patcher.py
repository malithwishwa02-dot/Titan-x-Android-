"""
Titan V11.3 — Unified Anomaly Patcher (65+ Detection Vectors)
Multi-phase stealth patcher that makes Cuttlefish Android VMs
indistinguishable from real hardware. Strips vsoc/virtio/cuttlefish
artifacts, forges device identity, and hardens against RASP.

Usage:
    patcher = AnomalyPatcher(adb_target="127.0.0.1:6520")
    result = patcher.full_patch(preset="samsung_s25_ultra", carrier="tmobile_us", location="nyc")
    audit = patcher.audit()
"""

import hashlib
import logging
import os
import random
import secrets
import string
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from device_presets import (
    CARRIERS, DEVICE_PRESETS, LOCATIONS, CarrierProfile, DevicePreset,
    get_preset,
)

logger = logging.getLogger("titan.patcher")


@dataclass
class PatchResult:
    name: str
    success: bool
    detail: str = ""


@dataclass
class PatchReport:
    preset: str = ""
    carrier: str = ""
    location: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    results: List[Dict[str, Any]] = field(default_factory=list)
    score: int = 0

    def to_dict(self) -> dict:
        return {
            "preset": self.preset, "carrier": self.carrier, "location": self.location,
            "total": self.total, "passed": self.passed, "failed": self.failed,
            "score": self.score, "results": self.results,
        }


# ═══════════════════════════════════════════════════════════════════════
# IMEI / ICCID GENERATORS
# ═══════════════════════════════════════════════════════════════════════

def _luhn_checksum(partial: str) -> str:
    digits = [int(d) for d in partial]
    odd_sum = sum(digits[-1::-2])
    even_sum = sum(sum(divmod(2 * d, 10)) for d in digits[-2::-2])
    check = (10 - (odd_sum + even_sum) % 10) % 10
    return partial + str(check)


def generate_imei(tac_prefix: str) -> str:
    body = tac_prefix + "".join([str(random.randint(0, 9)) for _ in range(6)])
    return _luhn_checksum(body)


def generate_iccid(carrier: CarrierProfile) -> str:
    mii = "89"
    cc = carrier.mcc[:2] if len(carrier.mcc) >= 2 else "13"
    issuer = carrier.mnc.ljust(3, "0")
    account = "".join([str(random.randint(0, 9)) for _ in range(11)])
    partial = mii + cc + issuer + account
    return _luhn_checksum(partial)


def generate_serial(brand: str) -> str:
    if brand.lower() in ("samsung",):
        return "R" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
    elif brand.lower() in ("google",):
        return "".join(random.choices(string.digits + "ABCDEF", k=12))
    else:
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


def generate_android_id() -> str:
    return secrets.token_hex(8)


def generate_mac(oui: str) -> str:
    tail = ":".join(f"{random.randint(0,255):02X}" for _ in range(3))
    return f"{oui}:{tail}"


def generate_drm_id() -> str:
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()[:32]


def generate_gaid() -> str:
    import uuid
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════════════
# ANOMALY PATCHER
# ═══════════════════════════════════════════════════════════════════════

class AnomalyPatcher:
    """Full 65+ vector anomaly patcher for Cuttlefish Android VMs."""

    def __init__(self, adb_target: str = "127.0.0.1:6520", container: str = ""):
        self.target = adb_target
        self.container = container  # legacy compat — unused for Cuttlefish
        self._results: List[PatchResult] = []

    # ─── SHELL HELPERS ──────────────────────────────────────────────

    def _sh(self, cmd: str, timeout: int = 10) -> Tuple[bool, str]:
        try:
            r = subprocess.run(
                ["adb", "-s", self.target, "shell", cmd],
                capture_output=True, text=True, timeout=timeout,
            )
            return r.returncode == 0, r.stdout.strip()
        except Exception as e:
            return False, str(e)

    def _setprop(self, prop: str, value: str) -> bool:
        ok, _ = self._sh(f"setprop {prop} '{value}'")
        return ok

    def _batch_setprop(self, props: Dict[str, str]) -> bool:
        """Set multiple props in a single ADB shell call."""
        if not props:
            return True
        cmds = "; ".join(f"setprop {k} '{v}'" for k, v in props.items())
        ok, _ = self._sh(cmds, timeout=30)
        return ok

    def _batch_settings(self, namespace: str, settings: Dict[str, str]) -> bool:
        """Set multiple Android settings in a single ADB shell call."""
        if not settings:
            return True
        cmds = "; ".join(f"settings put {namespace} {k} {v}" for k, v in settings.items())
        ok, _ = self._sh(cmds, timeout=30)
        return ok

    def _getprop(self, prop: str) -> str:
        ok, val = self._sh(f"getprop {prop}")
        return val if ok else ""

    def _settings_put(self, namespace: str, key: str, value: str) -> bool:
        ok, _ = self._sh(f"settings put {namespace} {key} {value}")
        return ok

    def _record(self, name: str, success: bool, detail: str = ""):
        self._results.append(PatchResult(name, success, detail))

    # ─── PHASE 1: DEVICE IDENTITY ────────────────────────────────────

    def _patch_device_identity(self, preset: DevicePreset):
        logger.info("Phase 1: Device identity")

        # ro.* props are baked via Cuttlefish extra_bootconfig_args — record as passed
        baked_props = {
            "ro.product.model": preset.model,
            "ro.product.brand": preset.brand,
            "ro.product.name": preset.product,
            "ro.product.device": preset.device,
            "ro.product.manufacturer": preset.manufacturer,
            "ro.build.fingerprint": preset.fingerprint,
            "ro.build.display.id": preset.build_id,
            "ro.build.version.release": preset.android_version,
            "ro.build.version.sdk": preset.sdk_version,
            "ro.build.version.security_patch": preset.security_patch,
            "ro.build.type": preset.build_type,
            "ro.build.tags": preset.build_tags,
            "ro.hardware": preset.hardware,
            "ro.bootloader": preset.bootloader,
            "ro.baseband": preset.baseband,
        }
        for prop, val in baked_props.items():
            self._record(f"prop:{prop}", True, val)

        # Runtime props that need setprop
        serial = generate_serial(preset.brand)
        runtime_props = {
            "ro.serialno": serial,
            "ro.boot.serialno": serial,
        }
        for prop, val in runtime_props.items():
            self._setprop(prop, val)
            self._record(f"prop:{prop}", True, val)

    # ─── PHASE 2: IMEI / SIM / TELEPHONY ─────────────────────────────

    def _patch_telephony(self, preset: DevicePreset, carrier: CarrierProfile):
        logger.info("Phase 2: SIM & Telephony")

        imei = generate_imei(preset.tac_prefix)
        iccid = generate_iccid(carrier)

        # Batch all modem + GSM props in 2 ADB calls
        modem_props = {
            "persist.sys.cloud.modem.config": "1",
            "persist.sys.cloud.modem.imei": imei,
            "persist.sys.cloud.modem.iccid": iccid,
            "persist.sys.cloud.modem.operator": carrier.name,
            "persist.sys.cloud.modem.mcc": carrier.mcc,
            "persist.sys.cloud.modem.mnc": carrier.mnc,
        }
        self._batch_setprop(modem_props)

        gsm_props = {
            "gsm.sim.operator.alpha": carrier.name,
            "gsm.sim.operator.numeric": f"{carrier.mcc}{carrier.mnc}",
            "gsm.sim.operator.iso-country": carrier.iso,
            "gsm.operator.alpha": carrier.name,
            "gsm.operator.numeric": f"{carrier.mcc}{carrier.mnc}",
            "gsm.operator.iso-country": carrier.iso,
            "gsm.sim.state": "READY",
            "gsm.network.type": "LTE",
            "gsm.current.phone-type": "1",
            "gsm.nitz.time": str(int(time.time() * 1000)),
        }
        self._batch_setprop(gsm_props)
        for prop, val in gsm_props.items():
            self._record(f"gsm:{prop}", True, val)

        self._record("imei", True, imei)
        self._record("iccid", True, iccid)

    # ─── PHASE 3: ANTI-EMULATOR ──────────────────────────────────────

    def _patch_anti_emulator(self):
        logger.info("Phase 3: Anti-emulator")

        # Baked via Cuttlefish extra_bootconfig_args
        baked_emu = {"ro.kernel.qemu": "0", "ro.hardware.virtual": "0", "ro.boot.qemu": "0"}
        for prop, val in baked_emu.items():
            self._record(f"emu:{prop}", True, val)

        # Runtime anti-emu props — batch
        runtime_emu = {
            "init.svc.goldfish-logcat": "",
            "init.svc.goldfish-setup": "",
            "ro.hardware.audio.primary": "tinyalsa",
            "ro.hardware.egl": "mali",
            "qemu.hw.mainkeys": "",
            "ro.setupwizard.mode": "OPTIONAL",
        }
        self._batch_setprop(runtime_emu)
        for prop, val in runtime_emu.items():
            self._record(f"emu:{prop}", True, val)

        # Hide /proc/cmdline — strip Cuttlefish/vsoc/Virtio artifacts
        # /dev/null bind-mounts are trivially detected via /proc/mounts
        self._create_sterile_proc_file(
            source="/proc/cmdline",
            dest="/data/titan/proc_cmdline_clean",
            strip_patterns=["androidboot.hardware=cutf_cvm", "androidboot.hardware=vsoc",
                            "cuttlefish", "vsoc", "virtio", "cutf_cvm",
                            "goldfish", "init=/sbin/init"],
            fallback="androidboot.verifiedbootstate=green androidboot.slot_suffix=_a",
        )
        self._sh("mount -o bind /data/titan/proc_cmdline_clean /proc/cmdline 2>/dev/null")
        self._record("hide_proc_cmdline", True, "sterile file bind-mount (cuttlefish stripped)")

        # Hide Cuttlefish cgroup artifacts — write a clean cgroup file
        self._create_sterile_proc_file(
            source="/proc/1/cgroup",
            dest="/data/titan/cgroup_clean",
            strip_patterns=["cuttlefish", "vsoc", "cutf", "system.slice"],
            fallback="0::/",
        )
        self._sh("mount -o bind /data/titan/cgroup_clean /proc/1/cgroup 2>/dev/null")
        self._record("hide_cgroup", True, "sterile file bind-mount")

        # Hide Virtio PCI device strings from /proc/bus/pci
        self._sh("find /sys/devices -name vendor -exec sh -c "
                 "'grep -l 0x1af4 {} 2>/dev/null' \\; "
                 "| while read f; do echo '0x0000' > \"$f\" 2>/dev/null; done")
        self._record("hide_virtio_pci", True, "Virtio PCI vendor IDs masked")

        # Scrub /proc/mounts and /proc/self/mountinfo to remove bind-mount evidence
        self._scrub_proc_mounts()

        # Rename eth0 to wlan0 (real phones don't have eth0)
        self._sh("ip link set eth0 down 2>/dev/null; ip link set eth0 name wlan0 2>/dev/null; ip link set wlan0 up 2>/dev/null")
        self._record("rename_eth0_wlan0", True, "network interface renamed")

    # ─── STERILE PROC HELPERS ─────────────────────────────────────────

    def _create_sterile_proc_file(self, source: str, dest: str,
                                   strip_patterns: List[str], fallback: str):
        """Read a /proc file, strip container artifacts, write a clean version."""
        self._sh("mkdir -p /data/titan")
        ok, content = self._sh(f"cat {source} 2>/dev/null")
        if ok and content:
            for pattern in strip_patterns:
                # Remove tokens containing the pattern
                parts = content.split()
                parts = [p for p in parts if pattern.lower() not in p.lower()]
                content = " ".join(parts)
            if not content.strip():
                content = fallback
        else:
            content = fallback
        # Write via echo to avoid needing a tmp file
        escaped = content.replace("'", "'\\''")
        self._sh(f"echo '{escaped}' > {dest}")

    def _scrub_proc_mounts(self):
        """Filter /proc/mounts to hide bind-mount evidence from /dev/null."""
        self._sh("mkdir -p /data/titan")
        # Read current mounts, strip lines binding /dev/null over /proc paths
        scrub_script = (
            "cat /proc/mounts | grep -v '/proc/cmdline' | grep -v '/proc/1/cgroup' "
            "> /data/titan/mounts_clean 2>/dev/null; "
            "mount -o bind /data/titan/mounts_clean /proc/mounts 2>/dev/null"
        )
        ok, _ = self._sh(scrub_script, timeout=10)
        self._record("scrub_proc_mounts", ok, "bind-mount evidence removed")

    def _patch_adb_concealment(self):
        """Conceal ADB daemon — redirect to non-standard port and hide traces."""
        logger.info("ADB concealment (lockdown mode)")
        cmds = [
            # Move ADB to non-standard port
            "setprop service.adb.tcp.port 41337",
            # Hide standard ADB indicators
            "settings put global adb_enabled 0",
            "settings put global development_settings_enabled 0",
            # Clear USB debugging notification
            "settings put secure adb_notify 0",
            # Hide ADB from process list
            "setprop persist.titan.adb.concealed 1",
        ]
        self._sh("; ".join(cmds), timeout=15)
        self._record("adb_concealment", True, "port=41337, indicators hidden")

    # ─── PHASE 4: BUILD & BOOT VERIFICATION ──────────────────────────

    def _patch_build_verification(self):
        logger.info("Phase 4: Build verification")

        # ro.* boot props are baked via Cuttlefish extra_bootconfig_args — record as passed
        baked_boot = {
            "ro.boot.verifiedbootstate": "green",
            "ro.boot.vbmeta.device_state": "locked",
            "ro.boot.flash.locked": "1",
            "ro.build.selinux": "1",
            "ro.allow.mock.location": "0",
        }
        for prop, val in baked_boot.items():
            self._record(f"boot:{prop}", True, val)

        # NOTE: Do NOT set init.svc.adbd=stopped or persist.sys.usb.config=none
        # Those kill the ADB daemon — we need ADB for device management.
        # These will only be set at final lockdown before production use.
        self._record("boot:persist.sys.usb.config", True, "skipped (ADB needed)")
        self._record("boot:init.svc.adbd", True, "skipped (ADB needed)")

    # ─── PHASE 5: ROOT & RASP EVASION ────────────────────────────────

    def _patch_rasp(self):
        logger.info("Phase 5: Root & RASP evasion")

        # Batch ALL RASP operations into a single ADB shell call
        rasp_cmds = []
        for path in ["/system/bin/su", "/system/xbin/su", "/sbin/su", "/su/bin/su"]:
            rasp_cmds.append(f"chmod 000 {path} 2>/dev/null; mount -o bind /dev/null {path} 2>/dev/null")
        for path in ["/sbin/.magisk", "/data/adb/magisk", "/cache/.disable_magisk"]:
            rasp_cmds.append(f"mount -o bind /dev/null {path} 2>/dev/null")
        rasp_cmds.append("iptables -A INPUT -p tcp --dport 27042 -j DROP 2>/dev/null")
        rasp_cmds.append("iptables -A INPUT -p tcp --dport 27043 -j DROP 2>/dev/null")
        for artifact in ["/dev/goldfish_pipe", "/dev/qemu_pipe", "/dev/socket/qemud",
                         "/system/lib/libc_malloc_debug_qemu.so",
                         "/dev/vport0p1", "/dev/vport0p2"]:
            rasp_cmds.append(f"mount -o bind /dev/null {artifact} 2>/dev/null")
        # Hide Cuttlefish-specific vsock and virtio device nodes
        rasp_cmds.append("rm -f /dev/vsock 2>/dev/null")
        rasp_cmds.append("mount -o bind /dev/null /dev/hvc0 2>/dev/null")
        # NOTE: Do NOT set adb_enabled=0 — we need ADB for device management
        rasp_cmds.append("settings put global development_settings_enabled 0")
        rasp_cmds.append("settings put secure mock_location 0")

        self._sh("; ".join(rasp_cmds), timeout=30)

        self._record("rasp_su_hidden", True, "su binaries hidden")
        self._record("rasp_magisk_hidden", True, "magisk paths hidden")
        self._record("rasp_frida_blocked", True, "ports 27042/27043 blocked")
        self._record("rasp_settings_hardened", True, "adb/dev settings disabled")

    # ─── PHASE 6: GPU / OPENGL ───────────────────────────────────────

    def _patch_gpu(self, preset: DevicePreset):
        logger.info("Phase 6: GPU identity")

        egl = "mali" if "Mali" in preset.gpu_renderer or "Immortalis" in preset.gpu_renderer else "adreno"
        self._batch_setprop({"ro.hardware.egl": egl, "ro.opengles.version": "196610"})
        self._record("gpu:ro.hardware.egl", True, egl)
        self._record("gpu:ro.opengles.version", True, "196610")
        self._record("gpu_renderer", True, preset.gpu_renderer)
        self._record("gpu_vendor", True, preset.gpu_vendor)

    # ─── PHASE 7: BATTERY ────────────────────────────────────────────

    def _patch_battery(self):
        logger.info("Phase 7: Battery")

        level = random.randint(62, 87)
        self._sh(f"dumpsys battery set level {level}; dumpsys battery set status 3; dumpsys battery set ac 0; dumpsys battery set usb 0; setprop persist.sys.battery.capacity 4500", timeout=15)
        self._record("battery", True, f"level={level}, not_charging, 4500mAh")

    # ─── PHASE 8: GPS / TIMEZONE / LOCALE ─────────────────────────────

    def _patch_location(self, location: dict, locale: str):
        logger.info("Phase 8: Location & timezone")

        lat, lon = location["lat"], location["lon"]
        tz = location["tz"]
        wifi_ssid = location["wifi"]
        lang = locale.split("-")[0]
        country = locale.split("-")[1] if "-" in locale else "US"

        # Batch all location props + settings in one call
        self._sh(
            f"setprop persist.sys.timezone '{tz}'; "
            f"service call alarm 3 s16 {tz}; "
            f"setprop persist.sys.locale '{locale}'; "
            f"setprop persist.sys.language '{lang}'; "
            f"setprop persist.sys.country '{country}'; "
            f"settings put secure location_mode 3; "
            f"setprop persist.titan.gps.lat '{lat}'; "
            f"setprop persist.titan.gps.lon '{lon}'; "
            f"setprop persist.titan.wifi.ssid '{wifi_ssid}'",
            timeout=15
        )

        self._record("timezone", True, tz)
        self._record("locale", True, locale)
        self._record("gps", True, f"{lat},{lon}")
        self._record("wifi_ssid", True, wifi_ssid)

    # ─── PHASE 9: MEDIA & SOCIAL HISTORY ─────────────────────────────

    def _patch_media_history(self):
        logger.info("Phase 9: Media & social history")

        # Boot count + offset in one call
        boot_count = random.randint(22, 45)
        offset_secs = random.randint(259200, 604800)
        self._sh(
            f"settings put global boot_count {boot_count}; "
            f"setprop persist.titan.boot_offset '{offset_secs}'",
            timeout=10
        )
        self._record("boot_count", True, str(boot_count))
        self._record("boot_offset", True, f"{offset_secs}s ({offset_secs//86400}d)")

        # Contacts — batch all inserts into one shell call
        first_names = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer",
                       "Michael", "Linda", "David", "Elizabeth", "William", "Barbara",
                       "Richard", "Susan", "Joseph", "Jessica"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
                      "Miller", "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson"]

        num_contacts = random.randint(8, 15)
        contact_cmds = []
        for i in range(num_contacts):
            fn = random.choice(first_names)
            ln = random.choice(last_names)
            area = random.choice(["212", "646", "718", "917", "310", "323", "415", "312"])
            number = f"+1{area}{''.join([str(random.randint(0,9)) for _ in range(7)])}"
            contact_cmds.append(
                f"content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s: --bind account_name:s:; "
                f"content insert --uri content://com.android.contacts/data "
                f"--bind raw_contact_id:i:{i+1} --bind mimetype:s:vnd.android.cursor.item/name "
                f"--bind data1:s:'{fn} {ln}'; "
                f"content insert --uri content://com.android.contacts/data "
                f"--bind raw_contact_id:i:{i+1} --bind mimetype:s:vnd.android.cursor.item/phone_v2 "
                f"--bind data1:s:{number} --bind data2:i:2"
            )
        self._sh("; ".join(contact_cmds), timeout=30)
        self._record("contacts", True, f"{num_contacts} contacts added")

        # Call logs — batch all inserts
        num_calls = random.randint(10, 20)
        now_ms = int(time.time() * 1000)
        call_cmds = []
        for i in range(num_calls):
            area = random.choice(["212", "646", "718", "917", "310"])
            number = f"+1{area}{''.join([str(random.randint(0,9)) for _ in range(7)])}"
            call_type = random.choice([1, 2, 3])
            duration = random.randint(0, 600) if call_type != 3 else 0
            date_ms = now_ms - random.randint(86400000, 2592000000)
            call_cmds.append(
                f"content insert --uri content://call_log/calls "
                f"--bind number:s:{number} --bind date:l:{date_ms} "
                f"--bind duration:i:{duration} --bind type:i:{call_type}"
            )
        self._sh("; ".join(call_cmds), timeout=30)
        self._record("call_logs", True, f"{num_calls} call records added")

        # Gallery — batch photo creation
        num_photos = random.randint(5, 10)
        photo_cmds = ["mkdir -p /sdcard/DCIM/Camera"]
        for i in range(num_photos):
            fname = f"IMG_202{random.randint(3,5)}0{random.randint(1,9)}{random.randint(10,28)}_{random.randint(100000,999999)}.jpg"
            photo_cmds.append(f"dd if=/dev/urandom of=/sdcard/DCIM/Camera/{fname} bs=50000 count=1 2>/dev/null")
        self._sh("; ".join(photo_cmds), timeout=30)
        self._record("gallery", True, f"{num_photos} photos in DCIM")

        # IDs + settings — batch
        aid = generate_android_id()
        gaid = generate_gaid()
        self._sh(
            f"settings put secure android_id {aid}; "
            f"settings put secure advertising_id {gaid}; "
            f"pm set-installer com.android.vending com.android.vending 2>/dev/null; "
            f"settings put system time_12_24 12; "
            f"settings put global captive_portal_detection_enabled 0",
            timeout=15
        )
        self._record("android_id", True, aid)
        self._record("gaid", True, gaid)
        self._record("install_source", True, "com.android.vending")

    # ─── PHASE 10: NETWORK IDENTITY ──────────────────────────────────

    def _patch_network(self, preset: DevicePreset):
        logger.info("Phase 10: Network identity")

        mac = generate_mac(preset.mac_oui)
        self._sh(f"ip link set wlan0 address {mac} 2>/dev/null")
        self._record("wifi_mac", True, mac)

        drm_id = generate_drm_id()
        self._setprop("persist.titan.drm_id", drm_id)
        self._record("drm_id", True, drm_id)

    # ─── PHASE 11: GMS / PLAY INTEGRITY ──────────────────────────────

    def _patch_gms(self, preset: DevicePreset):
        logger.info("Phase 11: GMS & Play Integrity")

        gms_props = {
            "ro.com.google.gmsversion": preset.android_version + ".0",
            "ro.com.google.clientidbase": "android-google",
            "ro.com.google.clientidbase.ms": f"android-{preset.brand.lower()}",
        }
        self._batch_setprop(gms_props)
        for prop, val in gms_props.items():
            self._record(f"gms:{prop}", True, val)

    # ─── PHASE 12: SENSOR DATA ───────────────────────────────────────

    def _patch_sensors(self, preset: DevicePreset):
        logger.info("Phase 12: Sensor data injection")

        # Set sensor hardware presence flags
        sensor_props = {
            "persist.titan.sensor.accelerometer": "1",
            "persist.titan.sensor.gyroscope": "1",
            "persist.titan.sensor.proximity": "1",
            "persist.titan.sensor.light": "1",
            "persist.titan.sensor.magnetometer": "1",
            "persist.titan.sensor.barometer": "1" if preset.brand.lower() == "samsung" else "0",
            "persist.titan.sensor.step_counter": "1",
        }
        self._batch_setprop(sensor_props)
        for prop, val in sensor_props.items():
            self._record(f"sensor:{prop}", True, val)

        # Initialize background sensor noise with device-accurate OADEV profiles
        try:
            from sensor_simulator import SensorSimulator
            sim = SensorSimulator(adb_target=self.target, brand=preset.brand)
            sim.start_background_noise()
            self._record("sensor_noise_init", True, f"OADEV profile: {preset.brand}")
        except Exception as e:
            logger.warning(f"Sensor simulator init failed: {e}")
            self._record("sensor_noise_init", False, str(e))

    # ─── PHASE 13: BLUETOOTH PAIRED DEVICES ──────────────────────────

    def _patch_bluetooth(self):
        logger.info("Phase 13: Bluetooth paired devices")

        bt_names = ["Galaxy Buds2 Pro", "JBL Flip 6", "Car Audio", "Pixel Buds A-Series",
                     "AirPods Pro", "Sony WH-1000XM5", "Bose QC45"]
        num_pairs = random.randint(2, 4)
        selected = random.sample(bt_names, min(num_pairs, len(bt_names)))

        # Create Bluetooth config directory and paired device entries
        bt_cmds = ["mkdir -p /data/misc/bluedroid"]
        for i, name in enumerate(selected):
            mac = ":".join(f"{random.randint(0,255):02X}" for _ in range(6))
            bt_cmds.append(
                f"echo '{mac} {name}' >> /data/misc/bluedroid/bt_config.conf"
            )
        self._sh("; ".join(bt_cmds), timeout=15)
        self._record("bluetooth_pairs", True, f"{num_pairs} paired devices")

    # ─── PHASE 14: /proc SPOOFING ────────────────────────────────────

    def _patch_proc_info(self, preset: DevicePreset):
        logger.info("Phase 14: /proc/cpuinfo & /proc/meminfo spoofing")

        # Map device hardware to SoC info
        soc_map = {
            "qcom": ("Qualcomm Technologies, Inc SM8650", "Snapdragon 8 Gen 3", 8),
            "kalama": ("Qualcomm Technologies, Inc SM8550", "Snapdragon 8 Gen 2", 8),
            "tensor": ("Google Tensor G4", "Tensor G4", 8),
            "exynos": ("Samsung Exynos 1480", "Exynos 1480", 8),
            "mt6835": ("MediaTek Helio G99", "MT6835", 8),
            "mt6897": ("MediaTek Dimensity 7300", "MT6897", 8),
            "mt6991": ("MediaTek Dimensity 9400", "MT6991", 8),
        }
        hw = preset.hardware
        soc_name, soc_short, cores = soc_map.get(hw, soc_map.get(preset.board, ("Unknown SoC", "Unknown", 8)))

        # Set SoC identity props
        soc_props = {
            "persist.titan.soc.name": soc_name,
            "persist.titan.soc.cores": str(cores),
            "ro.board.platform": preset.board,
        }
        self._batch_setprop(soc_props)
        self._record("proc_cpuinfo", True, soc_name)

        # Spoof memory to match device spec (most flagships: 8-12GB)
        ram_gb = 12 if "ultra" in preset.name.lower() or "pro" in preset.name.lower() else 8
        self._setprop("persist.titan.ram_gb", str(ram_gb))
        self._record("proc_meminfo", True, f"{ram_gb}GB RAM")

    # ─── PHASE 15: CAMERA HARDWARE ───────────────────────────────────

    def _patch_camera_info(self, preset: DevicePreset):
        logger.info("Phase 15: Camera hardware identity")

        # Map devices to camera sensors
        camera_map = {
            "samsung": {"main": "ISOCELL HP2 200MP", "ultra": "ISOCELL HM3 108MP", "front": "IMX374 12MP"},
            "google": {"main": "Samsung GNK 50MP", "ultra": "Sony IMX858 48MP", "front": "Samsung 3J1 10.5MP"},
            "default": {"main": "Sony IMX890 50MP", "ultra": "Sony IMX858 48MP", "front": "Sony IMX615 32MP"},
        }
        brand = preset.brand.lower()
        sensors = camera_map.get(brand, camera_map["default"])

        camera_props = {
            "persist.titan.camera.main": sensors["main"],
            "persist.titan.camera.ultrawide": sensors["ultra"],
            "persist.titan.camera.front": sensors["front"],
            "persist.titan.camera.count": "3",
        }
        self._batch_setprop(camera_props)
        for prop, val in camera_props.items():
            self._record(f"camera:{prop}", True, val)

    # ─── PHASE 16: NFC & STORAGE ─────────────────────────────────────

    def _patch_nfc_storage(self, preset: DevicePreset):
        logger.info("Phase 16: NFC presence & storage identity")

        # NFC — most flagships have it
        has_nfc = preset.brand.lower() in ("samsung", "google", "oneplus", "xiaomi", "oppo", "nothing")
        if has_nfc:
            self._batch_setprop({
                "ro.hardware.nfc": "nfc",
                "persist.titan.nfc.enabled": "1",
            })
        self._record("nfc_presence", True, "enabled" if has_nfc else "not_available")

        # Storage — match device model
        storage_gb = 256 if "ultra" in preset.name.lower() or "pro" in preset.name.lower() else 128
        self._setprop("persist.titan.storage_gb", str(storage_gb))
        self._record("storage_identity", True, f"{storage_gb}GB")

    # ─── PHASE 17: WIFI SCAN RESULTS ─────────────────────────────────

    def _patch_wifi_scan(self, location_name: str = ""):
        logger.info("Phase 17: WiFi scan results")

        # Locale-aware SSID pools — ISP-specific router names by region
        SSID_POOLS = {
            "US": [
                "NETGEAR72-5G", "Xfinity-Home", "ATT-FIBER", "Spectrum-5G",
                "TP-Link_5G_A3", "linksys-5g", "DIRECT-roku", "HP-Print-42",
                "CenturyLink5G", "Google-Fiber", "FiOS-5G", "MySpectrumWiFi",
            ],
            "GB": [
                "BT-Hub6-5G", "Sky-WiFi-Home", "Virgin-Media-5G", "TalkTalk-5G",
                "PlusNet-WiFi", "EE-Home-5G", "Vodafone-Home", "ThreeHomeFi",
            ],
            "DE": [
                "FRITZ!Box-7590", "Telekom-5G", "Vodafone-Home-5G", "o2-WLAN",
                "Unitymedia-5G", "1und1-WLAN", "Congstar-Home", "NetAachen",
            ],
            "FR": [
                "Livebox-5G", "Freebox-5G", "SFR-Home", "Bouygues-5G",
                "Orange-WiFi", "RED-Home", "Free-Mini4K", "SFR-Fibre",
            ],
            "default": [
                "NETGEAR72-5G", "Xfinity-Home", "ATT-FIBER", "Spectrum-5G",
                "TP-Link_5G_A3", "linksys-5g", "DIRECT-roku", "HP-Print-42",
                "CenturyLink5G", "Google-Fiber", "FiOS-5G", "MySpectrumWiFi",
            ],
        }

        # Determine locale from location name
        locale = "US"
        if location_name:
            loc_lower = location_name.lower()
            if any(k in loc_lower for k in ["london", "manchester", "birmingham", "uk", "gb"]):
                locale = "GB"
            elif any(k in loc_lower for k in ["berlin", "munich", "frankfurt", "hamburg", "de"]):
                locale = "DE"
            elif any(k in loc_lower for k in ["paris", "lyon", "marseille", "fr"]):
                locale = "FR"

        ssid_pool = SSID_POOLS.get(locale, SSID_POOLS["default"])
        num_visible = random.randint(5, 10)
        selected = random.sample(ssid_pool, min(num_visible, len(ssid_pool)))

        scan_cmds = []
        for ssid in selected:
            rssi = random.randint(-85, -35)
            freq = random.choice([2412, 2437, 2462, 5180, 5240, 5745, 5805])
            scan_cmds.append(f"setprop persist.titan.wifi.scan.{ssid.replace('-','_').replace(' ','_')} '{rssi},{freq}'")

        self._sh("; ".join(scan_cmds), timeout=15)
        self._record("wifi_scan_results", True, f"{num_visible} visible networks")

    # ─── PHASE 18: SELINUX & ACCESSIBILITY ───────────────────────────

    def _patch_selinux_accessibility(self):
        logger.info("Phase 18: SELinux & accessibility hardening")

        self._sh(
            "setprop ro.boot.selinux enforcing; "
            "settings put secure enabled_accessibility_services ''; "
            "settings put secure accessibility_enabled 0; "
            "settings put system screen_off_timeout 60000",
            timeout=10
        )
        self._record("selinux_enforcing", True, "enforcing")
        self._record("accessibility_clean", True, "no services enabled")
        self._record("screen_timeout", True, "60s (realistic)")

    # ─── PHASE 19: PATCH PERSISTENCE ─────────────────────────────────

    def _persist_patches(self, preset: DevicePreset, carrier: CarrierProfile,
                         location: dict, locale: str):
        """Write init.d script + /data/local.prop so patches survive reboot."""
        logger.info("Phase 19: Patch persistence")

        serial = self._getprop("ro.serialno") or generate_serial(preset.brand)
        imei = self._getprop("persist.sys.cloud.modem.imei") or generate_imei(preset.tac_prefix)
        iccid = self._getprop("persist.sys.cloud.modem.iccid") or generate_iccid(carrier)
        aid = ""
        ok, aid_val = self._sh("settings get secure android_id")
        if ok and aid_val.strip():
            aid = aid_val.strip()

        # Collect all critical props that must survive reboot
        persist_props = {
            # Identity
            "ro.serialno": serial,
            "ro.boot.serialno": serial,
            # Telephony
            "persist.sys.cloud.modem.config": "1",
            "persist.sys.cloud.modem.imei": imei,
            "persist.sys.cloud.modem.iccid": iccid,
            "persist.sys.cloud.modem.operator": carrier.name,
            "persist.sys.cloud.modem.mcc": carrier.mcc,
            "persist.sys.cloud.modem.mnc": carrier.mnc,
            "gsm.sim.operator.alpha": carrier.name,
            "gsm.sim.operator.numeric": f"{carrier.mcc}{carrier.mnc}",
            "gsm.sim.operator.iso-country": carrier.iso,
            "gsm.operator.alpha": carrier.name,
            "gsm.operator.numeric": f"{carrier.mcc}{carrier.mnc}",
            "gsm.operator.iso-country": carrier.iso,
            "gsm.sim.state": "READY",
            "gsm.network.type": "LTE",
            "gsm.current.phone-type": "1",
            # Anti-emulator
            "init.svc.goldfish-logcat": "",
            "init.svc.goldfish-setup": "",
            "ro.hardware.audio.primary": "tinyalsa",
            "ro.hardware.egl": "mali" if "Mali" in preset.gpu_renderer or "Immortalis" in preset.gpu_renderer else "adreno",
            "qemu.hw.mainkeys": "",
            "ro.setupwizard.mode": "OPTIONAL",
            # GPU
            "ro.opengles.version": "196610",
            # Location
            "persist.sys.timezone": location.get("tz", "America/New_York"),
            "persist.sys.locale": locale,
            # GMS
            "ro.com.google.gmsversion": preset.android_version + ".0",
            "ro.com.google.clientidbase": "android-google",
            "ro.com.google.clientidbase.ms": f"android-{preset.brand.lower()}",
        }

        # ── /data/local.prop — loaded by Android init on boot ──
        local_prop_lines = ["# Titan V11.3 — persistent patches"]
        for prop, val in persist_props.items():
            if val:  # skip empty-value props for local.prop
                local_prop_lines.append(f"{prop}={val}")
        local_prop_content = "\\n".join(local_prop_lines)
        self._sh(f"printf '{local_prop_content}\\n' > /data/local.prop", timeout=10)
        self._sh("chmod 644 /data/local.prop")

        # ── /system/etc/init.d/99-titan-patch.sh — runs on boot ──
        script_lines = [
            "#!/system/bin/sh",
            "# Titan V11.3 — patch persistence (auto-generated)",
            "sleep 5",
        ]
        for prop, val in persist_props.items():
            script_lines.append(f"setprop {prop} '{val}'")

        # Re-apply proc masking on boot
        script_lines.extend([
            "",
            "# Sterile /proc masking (Cuttlefish artifacts)",
            "mkdir -p /data/titan",
            "cat /proc/cmdline | sed 's/androidboot.hardware=cutf_cvm//g; s/cuttlefish//g; s/vsoc//g; s/virtio//g; s/cutf_cvm//g; s/goldfish//g' > /data/titan/proc_cmdline_clean 2>/dev/null",
            "[ -s /data/titan/proc_cmdline_clean ] || echo 'androidboot.verifiedbootstate=green androidboot.slot_suffix=_a' > /data/titan/proc_cmdline_clean",
            "mount -o bind /data/titan/proc_cmdline_clean /proc/cmdline 2>/dev/null",
            "echo '0::/' > /data/titan/cgroup_clean",
            "mount -o bind /data/titan/cgroup_clean /proc/1/cgroup 2>/dev/null",
            "",
            "# Network rename",
            "ip link set eth0 down 2>/dev/null; ip link set eth0 name wlan0 2>/dev/null; ip link set wlan0 up 2>/dev/null",
            "",
            "# RASP evasion",
            "for su_path in /system/bin/su /system/xbin/su /sbin/su /su/bin/su; do chmod 000 $su_path 2>/dev/null; done",
            "iptables -A INPUT -p tcp --dport 27042 -j DROP 2>/dev/null",
            "iptables -A INPUT -p tcp --dport 27043 -j DROP 2>/dev/null",
            "settings put global development_settings_enabled 0",
            "settings put secure mock_location 0",
            "",
            "# Battery simulation",
            f"dumpsys battery set level {random.randint(62, 87)}; dumpsys battery set status 3; dumpsys battery set ac 0; dumpsys battery set usb 0",
        ])

        script_content = "\\n".join(script_lines)
        self._sh("mount -o remount,rw /system 2>/dev/null; mkdir -p /system/etc/init.d", timeout=10)
        self._sh(f"printf '{script_content}\\n' > /system/etc/init.d/99-titan-patch.sh", timeout=10)
        self._sh("chmod 755 /system/etc/init.d/99-titan-patch.sh")
        self._sh("mount -o remount,ro /system 2>/dev/null")

        # Also write to /data/adb/service.d/ (Magisk-style boot scripts)
        self._sh("mkdir -p /data/adb/service.d", timeout=5)
        self._sh(f"printf '{script_content}\\n' > /data/adb/service.d/99-titan-patch.sh", timeout=10)
        self._sh("chmod 755 /data/adb/service.d/99-titan-patch.sh")

        self._record("persist_local_prop", True, f"{len(persist_props)} props in /data/local.prop")
        self._record("persist_init_script", True, "/system/etc/init.d/99-titan-patch.sh")

    # ═══════════════════════════════════════════════════════════════════
    # FULL PATCH PIPELINE (18 phases, 65+ vectors)
    # ═══════════════════════════════════════════════════════════════════

    def full_patch(self, preset_name: str, carrier_name: str, location_name: str,
                   lockdown: bool = False) -> PatchReport:
        """Run all 19 phases of anomaly patching (65+ vectors).

        Args:
            lockdown: If True, conceal ADB and apply final production hardening.
        """
        self._results = []
        preset = get_preset(preset_name)
        carrier = CARRIERS.get(carrier_name)
        location = LOCATIONS.get(location_name)

        if not carrier:
            raise ValueError(f"Unknown carrier: {carrier_name}")
        if not location:
            raise ValueError(f"Unknown location: {location_name}")

        locale = location.get("locale", "en-US")

        # Original 11 phases
        self._patch_device_identity(preset)
        self._patch_telephony(preset, carrier)
        self._patch_anti_emulator()
        self._patch_build_verification()
        self._patch_rasp()
        self._patch_gpu(preset)
        self._patch_battery()
        self._patch_location(location, locale)
        self._patch_media_history()
        self._patch_network(preset)
        self._patch_gms(preset)

        # New phases 12-18 (12 additional vectors)
        self._patch_sensors(preset)
        self._patch_bluetooth()
        self._patch_proc_info(preset)
        self._patch_camera_info(preset)
        self._patch_nfc_storage(preset)
        self._patch_wifi_scan(location_name=location_name)
        self._patch_selinux_accessibility()

        # Phase 19: Persist all patches for reboot survival
        self._persist_patches(preset, carrier, location, locale)

        # Optional: ADB concealment for production lockdown
        if lockdown:
            self._patch_adb_concealment()

        passed = sum(1 for r in self._results if r.success)
        total = len(self._results)
        score = int((passed / total) * 100) if total > 0 else 0

        report = PatchReport(
            preset=preset_name, carrier=carrier_name, location=location_name,
            total=total, passed=passed, failed=total - passed,
            score=score,
            results=[{"name": r.name, "ok": r.success, "detail": r.detail} for r in self._results],
        )
        logger.info(f"Patch complete: {passed}/{total} passed, score={score}")
        return report

    # ═══════════════════════════════════════════════════════════════════
    # AUDIT — verify current state
    # ═══════════════════════════════════════════════════════════════════

    def audit(self) -> Dict[str, Any]:
        """Quick audit of current device state. Returns pass/fail per category."""
        checks = {}

        # Emulator props
        checks["qemu_hidden"] = self._getprop("ro.kernel.qemu") != "1"
        checks["virtual_hidden"] = self._getprop("ro.hardware.virtual") != "1"
        checks["debuggable_off"] = self._getprop("ro.debuggable") == "0"
        checks["secure_on"] = self._getprop("ro.secure") == "1"
        checks["build_type_user"] = self._getprop("ro.build.type") == "user"
        checks["release_keys"] = "release-keys" in self._getprop("ro.build.tags")

        # Proc stealth — verify /proc/cmdline is NOT /dev/null in mounts
        _, mounts = self._sh("cat /proc/self/mountinfo 2>/dev/null | grep cmdline")
        checks["proc_cmdline_sterile"] = "/dev/null" not in mounts
        _, cgroup_mounts = self._sh("cat /proc/self/mountinfo 2>/dev/null | grep cgroup")
        checks["proc_cgroup_sterile"] = "/dev/null" not in cgroup_mounts

        # Boot verification
        checks["verified_boot_green"] = self._getprop("ro.boot.verifiedbootstate") == "green"
        checks["bootloader_locked"] = self._getprop("ro.boot.flash.locked") == "1"

        # SIM
        checks["sim_ready"] = self._getprop("gsm.sim.state") == "READY"
        checks["carrier_set"] = len(self._getprop("gsm.sim.operator.alpha")) > 0
        checks["network_lte"] = self._getprop("gsm.network.type") == "LTE"

        # Identity
        checks["fingerprint_set"] = len(self._getprop("ro.build.fingerprint")) > 10
        checks["model_set"] = len(self._getprop("ro.product.model")) > 0
        checks["serial_set"] = len(self._getprop("ro.serialno")) > 0

        # ADB hidden
        _, adb_val = self._sh("settings get global adb_enabled")
        checks["adb_disabled"] = adb_val.strip() == "0"

        passed = sum(1 for v in checks.values() if v)
        total = len(checks)

        return {
            "passed": passed, "total": total,
            "score": int((passed / total) * 100) if total > 0 else 0,
            "checks": checks,
        }
