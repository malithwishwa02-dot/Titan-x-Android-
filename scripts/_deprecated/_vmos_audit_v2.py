#!/usr/bin/env python3
"""
VMOS Audit v2 - Works around 500 errors on most endpoints.
Only asyncCmd is working, so we do EVERYTHING via shell.
Also: padTaskDetail is 500, so we use a callback/polling workaround.
"""
import hashlib, hmac, json, time, urllib.request, sys
from datetime import datetime, timezone

PAD = "ACP2509244LGV1MV"
AK = "BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi"
SK = "Q2SgcSwEfuwoedY0cijp6Mce"
HOST = "api.vmoscloud.com"
BASE = f"https://{HOST}"
SVC = "armcloud-paas"

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

def sh(cmd, timeout=25):
    """Execute shell and poll for result. Works around 500 on padTaskDetail by retrying."""
    r = api("/vcpcloud/api/padApi/asyncCmd", {"padCodes": [PAD], "scriptContent": cmd})
    if r.get("code") != 200:
        return f"SUBMIT_ERROR:{r.get('code')}:{r.get('msg','')}"
    tasks = r.get("data", [])
    if not tasks:
        return "NO_TASK"
    tid = tasks[0].get("taskId", 0)
    if not tid:
        return "NO_TASKID"
    
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(2.5)
        d = api("/vcpcloud/api/padApi/padTaskDetail", {"taskIds": [tid]})
        if d.get("code") == 500:
            # API is flaky, keep retrying
            continue
        if d.get("code") == 200 and d.get("data"):
            t = d["data"][0]
            st = t.get("taskStatus", 0)
            if st >= 3:
                res = t.get("taskResult", "")
                if st == 3:
                    return res or "(empty)"
                return f"FAIL:{t.get('errorMsg','')}"
        # Keep polling
    return "TIMEOUT"

# ═══════════════════════════════════════════════════════
# First: verify shell works at all
# ═══════════════════════════════════════════════════════
print("=" * 70)
print("VMOS DEVICE AUDIT (Shell-Only Mode)")
print("=" * 70)
print(f"\nTarget: {PAD}")
print(f"Note: Most VMOS APIs return 500, only asyncCmd works")
print(f"      padTaskDetail may also be flaky - will retry aggressively\n")

print("[*] Testing shell connectivity...")
t0 = time.time()
r = sh("echo ALIVE_$(date +%s)", timeout=30)
elapsed = time.time() - t0
print(f"    Result: {r}")
print(f"    Time: {elapsed:.1f}s")

if "SUBMIT_ERROR" in str(r):
    print("\n*** asyncCmd also broken - cannot audit device ***")
    sys.exit(1)

if "TIMEOUT" in str(r):
    print("\n*** Shell works but padTaskDetail is 500 - cannot get results ***")
    print("    Trying one more time with longer wait...")
    r = sh("echo ALIVE2", timeout=40)
    print(f"    Retry result: {r}")
    if "TIMEOUT" in str(r):
        print("\n*** padTaskDetail consistently 500 - VMOS API is down ***")
        print("    This is a VMOS Cloud server-side issue, not our code.")
        print("    The API endpoints returning 500:")
        print("      - /vcpcloud/api/padApi/infos")
        print("      - /vcpcloud/api/padApi/padProperties") 
        print("      - /vcpcloud/api/padApi/padTaskDetail")
        print("      - /vcpcloud/api/padApi/getLongGenerateUrl")
        print("    Only working: /vcpcloud/api/padApi/asyncCmd (submits tasks)")
        print("\n    Recommendation: Wait and retry later, or contact VMOS support.")
        
        # Try the other device too
        print("\n[*] Checking if PAD2 has same issue...")
        PAD = "ACP251008CRDQZPF"
        r2 = sh("echo ALIVE_PAD2", timeout=30)
        print(f"    PAD2 result: {r2}")
        sys.exit(1)

print(f"\n[✓] Shell is working! Running full audit...\n")

# ═══════════════════════════════════════════════════════
# BATCH 1: Device Identity
# ═══════════════════════════════════════════════════════
print("[BATCH 1] Device Identity & Build...")
b1 = sh("""
echo "::BRAND::" && getprop ro.product.brand
echo "::MODEL::" && getprop ro.product.model
echo "::DEVICE::" && getprop ro.product.device
echo "::MANUFACTURER::" && getprop ro.product.manufacturer
echo "::HARDWARE::" && getprop ro.hardware
echo "::FINGERPRINT::" && getprop ro.build.fingerprint
echo "::ANDROID::" && getprop ro.build.version.release
echo "::SDK::" && getprop ro.build.version.sdk
echo "::SECURITY::" && getprop ro.build.version.security_patch
echo "::BUILDTYPE::" && getprop ro.build.type
echo "::BUILDTAGS::" && getprop ro.build.tags
echo "::BUILDHOST::" && getprop ro.build.host
echo "::DISPLAY::" && getprop ro.build.display.id
""".strip(), timeout=25)
print(b1)

# ═══════════════════════════════════════════════════════
# BATCH 2: VMOS Detection Vectors
# ═══════════════════════════════════════════════════════
print("\n[BATCH 2] VMOS Detection Vectors...")
b2 = sh("""
echo "::VMOS_ROM::" && getprop ro.vmos.simplest.rom
echo "::PADCODE::" && getprop persist.sys.cloud.padcode
echo "::BOOT_VMOS::" && getprop ro.boot.vmos
echo "::VMOS_BROWSER::" && getprop vmos.browser.home
echo "::VMOS_XBIN::" && ls /system/xbin/vmos* 2>/dev/null || echo "(none)"
echo "::VMOS_DATA::" && ls -d /data/data/com.vmos* 2>/dev/null || echo "(none)"
echo "::VMOS_APPS::" && pm list packages 2>/dev/null | grep -i vmos || echo "(none)"
echo "::KERNEL::" && uname -a
echo "::PROC_VERSION::" && cat /proc/version
echo "::CPUINFO::" && head -6 /proc/cpuinfo
echo "::MOUNT_CHECK::" && mount | grep -i "vmos\|cloud" | head -3 || echo "(none)"
""".strip(), timeout=25)
print(b2)

# ═══════════════════════════════════════════════════════
# BATCH 3: Network & SIM & Phone/SMS Apps
# ═══════════════════════════════════════════════════════
print("\n[BATCH 3] Network & SIM & Phone/SMS Apps...")
b3 = sh("""
echo "::CARRIER::" && getprop gsm.operator.alpha
echo "::CARRIER_COUNTRY::" && getprop gsm.operator.iso-country
echo "::CARRIER_MCC::" && getprop gsm.operator.numeric
echo "::SIM_OP::" && getprop gsm.sim.operator.alpha
echo "::SIM_COUNTRY::" && getprop gsm.sim.operator.iso-country
echo "::SIM_MCC::" && getprop gsm.sim.operator.numeric
echo "::SIM_STATE::" && getprop gsm.sim.state
echo "::IMEI::" && getprop persist.sys.cloud.imeinum
echo "::ICCID::" && getprop persist.sys.cloud.iccidnum
echo "::PHONE_APPS::" && pm list packages 2>/dev/null | grep -iE "dialer|phone|telecom|incallui" || echo "NONE"
echo "::SMS_APPS::" && pm list packages 2>/dev/null | grep -iE "messaging|mms|sms" || echo "NONE"
echo "::TELEPHONY::" && dumpsys telephony.registry 2>/dev/null | head -3 || echo "NONE"
echo "::PROXY::" && settings get global http_proxy 2>/dev/null || echo "(none)"
echo "::DNS1::" && getprop net.dns1
echo "::DNS2::" && getprop net.dns2
""".strip(), timeout=25)
print(b3)

# ═══════════════════════════════════════════════════════
# BATCH 4: Google Services, Accounts, Sensors
# ═══════════════════════════════════════════════════════
print("\n[BATCH 4] Google, Accounts, Sensors...")
b4 = sh("""
echo "::GOOGLE_PKGS::" && pm list packages 2>/dev/null | grep com.google | head -15 || echo "NONE"
echo "::ACCOUNTS::" && dumpsys account 2>/dev/null | grep "Account {" | head -5 || echo "NONE"
echo "::SENSORS::" && dumpsys sensorservice 2>/dev/null | grep -E "^[0-9]" | head -10 || echo "NONE"
echo "::SENSOR_COUNT::" && dumpsys sensorservice 2>/dev/null | grep -cE "^[0-9]" || echo "0"
echo "::CAMERA::" && dumpsys media.camera 2>/dev/null | grep "Camera ID" | head -3 || echo "NONE"
echo "::GL_RENDERER::" && dumpsys SurfaceFlinger 2>/dev/null | grep -i "GLES" | head -2 || echo "NONE"
echo "::EGL::" && getprop ro.hardware.egl
echo "::BLUETOOTH::" && dumpsys bluetooth_manager 2>/dev/null | grep "name:" | head -2 || echo "NONE"
echo "::BT_ADDR::" && settings get secure bluetooth_address 2>/dev/null || echo "(none)"
""".strip(), timeout=25)
print(b4)

# ═══════════════════════════════════════════════════════
# BATCH 5: System State, Root, SELinux, USB
# ═══════════════════════════════════════════════════════
print("\n[BATCH 5] System State, Root, SELinux...")
b5 = sh("""
echo "::TIMEZONE::" && getprop persist.sys.timezone
echo "::DATE::" && date
echo "::UPTIME::" && uptime
echo "::BATTERY::" && dumpsys battery 2>/dev/null | grep -E "level|status|health|temperature|technology"
echo "::SCREEN_SIZE::" && wm size 2>/dev/null || echo "(none)"
echo "::SCREEN_DENSITY::" && wm density 2>/dev/null || echo "(none)"
echo "::SELINUX::" && getenforce 2>/dev/null || echo "(unknown)"
echo "::ROOT_SU::" && which su 2>/dev/null || echo "(none)"
echo "::ROOT_SUPERUSER::" && ls /system/app/Superuser.apk 2>/dev/null || echo "(none)"
echo "::USB_CONFIG::" && getprop sys.usb.config
echo "::USB_STATE::" && getprop sys.usb.state
echo "::ADB::" && settings get global adb_enabled 2>/dev/null || echo "(none)"
echo "::DEV_MODE::" && settings get global development_settings_enabled 2>/dev/null || echo "(none)"
echo "::ANDROID_ID::" && settings get secure android_id 2>/dev/null || echo "(none)"
echo "::ACCESSIBILITY::" && settings get secure enabled_accessibility_services 2>/dev/null || echo "(none)"
""".strip(), timeout=25)
print(b5)

# ═══════════════════════════════════════════════════════
# BATCH 6: Content (SMS, Calls, Contacts), Storage, MAC
# ═══════════════════════════════════════════════════════
print("\n[BATCH 6] Content Providers, Storage, MAC...")
b6 = sh("""
echo "::CONTACTS::" && content query --uri content://com.android.contacts/contacts --projection display_name 2>/dev/null | head -3 || echo "EMPTY"
echo "::CALL_LOG::" && content query --uri content://call_log/calls --projection number:type 2>/dev/null | head -3 || echo "EMPTY"
echo "::SMS::" && content query --uri content://sms --projection address:body 2>/dev/null | head -3 || echo "EMPTY"
echo "::DCIM::" && ls /sdcard/DCIM/ 2>/dev/null | head -3 || echo "EMPTY"
echo "::DOWNLOADS::" && ls /sdcard/Download/ 2>/dev/null | head -3 || echo "EMPTY"
echo "::STORAGE::" && df -h /data 2>/dev/null | tail -1
echo "::MAC_WLAN::" && cat /sys/class/net/wlan0/address 2>/dev/null || echo "(none)"
echo "::IP_LINK::" && ip link show 2>/dev/null | grep -A1 "wlan" | head -3 || echo "(none)"
echo "::ALL_PKGS::" && pm list packages 2>/dev/null | wc -l
echo "::USER_PKGS::" && pm list packages -3 2>/dev/null | wc -l
echo "::SYSTEM_PKGS::" && pm list packages -s 2>/dev/null | wc -l
""".strip(), timeout=25)
print(b6)

# ═══════════════════════════════════════════════════════
# BATCH 7: Extra Deep Checks
# ═══════════════════════════════════════════════════════
print("\n[BATCH 7] Deep Detection Checks...")
b7 = sh("""
echo "::INIT_SVC::" && getprop | grep -c "init.svc"
echo "::QEMU::" && getprop ro.kernel.qemu
echo "::GOLDFISH::" && getprop ro.hardware.audio.primary
echo "::EMULATOR::" && getprop ro.kernel.android.qemud
echo "::BOOTLOADER::" && getprop ro.bootloader
echo "::BOARD::" && getprop ro.product.board
echo "::SOC::" && getprop ro.board.platform
echo "::RADIO::" && getprop gsm.version.baseband
echo "::SERIALNO::" && getprop ro.serialno
echo "::BOOT_SERIAL::" && getprop ro.boot.serialno
echo "::BOOT_ID::" && cat /proc/sys/kernel/random/boot_id
echo "::WIFI_IFACE::" && ls /sys/class/net/ 2>/dev/null
echo "::PROPS_COUNT::" && getprop | wc -l
echo "::LOCATION_PROVIDERS::" && settings get secure location_providers_allowed 2>/dev/null || echo "(none)"
echo "::LOCALE::" && getprop persist.sys.locale
echo "::LANGUAGE::" && getprop persist.sys.language
echo "::COUNTRY::" && getprop persist.sys.country
""".strip(), timeout=25)
print(b7)

# ═══════════════════════════════════════════════════════
# ANALYSIS
# ═══════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANOMALY ANALYSIS")
print("=" * 70)

all_data = "\n".join([str(x) for x in [b1, b2, b3, b4, b5, b6, b7]])
anomalies = []

def check(condition, severity, desc):
    if condition:
        anomalies.append((severity, desc))

# VMOS detection
check("ro.vmos" in all_data and "::VMOS_ROM::" in all_data and all_data.split("::VMOS_ROM::")[1].split("::")[0].strip() not in ["", "(none)"],
      "CRITICAL", "VMOS ROM property (ro.vmos.simplest.rom) is set — instant detection")
check("persist.sys.cloud.padcode" in all_data and "::PADCODE::" in all_data and all_data.split("::PADCODE::")[1].split("::")[0].strip() not in ["", "(none)"],
      "CRITICAL", "VMOS Cloud padcode property exposed")
check("vmos" in all_data.lower() and ("(none)" not in all_data.split("::VMOS_APPS::")[1].split("::")[0] if "::VMOS_APPS::" in all_data else False),
      "CRITICAL", "VMOS app packages detected in package list")

# Missing phone/SMS
for tag, label in [("::PHONE_APPS::", "Phone/Dialer"), ("::SMS_APPS::", "SMS/Messaging")]:
    if tag in all_data:
        val = all_data.split(tag)[1].split("::")[0].strip()
        check("NONE" in val, "HIGH", f"No {label} apps installed — major red flag for any real phone")

# Telephony
if "::TELEPHONY::" in all_data:
    val = all_data.split("::TELEPHONY::")[1].split("::")[0].strip()
    check("NONE" in val, "HIGH", "No telephony registry — RIL/baseband framework missing")

# Sensors
if "::SENSOR_COUNT::" in all_data:
    val = all_data.split("::SENSOR_COUNT::")[1].split("::")[0].strip()
    try:
        cnt = int(val)
        check(cnt == 0, "HIGH", "Zero sensors — impossible on real hardware")
        check(0 < cnt < 5, "MEDIUM", f"Only {cnt} sensors — real phones have 10-20+")
    except: pass

# Camera
if "::CAMERA::" in all_data:
    val = all_data.split("::CAMERA::")[1].split("::")[0].strip()
    check("NONE" in val, "MEDIUM", "No camera service — unusual for modern phone")

# GL Renderer
gl_section = all_data.split("::GL_RENDERER::")[1].split("::")[0] if "::GL_RENDERER::" in all_data else ""
check("swiftshader" in gl_section.lower(), "CRITICAL", "SwiftShader GL renderer — software rendering = VM")
check("llvmpipe" in gl_section.lower(), "CRITICAL", "llvmpipe GL renderer — software rendering = VM")
check("NONE" in gl_section, "HIGH", "No GL renderer info available")

# SELinux
if "::SELINUX::" in all_data:
    val = all_data.split("::SELINUX::")[1].split("::")[0].strip()
    check("Permissive" in val, "HIGH", "SELinux Permissive — rooted/modified device indicator")

# Root
for tag, desc in [("::ROOT_SU::", "su binary"), ("::ROOT_SUPERUSER::", "Superuser.apk")]:
    if tag in all_data:
        val = all_data.split(tag)[1].split("::")[0].strip()
        check("(none)" not in val and val.strip(), "HIGH", f"Root detected: {desc} found")

# ADB
if "::ADB::" in all_data:
    val = all_data.split("::ADB::")[1].split("::")[0].strip()
    check(val == "1", "MEDIUM", "ADB enabled — unusual on consumer device")

# Developer mode
if "::DEV_MODE::" in all_data:
    val = all_data.split("::DEV_MODE::")[1].split("::")[0].strip()
    check(val == "1", "MEDIUM", "Developer options enabled")

# Bluetooth
if "::BLUETOOTH::" in all_data:
    val = all_data.split("::BLUETOOTH::")[1].split("::")[0].strip()
    check("NONE" in val, "MEDIUM", "No Bluetooth adapter — unusual for real phone")

# MAC address
if "::MAC_WLAN::" in all_data:
    val = all_data.split("::MAC_WLAN::")[1].split("::")[0].strip()
    check(val == "02:00:00:00:00:00", "HIGH", "Default null MAC 02:00:00:00:00:00")
    check("(none)" in val, "HIGH", "No wlan0 MAC address available")

# Kernel
if "::KERNEL::" in all_data:
    val = all_data.split("::KERNEL::")[1].split("::")[0].strip()
    check("generic" in val.lower(), "MEDIUM", "Generic kernel — not OEM-specific")

# Emulator properties
if "::QEMU::" in all_data:
    val = all_data.split("::QEMU::")[1].split("::")[0].strip()
    check(val == "1", "CRITICAL", "ro.kernel.qemu=1 — emulator flag set")

if "::GOLDFISH::" in all_data:
    val = all_data.split("::GOLDFISH::")[1].split("::")[0].strip()
    check("goldfish" in val.lower(), "CRITICAL", "Goldfish audio — Android emulator hardware")

# Google services
if "::GOOGLE_PKGS::" in all_data:
    val = all_data.split("::GOOGLE_PKGS::")[1].split("::")[0].strip()
    check("NONE" in val, "HIGH", "No Google packages installed")
    lines = [l for l in val.split("\n") if l.startswith("package:")]
    check(0 < len(lines) < 5, "MEDIUM", f"Only {len(lines)} Google packages (real device has 20+)")

# Accounts
if "::ACCOUNTS::" in all_data:
    val = all_data.split("::ACCOUNTS::")[1].split("::")[0].strip()
    check("NONE" in val, "MEDIUM", "No accounts registered")

# Empty content
if "::CONTACTS::" in all_data:
    val = all_data.split("::CONTACTS::")[1].split("::")[0].strip()
    check("EMPTY" in val or "No result" in val, "LOW", "No contacts on device")
if "::CALL_LOG::" in all_data:
    val = all_data.split("::CALL_LOG::")[1].split("::")[0].strip()
    check("EMPTY" in val or "No result" in val, "LOW", "Empty call log")
if "::SMS::" in all_data:
    val = all_data.split("::SMS::")[1].split("::")[0].strip()
    check("EMPTY" in val or "No result" in val, "LOW", "No SMS messages")

# SIM state
if "::SIM_STATE::" in all_data:
    val = all_data.split("::SIM_STATE::")[1].split("::")[0].strip().lower()
    check("absent" in val or "not_ready" in val, "HIGH", f"SIM state: {val} — no SIM detected")

# Build type
if "::BUILDTYPE::" in all_data:
    val = all_data.split("::BUILDTYPE::")[1].split("::")[0].strip()
    check(val == "eng", "HIGH", "Build type is 'eng' (engineering) — not production")
    check(val == "userdebug", "MEDIUM", "Build type is 'userdebug' — debugging enabled")

# Build tags
if "::BUILDTAGS::" in all_data:
    val = all_data.split("::BUILDTAGS::")[1].split("::")[0].strip()
    check("test-keys" in val, "HIGH", "Build signed with test-keys — not release-keys")

# Print results
print(f"\nTotal anomalies: {len(anomalies)}\n")

severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
anomalies.sort(key=lambda x: severity_order.get(x[0], 99))

for i, (sev, desc) in enumerate(anomalies, 1):
    icon = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "⚡", "LOW": "ℹ️"}.get(sev, "?")
    print(f"  {i:2d}. [{sev:8s}] {icon} {desc}")

crit = sum(1 for s,_ in anomalies if s == "CRITICAL")
high = sum(1 for s,_ in anomalies if s == "HIGH")
med  = sum(1 for s,_ in anomalies if s == "MEDIUM")
low  = sum(1 for s,_ in anomalies if s == "LOW")

print(f"\n  Summary: {crit} CRITICAL, {high} HIGH, {med} MEDIUM, {low} LOW")
risk = "EXTREME" if crit > 0 else "VERY HIGH" if high > 3 else "HIGH" if high > 1 else "MODERATE"
print(f"  Overall Detection Risk: {risk}")

print("\n" + "=" * 70)
print("RAW DATA DUMP (for AI screen agent analysis)")
print("=" * 70)
# Save raw data for reference
print(all_data[-2000:])  # Last 2000 chars
