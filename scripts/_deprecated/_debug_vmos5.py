#!/usr/bin/env python3
"""Debug restart API + verify prop changes via alternative methods."""
import asyncio, sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

os.environ['VMOS_API_KEY'] = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi'
os.environ['VMOS_API_SECRET'] = 'Q2SgcSwEfuwoedY0cijp6Mce'
os.environ['VMOS_API_HOST'] = 'api.vmoscloud.com'

from vmos_cloud_bridge import VMOSCloudBridge

PAD = 'ACP2509244LGV1MV'

async def main():
    bridge = VMOSCloudBridge()

    # 1. Check raw restart response
    print("=== Raw restart response ===")
    r = await bridge._post('/vcpcloud/api/padApi/restart', {'padCodes': [PAD]})
    print(json.dumps(r, indent=2, default=str)[:1500])

    # 2. Try reboot via shell
    print("\n=== Reboot via shell ===")
    r = await bridge.exec_shell(PAD, "reboot")
    print(f"  reboot shell: ok={r.ok} status={r.status} result={r.result[:200] if r.result else ''} error={r.error[:200] if r.error else ''}")

    # Wait for reboot
    print("\n=== Waiting 30s for reboot... ===")
    await asyncio.sleep(30)

    # 3. Test if alive
    print("=== Testing if alive ===")
    r = await bridge.exec_shell(PAD, "echo alive && getprop ro.product.brand && getprop ro.product.model")
    print(f"  ok={r.ok} result={r.result.strip() if r.result else '?'}")

    # 4. Check properties API
    print("\n=== Properties API ===")
    r = await bridge._post('/vcpcloud/api/padApi/padProperties', {'padCode': PAD})
    data = r.get('data', {})
    sys_props = {p['propertiesName']: p['propertiesValue'] for p in data.get('systemPropertiesList', [])}
    modem_props = {p['propertiesName']: p['propertiesValue'] for p in data.get('modemPropertiesList', [])}
    print(f"  Brand: {sys_props.get('ro.product.brand', '?')}")
    print(f"  Model: {sys_props.get('ro.product.model', '?')}")
    print(f"  IMEI:  {modem_props.get('imei', '?')}")
    print(f"  Phone: {modem_props.get('phonenum', '?')}")
    print(f"  MCC:   {modem_props.get('MCCMNC', '?')}")

    # 5. Try setprop via shell directly
    print("\n=== Direct setprop via shell ===")
    setprops = {
        'ro.product.brand': 'samsung',
        'ro.product.model': 'SM-S938U',
        'ro.product.device': 'e3q',
        'ro.product.manufacturer': 'samsung',
        'ro.build.version.release': '15',
        'ro.build.version.sdk': '35',
    }
    for k, v in setprops.items():
        r = await bridge.exec_shell(PAD, f"setprop {k} {v}")
        print(f"  setprop {k}={v}: ok={r.ok}")

    # Verify via getprop
    print("\n=== Verify via getprop ===")
    r = await bridge.exec_shell(PAD, "getprop ro.product.brand && getprop ro.product.model && getprop ro.product.device && getprop ro.build.version.release")
    print(f"  {r.result.strip() if r.result else '?'}")

    # 6. Verify data injection
    print("\n=== Data check ===")
    r = await bridge.exec_shell(PAD, "content query --uri content://contacts/phones --projection display_name 2>&1 | head -10")
    print(f"  Contacts: {r.result[:300] if r.result else 'empty'}")

    r = await bridge.exec_shell(PAD, "content query --uri content://call_log/calls --projection number:duration 2>&1 | head -10")
    print(f"  Calls: {r.result[:300] if r.result else 'empty'}")

    r = await bridge.exec_shell(PAD, "content query --uri content://sms --projection address:body 2>&1 | head -10")
    print(f"  SMS: {r.result[:300] if r.result else 'empty'}")

asyncio.run(main())
