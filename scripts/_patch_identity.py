#!/usr/bin/env python3
"""Fix the identity patch by sending props in small batches."""
import asyncio, os, sys, random, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from vmos_cloud_bridge import VMOSCloudBridge

PAD = "ACP2509244LGV1MV"
bridge = VMOSCloudBridge(
    api_key="BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi",
    api_secret="Q2SgcSwEfuwoedY0cijp6Mce"
)

def luhn(p):
    d = [int(c) for c in p]
    return p + str((10 - (sum(d[-1::-2]) + sum(sum(divmod(2*x,10)) for x in d[-2::-2])) % 10) % 10)

imei = luhn("35847631" + "".join([str(random.randint(0,9)) for _ in range(6)]))
iccid = luhn("8901260" + "".join([str(random.randint(0,9)) for _ in range(11)]))
phone = f"+1212{random.randint(2000000,9999999)}"
imsi = "310260" + "".join([str(random.randint(0,9)) for _ in range(9)])
serial = "R" + "".join([chr(random.randint(65,90)) if random.random()>0.5 else str(random.randint(0,9)) for _ in range(10)])
android_id = os.urandom(8).hex()
fp = "samsung/e3qxeq/e3q:15/AP4A.250305.002/S928USQU3AYC6:user/release-keys"

# Split into smaller batches
batches = [
    ("Device identity", {
        "ro.product.brand": "samsung",
        "ro.product.model": "SM-S928U",
        "ro.product.device": "e3q",
        "ro.product.name": "e3qxeq",
        "ro.product.manufacturer": "samsung",
        "ro.build.product": "e3q",
    }),
    ("Build info", {
        "ro.build.display.id": "AP4A.250305.002.S928USQU3AYC6",
        "ro.build.version.incremental": "S928USQU3AYC6",
        "ro.build.version.release": "15",
        "ro.build.version.sdk": "35",
        "ro.build.version.security_patch": "2026-03-05",
        "ro.build.type": "user",
        "ro.build.tags": "release-keys",
        "ro.build.flavor": "e3qxeq-user",
    }),
    ("Fingerprint", {
        "ro.build.fingerprint": fp,
        "ro.odm.build.fingerprint": fp,
        "ro.product.build.fingerprint": fp,
        "ro.system.build.fingerprint": fp,
        "ro.vendor.build.fingerprint": fp,
    }),
    ("SIM/Carrier", {
        "persist.sys.cloud.imeinum": imei,
        "persist.sys.cloud.iccidnum": iccid,
        "persist.sys.cloud.imsinum": imsi,
        "persist.sys.cloud.phonenum": phone,
        "persist.sys.cloud.mobileinfo": "310,260",
    }),
    ("Telephony state", {
        "gsm.sim.state": "READY",
        "gsm.sim.operator.alpha": "T-Mobile",
        "gsm.sim.operator.numeric": "310260",
        "gsm.sim.operator.iso-country": "us",
        "gsm.operator.alpha": "T-Mobile",
        "gsm.operator.numeric": "310260",
        "gsm.operator.iso-country": "us",
        "gsm.network.type": "LTE",
    }),
    ("Locale/TZ", {
        "persist.sys.timezone": "America/New_York",
        "persist.sys.locale": "en-US",
        "persist.sys.language": "en",
        "persist.sys.country": "US",
        "ro.boot.wificountrycode": "US",
    }),
    ("Hardware/Serial", {
        "ro.serialno": serial,
        "ro.boot.serialno": serial,
        "ro.hardware": "qcom",
        "ro.boot.hardware": "qcom",
        "gsm.version.ril-impl": "android samsung-ril 1.0",
    }),
    ("Security", {
        "ro.boot.verifiedbootstate": "green",
        "ro.boot.flash.locked": "1",
        "ro.secure": "1",
        "ro.debuggable": "0",
        "ro.kernel.qemu": "",
        "ro.sys.cloud.android_id": android_id,
    }),
    ("Battery/Gallery", {
        "persist.sys.cloud.battery.capacity": "5000",
        "persist.sys.cloud.battery.level": str(random.randint(45,88)),
        "ro.sys.cloud.rand_pics": "15",
    }),
]

async def main():
    print(f"Patching {PAD} — {len(batches)} batches")
    print(f"IMEI={imei} Serial={serial} Phone={phone}")
    
    ok = 0
    fail = 0
    for name, props in batches:
        print(f"\n  [{name}] {len(props)} props...")
        r = await bridge.update_android_props(PAD, props)
        if r.ok:
            print(f"    OK (status={r.status})")
            ok += 1
        else:
            print(f"    FAIL (status={r.status}, error={r.error!r})")
            fail += 1
            # Try one by one
            for k, v in props.items():
                r2 = await bridge.update_android_props(PAD, {k: v})
                s = "OK" if r2.ok else "FAIL"
                print(f"      {k}={v[:30]}: {s}")
    
    print(f"\nResult: {ok}/{ok+fail} batches OK")

asyncio.run(main())
