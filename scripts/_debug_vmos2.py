#!/usr/bin/env python3
"""Debug VMOS API: correct property update format + SMS via shell."""
import asyncio, sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

os.environ['VMOS_API_KEY'] = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi'
os.environ['VMOS_API_SECRET'] = 'Q2SgcSwEfuwoedY0cijp6Mce'
os.environ['VMOS_API_HOST'] = 'api.vmoscloud.com'

from vmos_cloud_bridge import VMOSCloudBridge

PAD = 'ACP2509244LGV1MV'

async def main():
    bridge = VMOSCloudBridge()

    # Found: padCode (singular) + 'props' key
    print("=== Props as dict with padCode singular ===")
    r = await bridge._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
        'padCode': PAD,
        'props': {'ro.product.brand': 'samsung', 'ro.product.model': 'SM-S938U'}
    })
    print(json.dumps(r, indent=2, default=str)[:1500])

    print("\n=== Props as list with padCode singular ===")
    r = await bridge._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
        'padCode': PAD,
        'props': [
            {'propertiesName': 'ro.product.brand', 'propertiesValue': 'samsung'},
            {'propertiesName': 'ro.product.model', 'propertiesValue': 'SM-S938U'},
        ]
    })
    print(json.dumps(r, indent=2, default=str)[:1500])

    print("\n=== padCodes array + props dict ===")
    r = await bridge._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
        'padCodes': [PAD],
        'props': {'ro.product.brand': 'samsung', 'ro.product.model': 'SM-S938U'}
    })
    print(json.dumps(r, indent=2, default=str)[:1500])

    print("\n=== padCodes + props list ===")
    r = await bridge._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
        'padCodes': [PAD],
        'props': [
            {'propertiesName': 'ro.product.brand', 'propertiesValue': 'samsung'},
        ]
    })
    print(json.dumps(r, indent=2, default=str)[:1500])

    # Try SMS via shell content provider insert
    print("\n=== SMS via shell: content insert ===")
    r = await bridge.exec_shell(PAD, 
        "content insert --uri content://sms "
        "--bind address:s:'+12125554432' "
        "--bind body:s:'Hey are you coming to dinner tonight?' "
        "--bind type:i:1 "
        "--bind date:l:1741870991000 "
        "--bind read:i:1"
    )
    print(f"SMS shell: ok={r.ok} status={r.status} result={r.result[:200] if r.result else ''} error={r.error[:200] if r.error else ''}")

asyncio.run(main())
