#!/usr/bin/env python3
"""Wait for prop update tasks, restart device, and verify modifications."""
import asyncio, sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

os.environ['VMOS_API_KEY'] = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi'
os.environ['VMOS_API_SECRET'] = 'Q2SgcSwEfuwoedY0cijp6Mce'
os.environ['VMOS_API_HOST'] = 'api.vmoscloud.com'

from vmos_cloud_bridge import VMOSCloudBridge

PAD = 'ACP2509244LGV1MV'

async def main():
    bridge = VMOSCloudBridge()

    # Check: does the device need restart?
    print("=== Pre-restart: Check current shell getprop ===")
    r = await bridge.exec_shell(PAD, "getprop ro.product.brand && getprop ro.product.model && getprop ro.build.fingerprint")
    print(f"  Current: {r.result.strip() if r.result else '?'}")

    # Restart the device
    print("\n=== Restarting device... ===")
    r = await bridge.restart_instance(PAD)
    print(f"  Restart: ok={r.ok} status={r.status} result={r.result[:200] if r.result else ''}")

    # Wait for device to come back online
    print("\n=== Waiting for device to come back online... ===")
    import time
    for i in range(30):
        await asyncio.sleep(5)
        try:
            instances = await bridge.list_instances()
            for inst in instances:
                if inst.pad_code == PAD:
                    print(f"  [{i*5}s] status={inst.status} online={inst.online}")
                    if inst.status == "running":
                        # Try a shell command to confirm it's really up
                        try:
                            r = await bridge.exec_shell(PAD, "echo alive")
                            if r.ok:
                                print(f"  Device is alive!")
                                break
                        except:
                            pass
        except Exception as e:
            print(f"  [{i*5}s] Error checking: {e}")
    else:
        print("  Timeout waiting for device")

    # Extra wait for boot completion
    print("\n  Waiting 15s extra for boot settle...")
    await asyncio.sleep(15)

    # Verify properties via API
    print("\n=== Post-restart: Properties via API ===")
    r = await bridge._post('/vcpcloud/api/padApi/padProperties', {'padCode': PAD})
    data = r.get('data', {})
    sys_props = {p['propertiesName']: p['propertiesValue'] for p in data.get('systemPropertiesList', [])}
    modem_props = {p['propertiesName']: p['propertiesValue'] for p in data.get('modemPropertiesList', [])}

    print(f"  Brand:       {sys_props.get('ro.product.brand', '?')}")
    print(f"  Model:       {sys_props.get('ro.product.model', '?')}")
    print(f"  Device:      {sys_props.get('ro.product.device', '?')}")
    print(f"  Fingerprint: {sys_props.get('ro.build.fingerprint', '?')[:80]}")
    print(f"  Android:     {sys_props.get('ro.build.version.release', '?')}")
    print(f"  SDK:         {sys_props.get('ro.build.version.sdk', '?')}")
    print(f"  SecPatch:    {sys_props.get('ro.build.version.security_patch', '?')}")
    print(f"  IMEI:        {modem_props.get('imei', '?')}")
    print(f"  Phone:       {modem_props.get('phonenum', '?')}")
    print(f"  MCCMNC:      {modem_props.get('MCCMNC', '?')}")
    print(f"  ICCID:       {modem_props.get('ICCID', '?')}")
    print(f"  IMSI:        {modem_props.get('IMSI', '?')}")

    # Verify via shell
    print("\n=== Post-restart: Shell getprop ===")
    for prop in ['ro.product.brand', 'ro.product.model', 'ro.product.device',
                 'ro.build.version.release', 'ro.build.version.sdk']:
        r = await bridge.exec_shell(PAD, f"getprop {prop}")
        val = r.result.strip() if r.result else '?'
        print(f"  {prop} = {val}")

    # Verify data (contacts, calls, SMS)
    print("\n=== Post-restart: Data verification ===")
    r = await bridge.exec_shell(PAD, "content query --uri content://contacts/phones --projection display_name 2>/dev/null | wc -l")
    print(f"  Contacts count: {r.result.strip() if r.result else '0'}")

    r = await bridge.exec_shell(PAD, "content query --uri content://call_log/calls --projection number 2>/dev/null | wc -l")
    print(f"  Call log count: {r.result.strip() if r.result else '0'}")

    r = await bridge.exec_shell(PAD, "content query --uri content://sms --projection address 2>/dev/null | wc -l")
    print(f"  SMS count: {r.result.strip() if r.result else '0'}")

    r = await bridge.exec_shell(PAD, "ls /sdcard/DCIM/Camera/ 2>/dev/null | wc -l")
    print(f"  Gallery count: {r.result.strip() if r.result else '0'}")

    r = await bridge.exec_shell(PAD, "ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null")
    print(f"  WiFi config: {'present' if r.result and r.result.strip() else 'missing'}")

    r = await bridge.exec_shell(PAD, "ls /data/data/com.instagram.android/shared_prefs/ 2>/dev/null")
    print(f"  Instagram prefs: {'present' if r.result and r.result.strip() else 'missing'}")

    print("\n=== VERIFICATION COMPLETE ===")

asyncio.run(main())
