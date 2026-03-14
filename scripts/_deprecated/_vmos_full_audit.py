#!/usr/bin/env python3
"""
Titan V11.3 — VMOS Full Anomaly Audit
Run against a VMOS Cloud device to detect every detectable anomaly.
"""
import asyncio, hashlib, hmac, json, os, sys, time, urllib.request
from datetime import datetime, timezone

PAD = "ACP2509244LGV1MV"
AK = "BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi"
SK = "Q2SgcSwEfuwoedY0cijp6Mce"
HOST = "api.vmoscloud.com"
BASE = f"https://{HOST}"
SVC = "armcloud-paas"

# ── Auth ──
def sign(body_str):
    x_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = x_date[:8]
    ct = "application/json;charset=UTF-8"
    sh = "content-type;host;x-content-sha256;x-date"
    xh = hashlib.sha256(body_str.encode()).hexdigest()
    canon = f"host:{HOST}\nx-date:{x_date}\ncontent-type:{ct}\nsignedHeaders:{sh}\nx-content-sha256:{xh}"
    hc = hashlib.sha256(canon.encode()).hexdigest()
    cs = f"{short}/{SVC}/request"
    sts = f"HMAC-SHA256\n{x_date}\n{cs}\n{hc}"
    kd = hmac.new(SK.encode(), short.encode(), hashlib.sha256).digest()
    ks = hmac.new(kd, SVC.encode(), hashlib.sha256).digest()
    kr = hmac.new(ks, b"request", hashlib.sha256).digest()
    sig = hmac.new(kr, sts.encode(), hashlib.sha256).hexdigest()
    return {"content-type": ct, "x-host": HOST, "x-date": x_date,
            "authorization": f"HMAC-SHA256 Credential={AK}, SignedHeaders={sh}, Signature={sig}"}

def api(path, body):
    bs = json.dumps(body, separators=(",", ":"))
    req = urllib.request.Request(f"{BASE}{path}", data=bs.encode(), headers=sign(bs), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"code": -1, "msg": str(e)}

def sh(cmd, timeout=15):
    """Execute shell on device, wait for result."""
    r = api("/vcpcloud/api/padApi/asyncCmd", {"padCodes": [PAD], "scriptContent": cmd})
    if r.get("code") != 200:
        return f"API_ERROR: {r.get('code')} {r.get('msg')}"
    tasks = r.get("data", [])
    if not tasks:
        return "NO_TASK"
    tid = tasks[0].get("taskId", 0)
    if not tid:
        return "NO_TASKID"
    start = time.time()
    while time.time() - start < timeout:
        d = api("/vcpcloud/api/padApi/padTaskDetail", {"taskIds": [tid]})
        tl = d.get("data", [])
        if tl:
            st = tl[0].get("taskStatus", 0)
            if st >= 3:
                res = tl[0].get("taskResult", "")
                err = tl[0].get("errorMsg", "")
                if st == 3:
                    return res or "(empty)"
                return f"TASK_FAIL: {err or res}"
        time.sleep(2)
    return "TIMEOUT"

# ═══════════════════════════════════════════════════════════════════
# PHASE 1: API STATUS CHECK
# ═══════════════════════════════════════════════════════════════════
print("=" * 70)
print("PHASE 1: VMOS API & DEVICE STATUS")
print("=" * 70)

# Check device info
info = api("/vcpcloud/api/padApi/infos", {"padCodes": [PAD]})
print(f"\n[API] infos code: {info.get('code')}")
if info.get("code") == 200:
    devs = info.get("data", [])
    if devs:
        d = devs[0]
        print(f"  padCode:  {d.get('padCode')}")
        print(f"  status:   {d.get('padStatus')}")
        print(f"  model:    {d.get('padModel')}")
        print(f"  android:  {d.get('androidVersion')}")
        print(f"  online:   {d.get('onlineStatus')}")
        print(f"  level:    {d.get('deviceLevel')}")
else:
    print(f"  ERROR: {info.get('msg')}")
    print(f"  Full response: {json.dumps(info, indent=2)[:500]}")

# Check properties API
props = api("/vcpcloud/api/padApi/padProperties", {"padCode": PAD})
print(f"\n[API] padProperties code: {props.get('code')}")
if props.get("code") == 200:
    pdata = props.get("data", {})
    if isinstance(pdata, dict):
        # Show key properties
        for key in ["ro.product.brand", "ro.product.model", "ro.product.device",
                     "ro.build.display.id", "persist.sys.timezone",
                     "persist.sys.cloud.imeinum", "persist.sys.cloud.iccidnum",
                     "gsm.operator.alpha", "gsm.sim.operator.alpha"]:
            val = pdata.get(key, "(not set)")
            print(f"  {key} = {val}")
        total = len(pdata)
        print(f"  ... total {total} properties")
    else:
        print(f"  Unexpected data type: {type(pdata)}")
else:
    print(f"  ERROR: {props.get('msg')}")

# Check for any pending tasks
print(f"\n[API] Quick shell test...")
r = sh("echo alive_$(date +%s)")
print(f"  Shell result: {r}")

if "API_ERROR" in str(r) or "TIMEOUT" in str(r):
    print("\n*** DEVICE NOT RESPONDING - Cannot proceed with audit ***")
    print(f"    Error: {r}")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════
# PHASE 2: COMPREHENSIVE SHELL AUDIT — BATCH 1 (Identity & Build)
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PHASE 2: SHELL-BASED ANOMALY DETECTION")
print("=" * 70)

BATCH1 = """
echo "===IDENTITY==="
getprop ro.product.brand
getprop ro.product.model
getprop ro.product.device
getprop ro.product.manufacturer
getprop ro.product.name
getprop ro.hardware
echo "===BUILD==="
getprop ro.build.display.id
getprop ro.build.version.release
getprop ro.build.version.sdk
getprop ro.build.version.security_patch
getprop ro.build.fingerprint
getprop ro.build.type
getprop ro.build.tags
getprop ro.build.host
echo "===VMOS_DETECT==="
getprop ro.vmos.simplest.rom
getprop persist.sys.cloud.padcode
getprop ro.boot.vmos
getprop vmos.browser.home
ls /system/xbin/vmos* 2>/dev/null || echo "no_vmos_xbin"
ls /data/data/com.vmos* 2>/dev/null || echo "no_vmos_data"
cat /proc/cpuinfo | head -5
echo "===SERIAL==="
getprop ro.serialno
getprop ro.boot.serialno
cat /proc/sys/kernel/random/boot_id
cat /sys/class/android_usb/android0/iSerial 2>/dev/null || echo "no_usb_serial"
""".strip()

print("\n[BATCH 1] Identity & Build & VMOS Detection...")
b1 = sh(BATCH1, timeout=20)
print(b1)

# ═══════════════════════════════════════════════════════════════════
# BATCH 2: Network & SIM & Connectivity
# ═══════════════════════════════════════════════════════════════════
BATCH2 = """
echo "===NETWORK==="
getprop gsm.operator.alpha
getprop gsm.operator.iso-country
getprop gsm.operator.numeric
getprop gsm.sim.operator.alpha
getprop gsm.sim.operator.iso-country
getprop gsm.sim.operator.numeric
getprop gsm.sim.state
getprop persist.sys.cloud.imeinum
getprop persist.sys.cloud.iccidnum
echo "===WIFI==="
ip addr show wlan0 2>/dev/null || echo "no_wlan0"
dumpsys wifi | grep "mNetworkInfo" | head -2
dumpsys connectivity | grep "NetworkAgentInfo" | head -3
echo "===DNS==="
getprop net.dns1
getprop net.dns2
cat /etc/resolv.conf 2>/dev/null || echo "no_resolv"
echo "===PROXY==="
getprop http.proxyHost
getprop http.proxyPort
settings get global http_proxy 2>/dev/null || echo "no_proxy_setting"
""".strip()

print("\n[BATCH 2] Network & SIM...")
b2 = sh(BATCH2, timeout=20)
print(b2)

# ═══════════════════════════════════════════════════════════════════
# BATCH 3: Apps & Services Missing (Call/SMS/etc)
# ═══════════════════════════════════════════════════════════════════
BATCH3 = """
echo "===PHONE_APP==="
pm list packages | grep -i "dialer\|phone\|telecom\|incallui" || echo "NO_PHONE_APPS"
pm list packages | grep -i "messaging\|mms\|sms" || echo "NO_SMS_APPS"
dumpsys telephony.registry 2>/dev/null | head -5 || echo "no_telephony"
echo "===GOOGLE_SERVICES==="
pm list packages | grep "com.google" | head -20
echo "===MISSING_SYSTEM_APPS==="
pm list packages -s | wc -l
echo "total_system_packages_above"
echo "===ACCOUNTS==="
dumpsys account 2>/dev/null | grep -i "Account {" | head -10 || echo "no_accounts"
echo "===SENSORS==="
dumpsys sensorservice 2>/dev/null | grep "^[0-9]" | head -15 || echo "no_sensors"
""".strip()

print("\n[BATCH 3] Apps & Services...")
b3 = sh(BATCH3, timeout=20)
print(b3)

# ═══════════════════════════════════════════════════════════════════
# BATCH 4: Storage/Files/Installed Apps/Fingerprint Leaks
# ═══════════════════════════════════════════════════════════════════
BATCH4 = """
echo "===STORAGE==="
df -h /data 2>/dev/null | tail -1
df -h /sdcard 2>/dev/null | tail -1
ls /sdcard/DCIM/ 2>/dev/null | head -5 || echo "no_dcim"
ls /sdcard/Download/ 2>/dev/null | head -5 || echo "no_downloads"
echo "===TIME==="
date
getprop persist.sys.timezone
uptime
echo "===BATTERY==="
dumpsys battery | grep -E "level|status|health|temperature|technology"
echo "===SCREEN==="
dumpsys display | grep "mBaseDisplayInfo" | head -2
wm size 2>/dev/null
wm density 2>/dev/null
echo "===USB==="
getprop sys.usb.config
getprop sys.usb.state
echo "===SELINUX==="
getenforce 2>/dev/null || echo "unknown"
echo "===ROOT==="
which su 2>/dev/null || echo "no_su"
ls /system/app/Superuser.apk 2>/dev/null || echo "no_superuser"
ls /system/xbin/su 2>/dev/null || echo "no_xbin_su"
""".strip()

print("\n[BATCH 4] Storage & System State...")
b4 = sh(BATCH4, timeout=20)
print(b4)

# ═══════════════════════════════════════════════════════════════════
# BATCH 5: Deep Fingerprint (MAC, GL, Kernel, Camera, Bluetooth)
# ═══════════════════════════════════════════════════════════════════
BATCH5 = """
echo "===MAC_ADDR==="
cat /sys/class/net/wlan0/address 2>/dev/null || echo "no_wlan0_mac"
ip link show 2>/dev/null | grep "link/ether"
echo "===BLUETOOTH==="
getprop bluetooth.status
getprop persist.bluetooth.btsnoop
dumpsys bluetooth_manager 2>/dev/null | grep "name:" | head -3 || echo "no_bt"
settings get secure bluetooth_address 2>/dev/null || echo "no_bt_addr"
echo "===GL_RENDERER==="
dumpsys SurfaceFlinger 2>/dev/null | grep -i "GLES" | head -3 || echo "no_gl"
getprop ro.hardware.egl
echo "===KERNEL==="
uname -a
cat /proc/version
echo "===CAMERA==="
dumpsys media.camera 2>/dev/null | grep "Camera ID" | head -5 || echo "no_camera_svc"
ls /dev/video* 2>/dev/null || echo "no_video_devs"
echo "===INSTALLED_APPS_COUNT==="
pm list packages | wc -l
echo "total_packages_above"
pm list packages -3 | wc -l
echo "third_party_above"
""".strip()

print("\n[BATCH 5] Deep Fingerprint...")
b5 = sh(BATCH5, timeout=20)
print(b5)

# ═══════════════════════════════════════════════════════════════════
# BATCH 6: Content Providers / Data (SMS, Calls, Contacts)
# ═══════════════════════════════════════════════════════════════════
BATCH6 = """
echo "===CONTACTS==="
content query --uri content://contacts/phones --projection display_name 2>/dev/null | head -5 || echo "no_contacts_provider"
content query --uri content://com.android.contacts/contacts --projection display_name 2>/dev/null | head -5 || echo "no_contacts"
echo "===CALL_LOG==="
content query --uri content://call_log/calls --projection number:type:date 2>/dev/null | head -5 || echo "no_call_log"
echo "===SMS==="
content query --uri content://sms --projection address:body:date 2>/dev/null | head -5 || echo "no_sms"
echo "===SETTINGS_SECURE==="
settings get secure android_id
settings get secure bluetooth_address 2>/dev/null || echo "none"
settings get global airplane_mode_on
echo "===ACCESSIBILITY==="
settings get secure enabled_accessibility_services 2>/dev/null || echo "none"
echo "===DEV_OPTIONS==="
settings get global development_settings_enabled
settings get global adb_enabled
""".strip()

print("\n[BATCH 6] Content Providers & Settings...")
b6 = sh(BATCH6, timeout=20)
print(b6)

# ═══════════════════════════════════════════════════════════════════
# PHASE 3: ANOMALY ANALYSIS
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PHASE 3: ANOMALY ANALYSIS SUMMARY")
print("=" * 70)

all_output = f"{b1}\n{b2}\n{b3}\n{b4}\n{b5}\n{b6}"
anomalies = []

# Check VMOS detection
if "vmos" in all_output.lower() and ("ro.vmos" in all_output or "padcode" in all_output.lower()):
    anomalies.append("CRITICAL: VMOS-specific properties detected (ro.vmos.*, persist.sys.cloud.padcode)")

if "no_vmos_xbin" not in all_output:
    anomalies.append("CRITICAL: VMOS binaries found in /system/xbin/")

if "no_vmos_data" not in all_output:
    anomalies.append("CRITICAL: VMOS data directory found in /data/data/")

# Check phone/SMS apps
if "NO_PHONE_APPS" in all_output:
    anomalies.append("HIGH: No dialer/phone apps installed — abnormal for any real device")

if "NO_SMS_APPS" in all_output:
    anomalies.append("HIGH: No SMS/messaging apps installed — abnormal for any real device")

# Check Google services
if "com.google.android.gms" not in all_output:
    anomalies.append("HIGH: Google Play Services missing")

# Check sensors
if "no_sensors" in all_output:
    anomalies.append("HIGH: No sensor data — VM/emulator indicator")

# Check camera
if "no_camera_svc" in all_output:
    anomalies.append("MEDIUM: No camera service running")

# Check Bluetooth
if "no_bt" in all_output:
    anomalies.append("MEDIUM: No Bluetooth manager data")

# Check USB/ADB
if "adb" in all_output.lower():
    # Check if adb_enabled=1
    if "adb_enabled" in all_output:
        anomalies.append("MEDIUM: ADB enabled — unusual for consumer device")

# Check SELinux
if "Permissive" in all_output:
    anomalies.append("HIGH: SELinux is Permissive — indicates rooted/modified device")

# Check root
if "no_su" not in all_output and "no_xbin_su" not in all_output:
    anomalies.append("HIGH: Root binaries (su) found")

# Check kernel
if "android" not in all_output.lower() or "generic" in all_output.lower():
    anomalies.append("MEDIUM: Generic/non-OEM kernel detected")

# Check GL renderer
if "swiftshader" in all_output.lower() or "llvmpipe" in all_output.lower():
    anomalies.append("CRITICAL: Software GL renderer (SwiftShader/llvmpipe) — VM indicator")

# Check MAC address
if "02:00:00:00:00:00" in all_output:
    anomalies.append("HIGH: Default/null MAC address 02:00:00:00:00:00")

# Check if timezone vs GPS mismatch could occur
if "America" in all_output or "US" in all_output:
    pass  # Check for mismatches would need both

# Check empty DCIM
if "no_dcim" in all_output:
    anomalies.append("MEDIUM: Empty DCIM folder — no photos (brand new device look)")

# Check uptime
for line in all_output.split("\n"):
    if "up" in line and ("min" in line or "day" in line):
        if "0 min" in line or "1 min" in line:
            anomalies.append("MEDIUM: Very low uptime — freshly started device")

# Check accounts
if "no_accounts" in all_output:
    anomalies.append("MEDIUM: No accounts registered on device")

# Check dev_options
if "development_settings_enabled" in all_output:
    for line in all_output.split("\n"):
        if "development_settings_enabled" in line and "1" in line:
            anomalies.append("MEDIUM: Developer options enabled")

# Check no contacts/calls/sms
if "no_contacts" in all_output or "no_contacts_provider" in all_output:
    anomalies.append("MEDIUM: No contacts on device")
if "no_call_log" in all_output:
    anomalies.append("MEDIUM: Empty call log")
if "no_sms" in all_output:
    anomalies.append("MEDIUM: No SMS messages")

# Check telephony
if "no_telephony" in all_output:
    anomalies.append("HIGH: No telephony registry — SIM/calling framework missing")

print(f"\nTotal anomalies found: {len(anomalies)}")
print()
for i, a in enumerate(anomalies, 1):
    print(f"  {i}. {a}")

# Severity breakdown
crit = sum(1 for a in anomalies if "CRITICAL" in a)
high = sum(1 for a in anomalies if "HIGH" in a)
med = sum(1 for a in anomalies if "MEDIUM" in a)
print(f"\n  CRITICAL: {crit}  |  HIGH: {high}  |  MEDIUM: {med}")
print(f"\n  Detection Risk: {'EXTREME' if crit > 0 else 'HIGH' if high > 2 else 'MODERATE' if high > 0 else 'LOW'}")

print("\n" + "=" * 70)
print("AUDIT COMPLETE")
print("=" * 70)
