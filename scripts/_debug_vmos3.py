#!/usr/bin/env python3
"""Full device modification: identity, GPS, SMS, gallery via corrected API format."""
import asyncio, sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

os.environ['VMOS_API_KEY'] = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi'
os.environ['VMOS_API_SECRET'] = 'Q2SgcSwEfuwoedY0cijp6Mce'
os.environ['VMOS_API_HOST'] = 'api.vmoscloud.com'

from vmos_cloud_bridge import VMOSCloudBridge

PAD = 'ACP2509244LGV1MV'

async def update_props(bridge, pad, props, label=""):
    """Use corrected format: padCode singular + props dict."""
    r = await bridge._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
        'padCode': pad,
        'props': props
    })
    task_id = r.get("data", {}).get("taskId", 0)
    if task_id:
        result = await bridge._wait_for_task(task_id, pad)
        print(f"  {label}: ok={result.ok} status={result.status}")
        return result
    else:
        print(f"  {label}: immediate response={r.get('code')} {r.get('msg','')}")
        return r

async def main():
    bridge = VMOSCloudBridge()

    # 1. Device identity -> Samsung Galaxy S25 Ultra (US T-Mobile)
    print("=== 1. DEVICE IDENTITY -> Samsung S25 Ultra ===")
    await update_props(bridge, PAD, {
        'ro.product.brand': 'samsung',
        'ro.product.model': 'SM-S938U',
        'ro.product.device': 'e3q',
        'ro.product.name': 'e3qsqx',
        'ro.product.manufacturer': 'samsung',
        'ro.product.board': 'sun',
        'ro.build.product': 'e3q',
        'ro.hardware': 'e3q',
        'ro.build.version.release': '15',
        'ro.build.version.sdk': '35',
        'ro.build.version.security_patch': '2026-02-05',
        'ro.build.type': 'user',
        'ro.build.tags': 'release-keys',
        'ro.build.fingerprint': 'samsung/e3qsqx/e3q:15/AP3A.241205.015/S938USQS2AXK2:user/release-keys',
        'ro.odm.build.fingerprint': 'samsung/e3qsqx/e3q:15/AP3A.241205.015/S938USQS2AXK2:user/release-keys',
        'ro.product.build.fingerprint': 'samsung/e3qsqx/e3q:15/AP3A.241205.015/S938USQS2AXK2:user/release-keys',
        'ro.system.build.fingerprint': 'samsung/e3qsqx/e3q:15/AP3A.241205.015/S938USQS2AXK2:user/release-keys',
        'ro.vendor.build.fingerprint': 'samsung/e3qsqx/e3q:15/AP3A.241205.015/S938USQS2AXK2:user/release-keys',
    }, label="Device identity")

    # 2. SIM / Carrier -> T-Mobile US
    print("\n=== 2. SIM IDENTITY -> T-Mobile US ===")
    await update_props(bridge, PAD, {
        'persist.sys.cloud.imeinum': '353912115847621',
        'persist.sys.cloud.iccidnum': '89012024716040892345',
        'persist.sys.cloud.imsinum': '310260987654321',
        'persist.sys.cloud.phonenum': '+12125559876',
        'persist.sys.cloud.mobileinfo': '310,260',
    }, label="SIM/Carrier")

    # 3. GPS -> NYC Times Square
    print("\n=== 3. GPS -> NYC Times Square ===")
    await update_props(bridge, PAD, {
        'persist.sys.cloud.gps.lat': '40.7580',
        'persist.sys.cloud.gps.lon': '-73.9855',
        'persist.sys.cloud.gps.altitude': '20.0',
        'persist.sys.cloud.gps.speed': '0',
        'persist.sys.cloud.gps.bearing': '0',
    }, label="GPS")

    # 4. Gallery photos
    print("\n=== 4. GALLERY -> 15 photos ===")
    await update_props(bridge, PAD, {
        'ro.sys.cloud.rand_pics': '15',
    }, label="Gallery")

    # 5. Battery
    print("\n=== 5. BATTERY SIM ===")
    await update_props(bridge, PAD, {
        'persist.sys.cloud.battery.capacity': '5000',
        'persist.sys.cloud.battery.level': '78',
    }, label="Battery")

    # 6. SMS via shell (content insert)
    print("\n=== 6. SMS -> 5 messages via shell ===")
    sms_list = [
        ('+12125554432', 'Hey are you coming to dinner tonight?', 1741870991000),
        ('+12125557821', 'Meeting moved to 3pm tomorrow. See you there!', 1741784591000),
        ('+12125551234', 'Call me when you get home sweetie', 1741698191000),
        ('+19175553214', 'Thanks for the recommendation, just ordered it', 1741611791000),
        ('+16465558765', 'Happy birthday! Hope you have an amazing day', 1741525391000),
    ]
    for sender, body, ts in sms_list:
        cmd = (
            f"content insert --uri content://sms "
            f"--bind address:s:'{sender}' "
            f"--bind body:s:'{body}' "
            f"--bind type:i:1 "
            f"--bind date:l:{ts} "
            f"--bind read:i:1"
        )
        r = await bridge.exec_shell(PAD, cmd)
        print(f"  SMS from {sender}: ok={r.ok}")

    # 7. Verify: read back properties
    print("\n=== 7. VERIFICATION: Read back properties ===")
    r = await bridge._post('/vcpcloud/api/padApi/padProperties', {'padCode': PAD})
    data = r.get('data', {})
    sys_props = {p['propertiesName']: p['propertiesValue'] for p in data.get('systemPropertiesList', [])}
    modem_props = {p['propertiesName']: p['propertiesValue'] for p in data.get('modemPropertiesList', [])}
    
    print(f"  Brand:    {sys_props.get('ro.product.brand', '?')}")
    print(f"  Model:    {sys_props.get('ro.product.model', '?')}")
    print(f"  Device:   {sys_props.get('ro.product.device', '?')}")
    print(f"  Android:  {sys_props.get('ro.build.version.release', '?')}")
    print(f"  IMEI:     {modem_props.get('imei', '?')}")
    print(f"  Phone:    {modem_props.get('phonenum', '?')}")
    print(f"  MCC,MNC:  {modem_props.get('MCCMNC', '?')}")
    print(f"  ICCID:    {modem_props.get('ICCID', '?')}")

    # 8. Verify via shell: check injected data
    print("\n=== 8. SHELL VERIFICATION ===")
    r = await bridge.exec_shell(PAD, "content query --uri content://contacts/phones --projection display_name:phone_number 2>/dev/null | head -10")
    print(f"  Contacts: {r.result[:300] if r.result else 'empty'}")

    r = await bridge.exec_shell(PAD, "content query --uri content://call_log/calls --projection number:duration --sort 'date DESC' 2>/dev/null | head -10")
    print(f"  Call logs: {r.result[:300] if r.result else 'empty'}")

    r = await bridge.exec_shell(PAD, "content query --uri content://sms --projection address:body --sort 'date DESC' 2>/dev/null | head -10")
    print(f"  SMS: {r.result[:300] if r.result else 'empty'}")

    r = await bridge.exec_shell(PAD, "ls /sdcard/DCIM/Camera/ 2>/dev/null | head -5")
    print(f"  Gallery: {r.result[:200] if r.result else 'empty'}")

    r = await bridge.exec_shell(PAD, "getprop ro.product.model")
    print(f"  getprop model: {r.result.strip() if r.result else '?'}")

    r = await bridge.exec_shell(PAD, "getprop ro.product.brand")
    print(f"  getprop brand: {r.result.strip() if r.result else '?'}")

    print("\n=== ALL MODIFICATIONS COMPLETE ===")

asyncio.run(main())
