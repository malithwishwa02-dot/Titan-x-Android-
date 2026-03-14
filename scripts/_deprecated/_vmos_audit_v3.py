#!/usr/bin/env python3
"""
VMOS Full Anomaly Audit v3
Uses http.client (not urllib) which works through TencentEdgeOne CDN.
"""
import hashlib, hmac, json, http.client, time, sys
from datetime import datetime, timezone

PAD = "ACP2509244LGV1MV"
AK = "BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi"
SK = "Q2SgcSwEfuwoedY0cijp6Mce"
HOST = "api.vmoscloud.com"
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
    conn = http.client.HTTPSConnection(HOST, timeout=30)
    conn.request("POST", path, body=bs.encode(), headers=sign(bs))
    resp = conn.getresponse()
    raw = resp.read().decode()
    conn.close()
    try:
        return json.loads(raw)
    except:
        return {"code": -1, "msg": raw[:300]}

def sh(cmd, timeout=25):
    r = api("/vcpcloud/api/padApi/asyncCmd", {"padCodes": [PAD], "scriptContent": cmd})
    if r.get("code") != 200:
        return f"SUBMIT_ERROR:{r.get('code')}"
    tasks = r.get("data", [])
    if not tasks or not tasks[0].get("taskId"):
        return "NO_TASKID"
    tid = tasks[0]["taskId"]
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(2)
        d = api("/vcpcloud/api/padApi/padTaskDetail", {"taskIds": [tid]})
        if d.get("code") == 200 and d.get("data"):
            t = d["data"][0]
            st = t.get("taskStatus", 0)
            if st >= 3:
                return t.get("taskResult", "") if st == 3 else f"FAIL:{t.get('errorMsg','')}"
    return "TIMEOUT"

print("=" * 72)
print("  VMOS CLOUD DEVICE ANOMALY AUDIT v3")
print("  Target: " + PAD)
print("  Using: http.client (bypasses urllib/CDN issue)")
print("=" * 72)

# ─── Device Info ───────────────────────────────────────────────────
print("\n[1/8] Device Info...")
r = api("/vcpcloud/api/padApi/infos", {"padCodes": [PAD]})
if r.get("code") == 200:
    pd = r["data"].get("pageData", [{}])[0]
    print(f"  Status: {pd.get('padStatus')} | IP: {pd.get('deviceIp')} | Grade: {pd.get('padGrade')}")
else:
    print(f"  ERROR: {r.get('msg','')[:100]}")

# ─── Shell connectivity ───────────────────────────────────────────
print("\n[2/8] Shell Connectivity...")
t0 = time.time()
r = sh("echo ALIVE_$(date +%s)")
print(f"  Result: {r} ({time.time()-t0:.1f}s)")
if "SUBMIT_ERROR" in str(r) or "TIMEOUT" in str(r):
    print("  FATAL: Cannot execute shell commands")
    sys.exit(1)

# ─── BATCH 1: Identity & Build ─────────────────────────────────────
print("\n[3/8] Identity & Build...")
b1 = sh("""
P(){ getprop "$1"; }
echo "BRAND=$(P ro.product.brand)"
echo "MODEL=$(P ro.product.model)"
echo "DEVICE=$(P ro.product.device)"
echo "MANUFACTURER=$(P ro.product.manufacturer)"
echo "HARDWARE=$(P ro.hardware)"
echo "FINGERPRINT=$(P ro.build.fingerprint)"
echo "ANDROID=$(P ro.build.version.release)"
echo "SDK=$(P ro.build.version.sdk)"
echo "SECURITY_PATCH=$(P ro.build.version.security_patch)"
echo "BUILD_TYPE=$(P ro.build.type)"
echo "BUILD_TAGS=$(P ro.build.tags)"
echo "DISPLAY=$(P ro.build.display.id)"
echo "BOARD=$(P ro.product.board)"
echo "PLATFORM=$(P ro.board.platform)"
echo "BOOTLOADER=$(P ro.bootloader)"
echo "SERIAL=$(P ro.serialno)"
echo "BOOT_SERIAL=$(P ro.boot.serialno)"
""".strip())
print(b1)

# ─── BATCH 2: VMOS Detection ──────────────────────────────────────
print("\n[4/8] VMOS Detection Vectors...")
b2 = sh("""
P(){ getprop "$1"; }
echo "VMOS_ROM=$(P ro.vmos.simplest.rom)"
echo "PADCODE=$(P persist.sys.cloud.padcode)"
echo "BOOT_VMOS=$(P ro.boot.vmos)"
echo "VMOS_BROWSER=$(P vmos.browser.home)"
echo "QEMU=$(P ro.kernel.qemu)"
echo "GOLDFISH=$(P ro.hardware.audio.primary)"
echo "EMUD=$(P ro.kernel.android.qemud)"
echo "---VMOS_XBIN---"
ls /system/xbin/vmos* 2>/dev/null || echo "(none)"
echo "---VMOS_DATA---"
ls -d /data/data/com.vmos* 2>/dev/null || echo "(none)"
echo "---VMOS_PKGS---"
pm list packages 2>/dev/null | grep -i vmos || echo "(none)"
echo "---KERNEL---"
uname -a
echo "---CPUINFO---"
head -8 /proc/cpuinfo
echo "---MOUNTS---"
mount | grep -iE "vmos|cloud" | head -3 || echo "(none)"
""".strip())
print(b2)

# ─── BATCH 3: Network & SIM & Telephony ───────────────────────────
print("\n[5/8] Network, SIM, Telephony...")
b3 = sh("""
P(){ getprop "$1"; }
echo "CARRIER=$(P gsm.operator.alpha)"
echo "CARRIER_CC=$(P gsm.operator.iso-country)"
echo "CARRIER_NUM=$(P gsm.operator.numeric)"
echo "SIM_OP=$(P gsm.sim.operator.alpha)"
echo "SIM_CC=$(P gsm.sim.operator.iso-country)"
echo "SIM_NUM=$(P gsm.sim.operator.numeric)"
echo "SIM_STATE=$(P gsm.sim.state)"
echo "NET_TYPE=$(P gsm.network.type)"
echo "BASEBAND=$(P gsm.version.baseband)"
echo "IMEI=$(P persist.sys.cloud.imeinum)"
echo "ICCID=$(P persist.sys.cloud.iccidnum)"
echo "TIMEZONE=$(P persist.sys.timezone)"
echo "LOCALE=$(P persist.sys.locale)"
echo "LANGUAGE=$(P persist.sys.language)"
echo "COUNTRY=$(P persist.sys.country)"
echo "DNS1=$(P net.dns1)"
echo "DNS2=$(P net.dns2)"
echo "---PHONE_APPS---"
pm list packages 2>/dev/null | grep -iE "dialer|phone|telecom|incallui" || echo "NONE"
echo "---SMS_APPS---"
pm list packages 2>/dev/null | grep -iE "messaging|mms|sms" || echo "NONE"
echo "---TELEPHONY---"
dumpsys telephony.registry 2>/dev/null | head -5 || echo "NONE"
echo "---INTERFACES---"
ls /sys/class/net/ 2>/dev/null
echo "---MAC---"
cat /sys/class/net/wlan0/address 2>/dev/null || echo "(none)"
""".strip())
print(b3)

# ─── BATCH 4: Google, Accounts, Sensors ───────────────────────────
print("\n[6/8] Google, Accounts, Sensors, Camera...")
b4 = sh("""
echo "---GOOGLE_PKGS---"
pm list packages 2>/dev/null | grep com.google | head -20 || echo "NONE"
echo "---ACCOUNTS---"
dumpsys account 2>/dev/null | grep "Account {" | head -5 || echo "NONE"
echo "---SENSORS---"
dumpsys sensorservice 2>/dev/null | grep -cE "^[0-9]" || echo "0"
echo "sensor_count_above"
dumpsys sensorservice 2>/dev/null | grep -E "^[0-9]" | head -10 || echo "(none)"
echo "---CAMERA---"
dumpsys media.camera 2>/dev/null | grep "Camera ID" | head -5 || echo "NONE"
echo "---GL---"
dumpsys SurfaceFlinger 2>/dev/null | grep -i "GLES" | head -2 || echo "NONE"
echo "EGL=$(getprop ro.hardware.egl)"
echo "---BLUETOOTH---"
dumpsys bluetooth_manager 2>/dev/null | grep "name:" | head -2 || echo "NONE"
echo "BT_ADDR=$(settings get secure bluetooth_address 2>/dev/null)"
""".strip())
print(b4)

# ─── BATCH 5: System State ────────────────────────────────────────
print("\n[7/8] System State, Root, SELinux...")
b5 = sh("""
echo "---DATETIME---"
date
echo "TZ=$(getprop persist.sys.timezone)"
uptime
echo "---BATTERY---"
dumpsys battery 2>/dev/null | grep -E "level|status|health|temperature|technology"
echo "---SCREEN---"
wm size 2>/dev/null
wm density 2>/dev/null
echo "---SECURITY---"
echo "SELINUX=$(getenforce 2>/dev/null)"
echo "SU=$(which su 2>/dev/null || echo none)"
echo "SUPERUSER=$(ls /system/app/Superuser.apk 2>/dev/null || echo none)"
echo "ADB=$(settings get global adb_enabled 2>/dev/null)"
echo "DEV_MODE=$(settings get global development_settings_enabled 2>/dev/null)"
echo "ANDROID_ID=$(settings get secure android_id 2>/dev/null)"
echo "USB_CFG=$(getprop sys.usb.config)"
echo "USB_STATE=$(getprop sys.usb.state)"
echo "LOCATION=$(settings get secure location_providers_allowed 2>/dev/null)"
echo "MOCK_LOC=$(settings get secure mock_location 2>/dev/null)"
""".strip())
print(b5)

# ─── BATCH 6: Content & Storage ──────────────────────────────────
print("\n[8/8] Content Providers, Storage...")
b6 = sh("""
echo "---CONTACTS---"
content query --uri content://com.android.contacts/contacts --projection display_name 2>/dev/null | wc -l || echo "0"
echo "contacts_count_above"
content query --uri content://com.android.contacts/contacts --projection display_name 2>/dev/null | head -3 || echo "EMPTY"
echo "---CALLS---"
content query --uri content://call_log/calls --projection number 2>/dev/null | wc -l || echo "0"
echo "calls_count_above"
echo "---SMS---"
content query --uri content://sms --projection address 2>/dev/null | wc -l || echo "0"
echo "sms_count_above"
echo "---STORAGE---"
df -h /data 2>/dev/null | tail -1
echo "---DCIM---"
ls /sdcard/DCIM/ 2>/dev/null | head -5 || echo "EMPTY"
echo "---DOWNLOADS---"
ls /sdcard/Download/ 2>/dev/null | head -5 || echo "EMPTY"
echo "---PKG_COUNT---"
echo "TOTAL=$(pm list packages 2>/dev/null | wc -l)"
echo "SYSTEM=$(pm list packages -s 2>/dev/null | wc -l)"
echo "USER=$(pm list packages -3 2>/dev/null | wc -l)"
echo "PROPS_COUNT=$(getprop | wc -l)"
echo "INIT_SVC=$(getprop | grep -c init.svc)"
""".strip())
print(b6)

# ══════════════════════════════════════════════════════════════════
# ANOMALY ANALYSIS
# ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("  ANOMALY ANALYSIS")
print("=" * 72)

all_raw = "\n".join([str(x) for x in [b1, b2, b3, b4, b5, b6]])
findings = []

def kv(data, key):
    """Extract KEY=VALUE from output."""
    for line in data.split("\n"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""

def section(data, marker):
    """Extract content between ---MARKER--- tags."""
    if f"---{marker}---" in data:
        after = data.split(f"---{marker}---", 1)[1]
        # Find next --- marker
        if "---" in after[3:]:
            idx = after.index("---", 3)
            return after[:idx].strip()
        return after.strip()
    return ""

def flag(sev, msg):
    findings.append((sev, msg))

## === IDENTITY ===
brand = kv(b1, "BRAND")
model = kv(b1, "MODEL")
fp = kv(b1, "FINGERPRINT")
bt = kv(b1, "BUILD_TYPE")
tags = kv(b1, "BUILD_TAGS")
serial = kv(b1, "SERIAL")

if "vmos" in brand.lower() or "vmos" in model.lower() or "vmos" in fp.lower():
    flag("CRITICAL", f"VMOS in device identity: brand={brand} model={model}")
if "vivo" in brand.lower() and "vmos" not in brand.lower():
    flag("HIGH", f"VMOS default brand 'vivo' detected (brand={brand}, model={model})")
if not serial:
    flag("HIGH", "Empty serial number (ro.serialno)")
if bt == "eng":
    flag("HIGH", "Build type is 'eng' (engineering build)")
elif bt == "userdebug":
    flag("MEDIUM", "Build type is 'userdebug' (debug enabled)")
if "test-keys" in tags:
    flag("HIGH", "Build signed with test-keys (not release-keys)")

## === VMOS DETECTION ===
vmos_rom = kv(b2, "VMOS_ROM")
padcode = kv(b2, "PADCODE")
boot_vmos = kv(b2, "BOOT_VMOS")
qemu = kv(b2, "QEMU")
goldfish = kv(b2, "GOLDFISH")

if vmos_rom:
    flag("CRITICAL", f"VMOS ROM property set: '{vmos_rom}'")
if padcode:
    flag("CRITICAL", f"Cloud padcode exposed: '{padcode}'")
if boot_vmos:
    flag("CRITICAL", f"ro.boot.vmos set: '{boot_vmos}'")
if qemu == "1":
    flag("CRITICAL", "ro.kernel.qemu=1 (emulator flag)")
if "goldfish" in goldfish.lower():
    flag("CRITICAL", "Goldfish audio (emulator hardware)")

vmos_pkgs = section(b2, "VMOS_PKGS")
if "(none)" not in vmos_pkgs and vmos_pkgs:
    flag("CRITICAL", f"VMOS packages installed: {vmos_pkgs}")

vmos_xbin = section(b2, "VMOS_XBIN")
if "(none)" not in vmos_xbin and vmos_xbin:
    flag("CRITICAL", f"VMOS binaries in /system/xbin: {vmos_xbin}")

vmos_data = section(b2, "VMOS_DATA")
if "(none)" not in vmos_data and vmos_data:
    flag("CRITICAL", f"VMOS data dirs: {vmos_data}")

kernel = section(b2, "KERNEL")
if "generic" in kernel.lower():
    flag("MEDIUM", f"Generic kernel: {kernel[:80]}")

## === NETWORK/SIM ===
carrier = kv(b3, "CARRIER")
sim_state = kv(b3, "SIM_STATE")
sim_op = kv(b3, "SIM_OP")
sim_cc = kv(b3, "SIM_CC")
sim_num = kv(b3, "SIM_NUM")
tz = kv(b3, "TIMEZONE")
locale = kv(b3, "LOCALE")
country = kv(b3, "COUNTRY")
baseband = kv(b3, "BASEBAND")
net_type = kv(b3, "NET_TYPE")

if not carrier and not sim_op:
    flag("HIGH", "No carrier/operator name set")
if sim_state.lower() in ("absent", "not_ready", ""):
    flag("HIGH", f"SIM state: '{sim_state}' — no SIM detected")
if not baseband:
    flag("HIGH", "No baseband/RIL version (no real modem)")
if not net_type:
    flag("MEDIUM", "No network type (gsm.network.type empty)")

# Check phone/SMS apps
phone_apps = section(b3, "PHONE_APPS")
sms_apps = section(b3, "SMS_APPS")
if "NONE" in phone_apps:
    flag("HIGH", "No Phone/Dialer apps installed")
if "NONE" in sms_apps:
    flag("HIGH", "No SMS/Messaging apps installed")

telephony = section(b3, "TELEPHONY")
if "NONE" in telephony:
    flag("HIGH", "No telephony registry (RIL framework missing)")

# Network interfaces
ifaces = section(b3, "INTERFACES")
if "eth0" in ifaces:
    flag("HIGH", "eth0 interface present (cloud/VM indicator)")

mac = section(b3, "MAC")
if "02:00:00:00:00:00" in mac:
    flag("HIGH", "Default null MAC address 02:00:00:00:00:00")
if "(none)" in mac:
    flag("HIGH", "No wlan0 MAC address")

# Timezone/locale vs SIM mismatch
if tz and sim_cc:
    if "US" in sim_cc.upper() and "America" not in tz:
        flag("CRITICAL", f"Timezone/SIM mismatch: TZ={tz} but SIM country={sim_cc}")
    if "MY" in sim_cc.upper() or "502" in str(sim_num):
        flag("CRITICAL", f"Malaysian SIM detected: op={sim_op} mcc={sim_num} (with US proxy = fatal)")
elif tz and "Asia" in tz:
    flag("HIGH", f"Asian timezone ({tz}) — suspicious with US proxy")

## === GOOGLE/SENSORS ===
google = section(b4, "GOOGLE_PKGS")
accounts = section(b4, "ACCOUNTS")
sensors_raw = section(b4, "SENSORS")
camera = section(b4, "CAMERA")
gl = section(b4, "GL")
bt_section = section(b4, "BLUETOOTH")

if "NONE" in google:
    flag("HIGH", "No Google packages installed")
if "NONE" in accounts:
    flag("MEDIUM", "No accounts registered on device")

# Parse sensor count
sensor_lines = [l for l in sensors_raw.split("\n") if l.strip().isdigit()]
if sensor_lines:
    try:
        sensor_count = int(sensor_lines[0])
        if sensor_count == 0:
            flag("HIGH", "Zero sensors — impossible on real hardware")
        elif sensor_count < 5:
            flag("MEDIUM", f"Only {sensor_count} sensors (real phones have 10-20+)")
    except:
        pass

if "NONE" in camera:
    flag("MEDIUM", "No camera service")

if "swiftshader" in gl.lower():
    flag("CRITICAL", "SwiftShader GL renderer (software rendering = VM)")
elif "llvmpipe" in gl.lower():
    flag("CRITICAL", "llvmpipe GL renderer (software rendering = VM)")

if "NONE" in bt_section:
    flag("MEDIUM", "No Bluetooth manager")

## === SYSTEM STATE ===
selinux = kv(b5, "SELINUX")
su = kv(b5, "SU")
adb = kv(b5, "ADB")
dev_mode = kv(b5, "DEV_MODE")
mock_loc = kv(b5, "MOCK_LOC")

if "Permissive" in selinux:
    flag("HIGH", "SELinux Permissive (rooted/modified)")
if su and su != "none":
    flag("HIGH", f"Root: su binary at {su}")
if adb == "1":
    flag("MEDIUM", "ADB enabled")
if dev_mode == "1":
    flag("MEDIUM", "Developer options enabled")
if mock_loc == "1":
    flag("MEDIUM", "Mock location enabled")

## === CONTENT ===
contacts_sec = section(b6, "CONTACTS")
contacts_lines = contacts_sec.split("\n")
contacts_count = 0
for l in contacts_lines:
    if l.strip().isdigit():
        contacts_count = int(l.strip())
        break

calls_sec = section(b6, "CALLS")
calls_count = 0
for l in calls_sec.split("\n"):
    if l.strip().isdigit():
        calls_count = int(l.strip())
        break

sms_sec = section(b6, "SMS")
sms_count = 0
for l in sms_sec.split("\n"):
    if l.strip().isdigit():
        sms_count = int(l.strip())
        break

if contacts_count == 0:
    flag("LOW", "No contacts on device")
if calls_count == 0:
    flag("LOW", "Empty call log")
if sms_count == 0:
    flag("LOW", "No SMS messages")

dcim = section(b6, "DCIM")
if "EMPTY" in dcim:
    flag("MEDIUM", "Empty DCIM folder (no photos)")

# Print findings
severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
findings.sort(key=lambda x: severity_order.get(x[0], 99))

print()
for i, (sev, desc) in enumerate(findings, 1):
    icon = {"CRITICAL": "🚨", "HIGH": "⚠️ ", "MEDIUM": "⚡", "LOW": "ℹ️ "}.get(sev, "?")
    print(f"  {i:2d}. [{sev:8s}] {icon}  {desc}")

crit = sum(1 for s,_ in findings if s == "CRITICAL")
high = sum(1 for s,_ in findings if s == "HIGH")
med  = sum(1 for s,_ in findings if s == "MEDIUM")
low  = sum(1 for s,_ in findings if s == "LOW")

print(f"\n  Totals: {crit} CRITICAL | {high} HIGH | {med} MEDIUM | {low} LOW")
score = crit * 25 + high * 10 + med * 3 + low * 1
score = min(score, 100)
risk = "EXTREME" if crit > 0 else "VERY HIGH" if high > 3 else "HIGH" if high > 1 else "MODERATE"
print(f"  Risk Score: {score}/100   Detection Level: {risk}")

# ══════════════════════════════════════════════════════════════════
# SCREENSHOT URL for AI analysis
# ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("  SCREENSHOT FOR AI ANALYSIS")
print("=" * 72)
r = api("/vcpcloud/api/padApi/getLongGenerateUrl", {"padCodes": [PAD], "format": "png"})
if r.get("code") == 200:
    items = r.get("data", [])
    if items and items[0].get("success"):
        print(f"  URL: {items[0]['url']}")
    else:
        print("  Screenshot not available")
else:
    print(f"  Screenshot API error: {r.get('msg','')[:80]}")

print("\n" + "=" * 72)
print("  AUDIT COMPLETE")
print("=" * 72)
