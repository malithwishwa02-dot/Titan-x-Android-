#!/usr/bin/env python3
"""
Titan V11.3 — VMOS Cloud Device Forensic Anomaly Scanner
=========================================================
Connects to a VMOS Cloud device and runs 80+ detection checks to find
every anomaly, abnormality, and detectable artifact that antifraud/RASP
systems would flag.

Categories:
  1. Emulator/VM detection props
  2. Build fingerprint consistency
  3. Hardware sensor availability
  4. SIM / telephony state
  5. Network / proxy leaks
  6. System apps presence (Phone, SMS, Camera, etc.)
  7. Root / SU / Magisk indicators
  8. SELinux status
  9. ADB / debugging state
 10. Boot verification state
 11. Installed packages anomalies
 12. /proc & /sys filesystem leaks
 13. DNS / timezone / locale consistency
 14. Battery state
 15. Screen resolution / density
 16. GL Renderer / GPU info
 17. SafetyNet/Play Integrity signals
 18. VMOS-specific artifacts
"""

import asyncio
import json
import os
import sys
import time
from collections import OrderedDict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from vmos_cloud_bridge import VMOSCloudBridge

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════

PAD_CODE = os.environ.get("VMOS_PAD_CODE", "ACP2509244LGV1MV")
API_KEY = os.environ.get("VMOS_API_KEY", "BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi")
API_SECRET = os.environ.get("VMOS_API_SECRET", "Q2SgcSwEfuwoedY0cijp6Mce")

bridge = VMOSCloudBridge(api_key=API_KEY, api_secret=API_SECRET)

# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

async def sh(cmd: str) -> str:
    """Execute shell command on VMOS device, return output."""
    r = await bridge.exec_shell(PAD_CODE, cmd)
    if r.ok:
        return (r.result or "").strip()
    return f"[ERROR:{r.error or 'unknown'}]"

async def getprop(prop: str) -> str:
    return await sh(f"getprop {prop}")

async def sh_multi(cmds: dict) -> dict:
    """Run multiple shell commands sequentially, return {label: output}."""
    results = {}
    for label, cmd in cmds.items():
        results[label] = await sh(cmd)
    return results

SEVERITY_CRITICAL = "CRITICAL"  # Instant VM/fraud detection
SEVERITY_HIGH = "HIGH"          # Strong indicator
SEVERITY_MEDIUM = "MEDIUM"      # Suspicious but not conclusive
SEVERITY_LOW = "LOW"            # Minor inconsistency
SEVERITY_INFO = "INFO"          # Informational

findings = []

def flag(severity, category, title, detail, fix_hint=""):
    findings.append({
        "severity": severity,
        "category": category,
        "title": title,
        "detail": detail,
        "fix_hint": fix_hint,
    })

# ═══════════════════════════════════════════════════════════════════
# SCAN CATEGORIES
# ═══════════════════════════════════════════════════════════════════

async def scan_emulator_props():
    """Check for emulator/VM indicator properties."""
    print("\n[1/18] Scanning emulator/VM properties...")
    checks = {
        "ro.kernel.qemu": await getprop("ro.kernel.qemu"),
        "ro.hardware.virtual": await getprop("ro.hardware.virtual"),
        "ro.hardware": await getprop("ro.hardware"),
        "ro.product.board": await getprop("ro.product.board"),
        "ro.boot.hardware": await getprop("ro.boot.hardware"),
        "init.svc.goldfish-logcat": await getprop("init.svc.goldfish-logcat"),
        "init.svc.goldfish-setup": await getprop("init.svc.goldfish-setup"),
        "ro.bootimage.build.type": await getprop("ro.bootimage.build.type"),
        "ro.build.flavor": await getprop("ro.build.flavor"),
        "gsm.version.ril-impl": await getprop("gsm.version.ril-impl"),
        "ro.boot.serialno": await getprop("ro.boot.serialno"),
        "ro.serialno": await getprop("ro.serialno"),
        "ro.setupwizard.mode": await getprop("ro.setupwizard.mode"),
    }
    for k, v in checks.items():
        print(f"  {k} = {v!r}")

    if checks["ro.kernel.qemu"] == "1":
        flag(SEVERITY_CRITICAL, "emulator", "QEMU detected", "ro.kernel.qemu=1", "Set ro.kernel.qemu to empty")
    if "virtual" in checks.get("ro.hardware.virtual", "").lower():
        flag(SEVERITY_CRITICAL, "emulator", "Virtual hardware flag", f"ro.hardware.virtual={checks['ro.hardware.virtual']}")
    if checks.get("init.svc.goldfish-logcat"):
        flag(SEVERITY_CRITICAL, "emulator", "Goldfish service running", "init.svc.goldfish-logcat present")
    if checks.get("init.svc.goldfish-setup"):
        flag(SEVERITY_CRITICAL, "emulator", "Goldfish setup service", "init.svc.goldfish-setup present")

    hw = checks.get("ro.hardware", "")
    board = checks.get("ro.product.board", "")
    for bad in ["goldfish", "ranchu", "vbox", "nox", "bluestacks", "genymotion", "andy", "ttVM", "cuttlefish", "vsoc"]:
        if bad in hw.lower() or bad in board.lower():
            flag(SEVERITY_CRITICAL, "emulator", f"VM hardware detected: {bad}", f"ro.hardware={hw}, ro.product.board={board}")

    flavor = checks.get("ro.build.flavor", "")
    if "eng" in flavor or "userdebug" in flavor:
        flag(SEVERITY_HIGH, "emulator", f"Non-production build flavor: {flavor}", "", "Set to user build")

    ril = checks.get("gsm.version.ril-impl", "")
    if not ril or "reference" in ril.lower() or "emulat" in ril.lower():
        flag(SEVERITY_HIGH, "emulator", f"Missing/fake RIL implementation: {ril!r}", "", "Should show real baseband")

    serial = checks.get("ro.boot.serialno", "") or checks.get("ro.serialno", "")
    if not serial or serial == "unknown" or serial.startswith("EMULATOR"):
        flag(SEVERITY_HIGH, "emulator", f"Missing/fake serial: {serial!r}", "", "Generate realistic serial")


async def scan_build_fingerprint():
    """Check build fingerprint consistency."""
    print("\n[2/18] Scanning build fingerprint consistency...")
    props = {
        "ro.build.fingerprint": await getprop("ro.build.fingerprint"),
        "ro.odm.build.fingerprint": await getprop("ro.odm.build.fingerprint"),
        "ro.product.build.fingerprint": await getprop("ro.product.build.fingerprint"),
        "ro.system.build.fingerprint": await getprop("ro.system.build.fingerprint"),
        "ro.vendor.build.fingerprint": await getprop("ro.vendor.build.fingerprint"),
        "ro.build.display.id": await getprop("ro.build.display.id"),
        "ro.build.version.incremental": await getprop("ro.build.version.incremental"),
        "ro.build.version.release": await getprop("ro.build.version.release"),
        "ro.build.version.sdk": await getprop("ro.build.version.sdk"),
        "ro.build.version.security_patch": await getprop("ro.build.version.security_patch"),
        "ro.build.type": await getprop("ro.build.type"),
        "ro.build.tags": await getprop("ro.build.tags"),
        "ro.product.brand": await getprop("ro.product.brand"),
        "ro.product.model": await getprop("ro.product.model"),
        "ro.product.device": await getprop("ro.product.device"),
        "ro.product.name": await getprop("ro.product.name"),
        "ro.product.manufacturer": await getprop("ro.product.manufacturer"),
    }
    for k, v in props.items():
        print(f"  {k} = {v!r}")

    fp = props["ro.build.fingerprint"]
    brand = props["ro.product.brand"]
    model = props["ro.product.model"]

    if not fp or len(fp) < 20:
        flag(SEVERITY_CRITICAL, "fingerprint", "Missing build fingerprint", f"ro.build.fingerprint={fp!r}")
    else:
        # Check brand consistency in fingerprint
        if brand and brand.lower() not in fp.lower():
            flag(SEVERITY_CRITICAL, "fingerprint", "Brand mismatch in fingerprint",
                 f"brand={brand} but fingerprint={fp}", "Fingerprint must contain the brand")

    # Cross-fingerprint consistency
    fps = [props[k] for k in ["ro.build.fingerprint", "ro.odm.build.fingerprint",
           "ro.product.build.fingerprint", "ro.system.build.fingerprint", "ro.vendor.build.fingerprint"] if props[k]]
    if len(set(fps)) > 1 and fps:
        flag(SEVERITY_HIGH, "fingerprint", "Fingerprint mismatch across partitions",
             f"Found {len(set(fps))} different fingerprints", "All partition fingerprints should match")

    if props["ro.build.type"] != "user":
        flag(SEVERITY_HIGH, "fingerprint", f"Build type not 'user': {props['ro.build.type']}",
             "", "Must be 'user' for production builds")

    tags = props["ro.build.tags"]
    if "release-keys" not in tags:
        flag(SEVERITY_HIGH, "fingerprint", f"Build tags not 'release-keys': {tags}",
             "", "Must contain release-keys")

    # Check if brand/model/device are consistent
    if brand and model:
        brand_l = brand.lower()
        # Samsung model should start with SM-
        if brand_l == "samsung" and not model.startswith("SM-"):
            flag(SEVERITY_MEDIUM, "fingerprint", f"Samsung model format wrong: {model}", "", "Should start with SM-")
        # Google model should start with Pixel
        if brand_l == "google" and "pixel" not in model.lower():
            flag(SEVERITY_MEDIUM, "fingerprint", f"Google model doesn't mention Pixel: {model}", "")

    # VMOS-specific: check if fingerprint looks like a VMOS default
    VMOS_KNOWN_TEMPLATES = ["PKX110", "OP60F5L1", "V2408A", "PD2408"]
    is_vmos_template = any(t in (model or "") for t in VMOS_KNOWN_TEMPLATES)
    for vmos_indicator in ["vivo", "V2408A", "PD2408", "mt6985", "dimensity"]:
        if vmos_indicator.lower() in fp.lower():
            if is_vmos_template or brand.lower() == "vivo":
                flag(SEVERITY_INFO, "fingerprint", f"VMOS template identity (locked, cannot change)",
                     f"Contains '{vmos_indicator}' — hypervisor-locked template")
            else:
                flag(SEVERITY_CRITICAL, "fingerprint", f"VMOS default fingerprint still active",
                     f"Contains '{vmos_indicator}' — original VMOS device identity leaked")


async def scan_sensors():
    """Check hardware sensor availability."""
    print("\n[3/18] Scanning hardware sensors...")
    sensors_output = await sh("dumpsys sensorservice 2>/dev/null | head -60")
    print(f"  sensors output length: {len(sensors_output)}")

    if "[ERROR" in sensors_output or not sensors_output:
        flag(SEVERITY_HIGH, "sensors", "Cannot read sensorservice", sensors_output)
    else:
        for sensor_name in ["Accelerometer", "Gyroscope", "Magnetometer", "Proximity", "Light", "Barometer"]:
            if sensor_name.lower() not in sensors_output.lower():
                flag(SEVERITY_MEDIUM, "sensors", f"Missing sensor: {sensor_name}",
                     "Real devices have this sensor", f"Inject virtual {sensor_name}")
        # Check for suspiciously low sensor count
        sensor_lines = [l for l in sensors_output.split("\n") if "sensor" in l.lower() or "handle" in l.lower()]
        print(f"  sensor lines: {len(sensor_lines)}")
        if len(sensor_lines) < 5:
            flag(SEVERITY_HIGH, "sensors", f"Very few sensors detected ({len(sensor_lines)} lines)",
                 "Real phones have 15-30+ sensors", "VMOS may not emulate all sensors")


async def scan_sim_telephony():
    """Check SIM and telephony state."""
    print("\n[4/18] Scanning SIM / telephony...")
    tele = {
        "gsm.sim.state": await getprop("gsm.sim.state"),
        "gsm.sim.operator.alpha": await getprop("gsm.sim.operator.alpha"),
        "gsm.sim.operator.numeric": await getprop("gsm.sim.operator.numeric"),
        "gsm.sim.operator.iso-country": await getprop("gsm.sim.operator.iso-country"),
        "gsm.operator.alpha": await getprop("gsm.operator.alpha"),
        "gsm.operator.numeric": await getprop("gsm.operator.numeric"),
        "gsm.operator.iso-country": await getprop("gsm.operator.iso-country"),
        "gsm.network.type": await getprop("gsm.network.type"),
        "gsm.nitz.time": await getprop("gsm.nitz.time"),
        "persist.sys.cloud.imeinum": await getprop("persist.sys.cloud.imeinum"),
        "persist.sys.cloud.iccidnum": await getprop("persist.sys.cloud.iccidnum"),
        "persist.sys.cloud.imsinum": await getprop("persist.sys.cloud.imsinum"),
        "persist.sys.cloud.phonenum": await getprop("persist.sys.cloud.phonenum"),
        "persist.sys.cloud.mobileinfo": await getprop("persist.sys.cloud.mobileinfo"),
    }
    for k, v in tele.items():
        print(f"  {k} = {v!r}")

    if tele["gsm.sim.state"] != "READY":
        flag(SEVERITY_HIGH, "telephony", f"SIM not READY: {tele['gsm.sim.state']!r}",
             "Should be READY for US carrier", "Set gsm.sim.state=READY")

    if not tele["gsm.sim.operator.alpha"]:
        flag(SEVERITY_HIGH, "telephony", "No carrier name set",
             "gsm.sim.operator.alpha is empty", "Set to T-Mobile or AT&T")

    # Operator consistency
    sim_mccmnc = tele.get("gsm.sim.operator.numeric", "")
    net_mccmnc = tele.get("gsm.operator.numeric", "")
    if sim_mccmnc and net_mccmnc and sim_mccmnc != net_mccmnc:
        flag(SEVERITY_MEDIUM, "telephony", "SIM/network MCC-MNC mismatch",
             f"sim={sim_mccmnc}, network={net_mccmnc}")

    sim_country = tele.get("gsm.sim.operator.iso-country", "")
    net_country = tele.get("gsm.operator.iso-country", "")
    if sim_country and net_country and sim_country != net_country:
        flag(SEVERITY_HIGH, "telephony", "SIM/network country mismatch",
             f"sim_country={sim_country}, net_country={net_country}")

    imei = tele.get("persist.sys.cloud.imeinum", "")
    if not imei or len(imei) < 15:
        flag(SEVERITY_HIGH, "telephony", f"IMEI missing or invalid: {imei!r}",
             "Need valid 15-digit IMEI")

    net_type = tele.get("gsm.network.type", "")
    if not net_type or net_type == "0" or "unknown" in net_type.lower():
        flag(SEVERITY_MEDIUM, "telephony", f"No network type: {net_type!r}",
             "Should show LTE or NR", "Set gsm.network.type=LTE")


async def scan_network():
    """Check network configuration and proxy leaks."""
    print("\n[5/18] Scanning network / proxy...")
    net = await sh_multi({
        "ip_route": "ip route show 2>/dev/null | head -5",
        "dns_servers": "getprop net.dns1 && getprop net.dns2",
        "http_proxy": "settings get global http_proxy 2>/dev/null",
        "wifi_ip": "ip addr show wlan0 2>/dev/null | grep inet",
        "connectivity": "dumpsys connectivity 2>/dev/null | grep -i 'networktype\\|active' | head -10",
        "vpn_check": "dumpsys connectivity 2>/dev/null | grep -i vpn | head -5",
        "proxy_global": "settings get global global_http_proxy_host 2>/dev/null",
        "iptables": "iptables -t nat -L 2>/dev/null | head -10",
    })
    for k, v in net.items():
        print(f"  {k} = {v!r}")

    proxy = net.get("http_proxy", "")
    if proxy and proxy != "null" and proxy != ":0":
        flag(SEVERITY_MEDIUM, "network", f"HTTP proxy visible: {proxy}",
             "Proxy detectable via settings", "Clear global proxy after setting socks")

    # Check if DNS is suspicious (should match US)
    dns = net.get("dns_servers", "")
    if "8.8.8.8" in dns or "1.1.1.1" in dns:
        flag(SEVERITY_LOW, "network", "Generic DNS servers (8.8.8.8/1.1.1.1)",
             "Less suspicious but not carrier DNS", "Use carrier-specific DNS")

    vpn = net.get("vpn_check", "")
    if "VPN" in vpn.upper():
        flag(SEVERITY_MEDIUM, "network", "VPN detected in connectivity manager",
             vpn[:200], "Use proxy instead of VPN for stealth")


async def scan_system_apps():
    """Check for critical system apps presence."""
    print("\n[6/18] Scanning system apps...")
    apps = await sh_multi({
        "dialer": "pm list packages 2>/dev/null | grep -i 'dialer\\|phone\\|telecom'",
        "sms": "pm list packages 2>/dev/null | grep -i 'messaging\\|sms\\|mms'",
        "camera": "pm list packages 2>/dev/null | grep -i camera",
        "contacts": "pm list packages 2>/dev/null | grep -i contacts",
        "calendar": "pm list packages 2>/dev/null | grep -i calendar",
        "clock": "pm list packages 2>/dev/null | grep -i clock\\|deskclock",
        "files": "pm list packages 2>/dev/null | grep -i 'filemanager\\|files\\|documentsui'",
        "settings": "pm list packages 2>/dev/null | grep -i 'com.android.settings'",
        "gms": "pm list packages 2>/dev/null | grep -i 'com.google.android.gms'",
        "play_store": "pm list packages 2>/dev/null | grep -i 'com.android.vending'",
        "gmail": "pm list packages 2>/dev/null | grep -i 'com.google.android.gm'",
        "chrome": "pm list packages 2>/dev/null | grep -i 'com.android.chrome'",
        "youtube": "pm list packages 2>/dev/null | grep -i 'com.google.android.youtube'",
        "maps": "pm list packages 2>/dev/null | grep -i 'com.google.android.apps.maps'",
        "all_count": "pm list packages 2>/dev/null | wc -l",
    })
    for k, v in apps.items():
        print(f"  {k} = {v!r}")

    # Critical apps that must exist
    critical_apps = {
        "dialer": ("Phone/Dialer app", "Install com.google.android.dialer or com.android.phone"),
        "sms": ("SMS/Messaging app", "Install com.google.android.apps.messaging"),
        "camera": ("Camera app", "Install com.android.camera2 or com.google.android.GoogleCamera"),
        "contacts": ("Contacts app", "Install com.android.contacts"),
    }
    for key, (name, fix) in critical_apps.items():
        if not apps.get(key, "").strip():
            flag(SEVERITY_CRITICAL, "apps", f"MISSING: {name}",
                 f"No {name} found — instant VMOS detection!", fix)

    important_apps = {
        "gms": ("Google Play Services", "Install GMS"),
        "play_store": ("Google Play Store", "Install Play Store"),
        "chrome": ("Chrome browser", "Install Chrome"),
    }
    for key, (name, fix) in important_apps.items():
        if not apps.get(key, "").strip():
            flag(SEVERITY_HIGH, "apps", f"MISSING: {name}", f"No {name} installed", fix)

    # Package count check
    try:
        count = int(apps.get("all_count", "0").strip())
        print(f"  Total packages: {count}")
        if count < 80:
            flag(SEVERITY_HIGH, "apps", f"Very few packages installed ({count})",
                 "Real phones have 150-300+ packages", "Install more system apps")
        elif count < 120:
            flag(SEVERITY_MEDIUM, "apps", f"Below-average package count ({count})",
                 "Real phones typically have 150+")
    except ValueError:
        pass


async def scan_vmos_artifacts():
    """Check for VMOS-specific detectable artifacts."""
    print("\n[7/18] Scanning VMOS-specific artifacts...")
    vmos = await sh_multi({
        "vmos_packages": "pm list packages 2>/dev/null | grep -i vmos",
        "vmos_props": "getprop | grep -i vmos 2>/dev/null",
        "vmos_files": "ls -la /data/data/com.vmos* 2>/dev/null; ls -la /system/app/VMOS* 2>/dev/null; ls /system/bin/vmos* 2>/dev/null",
        "vmos_cloud_props": "getprop | grep -i 'cloud\\|armcloud\\|vcp' 2>/dev/null",
        "vm_detect_files": "ls /dev/goldfish_pipe 2>/dev/null; ls /dev/qemu_pipe 2>/dev/null; ls /dev/vport* 2>/dev/null",
        "proc_check": "cat /proc/cpuinfo 2>/dev/null | head -20",
        "mount_check": "mount 2>/dev/null | grep -i 'vmos\\|virtio\\|9p' | head -5",
    })
    for k, v in vmos.items():
        v_short = v[:500] if v else "(empty)"
        print(f"  {k} = {v_short!r}")

    if vmos.get("vmos_packages", "").strip():
        flag(SEVERITY_CRITICAL, "vmos", "VMOS packages detected",
             vmos["vmos_packages"], "Remove or hide VMOS packages")

    if vmos.get("vmos_props", "").strip():
        flag(SEVERITY_CRITICAL, "vmos", "VMOS properties visible",
             vmos["vmos_props"][:300], "Clear all VMOS-related props")

    if vmos.get("vmos_files", "").strip() and "No such file" not in vmos["vmos_files"]:
        flag(SEVERITY_CRITICAL, "vmos", "VMOS files found on filesystem",
             vmos["vmos_files"][:300], "Remove VMOS artifacts from filesystem")

    cloud_props = vmos.get("vmos_cloud_props", "")
    if cloud_props.strip():
        # Filter: persist.sys.cloud.* are expected (our injection props)
        non_inject = [l for l in cloud_props.split("\n") if l.strip() and
                      not any(ok in l for ok in ["persist.sys.cloud.gps", "persist.sys.cloud.battery",
                              "persist.sys.cloud.imeinum", "persist.sys.cloud.iccidnum",
                              "persist.sys.cloud.imsinum", "persist.sys.cloud.phonenum",
                              "persist.sys.cloud.mobileinfo", "persist.sys.cloud.rand_pics"])]
        if non_inject:
            flag(SEVERITY_HIGH, "vmos", "Unexpected cloud/VMOS props visible",
                 "\n".join(non_inject[:5]), "Hide or remove these props")

    # VM detection files
    vm_files = vmos.get("vm_detect_files", "")
    if vm_files.strip() and "No such file" not in vm_files:
        flag(SEVERITY_CRITICAL, "vmos", "VM device files found (/dev/goldfish_pipe etc)",
             vm_files, "These are instant VM detectors")

    # CPU info check
    cpu = vmos.get("proc_check", "")
    for vm_cpu in ["QEMU", "Virtual", "Emulat"]:
        if vm_cpu.lower() in cpu.lower():
            flag(SEVERITY_CRITICAL, "vmos", f"VM CPU in /proc/cpuinfo: {vm_cpu}",
                 cpu[:200], "CPU info reveals virtual environment")


async def scan_root_indicators():
    """Check for root/SU/Magisk indicators."""
    print("\n[8/18] Scanning root/SU indicators...")
    root = await sh_multi({
        "su_binary": "which su 2>/dev/null; ls /system/bin/su /system/xbin/su /sbin/su 2>/dev/null",
        "su_apps": "pm list packages 2>/dev/null | grep -i 'supersu\\|superuser\\|magisk\\|kingroot'",
        "magisk_files": "ls /data/adb/magisk 2>/dev/null; ls /cache/magisk* 2>/dev/null",
        "selinux": "getenforce 2>/dev/null",
        "root_prop": "getprop ro.debuggable",
        "test_su": "su -c id 2>&1 | head -3",
    })
    for k, v in root.items():
        print(f"  {k} = {v!r}")

    if root.get("su_binary", "").strip() and "not found" not in root["su_binary"].lower():
        flag(SEVERITY_CRITICAL, "root", "SU binary found",
             root["su_binary"], "Remove or hide su binary")

    if root.get("su_apps", "").strip():
        flag(SEVERITY_CRITICAL, "root", "Root manager app installed",
             root["su_apps"], "Uninstall root manager apps")

    if root.get("magisk_files", "").strip() and "No such file" not in root["magisk_files"]:
        flag(SEVERITY_CRITICAL, "root", "Magisk files detected", root["magisk_files"])

    selinux = root.get("selinux", "").strip()
    if selinux.lower() != "enforcing":
        flag(SEVERITY_HIGH, "root", f"SELinux not enforcing: {selinux!r}",
             "Must be 'Enforcing' on production devices", "Enable SELinux")

    if root.get("root_prop", "").strip() == "1":
        flag(SEVERITY_HIGH, "root", "ro.debuggable=1", "", "Set ro.debuggable=0")

    test_su = root.get("test_su", "")
    if "uid=0" in test_su:
        flag(SEVERITY_CRITICAL, "root", "SU command works (device is rooted)", test_su)


async def scan_adb_debug():
    """Check ADB and debugging state."""
    print("\n[9/18] Scanning ADB / debug state...")
    debug = await sh_multi({
        "adb_enabled": "settings get global adb_enabled 2>/dev/null",
        "dev_options": "settings get global development_settings_enabled 2>/dev/null",
        "usb_debug": "settings get global adb_wifi_enabled 2>/dev/null",
        "mock_location": "settings get secure mock_location 2>/dev/null",
        "install_unknown": "settings get secure install_non_market_apps 2>/dev/null",
    })
    for k, v in debug.items():
        print(f"  {k} = {v!r}")

    adb = debug.get("adb_enabled", "").strip()
    if adb == "1":
        flag(SEVERITY_HIGH, "debug", "ADB enabled",
             "adb_enabled=1", "settings put global adb_enabled 0")

    dev = debug.get("dev_options", "").strip()
    if dev == "1":
        flag(SEVERITY_MEDIUM, "debug", "Developer options enabled",
             "development_settings_enabled=1", "Disable developer options")

    mock = debug.get("mock_location", "").strip()
    if mock == "1":
        flag(SEVERITY_HIGH, "debug", "Mock location enabled",
             "This flags GPS spoofing", "settings put secure mock_location 0")


async def scan_boot_state():
    """Check verified boot and bootloader state."""
    print("\n[10/18] Scanning boot verification state...")
    boot = {
        "verified_boot": await getprop("ro.boot.verifiedbootstate"),
        "bootloader_locked": await getprop("ro.boot.flash.locked"),
        "boot_vbmeta_avb": await getprop("ro.boot.vbmeta.avb_version"),
        "dm_verity": await getprop("ro.boot.veritymode"),
        "secure_boot": await getprop("ro.secure"),
        "oem_unlock": await getprop("ro.oem_unlock_supported"),
    }
    for k, v in boot.items():
        print(f"  {k} = {v!r}")

    if boot["verified_boot"] != "green":
        flag(SEVERITY_HIGH, "boot", f"Verified boot not green: {boot['verified_boot']!r}",
             "Should be 'green' for locked bootloader", "Set ro.boot.verifiedbootstate=green")

    if boot["bootloader_locked"] != "1":
        flag(SEVERITY_HIGH, "boot", f"Bootloader not locked: {boot['bootloader_locked']!r}",
             "Should be '1'", "Set ro.boot.flash.locked=1")

    if boot["secure_boot"] != "1":
        flag(SEVERITY_HIGH, "boot", f"ro.secure not 1: {boot['secure_boot']!r}",
             "", "Set ro.secure=1")


async def scan_proc_sys():
    """Check /proc and /sys filesystem for VM leaks."""
    print("\n[11/18] Scanning /proc & /sys leaks...")
    proc = await sh_multi({
        "cmdline": "cat /proc/cmdline 2>/dev/null | head -5",
        "version": "cat /proc/version 2>/dev/null",
        "mounts": "cat /proc/mounts 2>/dev/null | grep -v 'proc\\|sys\\|dev\\|tmpfs' | head -10",
        "battery": "cat /sys/class/power_supply/battery/status 2>/dev/null; cat /sys/class/power_supply/battery/capacity 2>/dev/null",
        "thermal": "ls /sys/class/thermal/thermal_zone* 2>/dev/null | wc -l",
        "bluetooth": "ls /sys/class/bluetooth/ 2>/dev/null",
        "net_iface": "ls /sys/class/net/ 2>/dev/null",
        "display": "cat /sys/class/graphics/fb0/virtual_size 2>/dev/null || cat /sys/class/drm/card*/mode 2>/dev/null | head -3",
        "backing_dev": "cat /sys/block/*/device/vendor 2>/dev/null | head -3",
    })
    for k, v in proc.items():
        v_short = v[:300] if v else "(empty)"
        print(f"  {k} = {v_short!r}")

    cmdline = proc.get("cmdline", "")
    for vm_token in ["androidboot.hardware=goldfish", "androidboot.hardware=ranchu",
                     "qemu=", "vbox", "hypervisor"]:
        if vm_token.lower() in cmdline.lower():
            flag(SEVERITY_CRITICAL, "proc", f"VM indicator in /proc/cmdline: {vm_token}",
                 cmdline[:200], "Patch kernel cmdline")

    version = proc.get("version", "")
    if "android" not in version.lower() and not version:
        flag(SEVERITY_MEDIUM, "proc", "Kernel version missing or suspicious",
             version[:200])

    # Thermal zones (real phones have 20+)
    try:
        thermal_count = int(proc.get("thermal", "0").strip())
        if thermal_count < 5:
            flag(SEVERITY_MEDIUM, "proc", f"Few thermal zones ({thermal_count})",
                 "Real phones have 20-40+ thermal zones")
    except ValueError:
        pass

    # Network interfaces
    net = proc.get("net_iface", "")
    if "eth0" in net and "wlan0" not in net:
        flag(SEVERITY_HIGH, "proc", "Only eth0 network (no wlan0)",
             "Real phones have wlan0", "VMOS should emulate wlan0")

    battery = proc.get("battery", "")
    if not battery or "No such file" in battery:
        flag(SEVERITY_MEDIUM, "proc", "Battery sysfs missing",
             "Real phones have /sys/class/power_supply/battery/")


async def scan_timezone_locale():
    """Check timezone, locale, and DNS consistency."""
    print("\n[12/18] Scanning timezone / locale / DNS...")
    tz = await sh_multi({
        "timezone": "getprop persist.sys.timezone",
        "locale": "getprop persist.sys.locale",
        "language": "getprop persist.sys.language",
        "country": "getprop persist.sys.country",
        "date": "date",
        "dns1": "getprop net.dns1",
        "dns2": "getprop net.dns2",
        "wifi_country": "getprop ro.boot.wificountrycode",
    })
    for k, v in tz.items():
        print(f"  {k} = {v!r}")

    timezone = tz.get("timezone", "")
    locale = tz.get("locale", "")
    country = tz.get("country", "")
    wifi_cc = tz.get("wifi_country", "")

    # If US proxy is set, check US consistency
    if timezone and "America" not in timezone and "US" not in timezone:
        flag(SEVERITY_HIGH, "locale", f"Timezone not US: {timezone}",
             "With US proxy, timezone should be America/*", "Set persist.sys.timezone=America/New_York")

    if locale and "en" not in locale.lower() and "us" not in locale.lower():
        flag(SEVERITY_MEDIUM, "locale", f"Locale not English/US: {locale}",
             "", "Set persist.sys.locale=en-US")

    if country and country.lower() not in ["us", ""]:
        flag(SEVERITY_MEDIUM, "locale", f"Country not US: {country}",
             "", "Set persist.sys.country=US")

    if wifi_cc and wifi_cc.upper() != "US":
        flag(SEVERITY_MEDIUM, "locale", f"WiFi country code not US: {wifi_cc}",
             "", "Set ro.boot.wificountrycode=US")


async def scan_screen_display():
    """Check screen resolution and density."""
    print("\n[13/18] Scanning screen / display...")
    display = await sh_multi({
        "resolution": "wm size 2>/dev/null",
        "density": "wm density 2>/dev/null",
        "display_info": "dumpsys display 2>/dev/null | grep -i 'mBaseDisplayInfo\\|uniqueId\\|DisplayDeviceInfo' | head -10",
    })
    for k, v in display.items():
        print(f"  {k} = {v!r}")

    res = display.get("resolution", "")
    density = display.get("density", "")
    print(f"  Resolution: {res}, Density: {density}")

    # Check for suspicious display info containing VM indicators
    dinfo = display.get("display_info", "")
    for vm_ind in ["Built-in Screen", "virtual", "emulat"]:
        if vm_ind.lower() in dinfo.lower() and "Built-in" not in vm_ind:
            flag(SEVERITY_MEDIUM, "display", f"VM display indicator: {vm_ind}", dinfo[:200])


async def scan_gl_gpu():
    """Check OpenGL renderer and GPU info."""
    print("\n[14/18] Scanning GL/GPU info...")
    gl = await sh_multi({
        "gl_renderer": "getprop ro.hardware.egl",
        "gl_vendor": "dumpsys SurfaceFlinger 2>/dev/null | grep -i 'GLES\\|vendor\\|renderer' | head -5",
        "gpu_info": "getprop ro.hardware.vulkan",
    })
    for k, v in gl.items():
        print(f"  {k} = {v!r}")

    vendor = gl.get("gl_vendor", "")
    for vm_gl in ["SwiftShader", "LLVMpipe", "softpipe", "VirtualBox", "Emulator"]:
        if vm_gl.lower() in vendor.lower():
            flag(SEVERITY_CRITICAL, "gpu", f"Virtual GPU detected: {vm_gl}",
                 vendor[:200], "Real device should have Mali/Adreno/PowerVR")


async def scan_installed_packages():
    """Deep scan of installed packages for anomalies."""
    print("\n[15/18] Scanning installed packages...")
    pkgs = await sh_multi({
        "all_packages": "pm list packages 2>/dev/null",
        "system_packages": "pm list packages -s 2>/dev/null | wc -l",
        "third_party": "pm list packages -3 2>/dev/null",
        "disabled": "pm list packages -d 2>/dev/null",
        "vmos_related": "pm list packages 2>/dev/null | grep -iE 'vmos|vphone|nox|bluestack|geny|andy|ldplayer|memu'",
        "automation": "pm list packages 2>/dev/null | grep -iE 'appium|espresso|uiautomator|robotium|selendroid|frida'",
        "hooking": "pm list packages 2>/dev/null | grep -iE 'xposed|lsposed|edxposed|riru|zygisk'",
    })
    for k, v in pkgs.items():
        v_short = v[:500] if v else "(empty)"
        print(f"  {k} = {v_short!r}")

    if pkgs.get("vmos_related", "").strip():
        flag(SEVERITY_CRITICAL, "packages", "VM/emulator packages found",
             pkgs["vmos_related"], "Uninstall all VM-related packages")

    if pkgs.get("automation", "").strip():
        flag(SEVERITY_CRITICAL, "packages", "Automation framework packages found",
             pkgs["automation"], "Remove automation tools")

    if pkgs.get("hooking", "").strip():
        flag(SEVERITY_CRITICAL, "packages", "Hooking framework packages found",
             pkgs["hooking"], "Remove Xposed/LSPosed/etc")

    try:
        sys_count = int(pkgs.get("system_packages", "0").strip())
        if sys_count < 50:
            flag(SEVERITY_HIGH, "packages", f"Very few system packages ({sys_count})",
                 "Real phones have 100+ system packages")
    except ValueError:
        pass

    third = pkgs.get("third_party", "").strip()
    if not third:
        flag(SEVERITY_MEDIUM, "packages", "No third-party apps installed",
             "Real used phone has many apps installed")


async def scan_accounts():
    """Check Google and other accounts."""
    print("\n[16/18] Scanning accounts...")
    accounts = await sh_multi({
        "accounts": "dumpsys account 2>/dev/null | grep -i 'name=' | head -20",
        "google_account": "dumpsys account 2>/dev/null | grep -i 'com.google' | head -10",
        "account_count": "dumpsys account 2>/dev/null | grep -c 'Account {' 2>/dev/null || echo 0",
    })
    for k, v in accounts.items():
        print(f"  {k} = {v!r}")

    try:
        count = int(accounts.get("account_count", "0").strip())
        if count == 0:
            flag(SEVERITY_HIGH, "accounts", "No accounts registered",
                 "Real phones have at least 1 Google account", "Add a Google account")
    except ValueError:
        pass

    google = accounts.get("google_account", "")
    if not google.strip():
        flag(SEVERITY_HIGH, "accounts", "No Google account",
             "Most Android phones have a Google account signed in")


async def scan_usage_data():
    """Check for signs of genuine usage."""
    print("\n[17/18] Scanning usage data / history...")
    usage = await sh_multi({
        "contacts_count": "content query --uri content://contacts/phones 2>/dev/null | wc -l",
        "sms_count": "content query --uri content://sms 2>/dev/null | wc -l",
        "call_log_count": "content query --uri content://call_log/calls 2>/dev/null | wc -l",
        "media_count": "content query --uri content://media/external/images/media 2>/dev/null | wc -l",
        "downloads": "ls /sdcard/Download/ 2>/dev/null | wc -l",
        "wifi_networks": "dumpsys wifi 2>/dev/null | grep -i 'ConfigKey\\|SSID' | head -10",
        "app_usage": "dumpsys usagestats 2>/dev/null | grep 'package=' | head -20",
        "notifications": "dumpsys notification 2>/dev/null | grep -c 'StatusBarNotification' 2>/dev/null || echo 0",
    })
    for k, v in usage.items():
        v_short = v[:300] if v else "(empty)"
        print(f"  {k} = {v_short!r}")

    for key, name, threshold in [
        ("contacts_count", "contacts", 5),
        ("sms_count", "SMS messages", 3),
        ("call_log_count", "call log entries", 3),
        ("media_count", "photos/media", 5),
    ]:
        try:
            count = int(usage.get(key, "0").strip())
            if count < threshold:
                flag(SEVERITY_MEDIUM, "usage", f"Low {name} count: {count}",
                     f"Real phone should have {threshold}+", f"Inject more {name}")
        except ValueError:
            pass


async def scan_advanced_detection():
    """Advanced antifraud detection vectors."""
    print("\n[18/18] Scanning advanced detection vectors...")
    adv = await sh_multi({
        # Runtime checks
        "uptime": "cat /proc/uptime 2>/dev/null",
        "bootcount": "settings get global boot_count 2>/dev/null",
        # File system checks
        "system_rw": "mount 2>/dev/null | grep ' /system ' | head -1",
        "data_partition": "df /data 2>/dev/null | tail -1",
        # Input devices (touchscreen, etc)
        "input_devices": "cat /proc/bus/input/devices 2>/dev/null | grep -i 'Name\\|Handlers' | head -20",
        # Wi-Fi MAC
        "wifi_mac": "cat /sys/class/net/wlan0/address 2>/dev/null",
        # Android ID
        "android_id": "settings get secure android_id 2>/dev/null",
        # Accessibility
        "accessibility": "settings get secure enabled_accessibility_services 2>/dev/null",
        # Play Protect / SafetyNet hints
        "gms_version": "dumpsys package com.google.android.gms 2>/dev/null | grep versionName | head -1",
        # Screen lock
        "lockscreen": "settings get secure lockscreen.disabled 2>/dev/null",
        # Installation date of first app
        "first_install": "stat -c %y /data/data/com.android.settings 2>/dev/null || stat /data/data/com.android.settings 2>/dev/null | head -3",
    })
    for k, v in adv.items():
        v_short = v[:300] if v else "(empty)"
        print(f"  {k} = {v_short!r}")

    # Uptime check (too fresh = suspicious)
    uptime_str = adv.get("uptime", "")
    if uptime_str:
        try:
            up_secs = float(uptime_str.split()[0])
            up_hours = up_secs / 3600
            print(f"  Uptime: {up_hours:.1f} hours ({up_secs:.0f}s)")
            if up_hours < 1:
                flag(SEVERITY_LOW, "advanced", f"Very fresh device (uptime {up_hours:.1f}h)",
                     "A 'real' device should have days of uptime")
        except (ValueError, IndexError):
            pass

    # Boot count
    boot_count = adv.get("bootcount", "").strip()
    if boot_count and boot_count != "null":
        try:
            bc = int(boot_count)
            if bc < 5:
                flag(SEVERITY_LOW, "advanced", f"Low boot count: {bc}",
                     "Real phones rebooted many times")
        except ValueError:
            pass

    # System mounted read-write is suspicious
    sys_mount = adv.get("system_rw", "")
    if "rw" in sys_mount and "/system" in sys_mount:
        flag(SEVERITY_HIGH, "advanced", "/system mounted read-write",
             sys_mount, "Should be read-only")

    # Input devices should include touchscreen
    inputs = adv.get("input_devices", "")
    if "touch" not in inputs.lower() and "ts" not in inputs.lower():
        flag(SEVERITY_MEDIUM, "advanced", "No touchscreen in input devices",
             "Real phone has touchscreen input device")

    # WiFi MAC
    mac = adv.get("wifi_mac", "").strip()
    if mac:
        if mac.startswith("02:00:00") or mac == "00:00:00:00:00:00":
            flag(SEVERITY_HIGH, "advanced", f"Default/zeroed WiFi MAC: {mac}",
                 "", "Set a realistic MAC address")

    # Android ID
    aid = adv.get("android_id", "").strip()
    if not aid or aid == "null" or len(aid) < 10:
        flag(SEVERITY_HIGH, "advanced", f"Invalid Android ID: {aid!r}",
             "", "Generate valid 16-char hex Android ID")

    # Accessibility (automation detection)
    access = adv.get("accessibility", "").strip()
    if access and access != "null" and len(access) > 5:
        flag(SEVERITY_MEDIUM, "advanced", f"Accessibility services enabled: {access}",
             "May indicate automation")

    # GMS version
    if not adv.get("gms_version", "").strip():
        flag(SEVERITY_HIGH, "advanced", "Google Play Services version not found",
             "GMS may not be installed/working properly")

    # Lock screen
    lockscreen = adv.get("lockscreen", "").strip()
    if lockscreen == "1":
        flag(SEVERITY_LOW, "advanced", "Lock screen disabled",
             "Most real phones have a lock screen")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("  TITAN v11.3 — VMOS Device Forensic Anomaly Scanner")
    print(f"  Target: {PAD_CODE}")
    print("=" * 70)

    # First, verify device is alive
    print("\n[0/18] Checking device connectivity...")
    alive = await sh("echo ALIVE")
    if "ALIVE" not in alive:
        print(f"  ERROR: Device not responding: {alive}")
        print("  Cannot continue scan.")
        return

    print(f"  Device OK: {alive}")

    # Also get properties snapshot
    print("\nFetching device properties from VMOS API...")
    props = await bridge.get_instance_properties(PAD_CODE)
    if props:
        # Print key props
        key_props = {}
        if isinstance(props, dict):
            for section_name, section_data in props.items():
                if isinstance(section_data, dict):
                    for k, v in section_data.items():
                        if any(kw in k.lower() for kw in ["brand", "model", "device", "fingerprint",
                               "carrier", "imei", "build", "version", "manufacturer"]):
                            key_props[k] = v
        if key_props:
            print(f"  Key API properties ({len(key_props)}):")
            for k, v in list(key_props.items())[:20]:
                print(f"    {k} = {v!r}")
    else:
        print("  (No properties from API)")

    # Run all scans
    t0 = time.time()
    await scan_emulator_props()
    await scan_build_fingerprint()
    await scan_sensors()
    await scan_sim_telephony()
    await scan_network()
    await scan_system_apps()
    await scan_vmos_artifacts()
    await scan_root_indicators()
    await scan_adb_debug()
    await scan_boot_state()
    await scan_proc_sys()
    await scan_timezone_locale()
    await scan_screen_display()
    await scan_gl_gpu()
    await scan_installed_packages()
    await scan_accounts()
    await scan_usage_data()
    await scan_advanced_detection()
    elapsed = time.time() - t0

    # ═══════ REPORT ═══════
    print("\n" + "=" * 70)
    print("  ANOMALY SCAN REPORT")
    print("=" * 70)

    # Count by severity
    sev_counts = {}
    for f in findings:
        s = f["severity"]
        sev_counts[s] = sev_counts.get(s, 0) + 1

    total = len(findings)
    crit = sev_counts.get(SEVERITY_CRITICAL, 0)
    high = sev_counts.get(SEVERITY_HIGH, 0)
    med = sev_counts.get(SEVERITY_MEDIUM, 0)
    low = sev_counts.get(SEVERITY_LOW, 0)
    info = sev_counts.get(SEVERITY_INFO, 0)

    print(f"\n  Total findings: {total}")
    print(f"  🔴 CRITICAL: {crit}")
    print(f"  🟠 HIGH:     {high}")
    print(f"  🟡 MEDIUM:   {med}")
    print(f"  🟢 LOW:      {low}")
    print(f"  ⚪ INFO:     {info}")
    print(f"  Scan time:   {elapsed:.1f}s")

    # Detection risk score (0-100, lower is better)
    risk_score = min(100, crit * 20 + high * 10 + med * 5 + low * 2 + info)
    print(f"\n  DETECTION RISK SCORE: {risk_score}/100", end="")
    if risk_score > 70:
        print(" — ❌ EASILY DETECTABLE")
    elif risk_score > 40:
        print(" — ⚠️ MODERATE RISK")
    elif risk_score > 15:
        print(" — 🔶 LOW RISK")
    else:
        print(" — ✅ STEALTH")

    # Print findings grouped by severity
    for sev in [SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW, SEVERITY_INFO]:
        sev_findings = [f for f in findings if f["severity"] == sev]
        if not sev_findings:
            continue
        print(f"\n  ── {sev} ({len(sev_findings)}) ──")
        for i, f in enumerate(sev_findings, 1):
            print(f"  {i}. [{f['category']}] {f['title']}")
            if f["detail"]:
                detail = f["detail"][:150].replace("\n", " ")
                print(f"     Detail: {detail}")
            if f["fix_hint"]:
                print(f"     Fix: {f['fix_hint']}")

    # Save JSON report
    report = {
        "device": PAD_CODE,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scan_time_seconds": round(elapsed, 1),
        "risk_score": risk_score,
        "summary": {
            "total": total,
            "critical": crit,
            "high": high,
            "medium": med,
            "low": low,
            "info": info,
        },
        "findings": findings,
    }
    report_path = os.path.join(os.path.dirname(__file__), f"anomaly_report_{PAD_CODE}.json")
    with open(report_path, "w") as fp:
        json.dump(report, fp, indent=2)
    print(f"\n  Full report saved to: {report_path}")

    return report

if __name__ == "__main__":
    asyncio.run(main())
