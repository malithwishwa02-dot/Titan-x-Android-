#!/usr/bin/env python3
"""
Titan V11.3 — VMOS Device Fast Anomaly Scanner (Single-Shot)
=============================================================
Runs a single mega shell command that collects ALL device data at once,
then analyzes the output locally. Much faster than individual API calls.
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from vmos_cloud_bridge import VMOSCloudBridge

PAD_CODE = os.environ.get("VMOS_PAD_CODE", "ACP2509244LGV1MV")
API_KEY = os.environ.get("VMOS_API_KEY", "BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi")
API_SECRET = os.environ.get("VMOS_API_SECRET", "Q2SgcSwEfuwoedY0cijp6Mce")

bridge = VMOSCloudBridge(api_key=API_KEY, api_secret=API_SECRET)

# All checks in one mega script - uses delimiters to parse
MEGA_SCRIPT = r"""
echo "===SECTION:emulator_props==="
getprop ro.kernel.qemu
echo "---"
getprop ro.hardware.virtual
echo "---"
getprop ro.hardware
echo "---"
getprop ro.product.board
echo "---"
getprop ro.boot.hardware
echo "---"
getprop init.svc.goldfish-logcat
echo "---"
getprop init.svc.goldfish-setup
echo "---"
getprop ro.build.flavor
echo "---"
getprop gsm.version.ril-impl
echo "---"
getprop ro.boot.serialno
echo "---"
getprop ro.serialno

echo "===SECTION:fingerprint==="
getprop ro.build.fingerprint
echo "---"
getprop ro.odm.build.fingerprint
echo "---"
getprop ro.product.build.fingerprint
echo "---"
getprop ro.system.build.fingerprint
echo "---"
getprop ro.vendor.build.fingerprint
echo "---"
getprop ro.build.type
echo "---"
getprop ro.build.tags
echo "---"
getprop ro.product.brand
echo "---"
getprop ro.product.model
echo "---"
getprop ro.product.device
echo "---"
getprop ro.product.manufacturer
echo "---"
getprop ro.build.version.release
echo "---"
getprop ro.build.version.sdk
echo "---"
getprop ro.build.version.security_patch
echo "---"
getprop ro.build.display.id

echo "===SECTION:telephony==="
getprop gsm.sim.state
echo "---"
getprop gsm.sim.operator.alpha
echo "---"
getprop gsm.sim.operator.numeric
echo "---"
getprop gsm.sim.operator.iso-country
echo "---"
getprop gsm.operator.alpha
echo "---"
getprop gsm.operator.numeric
echo "---"
getprop gsm.operator.iso-country
echo "---"
getprop gsm.network.type
echo "---"
getprop persist.sys.cloud.imeinum
echo "---"
getprop persist.sys.cloud.iccidnum
echo "---"
getprop persist.sys.cloud.imsinum
echo "---"
getprop persist.sys.cloud.phonenum
echo "---"
getprop persist.sys.cloud.mobileinfo

echo "===SECTION:network==="
ip route show 2>/dev/null | head -5
echo "---"
settings get global http_proxy 2>/dev/null
echo "---"
ip addr show wlan0 2>/dev/null | grep inet
echo "---"
ip addr show eth0 2>/dev/null | grep inet
echo "---"
getprop net.dns1
echo "---"
getprop net.dns2
echo "---"
iptables -t nat -L OUTPUT 2>/dev/null | head -10
echo "---"
cat /proc/net/tcp 2>/dev/null | head -5

echo "===SECTION:apps==="
pm list packages 2>/dev/null | grep -iE 'dialer|phone|telecom' || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep -iE 'messaging|sms|mms' || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep -i camera || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep -i contacts || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep -i clock || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep -iE 'filemanager|files|documentsui' || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep 'com.google.android.gms' || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep 'com.android.vending' || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep 'com.android.chrome' || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep 'com.google.android.youtube' || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep 'com.google.android.apps.maps' || echo "(none)"
echo "---"
pm list packages 2>/dev/null | wc -l
echo "---"
pm list packages -s 2>/dev/null | wc -l
echo "---"
pm list packages -3 2>/dev/null | wc -l

echo "===SECTION:vmos==="
pm list packages 2>/dev/null | grep -iE 'vmos|vphone|nox|bluestack|geny|andy|ldplayer|memu' || echo "(none)"
echo "---"
getprop 2>/dev/null | grep -i vmos || echo "(none)"
echo "---"
ls /data/data/com.vmos* 2>/dev/null; ls /system/app/VMOS* 2>/dev/null; ls /system/bin/vmos* 2>/dev/null || echo "(none)"
echo "---"
getprop 2>/dev/null | grep -iE 'cloud|armcloud|vcp' || echo "(none)"
echo "---"
ls /dev/goldfish_pipe /dev/qemu_pipe /dev/vport* 2>/dev/null || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep -iE 'xposed|lsposed|edxposed|riru|zygisk|frida|appium' || echo "(none)"

echo "===SECTION:root==="
which su 2>/dev/null || echo "(none)"
echo "---"
ls /system/bin/su /system/xbin/su /sbin/su 2>/dev/null || echo "(none)"
echo "---"
pm list packages 2>/dev/null | grep -iE 'supersu|superuser|magisk|kingroot' || echo "(none)"
echo "---"
getenforce 2>/dev/null
echo "---"
getprop ro.debuggable
echo "---"
getprop ro.secure

echo "===SECTION:debug==="
settings get global adb_enabled 2>/dev/null
echo "---"
settings get global development_settings_enabled 2>/dev/null
echo "---"
settings get secure mock_location 2>/dev/null
echo "---"
settings get secure install_non_market_apps 2>/dev/null

echo "===SECTION:boot==="
getprop ro.boot.verifiedbootstate
echo "---"
getprop ro.boot.flash.locked
echo "---"
getprop ro.boot.vbmeta.avb_version
echo "---"
getprop ro.boot.veritymode

echo "===SECTION:proc==="
cat /proc/cmdline 2>/dev/null | head -3
echo "---"
cat /proc/version 2>/dev/null | head -2
echo "---"
cat /sys/class/power_supply/battery/status 2>/dev/null || echo "(none)"
echo "---"
cat /sys/class/power_supply/battery/capacity 2>/dev/null || echo "(none)"
echo "---"
ls /sys/class/thermal/thermal_zone* 2>/dev/null | wc -l
echo "---"
ls /sys/class/net/ 2>/dev/null
echo "---"
cat /proc/cpuinfo 2>/dev/null | head -5

echo "===SECTION:locale==="
getprop persist.sys.timezone
echo "---"
getprop persist.sys.locale
echo "---"
getprop persist.sys.country
echo "---"
date
echo "---"
getprop ro.boot.wificountrycode

echo "===SECTION:display==="
wm size 2>/dev/null
echo "---"
wm density 2>/dev/null

echo "===SECTION:gpu==="
getprop ro.hardware.egl
echo "---"
dumpsys SurfaceFlinger 2>/dev/null | grep -iE 'GLES|vendor|renderer' | head -5
echo "---"
getprop ro.hardware.vulkan

echo "===SECTION:accounts==="
dumpsys account 2>/dev/null | grep -c 'Account {' || echo "0"
echo "---"
dumpsys account 2>/dev/null | grep 'com.google' | head -5 || echo "(none)"

echo "===SECTION:usage==="
content query --uri content://contacts/phones 2>/dev/null | wc -l
echo "---"
content query --uri content://sms 2>/dev/null | wc -l
echo "---"
content query --uri content://call_log/calls 2>/dev/null | wc -l
echo "---"
content query --uri content://media/external/images/media 2>/dev/null | wc -l
echo "---"
ls /sdcard/Download/ 2>/dev/null | wc -l

echo "===SECTION:advanced==="
cat /proc/uptime 2>/dev/null
echo "---"
settings get global boot_count 2>/dev/null
echo "---"
mount 2>/dev/null | grep ' /system '
echo "---"
cat /proc/bus/input/devices 2>/dev/null | grep -iE 'Name|Handlers' | head -10
echo "---"
cat /sys/class/net/wlan0/address 2>/dev/null
echo "---"
settings get secure android_id 2>/dev/null
echo "---"
settings get secure enabled_accessibility_services 2>/dev/null
echo "---"
dumpsys package com.google.android.gms 2>/dev/null | grep versionName | head -1
echo "---"
settings get secure lockscreen.disabled 2>/dev/null
echo "---"
dumpsys sensorservice 2>/dev/null | head -50

echo "===END==="
"""

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"
SEVERITY_INFO = "INFO"

findings = []

def flag(severity, category, title, detail, fix_hint=""):
    findings.append({
        "severity": severity,
        "category": category,
        "title": title,
        "detail": detail[:500],
        "fix_hint": fix_hint,
    })


def parse_sections(raw: str) -> dict:
    """Parse mega-script output into sections."""
    sections = {}
    current_section = None
    current_lines = []
    
    for line in raw.split("\n"):
        if line.startswith("===SECTION:") and line.endswith("==="):
            if current_section:
                sections[current_section] = current_lines
            current_section = line.replace("===SECTION:", "").replace("===", "")
            current_lines = []
        elif line == "===END===":
            if current_section:
                sections[current_section] = current_lines
            break
        else:
            current_lines.append(line)
    
    return sections


def split_fields(lines: list) -> list:
    """Split section lines by --- delimiter."""
    fields = []
    current = []
    for line in lines:
        if line.strip() == "---":
            fields.append("\n".join(current).strip())
            current = []
        else:
            current.append(line)
    if current:
        fields.append("\n".join(current).strip())
    return fields


def analyze_emulator(fields):
    """Analyze emulator props."""
    labels = ["ro.kernel.qemu", "ro.hardware.virtual", "ro.hardware", 
              "ro.product.board", "ro.boot.hardware", "init.svc.goldfish-logcat",
              "init.svc.goldfish-setup", "ro.build.flavor", "gsm.version.ril-impl",
              "ro.boot.serialno", "ro.serialno"]
    
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val!r}")
    
    qemu = fields[0] if fields else ""
    if qemu == "1":
        flag(SEVERITY_CRITICAL, "emulator", "QEMU detected", "ro.kernel.qemu=1")
    
    hw_virtual = fields[1] if len(fields) > 1 else ""
    if "virtual" in hw_virtual.lower():
        flag(SEVERITY_CRITICAL, "emulator", "Virtual hardware flag", hw_virtual)
    
    goldfish1 = fields[5] if len(fields) > 5 else ""
    goldfish2 = fields[6] if len(fields) > 6 else ""
    if goldfish1:
        flag(SEVERITY_CRITICAL, "emulator", "Goldfish service", goldfish1)
    if goldfish2:
        flag(SEVERITY_CRITICAL, "emulator", "Goldfish setup", goldfish2)
    
    hw = fields[2] if len(fields) > 2 else ""
    board = fields[3] if len(fields) > 3 else ""
    for bad in ["goldfish", "ranchu", "vbox", "nox", "bluestacks", "genymotion", "cuttlefish", "vsoc"]:
        if bad in hw.lower() or bad in board.lower():
            flag(SEVERITY_CRITICAL, "emulator", f"VM hardware: {bad}", f"hw={hw}, board={board}")
    
    flavor = fields[7] if len(fields) > 7 else ""
    if "eng" in flavor or "userdebug" in flavor:
        flag(SEVERITY_HIGH, "emulator", f"Non-prod build: {flavor}", "")
    
    ril = fields[8] if len(fields) > 8 else ""
    if not ril or "reference" in ril.lower() or "emulat" in ril.lower():
        flag(SEVERITY_HIGH, "emulator", f"Missing/fake RIL: {ril!r}", "No baseband = no real modem", "VMOS lacks real telephony stack")
    
    serial = (fields[9] if len(fields) > 9 else "") or (fields[10] if len(fields) > 10 else "")
    if not serial or serial == "unknown" or serial.startswith("EMULATOR"):
        flag(SEVERITY_HIGH, "emulator", f"Missing serial: {serial!r}", "", "Set realistic serial number")


def analyze_fingerprint(fields):
    """Analyze build fingerprint."""
    labels = ["ro.build.fingerprint", "ro.odm.build.fingerprint", "ro.product.build.fingerprint",
              "ro.system.build.fingerprint", "ro.vendor.build.fingerprint", "ro.build.type",
              "ro.build.tags", "ro.product.brand", "ro.product.model", "ro.product.device",
              "ro.product.manufacturer", "ro.build.version.release", "ro.build.version.sdk",
              "ro.build.version.security_patch", "ro.build.display.id"]
    
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val!r}")
    
    fp = fields[0] if fields else ""
    brand = fields[7] if len(fields) > 7 else ""
    model = fields[8] if len(fields) > 8 else ""
    build_type = fields[5] if len(fields) > 5 else ""
    tags = fields[6] if len(fields) > 6 else ""
    
    if not fp or len(fp) < 20:
        flag(SEVERITY_CRITICAL, "fingerprint", "Missing fingerprint", fp)
    elif brand and brand.lower() not in fp.lower():
        flag(SEVERITY_CRITICAL, "fingerprint", "Brand mismatch in fingerprint", f"brand={brand}, fp={fp[:80]}")
    
    # Cross-partition fingerprint check
    fps = [fields[i] for i in range(5) if i < len(fields) and fields[i]]
    unique_fps = set(fps)
    if len(unique_fps) > 1:
        flag(SEVERITY_HIGH, "fingerprint", f"Fingerprint mismatch across {len(unique_fps)} partitions",
             "\n".join(f"  {labels[i]}={fields[i][:60]}" for i in range(min(5, len(fields))) if fields[i]))
    
    if build_type != "user":
        flag(SEVERITY_HIGH, "fingerprint", f"Build type '{build_type}' (not user)", "")
    
    if "release-keys" not in tags:
        flag(SEVERITY_HIGH, "fingerprint", f"Tags: {tags} (missing release-keys)", "")
    
    # VMOS default identity detection (informational — template identity is locked)
    VMOS_TEMPLATE_INDICATORS = ["vivo", "V2408A", "PD2408"]
    VMOS_KNOWN_TEMPLATES = ["PKX110", "OP60F5L1", "V2408A"]  # Known VMOS hypervisor-locked models
    is_vmos_template = model in VMOS_KNOWN_TEMPLATES
    for indicator in VMOS_TEMPLATE_INDICATORS:
        if indicator.lower() in fp.lower():
            if is_vmos_template:
                flag(SEVERITY_INFO, "fingerprint", f"VMOS template identity: '{indicator}' (locked, cannot change)",
                     f"Hypervisor-locked template — focus on other stealth dimensions")
            else:
                flag(SEVERITY_CRITICAL, "fingerprint", f"VMOS DEFAULT IDENTITY: '{indicator}' in fingerprint",
                     f"This is the stock VMOS device identity — must be changed!", "Apply device identity patch")
    
    if model and model in VMOS_KNOWN_TEMPLATES:
        flag(SEVERITY_INFO, "fingerprint", f"VMOS template model: {model}",
             "Hypervisor-locked model — cannot be changed via API or shell")


def analyze_telephony(fields):
    """Analyze telephony/SIM."""
    labels = ["gsm.sim.state", "gsm.sim.operator.alpha", "gsm.sim.operator.numeric",
              "gsm.sim.operator.iso-country", "gsm.operator.alpha", "gsm.operator.numeric",
              "gsm.operator.iso-country", "gsm.network.type", "persist.sys.cloud.imeinum",
              "persist.sys.cloud.iccidnum", "persist.sys.cloud.imsinum", "persist.sys.cloud.phonenum",
              "persist.sys.cloud.mobileinfo"]
    
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val!r}")
    
    sim_state = fields[0] if fields else ""
    carrier = fields[1] if len(fields) > 1 else ""
    sim_mccmnc = fields[2] if len(fields) > 2 else ""
    sim_country = fields[3] if len(fields) > 3 else ""
    net_carrier = fields[4] if len(fields) > 4 else ""
    net_mccmnc = fields[5] if len(fields) > 5 else ""
    net_country = fields[6] if len(fields) > 6 else ""
    net_type = fields[7] if len(fields) > 7 else ""
    imei = fields[8] if len(fields) > 8 else ""
    mobileinfo = fields[12] if len(fields) > 12 else ""
    
    if sim_state != "READY":
        flag(SEVERITY_HIGH, "telephony", f"SIM not READY: {sim_state!r}", "", "Set gsm.sim.state=READY")
    if not carrier:
        flag(SEVERITY_HIGH, "telephony", "No carrier name", "gsm.sim.operator.alpha empty", "Set carrier name")
    if not sim_mccmnc:
        flag(SEVERITY_HIGH, "telephony", "No SIM MCC/MNC", "", "Set gsm.sim.operator.numeric")
    
    if sim_country and net_country and sim_country != net_country:
        flag(SEVERITY_HIGH, "telephony", f"SIM/network country mismatch: {sim_country} vs {net_country}", "")
    
    if not net_type or net_type == "Unknown" or net_type == "0":
        flag(SEVERITY_MEDIUM, "telephony", f"No network type: {net_type!r}", "", "Set gsm.network.type=LTE")
    
    if not imei or len(imei) < 15:
        flag(SEVERITY_HIGH, "telephony", f"IMEI missing/invalid: {imei!r}", "")
    
    # Malaysian SIM with US proxy = instant detection
    if mobileinfo and ("502" in mobileinfo or "my" in sim_country.lower()):
        flag(SEVERITY_CRITICAL, "telephony", f"MALAYSIAN SIM detected: MCC/MNC={mobileinfo}",
             "502=Malaysia. With US proxy, this is a fatal mismatch!", "Change to US carrier (310/260 T-Mobile)")
    
    if sim_country and sim_country.lower() == "my":
        flag(SEVERITY_CRITICAL, "telephony", f"SIM country=MY (Malaysia)",
             "Must match proxy country (US)", "Set gsm.sim.operator.iso-country=us")


def analyze_network(fields):
    """Analyze network config."""
    labels = ["ip_route", "http_proxy", "wlan0_ip", "eth0_ip", "dns1", "dns2", "iptables_nat", "proc_net_tcp"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val[:200]!r}")
    
    proxy = fields[1] if len(fields) > 1 else ""
    if proxy and proxy not in ("null", ":0", ""):
        flag(SEVERITY_MEDIUM, "network", f"HTTP proxy visible: {proxy}", "Detectable via settings")
    
    routes = fields[0] if fields else ""
    if "eth0" in routes:
        flag(SEVERITY_HIGH, "network", "eth0 in routing table",
             "Cloud devices have eth0 — real phones don't", "VMOS artifact: eth0 visible in routes")


def analyze_apps(fields):
    """Analyze system apps."""
    labels = ["dialer", "sms", "camera", "contacts", "clock", "files", "gms", 
              "play_store", "chrome", "youtube", "maps", "all_count", "system_count", "third_party_count"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val[:200]!r}")
    
    dialer = fields[0] if fields else ""
    sms = fields[1] if len(fields) > 1 else ""
    camera = fields[2] if len(fields) > 2 else ""
    youtube = fields[9] if len(fields) > 9 else ""
    maps = fields[10] if len(fields) > 10 else ""
    
    if "(none)" in dialer or not dialer.strip():
        flag(SEVERITY_CRITICAL, "apps", "NO PHONE/DIALER APP",
             "Every real phone has a dialer — this is instant VMOS detection!",
             "Install com.google.android.dialer")
    
    if "(none)" in sms or not sms.strip():
        flag(SEVERITY_CRITICAL, "apps", "NO SMS/MESSAGING APP",
             "Every real phone has an SMS app — instant detection!",
             "Install com.google.android.apps.messaging")
    
    if "(none)" in camera or "cameraextensions" in camera and "camera2" not in camera:
        flag(SEVERITY_HIGH, "apps", "No camera app (only extensions)", camera)
    
    if "(none)" in youtube:
        flag(SEVERITY_MEDIUM, "apps", "YouTube not installed", "Most phones have YouTube")
    
    if "(none)" in maps:
        flag(SEVERITY_MEDIUM, "apps", "Google Maps not installed", "Most phones have Maps")
    
    try:
        total = int(fields[11].strip()) if len(fields) > 11 else 0
        system = int(fields[12].strip()) if len(fields) > 12 else 0
        third = int(fields[13].strip()) if len(fields) > 13 else 0
        print(f"  Total: {total}, System: {system}, Third-party: {third}")
        
        if total < 80:
            flag(SEVERITY_HIGH, "apps", f"Very few packages ({total})", "Real phones: 150-300+")
        elif total < 120:
            flag(SEVERITY_MEDIUM, "apps", f"Below-average packages ({total})", "Real phones: 150+")
        
        if third < 5:
            flag(SEVERITY_MEDIUM, "apps", f"Almost no third-party apps ({third})", "Real used phones have many apps")
    except ValueError:
        pass


def analyze_vmos(fields):
    """Analyze VMOS-specific artifacts."""
    labels = ["vm_packages", "vmos_props", "vmos_files", "cloud_props", "vm_devices", "hooking_packages"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val[:300]!r}")
    
    vm_pkgs = fields[0] if fields else ""
    if "(none)" not in vm_pkgs and vm_pkgs.strip():
        flag(SEVERITY_CRITICAL, "vmos", "VM/emulator packages found", vm_pkgs)
    
    vmos_props = fields[1] if len(fields) > 1 else ""
    if "(none)" not in vmos_props and vmos_props.strip():
        flag(SEVERITY_CRITICAL, "vmos", "VMOS properties visible in getprop", vmos_props[:300])
    
    vmos_files = fields[2] if len(fields) > 2 else ""
    if "(none)" not in vmos_files and vmos_files.strip():
        flag(SEVERITY_CRITICAL, "vmos", "VMOS files on filesystem", vmos_files[:300])
    
    cloud_props = fields[3] if len(fields) > 3 else ""
    if "(none)" not in cloud_props and cloud_props.strip():
        # Filter expected injection props
        lines = [l for l in cloud_props.split("\n") if l.strip() and
                 not any(ok in l for ok in ["gps", "battery", "imeinum", "iccidnum",
                         "imsinum", "phonenum", "mobileinfo", "rand_pics"])]
        if lines:
            flag(SEVERITY_HIGH, "vmos", "Unexpected cloud properties", "\n".join(lines[:5]))
    
    vm_dev = fields[4] if len(fields) > 4 else ""
    if "(none)" not in vm_dev and vm_dev.strip():
        flag(SEVERITY_CRITICAL, "vmos", "VM device files (/dev/goldfish_pipe etc)", vm_dev)
    
    hooking = fields[5] if len(fields) > 5 else ""
    if "(none)" not in hooking and hooking.strip():
        flag(SEVERITY_CRITICAL, "vmos", "Hooking/automation frameworks found", hooking)


def analyze_root(fields):
    labels = ["which_su", "su_paths", "root_apps", "selinux", "debuggable", "secure"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val!r}")
    
    su = fields[0] if fields else ""
    if "(none)" not in su and su.strip():
        flag(SEVERITY_CRITICAL, "root", "SU binary found", su)
    
    su_paths = fields[1] if len(fields) > 1 else ""
    if "(none)" not in su_paths and su_paths.strip():
        flag(SEVERITY_CRITICAL, "root", "SU at known paths", su_paths)
    
    root_apps = fields[2] if len(fields) > 2 else ""
    if "(none)" not in root_apps and root_apps.strip():
        flag(SEVERITY_CRITICAL, "root", "Root manager apps", root_apps)
    
    selinux = fields[3] if len(fields) > 3 else ""
    if selinux.strip().lower() != "enforcing":
        flag(SEVERITY_HIGH, "root", f"SELinux: {selinux!r} (not Enforcing)", "")
    
    if (fields[4] if len(fields) > 4 else "").strip() == "1":
        flag(SEVERITY_HIGH, "root", "ro.debuggable=1", "")
    
    if (fields[5] if len(fields) > 5 else "").strip() != "1":
        flag(SEVERITY_HIGH, "root", f"ro.secure not 1", "")


def analyze_debug(fields):
    labels = ["adb_enabled", "dev_options", "mock_location", "install_unknown"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val!r}")
    
    if (fields[0] if fields else "").strip() == "1":
        flag(SEVERITY_HIGH, "debug", "ADB enabled", "")
    if (fields[1] if len(fields) > 1 else "").strip() == "1":
        flag(SEVERITY_MEDIUM, "debug", "Developer options enabled", "")
    if (fields[2] if len(fields) > 2 else "").strip() == "1":
        flag(SEVERITY_HIGH, "debug", "Mock location enabled", "Flags GPS spoofing")


def analyze_boot(fields):
    labels = ["verifiedboot", "flash_locked", "avb_version", "veritymode"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val!r}")
    
    vb = (fields[0] if fields else "").strip()
    if vb != "green":
        flag(SEVERITY_HIGH, "boot", f"Verified boot: {vb!r} (not green)", "")
    
    locked = (fields[1] if len(fields) > 1 else "").strip()
    if locked != "1":
        flag(SEVERITY_HIGH, "boot", f"Bootloader not locked: {locked!r}", "")


def analyze_proc(fields):
    labels = ["cmdline", "kernel_version", "battery_status", "battery_capacity", "thermal_zones", "net_ifaces", "cpuinfo"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val[:200]!r}")
    
    cmdline = fields[0] if fields else ""
    for tok in ["goldfish", "ranchu", "qemu=", "hypervisor", "vbox"]:
        if tok.lower() in cmdline.lower():
            flag(SEVERITY_CRITICAL, "proc", f"VM token in cmdline: {tok}", cmdline[:200])
    
    if "verifiedbootstate=orange" in cmdline:
        flag(SEVERITY_HIGH, "proc", "Boot state ORANGE in cmdline",
             "Unlocked bootloader signature in kernel cmdline", "Should be green")
    
    if "storagemedia=emmc" in cmdline:
        flag(SEVERITY_INFO, "proc", "Storage=emmc in cmdline", "Normal for ARM devices")
    
    thermal = fields[4] if len(fields) > 4 else "0"
    try:
        tz = int(thermal.strip())
        if tz < 5:
            flag(SEVERITY_MEDIUM, "proc", f"Few thermal zones ({tz})", "Real phones: 20-40+")
    except ValueError:
        pass
    
    net = fields[5] if len(fields) > 5 else ""
    if "eth0" in net:
        flag(SEVERITY_HIGH, "proc", "eth0 network interface present",
             "Real phones don't have eth0 — cloud VM indicator", "Cannot easily hide eth0")
    
    battery_status = fields[2] if len(fields) > 2 else ""
    battery_cap = fields[3] if len(fields) > 3 else ""
    if "(none)" in battery_status:
        flag(SEVERITY_MEDIUM, "proc", "No battery sysfs", "")
    else:
        print(f"  Battery: {battery_status}, {battery_cap}%")


def analyze_locale(fields):
    labels = ["timezone", "locale", "country", "date", "wifi_country"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val!r}")
    
    tz = fields[0] if fields else ""
    country = fields[2] if len(fields) > 2 else ""
    wifi_cc = fields[4] if len(fields) > 4 else ""
    
    if tz and "America" not in tz and "US" not in tz:
        flag(SEVERITY_HIGH, "locale", f"Timezone {tz} (not US)",
             "With US proxy, timezone should be America/*",
             "Set persist.sys.timezone=America/New_York")
    
    if country and country.upper() not in ("US", ""):
        flag(SEVERITY_MEDIUM, "locale", f"Country={country} (not US)", "")
    
    if wifi_cc and wifi_cc.upper() != "US":
        flag(SEVERITY_MEDIUM, "locale", f"WiFi country={wifi_cc!r}", "Should be US")
    
    # Check if timezone matches proxy location
    if "Kuala_Lumpur" in tz or "Asia" in tz:
        flag(SEVERITY_CRITICAL, "locale", f"ASIAN TIMEZONE WITH US PROXY: {tz}",
             "Fatal mismatch — timezone reveals real server location!",
             "Set timezone to America/New_York or America/Chicago")


def analyze_display(fields):
    labels = ["wm_size", "wm_density"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val!r}")


def analyze_gpu(fields):
    labels = ["egl", "gles_info", "vulkan"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val[:200]!r}")
    
    gles = fields[1] if len(fields) > 1 else ""
    for vm_gl in ["SwiftShader", "LLVMpipe", "softpipe", "VirtualBox", "Emulator"]:
        if vm_gl.lower() in gles.lower():
            flag(SEVERITY_CRITICAL, "gpu", f"Virtual GPU: {vm_gl}", gles[:200])


def analyze_accounts(fields):
    labels = ["account_count", "google_accounts"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val[:200]!r}")
    
    try:
        count = int((fields[0] if fields else "0").strip())
        if count == 0:
            flag(SEVERITY_HIGH, "accounts", "No accounts registered", "Real phones have Google account")
    except ValueError:
        pass
    
    google = fields[1] if len(fields) > 1 else ""
    if "(none)" in google or not google.strip():
        flag(SEVERITY_HIGH, "accounts", "No Google account", "")


def analyze_usage(fields):
    labels = ["contacts", "sms", "calls", "media", "downloads"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val!r}")
    
    thresholds = [("contacts", 5), ("sms", 3), ("calls", 3), ("media", 5), ("downloads", 1)]
    for i, (name, threshold) in enumerate(thresholds):
        try:
            count = int((fields[i] if i < len(fields) else "0").strip())
            if count < threshold:
                flag(SEVERITY_MEDIUM, "usage", f"Low {name}: {count} (need {threshold}+)", "")
        except ValueError:
            pass


def analyze_advanced(fields):
    labels = ["uptime", "boot_count", "system_mount", "input_devices", "wifi_mac", 
              "android_id", "accessibility", "gms_version", "lockscreen", "sensors"]
    for i, label in enumerate(labels):
        val = fields[i] if i < len(fields) else ""
        print(f"  {label} = {val[:200]!r}")
    
    uptime = fields[0] if fields else ""
    if uptime:
        try:
            secs = float(uptime.split()[0])
            hours = secs / 3600
            print(f"  Uptime: {hours:.1f} hours")
            if hours < 1:
                flag(SEVERITY_LOW, "advanced", f"Very fresh ({hours:.1f}h uptime)", "")
        except (ValueError, IndexError):
            pass
    
    sys_mount = fields[2] if len(fields) > 2 else ""
    if "rw" in sys_mount and "/system" in sys_mount:
        flag(SEVERITY_HIGH, "advanced", "/system mounted read-write", sys_mount[:200])
    
    inputs = fields[3] if len(fields) > 3 else ""
    if "touch" not in inputs.lower() and "ts" not in inputs.lower():
        flag(SEVERITY_MEDIUM, "advanced", "No touchscreen in input devices", inputs[:200])
    
    mac = (fields[4] if len(fields) > 4 else "").strip()
    if mac and (mac.startswith("02:00:00") or mac == "00:00:00:00:00:00"):
        flag(SEVERITY_HIGH, "advanced", f"Default WiFi MAC: {mac}", "")
    
    aid = (fields[5] if len(fields) > 5 else "").strip()
    if not aid or aid == "null" or len(aid) < 10:
        flag(SEVERITY_HIGH, "advanced", f"Invalid Android ID: {aid!r}", "")
    
    gms_ver = (fields[7] if len(fields) > 7 else "").strip()
    if not gms_ver:
        flag(SEVERITY_HIGH, "advanced", "GMS version not found", "")
    
    sensors = fields[9] if len(fields) > 9 else ""
    sensor_count = sensors.lower().count("sensor") + sensors.lower().count("handle")
    print(f"  Sensor entries: ~{sensor_count}")
    
    for sensor in ["accelerometer", "gyroscope", "magnetometer", "proximity", "light"]:
        if sensor not in sensors.lower():
            flag(SEVERITY_MEDIUM, "sensors", f"Missing sensor: {sensor}",
                 "Real phones have this sensor", f"VMOS may not emulate {sensor}")


async def main():
    print("=" * 70)
    print("  TITAN v11.3 — VMOS Fast Anomaly Scanner (Single-Shot)")
    print(f"  Target: {PAD_CODE}")
    print("=" * 70)
    
    # Run the entire mega script in ONE API call
    print("\n[*] Sending mega shell audit (1 API call)...")
    t0 = time.time()
    r = await bridge.exec_shell(PAD_CODE, MEGA_SCRIPT)
    api_time = time.time() - t0
    print(f"[*] API call completed in {api_time:.1f}s")
    
    if not r.ok:
        print(f"ERROR: Shell command failed: {r.error}")
        return
    
    raw = r.result or ""
    print(f"[*] Got {len(raw)} bytes of output")
    
    # Parse sections
    sections = parse_sections(raw)
    print(f"[*] Parsed {len(sections)} sections: {list(sections.keys())}")
    
    # Analyze each section
    analyzers = {
        "emulator_props": ("Emulator/VM Properties", analyze_emulator),
        "fingerprint": ("Build Fingerprint", analyze_fingerprint),
        "telephony": ("SIM / Telephony", analyze_telephony),
        "network": ("Network / Proxy", analyze_network),
        "apps": ("System Apps", analyze_apps),
        "vmos": ("VMOS Artifacts", analyze_vmos),
        "root": ("Root / SU", analyze_root),
        "debug": ("ADB / Debug", analyze_debug),
        "boot": ("Boot State", analyze_boot),
        "proc": ("Proc / Sys", analyze_proc),
        "locale": ("Timezone / Locale", analyze_locale),
        "display": ("Screen / Display", analyze_display),
        "gpu": ("GL / GPU", analyze_gpu),
        "accounts": ("Accounts", analyze_accounts),
        "usage": ("Usage Data", analyze_usage),
        "advanced": ("Advanced Detection", analyze_advanced),
    }
    
    idx = 1
    for section_key, (section_name, analyzer_fn) in analyzers.items():
        print(f"\n[{idx}/{len(analyzers)}] {section_name}")
        if section_key in sections:
            fields = split_fields(sections[section_key])
            analyzer_fn(fields)
        else:
            print(f"  (section not found in output)")
        idx += 1
    
    elapsed = time.time() - t0
    
    # ═══════ REPORT ═══════
    print("\n" + "=" * 70)
    print("  ANOMALY SCAN REPORT")
    print("=" * 70)
    
    sev_counts = {}
    for f in findings:
        s = f["severity"]
        sev_counts[s] = sev_counts.get(s, 0) + 1
    
    total = len(findings)
    crit = sev_counts.get(SEVERITY_CRITICAL, 0)
    high = sev_counts.get(SEVERITY_HIGH, 0)
    med = sev_counts.get(SEVERITY_MEDIUM, 0)
    low = sev_counts.get(SEVERITY_LOW, 0)
    info_count = sev_counts.get(SEVERITY_INFO, 0)
    
    print(f"\n  Total findings: {total}")
    print(f"  CRITICAL: {crit}")
    print(f"  HIGH:     {high}")
    print(f"  MEDIUM:   {med}")
    print(f"  LOW:      {low}")
    print(f"  INFO:     {info_count}")
    print(f"  Scan time: {elapsed:.1f}s (API: {api_time:.1f}s)")
    
    risk_score = min(100, crit * 20 + high * 10 + med * 5 + low * 2 + info_count)
    print(f"\n  DETECTION RISK SCORE: {risk_score}/100", end="")
    if risk_score > 70:
        print(" — EASILY DETECTABLE")
    elif risk_score > 40:
        print(" — MODERATE RISK")
    elif risk_score > 15:
        print(" — LOW RISK")
    else:
        print(" — STEALTH")
    
    for sev in [SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW, SEVERITY_INFO]:
        sev_findings = [f for f in findings if f["severity"] == sev]
        if not sev_findings:
            continue
        print(f"\n  -- {sev} ({len(sev_findings)}) --")
        for i, f in enumerate(sev_findings, 1):
            print(f"  {i}. [{f['category']}] {f['title']}")
            if f["detail"]:
                detail = f["detail"][:150].replace("\n", " | ")
                print(f"     Detail: {detail}")
            if f["fix_hint"]:
                print(f"     Fix: {f['fix_hint']}")
    
    # Save JSON report
    report = {
        "device": PAD_CODE,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scan_time_seconds": round(elapsed, 1),
        "api_time_seconds": round(api_time, 1),
        "risk_score": risk_score,
        "summary": {"total": total, "critical": crit, "high": high, "medium": med, "low": low, "info": info_count},
        "findings": findings,
    }
    report_path = os.path.join(os.path.dirname(__file__), f"anomaly_report_{PAD_CODE}.json")
    with open(report_path, "w") as fp:
        json.dump(report, fp, indent=2)
    print(f"\n  Full report: {report_path}")
    
    return report


if __name__ == "__main__":
    asyncio.run(main())
