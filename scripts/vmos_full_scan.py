#!/usr/bin/env python3
"""
Titan V11.3 — VMOS Device Full Anomaly Scanner (Multi-Batch)
=============================================================
Splits checks into small batches to work within VMOS 2KB output limit.
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

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"
SEVERITY_INFO = "INFO"

findings = []

def flag(sev, cat, title, detail="", fix=""):
    findings.append({"severity": sev, "category": cat, "title": title,
                     "detail": detail[:500], "fix_hint": fix})

async def sh(cmd):
    r = await bridge.exec_shell(PAD_CODE, cmd)
    return (r.result or "").strip() if r.ok else ""

def kv(raw, sep="---"):
    """Split output by separator."""
    return [p.strip() for p in raw.split(sep)]


async def main():
    print("=" * 70)
    print("  TITAN v11.3 — VMOS Full Anomaly Scanner")
    print(f"  Target: {PAD_CODE}")
    print("=" * 70)

    t0 = time.time()

    # ═══════════════════════════════════════════════════════════════
    # BATCH 1: Core identity + emulator props
    # ═══════════════════════════════════════════════════════════════
    print("\n[1/8] Core identity & emulator props...")
    b1 = await sh("""
echo "$(getprop ro.kernel.qemu)---$(getprop ro.hardware)---$(getprop ro.product.board)---$(getprop ro.build.flavor)---$(getprop gsm.version.ril-impl)---$(getprop ro.boot.serialno)---$(getprop ro.serialno)---$(getprop ro.hardware.virtual)---$(getprop init.svc.goldfish-logcat)---$(getprop init.svc.goldfish-setup)"
""")
    f1 = kv(b1)
    labels1 = ["qemu","hardware","board","flavor","ril","boot_serial","serial","hw_virtual","goldfish_log","goldfish_setup"]
    for i,l in enumerate(labels1):
        v = f1[i] if i < len(f1) else ""
        print(f"  {l} = {v!r}")
    
    qemu = f1[0] if f1 else ""
    hw = f1[1] if len(f1) > 1 else ""
    board = f1[2] if len(f1) > 2 else ""
    flavor = f1[3] if len(f1) > 3 else ""
    ril = f1[4] if len(f1) > 4 else ""
    serial = (f1[5] if len(f1) > 5 else "") or (f1[6] if len(f1) > 6 else "")
    hw_virtual = f1[7] if len(f1) > 7 else ""
    gf1 = f1[8] if len(f1) > 8 else ""
    gf2 = f1[9] if len(f1) > 9 else ""
    
    if qemu == "1": flag(SEVERITY_CRITICAL, "emulator", "QEMU detected", "ro.kernel.qemu=1")
    if "virtual" in hw_virtual.lower(): flag(SEVERITY_CRITICAL, "emulator", "Virtual hardware flag")
    if gf1: flag(SEVERITY_CRITICAL, "emulator", "Goldfish logcat service")
    if gf2: flag(SEVERITY_CRITICAL, "emulator", "Goldfish setup service")
    for bad in ["goldfish","ranchu","vbox","nox","bluestacks","genymotion","cuttlefish","vsoc"]:
        if bad in hw.lower() or bad in board.lower():
            flag(SEVERITY_CRITICAL, "emulator", f"VM hardware: {bad}", f"hw={hw},board={board}")
    if not ril: flag(SEVERITY_HIGH, "emulator", "No RIL (no real modem)", "gsm.version.ril-impl empty", "VMOS lacks real telephony stack")
    if not serial: flag(SEVERITY_HIGH, "emulator", "No serial number", "", "Generate realistic serial")
    if "eng" in flavor or "userdebug" in flavor: flag(SEVERITY_HIGH, "emulator", f"Non-prod build: {flavor}")

    # ═══════════════════════════════════════════════════════════════
    # BATCH 2: Build fingerprint
    # ═══════════════════════════════════════════════════════════════
    print("\n[2/8] Build fingerprint...")
    b2 = await sh("""
echo "$(getprop ro.build.fingerprint)|$(getprop ro.odm.build.fingerprint)|$(getprop ro.product.build.fingerprint)|$(getprop ro.system.build.fingerprint)|$(getprop ro.vendor.build.fingerprint)|$(getprop ro.build.type)|$(getprop ro.build.tags)|$(getprop ro.product.brand)|$(getprop ro.product.model)|$(getprop ro.product.device)|$(getprop ro.product.manufacturer)|$(getprop ro.build.version.release)|$(getprop ro.build.version.sdk)|$(getprop ro.build.version.security_patch)"
""")
    f2 = b2.split("|")
    labels2 = ["fingerprint","odm_fp","product_fp","system_fp","vendor_fp","build_type","build_tags",
               "brand","model","device","manufacturer","version","sdk","security_patch"]
    for i,l in enumerate(labels2):
        v = f2[i] if i < len(f2) else ""
        print(f"  {l} = {v!r}")
    
    fp = f2[0] if f2 else ""
    brand = f2[7] if len(f2) > 7 else ""
    model = f2[8] if len(f2) > 8 else ""
    build_type = f2[5] if len(f2) > 5 else ""
    tags = f2[6] if len(f2) > 6 else ""
    
    if not fp or len(fp) < 20: flag(SEVERITY_CRITICAL, "fingerprint", "Missing fingerprint")
    
    fps = [f2[i] for i in range(5) if i < len(f2) and f2[i]]
    if len(set(fps)) > 1: flag(SEVERITY_HIGH, "fingerprint", f"Fingerprint mismatch across {len(set(fps))} partitions",
                               " / ".join(fp[:50] for fp in set(fps)))
    
    if build_type != "user": flag(SEVERITY_HIGH, "fingerprint", f"Build type: {build_type} (not user)")
    if "release-keys" not in tags: flag(SEVERITY_HIGH, "fingerprint", f"Tags: {tags}")
    
    for ind in ["vivo", "V2408A", "PD2408"]:
        if ind.lower() in (fp + model + brand).lower():
            flag(SEVERITY_CRITICAL, "fingerprint", f"VMOS DEFAULT IDENTITY: {ind}",
                 "Stock VMOS device — must change!", "Apply Samsung/Google identity")
    

    # ═══════════════════════════════════════════════════════════════
    # BATCH 3: SIM / Telephony  
    # ═══════════════════════════════════════════════════════════════
    print("\n[3/8] SIM / Telephony...")
    b3 = await sh("""
echo "$(getprop gsm.sim.state)|$(getprop gsm.sim.operator.alpha)|$(getprop gsm.sim.operator.numeric)|$(getprop gsm.sim.operator.iso-country)|$(getprop gsm.operator.alpha)|$(getprop gsm.operator.numeric)|$(getprop gsm.operator.iso-country)|$(getprop gsm.network.type)|$(getprop persist.sys.cloud.imeinum)|$(getprop persist.sys.cloud.iccidnum)|$(getprop persist.sys.cloud.imsinum)|$(getprop persist.sys.cloud.phonenum)|$(getprop persist.sys.cloud.mobileinfo)"
""")
    f3 = b3.split("|")
    labels3 = ["sim_state","carrier","sim_mccmnc","sim_country","net_carrier","net_mccmnc",
               "net_country","net_type","imei","iccid","imsi","phone","mobileinfo"]
    for i,l in enumerate(labels3):
        v = f3[i] if i < len(f3) else ""
        print(f"  {l} = {v!r}")
    
    sim_state = f3[0] if f3 else ""
    carrier_name = f3[1] if len(f3) > 1 else ""
    sim_mccmnc = f3[2] if len(f3) > 2 else ""
    sim_country = f3[3] if len(f3) > 3 else ""
    net_type = f3[7] if len(f3) > 7 else ""
    imei = f3[8] if len(f3) > 8 else ""
    mobileinfo = f3[12] if len(f3) > 12 else ""
    
    if sim_state != "READY": flag(SEVERITY_HIGH, "telephony", f"SIM not READY: {sim_state!r}", "", "Set gsm.sim.state=READY")
    if not carrier_name: flag(SEVERITY_HIGH, "telephony", "No carrier name", "", "Set to T-Mobile or AT&T")
    if not sim_mccmnc: flag(SEVERITY_HIGH, "telephony", "No SIM MCC/MNC", "", "Set gsm.sim.operator.numeric=310260")
    if not net_type or net_type in ("Unknown","0"): flag(SEVERITY_MEDIUM, "telephony", f"No network type: {net_type!r}", "", "Set gsm.network.type=LTE")
    if not imei or len(imei) < 15: flag(SEVERITY_HIGH, "telephony", f"IMEI invalid: {imei!r}")
    
    if mobileinfo and "502" in mobileinfo:
        flag(SEVERITY_CRITICAL, "telephony", f"MALAYSIAN SIM: MCC/MNC={mobileinfo}",
             "502=Malaysia. With US proxy = fatal mismatch!", "Set MCC/MNC to 310,260 (T-Mobile US)")
    if sim_country and sim_country.lower() == "my":
        flag(SEVERITY_CRITICAL, "telephony", f"SIM country=MY (Malaysia)", "", "Change to US")

    # ═══════════════════════════════════════════════════════════════
    # BATCH 4: Apps, VMOS artifacts, root
    # ═══════════════════════════════════════════════════════════════
    print("\n[4/8] Apps & VMOS artifacts...")
    b4 = await sh(r"""
D=$(pm list packages 2>/dev/null | grep -ciE 'dialer|com.android.phone|telecom')
S=$(pm list packages 2>/dev/null | grep -ciE 'messaging|sms|mms')
C=$(pm list packages 2>/dev/null | grep -ci camera)
T=$(pm list packages 2>/dev/null | wc -l)
S3=$(pm list packages -3 2>/dev/null | wc -l)
GMS=$(pm list packages 2>/dev/null | grep -c 'com.google.android.gms')
YT=$(pm list packages 2>/dev/null | grep -c youtube)
MAP=$(pm list packages 2>/dev/null | grep -c 'apps.maps')
CLK=$(pm list packages 2>/dev/null | grep -ciE 'clock|deskclock')
FIL=$(pm list packages 2>/dev/null | grep -ciE 'documentsui|filemanager')
VM=$(pm list packages 2>/dev/null | grep -ciE 'vmos|vphone|nox|bluestack|geny|andy|ldplayer|memu')
HOOK=$(pm list packages 2>/dev/null | grep -ciE 'xposed|lsposed|edxposed|riru|zygisk|frida|appium')
VP=$(getprop 2>/dev/null | grep -ci vmos)
echo "$D|$S|$C|$T|$S3|$GMS|$YT|$MAP|$CLK|$FIL|$VM|$HOOK|$VP"
""")
    f4 = b4.split("|")
    labels4 = ["dialer_count","sms_count","camera_count","total_pkgs","third_party","gms","youtube","maps","clock","files","vm_pkgs","hook_pkgs","vmos_props"]
    for i,l in enumerate(labels4):
        v = f4[i] if i < len(f4) else ""
        print(f"  {l} = {v!r}")
    
    try:
        dialer_c = int(f4[0]) if f4 else 0
        sms_c = int(f4[1]) if len(f4) > 1 else 0
        total_c = int(f4[3]) if len(f4) > 3 else 0
        third_c = int(f4[4]) if len(f4) > 4 else 0
        gms_c = int(f4[5]) if len(f4) > 5 else 0
        yt_c = int(f4[6]) if len(f4) > 6 else 0
        map_c = int(f4[7]) if len(f4) > 7 else 0
        clk_c = int(f4[8]) if len(f4) > 8 else 0
        fil_c = int(f4[9]) if len(f4) > 9 else 0
        vm_c = int(f4[10]) if len(f4) > 10 else 0
        hook_c = int(f4[11]) if len(f4) > 11 else 0
        vmos_p = int(f4[12]) if len(f4) > 12 else 0
        
        if dialer_c == 0: flag(SEVERITY_CRITICAL, "apps", "NO PHONE/DIALER APP",
                               "Every real phone has a dialer!", "Install com.google.android.dialer")
        if sms_c == 0: flag(SEVERITY_CRITICAL, "apps", "NO SMS/MESSAGING APP",
                            "Every phone has SMS app!", "Install com.google.android.apps.messaging")
        if clk_c == 0: flag(SEVERITY_MEDIUM, "apps", "No clock/alarm app", "", "Install DeskClock")
        if fil_c == 0: flag(SEVERITY_MEDIUM, "apps", "No file manager", "", "Install DocumentsUI")
        if gms_c == 0: flag(SEVERITY_HIGH, "apps", "No Google Play Services")
        if yt_c == 0: flag(SEVERITY_MEDIUM, "apps", "No YouTube")
        if map_c == 0: flag(SEVERITY_MEDIUM, "apps", "No Google Maps")
        if total_c < 80: flag(SEVERITY_HIGH, "apps", f"Very few packages ({total_c})", "Real: 150-300+")
        elif total_c < 120: flag(SEVERITY_MEDIUM, "apps", f"Below-average packages ({total_c})")
        if third_c < 5: flag(SEVERITY_MEDIUM, "apps", f"Almost no third-party apps ({third_c})")
        if vm_c > 0: flag(SEVERITY_CRITICAL, "vmos", f"VM/emulator packages found ({vm_c})")
        if hook_c > 0: flag(SEVERITY_CRITICAL, "vmos", f"Hooking frameworks found ({hook_c})")
        if vmos_p > 0: flag(SEVERITY_CRITICAL, "vmos", f"VMOS properties in getprop ({vmos_p})")
    except ValueError as e:
        print(f"  Parse error: {e}")

    # ═══════════════════════════════════════════════════════════════
    # BATCH 5: Root, boot, debug, SELinux
    # ═══════════════════════════════════════════════════════════════
    print("\n[5/8] Root, boot, debug...")
    b5 = await sh(r"""
SU=$(which su 2>/dev/null && echo "FOUND" || echo "NONE")
SE=$(getenforce 2>/dev/null)
DBG=$(getprop ro.debuggable)
SEC=$(getprop ro.secure)
ADB=$(settings get global adb_enabled 2>/dev/null)
DEV=$(settings get global development_settings_enabled 2>/dev/null)
MOCK=$(settings get secure mock_location 2>/dev/null)
VB=$(getprop ro.boot.verifiedbootstate)
BL=$(getprop ro.boot.flash.locked)
echo "$SU|$SE|$DBG|$SEC|$ADB|$DEV|$MOCK|$VB|$BL"
""")
    f5 = b5.split("|")
    labels5 = ["su","selinux","debuggable","secure","adb","dev_options","mock_loc","verified_boot","bootloader"]
    for i,l in enumerate(labels5):
        v = f5[i] if i < len(f5) else ""
        print(f"  {l} = {v!r}")
    
    su = f5[0] if f5 else ""
    if "FOUND" in su: flag(SEVERITY_CRITICAL, "root", "SU binary found", su)
    
    selinux = (f5[1] if len(f5) > 1 else "").strip()
    if selinux.lower() != "enforcing": flag(SEVERITY_HIGH, "root", f"SELinux: {selinux!r}")
    
    if (f5[2] if len(f5) > 2 else "").strip() == "1": flag(SEVERITY_HIGH, "root", "ro.debuggable=1")
    if (f5[3] if len(f5) > 3 else "").strip() != "1": flag(SEVERITY_HIGH, "root", "ro.secure not 1")
    if (f5[4] if len(f5) > 4 else "").strip() == "1": flag(SEVERITY_HIGH, "debug", "ADB enabled")
    if (f5[5] if len(f5) > 5 else "").strip() == "1": flag(SEVERITY_MEDIUM, "debug", "Dev options enabled")
    if (f5[6] if len(f5) > 6 else "").strip() == "1": flag(SEVERITY_HIGH, "debug", "Mock location enabled")
    
    vb = (f5[7] if len(f5) > 7 else "").strip()
    if vb != "green": flag(SEVERITY_HIGH, "boot", f"Verified boot: {vb!r} (not green)")
    bl = (f5[8] if len(f5) > 8 else "").strip()
    if bl != "1": flag(SEVERITY_HIGH, "boot", f"Bootloader not locked: {bl!r}")

    # ═══════════════════════════════════════════════════════════════
    # BATCH 6: Timezone, locale, network iface, proc
    # ═══════════════════════════════════════════════════════════════
    print("\n[6/8] Timezone, locale, proc...")
    b6 = await sh(r"""
TZ=$(getprop persist.sys.timezone)
LOC=$(getprop persist.sys.locale)
CC=$(getprop persist.sys.country)
WCC=$(getprop ro.boot.wificountrycode)
NET=$(ls /sys/class/net/ 2>/dev/null | tr '\n' ',')
UP=$(cat /proc/uptime 2>/dev/null | awk '{print $1}')
BC=$(settings get global boot_count 2>/dev/null)
MAC=$(cat /sys/class/net/wlan0/address 2>/dev/null)
AID=$(settings get secure android_id 2>/dev/null)
TH=$(ls /sys/class/thermal/thermal_zone* 2>/dev/null | wc -l)
BAT=$(cat /sys/class/power_supply/battery/status 2>/dev/null)
BATL=$(cat /sys/class/power_supply/battery/capacity 2>/dev/null)
echo "$TZ|$LOC|$CC|$WCC|$NET|$UP|$BC|$MAC|$AID|$TH|$BAT|$BATL"
""")
    f6 = b6.split("|")
    labels6 = ["timezone","locale","country","wifi_cc","net_ifaces","uptime_secs","boot_count",
               "wifi_mac","android_id","thermal_zones","battery_status","battery_level"]
    for i,l in enumerate(labels6):
        v = f6[i] if i < len(f6) else ""
        print(f"  {l} = {v!r}")
    
    tz = f6[0] if f6 else ""
    country_code = f6[2] if len(f6) > 2 else ""
    wifi_cc = f6[3] if len(f6) > 3 else ""
    net_ifaces = f6[4] if len(f6) > 4 else ""
    
    if tz and ("Asia" in tz or "Kuala_Lumpur" in tz):
        flag(SEVERITY_CRITICAL, "locale", f"ASIAN TIMEZONE: {tz}",
             "With US proxy = fatal timezone mismatch!", "Set to America/New_York")
    elif tz and "America" not in tz and "US" not in tz:
        flag(SEVERITY_HIGH, "locale", f"Timezone not US: {tz}", "")
    
    if country_code and country_code.upper() not in ("US",""):
        flag(SEVERITY_MEDIUM, "locale", f"Country={country_code} (not US)")
    
    if "eth0" in net_ifaces:
        flag(SEVERITY_HIGH, "network", "eth0 interface present",
             "Real phones don't have eth0 — cloud VM indicator")
    
    mac = (f6[7] if len(f6) > 7 else "").strip()
    if mac and (mac.startswith("02:00:00") or mac == "00:00:00:00:00:00"):
        flag(SEVERITY_HIGH, "network", f"Default WiFi MAC: {mac}")
    
    aid = (f6[8] if len(f6) > 8 else "").strip()
    if not aid or aid == "null" or len(aid) < 10:
        flag(SEVERITY_HIGH, "advanced", f"Invalid Android ID: {aid!r}")
    
    try:
        thermal = int((f6[9] if len(f6) > 9 else "0").strip())
        if thermal < 5: flag(SEVERITY_MEDIUM, "proc", f"Few thermal zones ({thermal})", "Real: 20-40+")
    except ValueError:
        pass
    
    try:
        uptime = float((f6[5] if len(f6) > 5 else "0").strip())
        hours = uptime / 3600
        print(f"  Uptime: {hours:.1f} hours")
        if hours < 1: flag(SEVERITY_LOW, "advanced", f"Very fresh ({hours:.1f}h uptime)")
    except ValueError:
        pass

    # ═══════════════════════════════════════════════════════════════
    # BATCH 7: /proc checks, kernel cmdline, GPU
    # ═══════════════════════════════════════════════════════════════
    print("\n[7/8] Kernel, GPU, display...")
    b7 = await sh(r"""
CMD=$(cat /proc/cmdline 2>/dev/null | head -1 | cut -c1-500)
EGL=$(getprop ro.hardware.egl)
VLK=$(getprop ro.hardware.vulkan)
WM=$(wm size 2>/dev/null)
DN=$(wm density 2>/dev/null)
echo "$EGL|$VLK|$WM|$DN"
echo "===CMD==="
echo "$CMD"
""")
    # Parse carefully
    parts = b7.split("===CMD===")
    f7_top = parts[0].strip().split("|") if parts else []
    cmdline = parts[1].strip() if len(parts) > 1 else ""
    
    labels7 = ["egl","vulkan","wm_size","wm_density"]
    for i,l in enumerate(labels7):
        v = f7_top[i] if i < len(f7_top) else ""
        print(f"  {l} = {v!r}")
    print(f"  cmdline = {cmdline[:200]!r}")
    
    for tok in ["goldfish","ranchu","qemu=","vbox","hypervisor"]:
        if tok.lower() in cmdline.lower():
            flag(SEVERITY_CRITICAL, "proc", f"VM token in cmdline: {tok}", cmdline[:200])
    
    if "verifiedbootstate=orange" in cmdline:
        flag(SEVERITY_HIGH, "proc", "Boot state ORANGE in kernel cmdline",
             "Unlocked bootloader leaked in cmdline", "Should be green")

    # ═══════════════════════════════════════════════════════════════
    # BATCH 8: Usage data, accounts, sensors, input devices
    # ═══════════════════════════════════════════════════════════════
    print("\n[8/8] Usage data, accounts, sensors...")
    b8 = await sh(r"""
CON=$(content query --uri content://contacts/phones 2>/dev/null | wc -l)
SMS=$(content query --uri content://sms 2>/dev/null | wc -l)
CAL=$(content query --uri content://call_log/calls 2>/dev/null | wc -l)
MED=$(content query --uri content://media/external/images/media 2>/dev/null | wc -l)
ACC=$(dumpsys account 2>/dev/null | grep -c 'Account {' || echo 0)
GA=$(dumpsys account 2>/dev/null | grep -c 'com.google' || echo 0)
GV=$(dumpsys package com.google.android.gms 2>/dev/null | grep versionName | head -1 | tr -d ' ')
INP=$(cat /proc/bus/input/devices 2>/dev/null | grep -ci touch)
SEN=$(dumpsys sensorservice 2>/dev/null | grep -ciE 'accelerometer|gyroscope|magnetometer|proximity|light|barometer')
echo "$CON|$SMS|$CAL|$MED|$ACC|$GA|$GV|$INP|$SEN"
""")
    f8 = b8.split("|")
    labels8 = ["contacts","sms","calls","media","accounts","google_acc","gms_version","touchscreen","sensor_count"]
    for i,l in enumerate(labels8):
        v = f8[i] if i < len(f8) else ""
        print(f"  {l} = {v!r}")
    
    try:
        contacts = int(f8[0]) if f8 else 0
        sms_count = int(f8[1]) if len(f8) > 1 else 0
        calls = int(f8[2]) if len(f8) > 2 else 0
        media = int(f8[3]) if len(f8) > 3 else 0
        accounts = int(f8[4]) if len(f8) > 4 else 0
        google_acc = int(f8[5]) if len(f8) > 5 else 0
        touch = int(f8[7]) if len(f8) > 7 else 0
        sensor_cnt = int(f8[8]) if len(f8) > 8 else 0
        
        if contacts < 5: flag(SEVERITY_MEDIUM, "usage", f"Low contacts: {contacts}", "", "Inject more contacts")
        if sms_count < 3: flag(SEVERITY_MEDIUM, "usage", f"Low SMS: {sms_count}", "", "Inject more SMS")
        if calls < 3: flag(SEVERITY_MEDIUM, "usage", f"Low call logs: {calls}", "", "Inject more calls")
        if media < 5: flag(SEVERITY_MEDIUM, "usage", f"Low media: {media}", "", "Inject photos")
        if accounts == 0: flag(SEVERITY_HIGH, "accounts", "No accounts registered")
        if google_acc == 0: flag(SEVERITY_HIGH, "accounts", "No Google account")
        if touch == 0: flag(SEVERITY_MEDIUM, "input", "No touchscreen input device")
        if sensor_cnt < 3: flag(SEVERITY_MEDIUM, "sensors", f"Missing sensors ({sensor_cnt} basic found)",
                                "Need accelerometer,gyroscope,etc", "VMOS may lack full sensor emulation")
    except ValueError as e:
        print(f"  Parse error: {e}")
    
    gms_ver = (f8[6] if len(f8) > 6 else "").strip()
    if not gms_ver: flag(SEVERITY_HIGH, "advanced", "GMS version not found")
    else: print(f"  GMS: {gms_ver}")

    elapsed = time.time() - t0

    # ═══════════════════════════════════════════════════════════════
    # REPORT
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  ANOMALY SCAN REPORT")
    print("=" * 70)
    
    sev_counts = {}
    for f in findings:
        sev_counts[f["severity"]] = sev_counts.get(f["severity"], 0) + 1
    
    total = len(findings)
    crit = sev_counts.get(SEVERITY_CRITICAL, 0)
    high = sev_counts.get(SEVERITY_HIGH, 0)
    med = sev_counts.get(SEVERITY_MEDIUM, 0)
    low = sev_counts.get(SEVERITY_LOW, 0)
    info_c = sev_counts.get(SEVERITY_INFO, 0)
    
    print(f"\n  Total findings: {total}")
    print(f"  CRITICAL: {crit}")
    print(f"  HIGH:     {high}")
    print(f"  MEDIUM:   {med}")
    print(f"  LOW:      {low}")
    print(f"  INFO:     {info_c}")
    print(f"  Scan time: {elapsed:.1f}s ({8} API calls)")
    
    risk_score = min(100, crit * 20 + high * 10 + med * 5 + low * 2 + info_c)
    print(f"\n  DETECTION RISK SCORE: {risk_score}/100", end="")
    if risk_score > 70: print(" — EASILY DETECTABLE")
    elif risk_score > 40: print(" — MODERATE RISK")
    elif risk_score > 15: print(" — LOW RISK")
    else: print(" — STEALTH")
    
    for sev in [SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW, SEVERITY_INFO]:
        sev_findings = [f for f in findings if f["severity"] == sev]
        if not sev_findings: continue
        print(f"\n  -- {sev} ({len(sev_findings)}) --")
        for i, f in enumerate(sev_findings, 1):
            print(f"  {i}. [{f['category']}] {f['title']}")
            if f["detail"]:
                print(f"     {f['detail'][:120].replace(chr(10),' ')}")
            if f["fix_hint"]:
                print(f"     FIX: {f['fix_hint']}")
    
    report = {
        "device": PAD_CODE,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scan_time_seconds": round(elapsed, 1),
        "risk_score": risk_score,
        "summary": {"total": total, "critical": crit, "high": high, "medium": med, "low": low, "info": info_c},
        "findings": findings,
    }
    rpath = os.path.join(os.path.dirname(__file__), f"anomaly_report_{PAD_CODE}.json")
    with open(rpath, "w") as fp:
        json.dump(report, fp, indent=2)
    print(f"\n  Full report: {rpath}")
    
    return report

if __name__ == "__main__":
    asyncio.run(main())
