#!/usr/bin/env python3
"""
All-in-one: UI analysis, Samsung identity patch, content injection, and audit.
Uses http.client for VMOS Cloud API (workaround for TencentEdgeOne CDN).
"""
import hashlib, hmac, http.client, json, time, re, sys
from datetime import datetime, timezone

AK = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi'
SK = 'Q2SgcSwEfuwoedY0cijp6Mce'
HOST = 'api.vmoscloud.com'
SVC = 'armcloud-paas'
PAD = 'ACP2509244LGV1MV'

def sign(body_str):
    x_date = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    short = x_date[:8]
    ct = 'application/json;charset=UTF-8'
    sh_h = 'content-type;host;x-content-sha256;x-date'
    xh = hashlib.sha256(body_str.encode()).hexdigest()
    canon = f'host:{HOST}\nx-date:{x_date}\ncontent-type:{ct}\nsignedHeaders:{sh_h}\nx-content-sha256:{xh}'
    hc = hashlib.sha256(canon.encode()).hexdigest()
    cs = f'{short}/{SVC}/request'
    sts = f'HMAC-SHA256\n{x_date}\n{cs}\n{hc}'
    kd = hmac.new(SK.encode(), short.encode(), hashlib.sha256).digest()
    ks = hmac.new(kd, SVC.encode(), hashlib.sha256).digest()
    kr = hmac.new(ks, b'request', hashlib.sha256).digest()
    sig = hmac.new(kr, sts.encode(), hashlib.sha256).hexdigest()
    return {'content-type': ct, 'x-host': HOST, 'x-date': x_date,
            'authorization': f'HMAC-SHA256 Credential={AK}, SignedHeaders={sh_h}, Signature={sig}'}

def api(path, body):
    bs = json.dumps(body, separators=(',', ':'))
    conn = http.client.HTTPSConnection(HOST, timeout=30)
    conn.request('POST', path, body=bs.encode(), headers=sign(bs))
    resp = conn.getresponse()
    raw = resp.read().decode()
    conn.close()
    return json.loads(raw)

def sh(cmd, timeout=60):
    r = api('/vcpcloud/api/padApi/asyncCmd', {'padCodes': [PAD], 'scriptContent': cmd})
    if r.get('code') != 200:
        return f'CMD_ERR:{r.get("code")}'
    tid = r.get('data', [{}])[0].get('taskId', 0)
    if not tid:
        return 'NO_TID'
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(3)
        d = api('/vcpcloud/api/padApi/padTaskDetail', {'taskIds': [tid]})
        if d.get('code') == 200 and d.get('data'):
            t = d['data'][0]
            ts = t.get('taskStatus', 0)
            if ts >= 3:
                return t.get('taskResult', '') if ts == 3 else f'FAIL:{t.get("errorMsg","")}'
    return 'TIMEOUT'

def update_props(props_dict):
    """Use updatePadAndroidProp API to set device properties."""
    r = api('/vcpcloud/api/padApi/updatePadAndroidProp', {
        'padCode': PAD,
        'props': props_dict
    })
    return r

def wait_between():
    time.sleep(3)

# ============================================================
# PHASE 1: UI ANALYSIS (quick — just get XML chunks)
# ============================================================
def phase1_ui():
    print("=" * 60)
    print("PHASE 1: UI ANALYSIS")
    print("=" * 60)

    # Get 6 chunks of 1900 bytes each covering the 11309 byte file
    full_xml = ""
    for i in range(6):
        skip = i * 1900
        r = sh(f'tail -c +{skip + 1} /sdcard/ui_dump.xml | head -c 1900')
        if r and r not in ('TIMEOUT', 'NO_TID'):
            full_xml += r
        wait_between()

    if not full_xml:
        print("  [!] Could not retrieve UI dump")
        return

    # Parse the XML for key attributes
    texts = set(re.findall(r'text="([^"]+)"', full_xml))
    descs = set(re.findall(r'content-desc="([^"]+)"', full_xml))
    pkgs = set(re.findall(r'package="([^"]+)"', full_xml))
    res_ids = set(re.findall(r'resource-id="([^"]+)"', full_xml))

    print(f"\n  VISIBLE TEXT: {sorted(texts) if texts else '(none)'}")
    print(f"  CONTENT DESCS: {sorted(descs) if descs else '(none)'}")
    print(f"  PACKAGES: {sorted(pkgs)}")
    print(f"  RESOURCE IDS: {sorted(res_ids)[:20]}")

    # Anomaly checks
    anomalies = []
    if 'com.android.mxLauncher3' in pkgs:
        anomalies.append("[HIGH] VMOS custom launcher 'mxLauncher3' visible — detectable!")
    if any('vmos' in t.lower() for t in texts | descs):
        anomalies.append("[HIGH] VMOS branding visible on screen")
    if any('emulat' in t.lower() or 'virtual' in t.lower() for t in texts | descs):
        anomalies.append("[MED] Emulator/virtual references visible")

    if anomalies:
        print(f"\n  UI ANOMALIES FOUND:")
        for a in anomalies:
            print(f"    {a}")
    else:
        print(f"\n  UI ANOMALIES: None found (besides launcher package)")
    print()

# ============================================================
# PHASE 2: SAMSUNG IDENTITY PATCH (via updatePadAndroidProp)
# ============================================================
def phase2_identity():
    print("=" * 60)
    print("PHASE 2: SAMSUNG GALAXY S25 ULTRA IDENTITY PATCH")
    print("=" * 60)

    # Samsung Galaxy S25 Ultra identity
    # Split into batches of max 8 props (API format: key=value in props dict)
    batches = [
        # Batch 1: Core identity
        {
            "ro.product.brand": "samsung",
            "ro.product.device": "e3q",
            "ro.product.manufacturer": "samsung",
            "ro.product.model": "SM-S928U",
            "ro.product.name": "e3qxeq",
            "ro.product.board": "sun",
        },
        # Batch 2: Build info
        {
            "ro.build.display.id": "UP1A.231005.007.S928USQU3AXL2",
            "ro.build.fingerprint": "samsung/e3qxeq/e3q:15/UP1A.231005.007/S928USQU3AXL2:user/release-keys",
            "ro.build.description": "e3qxeq-user 15 UP1A.231005.007 S928USQU3AXL2 release-keys",
            "ro.build.product": "e3q",
            "ro.build.type": "user",
            "ro.build.tags": "release-keys",
        },
        # Batch 3: Hardware
        {
            "ro.hardware": "qcom",
            "ro.hardware.chipname": "sun",
            "ro.board.platform": "sun",
            "ro.product.first_api_level": "35",
            "ro.build.version.sdk": "35",
            "ro.build.version.release": "15",
        },
        # Batch 4: Security + serial
        {
            "ro.build.version.security_patch": "2025-02-01",
            "ro.serialno": "R5CT42WFGHJ",
            "ro.boot.serialno": "R5CT42WFGHJ",
            "gsm.version.baseband": "S928USQU3AXL2",
            "ro.build.version.incremental": "S928USQU3AXL2",
        },
        # Batch 5: Samsung-specific
        {
            "ro.product.vendor.brand": "samsung",
            "ro.product.vendor.device": "e3q",
            "ro.product.vendor.manufacturer": "samsung",
            "ro.product.vendor.model": "SM-S928U",
            "ro.product.vendor.name": "e3qxeq",
        },
        # Batch 6: System + ODM
        {
            "ro.product.system.brand": "samsung",
            "ro.product.system.device": "e3q",
            "ro.product.system.manufacturer": "samsung",
            "ro.product.system.model": "SM-S928U",
            "ro.product.system.name": "e3qxeq",
        },
        # Batch 7: Bootimage + persist props
        {
            "ro.product.bootimage.brand": "samsung",
            "ro.product.bootimage.device": "e3q",
            "ro.product.bootimage.model": "SM-S928U",
            "ro.product.bootimage.name": "e3qxeq",
            "persist.sys.timezone": "America/New_York",
            "persist.sys.language": "en",
            "persist.sys.country": "US",
        },
        # Batch 8: Display + Bluetooth
        {
            "ro.product.odm.brand": "samsung",
            "ro.product.odm.device": "e3q",
            "ro.product.odm.model": "SM-S928U",
            "ro.product.odm.name": "e3qxeq",
            "ro.boot.hardware": "qcom",
        },
    ]

    total_ok = 0
    total_fail = 0
    for i, batch in enumerate(batches):
        print(f"\n  Batch {i+1}/{len(batches)} ({len(batch)} props)...", end=" ", flush=True)
        r = update_props(batch)
        code = r.get('code')
        if code == 200:
            print(f"OK")
            total_ok += len(batch)
        else:
            print(f"FAIL: code={code}, msg={r.get('msg','')}")
            total_fail += len(batch)
        time.sleep(2)

    print(f"\n  RESULT: {total_ok} props set, {total_fail} failed")
    print()

# ============================================================
# PHASE 3: SET PERSIST PROPS VIA SHELL (these survive reboot)
# ============================================================
def phase3_persist():
    print("=" * 60)
    print("PHASE 3: PERSIST PROPS (via shell setprop)")
    print("=" * 60)

    persist_props = {
        "persist.sys.timezone": "America/New_York",
        "persist.sys.language": "en",
        "persist.sys.country": "US",
        "persist.sys.localevar": "",
        "persist.sys.wifi.country_code": "US",
        "persist.radio.device.imei": "358476311776126",
        "persist.sys.dalvik.vm.lib.2": "libart.so",
    }

    cmds = " && ".join([f'setprop {k} "{v}"' for k, v in persist_props.items()])
    cmds += ' && echo PERSIST_DONE'
    r = sh(cmds)
    print(f"  Result: {r}")
    print()

# ============================================================
# PHASE 4: INJECT CONTACTS, CALL LOG, SMS
# ============================================================
def phase4_content():
    print("=" * 60)
    print("PHASE 4: INJECT CONTACTS, CALLS, SMS")
    print("=" * 60)

    # --- Contacts ---
    contacts = [
        ("Mom", "+12125559001"),
        ("Dad", "+12125559002"),
        ("Sarah", "+14155559003"),
        ("Mike T", "+17185559004"),
        ("Work - Lisa", "+12125559005"),
        ("Dr. Martinez", "+12125559006"),
        ("Pizza Palace", "+17185559007"),
        ("Home Insurance", "+18005559008"),
        ("Jake", "+19175559009"),
        ("Ashley B", "+13475559010"),
        ("Gym Front Desk", "+12125559011"),
        ("Amazon Support", "+18005559012"),
    ]

    print(f"\n  Injecting {len(contacts)} contacts...")
    for name, number in contacts:
        # Use content insert for raw_contacts + data
        cmd = (
            f'content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s:local --bind account_name:s:local && '
            f'LAST_ID=$(content query --uri content://com.android.contacts/raw_contacts --projection _id --sort "_id DESC LIMIT 1" 2>/dev/null | head -1 | sed "s/.*_id=//;s/,.*//") && '
            f'content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$LAST_ID --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:"{name}" && '
            f'content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$LAST_ID --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:"{number}" --bind data2:i:2'
        )
        r = sh(cmd, timeout=20)
        status = "OK" if r and 'FAIL' not in r and 'ERR' not in r and 'TIMEOUT' not in r else f"FAIL({r[:50]})"
        print(f"    {name}: {status}")
        time.sleep(2)

    # --- Call Log ---
    print(f"\n  Injecting call log entries...")
    # Timestamps going back over recent days
    now = int(time.time() * 1000)
    calls = [
        ("+12125559001", "Mom", 1, 245000, now - 86400000 * 1),    # incoming yesterday
        ("+14155559003", "Sarah", 2, 182000, now - 86400000 * 1),   # outgoing yesterday  
        ("+12125559005", "Work - Lisa", 1, 420000, now - 86400000 * 2),  # incoming 2d ago
        ("+17185559004", "Mike T", 3, 0, now - 86400000 * 2),       # missed 2d ago
        ("+12125559001", "Mom", 2, 380000, now - 86400000 * 3),     # outgoing 3d ago
        ("+19175559009", "Jake", 1, 120000, now - 86400000 * 4),    # incoming 4d ago
        ("+13475559010", "Ashley B", 2, 560000, now - 86400000 * 5), # outgoing 5d ago
        ("+12125559006", "Dr. Martinez", 2, 95000, now - 86400000 * 7),  # outgoing 7d ago
        ("+18005559008", "Home Insurance", 1, 620000, now - 86400000 * 10), # incoming 10d ago
        ("+14155559003", "Sarah", 2, 340000, now - 86400000 * 12),  # outgoing 12d ago
        ("+12125559001", "Mom", 1, 190000, now - 86400000 * 14),    # incoming 14d ago
        ("+17185559007", "Pizza Palace", 2, 45000, now - 86400000 * 15), # outgoing 15d ago
        ("+19175559009", "Jake", 3, 0, now - 86400000 * 18),        # missed 18d ago
        ("+12125559011", "Gym Front Desk", 2, 30000, now - 86400000 * 20), # outgoing 20d ago
        ("+12125559005", "Work - Lisa", 1, 890000, now - 86400000 * 25), # incoming 25d ago
    ]

    for number, name, call_type, duration, date_ms in calls:
        cmd = (
            f'content insert --uri content://call_log/calls '
            f'--bind number:s:"{number}" '
            f'--bind name:s:"{name}" '
            f'--bind type:i:{call_type} '
            f'--bind duration:i:{duration // 1000} '
            f'--bind date:l:{date_ms} '
            f'--bind new:i:0'
        )
        r = sh(cmd, timeout=20)
        ctype = {1: "IN", 2: "OUT", 3: "MISS"}[call_type]
        status = "OK" if r and 'FAIL' not in r and 'ERR' not in r and 'TIMEOUT' not in r else f"FAIL"
        print(f"    {ctype} {name}: {status}")
        time.sleep(2)

    # --- SMS ---
    print(f"\n  Injecting SMS messages...")
    sms_msgs = [
        ("+12125559001", "Hey sweetie, don't forget dinner at 7!", 1, now - 86400000 * 1, 1),
        ("+12125559001", "On my way! Should I pick up dessert?", 2, now - 86400000 * 1 + 300000, 2),
        ("+14155559003", "Are we still on for Saturday?", 1, now - 86400000 * 2, 1),
        ("+14155559003", "Yes! I'll be there around 3", 2, now - 86400000 * 2 + 180000, 2),
        ("+17185559004", "Dude check out this restaurant I found", 1, now - 86400000 * 3, 1),
        ("+12125559005", "Meeting moved to 2pm. Conference room B.", 1, now - 86400000 * 4, 1),
        ("+12125559005", "Got it, thanks Lisa", 2, now - 86400000 * 4 + 60000, 2),
        ("+19175559009", "Yo are you coming to the game tonight", 1, now - 86400000 * 7, 1),
    ]

    for number, body, sms_type, date_ms, read in sms_msgs:
        safe_body = body.replace("'", "")
        cmd = (
            f"content insert --uri content://sms "
            f"--bind address:s:\"{number}\" "
            f"--bind body:s:\"{safe_body}\" "
            f"--bind type:i:{sms_type} "
            f"--bind date:l:{date_ms} "
            f"--bind read:i:{read}"
        )
        r = sh(cmd, timeout=20)
        direction = "IN" if sms_type == 1 else "OUT"
        status = "OK" if r and 'FAIL' not in r and 'ERR' not in r and 'TIMEOUT' not in r else "FAIL"
        print(f"    {direction} {number}: {status}")
        time.sleep(2)

    print()

# ============================================================
# PHASE 5: VERIFY 
# ============================================================
def phase5_verify():
    print("=" * 60)
    print("PHASE 5: VERIFICATION")
    print("=" * 60)

    print("\n  Checking identity props...")
    r = sh('getprop ro.product.brand && getprop ro.product.model && getprop ro.build.fingerprint')
    print(f"    Brand/Model/FP: {r}")
    wait_between()

    print("\n  Checking content counts...")
    r = sh('content query --uri content://com.android.contacts/contacts --projection _id 2>/dev/null | wc -l && content query --uri content://call_log/calls --projection _id 2>/dev/null | wc -l && content query --uri content://sms --projection _id 2>/dev/null | wc -l')
    print(f"    Contacts/Calls/SMS lines: {r}")
    wait_between()

    print("\n  Checking carrier/SIM...")
    r = sh('getprop gsm.sim.operator.alpha && getprop gsm.sim.state && getprop persist.sys.timezone')
    print(f"    Carrier/SIM/TZ: {r}")
    print()

# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    phases = sys.argv[1:] if len(sys.argv) > 1 else ['1', '2', '3', '4', '5']

    # Quick connectivity check
    print("Checking device connectivity...")
    r = sh('echo ALIVE')
    if 'ALIVE' not in str(r):
        print(f"  [!] Device not responding: {r}")
        print("  Waiting 30s for task queue...")
        time.sleep(30)
        r = sh('echo ALIVE')
        if 'ALIVE' not in str(r):
            print(f"  [!] Still not responding: {r}")
            sys.exit(1)
    print("  Device is ALIVE\n")

    if '1' in phases:
        phase1_ui()
    if '2' in phases:
        phase2_identity()
    if '3' in phases:
        phase3_persist()
    if '4' in phases:
        phase4_content()
    if '5' in phases:
        phase5_verify()

    print("=" * 60)
    print("ALL PHASES COMPLETE")
    print("=" * 60)
