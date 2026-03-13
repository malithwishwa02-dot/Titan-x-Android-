#!/usr/bin/env python3
"""Debug VMOS API parameter formats for property updates and SMS."""
import asyncio, sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

os.environ['VMOS_API_KEY'] = 'BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi'
os.environ['VMOS_API_SECRET'] = 'Q2SgcSwEfuwoedY0cijp6Mce'
os.environ['VMOS_API_HOST'] = 'api.vmoscloud.com'

from vmos_cloud_bridge import VMOSCloudBridge

PAD = 'ACP2509244LGV1MV'

async def main():
    bridge = VMOSCloudBridge()

    # --- updatePadAndroidProp: Try different param formats ---

    print("=== Try 1: properties as list of {propertiesName, propertiesValue} ===")
    r = await bridge._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
        'padCodes': [PAD],
        'properties': [
            {'propertiesName': 'ro.product.brand', 'propertiesValue': 'samsung'},
            {'propertiesName': 'ro.product.model', 'propertiesValue': 'SM-S938U'},
        ]
    })
    print(json.dumps(r, indent=2, default=str)[:1000])

    print("\n=== Try 2: padCode singular + properties dict ===")
    r = await bridge._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
        'padCode': PAD,
        'properties': {'ro.product.brand': 'samsung', 'ro.product.model': 'SM-S938U'}
    })
    print(json.dumps(r, indent=2, default=str)[:1000])

    print("\n=== Try 3: systemPropertiesList matching padProperties response format ===")
    r = await bridge._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
        'padCodes': [PAD],
        'systemPropertiesList': [
            {'propertiesName': 'ro.product.brand', 'propertiesValue': 'samsung'},
        ]
    })
    print(json.dumps(r, indent=2, default=str)[:1000])

    print("\n=== Try 4: propertiesList key ===")
    r = await bridge._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
        'padCodes': [PAD],
        'propertiesList': [
            {'propertiesName': 'ro.product.brand', 'propertiesValue': 'samsung'},
        ]
    })
    print(json.dumps(r, indent=2, default=str)[:1000])

    print("\n=== Try 5: flat key-value in body ===")
    r = await bridge._post('/vcpcloud/api/padApi/updatePadAndroidProp', {
        'padCodes': [PAD],
        'ro.product.brand': 'samsung',
        'ro.product.model': 'SM-S938U',
    })
    print(json.dumps(r, indent=2, default=str)[:1000])

    # --- Try separate endpoints for modem/system ---
    print("\n=== Try 6: updateModemProp ===")
    r = await bridge._post('/vcpcloud/api/padApi/updateModemProp', {
        'padCodes': [PAD],
        'properties': [
            {'propertiesName': 'imei', 'propertiesValue': '353912115847621'},
        ]
    })
    print(json.dumps(r, indent=2, default=str)[:1000])

    print("\n=== Try 7: updateSystemProp ===")
    r = await bridge._post('/vcpcloud/api/padApi/updateSystemProp', {
        'padCodes': [PAD],
        'properties': [
            {'propertiesName': 'ro.product.brand', 'propertiesValue': 'samsung'},
        ]
    })
    print(json.dumps(r, indent=2, default=str)[:1000])

    # --- SMS ---
    print("\n=== SMS Try 1: sendSms with phoneNumber ===")
    r = await bridge._post('/vcpcloud/api/padApi/sendSms', {
        'padCodes': [PAD],
        'phoneNumber': '+12125551234',
        'smsContent': 'Hello test'
    })
    print(json.dumps(r, indent=2, default=str)[:1000])

    print("\n=== SMS Try 2: simulateSendSms with senderNumber+smsContent ===")
    r = await bridge._post('/vcpcloud/api/padApi/simulateSendSms', {
        'padCode': PAD,
        'senderNumber': '+12125551234',
        'smsContent': 'Hello test'
    })
    print(json.dumps(r, indent=2, default=str)[:1000])

    print("\n=== SMS Try 3: simulateReceiveSms ===")
    r = await bridge._post('/vcpcloud/api/padApi/simulateReceiveSms', {
        'padCodes': [PAD],
        'senderNumber': '+12125551234',
        'smsContent': 'Hello test'
    })
    print(json.dumps(r, indent=2, default=str)[:1000])

asyncio.run(main())
