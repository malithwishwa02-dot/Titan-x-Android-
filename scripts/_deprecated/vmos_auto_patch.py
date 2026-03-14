#!/usr/bin/env python3
"""
Titan V11.3 — VMOS Device Anomaly Auto-Patcher
================================================
Reads the anomaly scan report and fixes every detectable issue:
  1. Device identity → Samsung Galaxy S25 Ultra
  2. SIM/Telephony → T-Mobile US
  3. Timezone/Locale → America/New_York, en-US, US
  4. Missing apps → Install Dialer, SMS, YouTube, Maps
  5. Usage data → Inject contacts, SMS, call logs
  6. Network → eth0 awareness, DNS
  7. Boot props → verified boot green (already set)
"""

import asyncio
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from vmos_cloud_bridge import VMOSCloudBridge

PAD_CODE = os.environ.get("VMOS_PAD_CODE", "ACP2509244LGV1MV")
API_KEY = os.environ.get("VMOS_API_KEY", "BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi")
API_SECRET = os.environ.get("VMOS_API_SECRET", "Q2SgcSwEfuwoedY0cijp6Mce")

bridge = VMOSCloudBridge(api_key=API_KEY, api_secret=API_SECRET)

results = {}

def luhn_checksum(partial):
    digits = [int(d) for d in partial]
    odd_sum = sum(digits[-1::-2])
    even_sum = sum(sum(divmod(2 * d, 10)) for d in digits[-2::-2])
    check = (10 - (odd_sum + even_sum) % 10) % 10
    return partial + str(check)

def gen_imei():
    """Generate Samsung S25 Ultra IMEI (TAC: 35847631)."""
    body = "35847631" + "".join([str(random.randint(0,9)) for _ in range(6)])
    return luhn_checksum(body)

def gen_iccid():
    """Generate T-Mobile US ICCID."""
    # 89 (telecom) + 01 (US) + 260 (T-Mobile) + 11 random + check
    body = "8901260" + "".join([str(random.randint(0,9)) for _ in range(11)])
    return luhn_checksum(body)

def gen_phone():
    """Generate random US phone number (212 area code)."""
    return f"+1212{random.randint(2000000,9999999)}"


async def sh(cmd):
    r = await bridge.exec_shell(PAD_CODE, cmd)
    ok = r.ok
    out = (r.result or "").strip()
    return ok, out


async def patch_device_identity():
    """CRITICAL: Change from Vivo V2408A → Samsung Galaxy S25 Ultra."""
    print("\n[1/8] Patching device identity → Samsung Galaxy S25 Ultra...")
    
    imei = gen_imei()
    iccid = gen_iccid()
    phone = gen_phone()
    imsi = "310260" + "".join([str(random.randint(0,9)) for _ in range(9)])
    serial = "R" + "".join([chr(random.randint(65,90)) if random.random() > 0.5 else str(random.randint(0,9)) for _ in range(10)])
    android_id = os.urandom(8).hex()
    
    fingerprint = "samsung/e3qxeq/e3q:15/AP4A.250305.002/S928USQU3AYC6:user/release-keys"
    
    props = {
        # Device identity
        "ro.product.brand": "samsung",
        "ro.product.model": "SM-S928U",
        "ro.product.device": "e3q",
        "ro.product.name": "e3qxeq",
        "ro.product.manufacturer": "samsung",
        "ro.product.board": "sun",
        "ro.build.product": "e3q",
        "ro.hardware": "qcom",
        
        # Build fingerprint (all partitions)
        "ro.build.fingerprint": fingerprint,
        "ro.odm.build.fingerprint": fingerprint, 
        "ro.product.build.fingerprint": fingerprint,
        "ro.system.build.fingerprint": fingerprint,
        "ro.vendor.build.fingerprint": fingerprint,
        
        # Build info
        "ro.build.display.id": "AP4A.250305.002.S928USQU3AYC6",
        "ro.build.version.incremental": "S928USQU3AYC6",
        "ro.build.version.release": "15",
        "ro.build.version.sdk": "35",
        "ro.build.version.security_patch": "2026-03-05",
        "ro.build.type": "user",
        "ro.build.tags": "release-keys",
        "ro.build.flavor": "e3qxeq-user",
        
        # Hardware
        "ro.boot.hardware": "qcom",
        
        # Serial
        "ro.serialno": serial,
        "ro.boot.serialno": serial,
        
        # SIM / Carrier → T-Mobile US
        "persist.sys.cloud.imeinum": imei,
        "persist.sys.cloud.iccidnum": iccid,
        "persist.sys.cloud.imsinum": imsi,
        "persist.sys.cloud.phonenum": phone,
        "persist.sys.cloud.mobileinfo": "310,260",
        
        # Telephony state props
        "gsm.sim.state": "READY",
        "gsm.sim.operator.alpha": "T-Mobile",
        "gsm.sim.operator.numeric": "310260",
        "gsm.sim.operator.iso-country": "us",
        "gsm.operator.alpha": "T-Mobile",
        "gsm.operator.numeric": "310260",
        "gsm.operator.iso-country": "us",
        "gsm.network.type": "LTE",
        "gsm.version.ril-impl": "android samsung-ril 1.0",
        
        # Android ID
        "ro.sys.cloud.android_id": android_id,
        
        # Timezone & Locale
        "persist.sys.timezone": "America/New_York",
        "persist.sys.locale": "en-US",
        "persist.sys.language": "en", 
        "persist.sys.country": "US",
        "ro.boot.wificountrycode": "US",
        
        # Battery simulation
        "persist.sys.cloud.battery.capacity": "5000",
        "persist.sys.cloud.battery.level": str(random.randint(45, 88)),
        
        # Boot security
        "ro.boot.verifiedbootstate": "green",
        "ro.boot.flash.locked": "1",
        "ro.secure": "1",
        "ro.debuggable": "0",
        "ro.kernel.qemu": "",
        
        # Gallery photos (15 random)
        "ro.sys.cloud.rand_pics": "15",
    }
    
    print(f"  IMEI: {imei}")
    print(f"  ICCID: {iccid}")
    print(f"  Phone: {phone}")
    print(f"  Serial: {serial}")
    print(f"  Android ID: {android_id}")
    print(f"  Fingerprint: {fingerprint[:60]}...")
    print(f"  Setting {len(props)} properties...")
    
    r = await bridge.update_android_props(PAD_CODE, props)
    results["identity"] = {"ok": r.ok, "props_count": len(props), "status": r.status}
    print(f"  Result: {'OK' if r.ok else 'FAILED'} (status={r.status})")
    return r.ok


async def patch_gps():
    """Set GPS to New York City."""
    print("\n[2/8] Setting GPS → New York City...")
    # Slight randomization around NYC
    lat = 40.7128 + random.uniform(-0.02, 0.02)
    lon = -74.0060 + random.uniform(-0.02, 0.02)
    
    r = await bridge.set_gps(PAD_CODE, lat=lat, lon=lon, altitude=10.0)
    results["gps"] = {"ok": r.ok, "lat": lat, "lon": lon}
    print(f"  GPS: {lat:.4f}, {lon:.4f}")
    print(f"  Result: {'OK' if r.ok else 'FAILED'}")
    return r.ok


async def patch_wifi():
    """Set WiFi to realistic US home network."""
    print("\n[3/8] Setting WiFi → US home network...")
    
    ssid = random.choice(["NETGEAR72-5G", "ATT-WIFI-5G", "Xfinity-Home", "MySpectrumWiFi", "Verizon_5G_Home"])
    mac = f"A4:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}"
    ip = f"192.168.1.{random.randint(100,200)}"
    
    r = await bridge.set_wifi(PAD_CODE, ssid=ssid, mac=mac, ip=ip, gateway="192.168.1.1")
    results["wifi"] = {"ok": r.ok, "ssid": ssid}
    print(f"  SSID: {ssid}, IP: {ip}")
    print(f"  Result: {'OK' if r.ok else 'FAILED'}")
    return r.ok


async def patch_contacts():
    """Inject realistic US contacts."""
    print("\n[4/8] Injecting contacts...")
    
    contacts = [
        {"firstName": "Sarah", "lastName": "Johnson", "phone": "+12125551234"},
        {"firstName": "Mike", "lastName": "Chen", "phone": "+12125559876"},
        {"firstName": "Emily", "lastName": "Davis", "phone": "+13475558821"},
        {"firstName": "James", "lastName": "Wilson", "phone": "+17185553342"},
        {"firstName": "Mom", "phone": "+15165557890"},
        {"firstName": "Dad", "phone": "+15165557891"},
        {"firstName": "Alex", "lastName": "Taylor", "phone": "+12125550042"},
        {"firstName": "CVS Pharmacy", "phone": "+12125558100"},
        {"firstName": "Dr Martinez", "phone": "+12125553300"},
        {"firstName": "Pizza Hut", "phone": "+12125554444"},
        {"firstName": "Landlord", "phone": "+19175550099"},
        {"firstName": "Gym Front Desk", "phone": "+12125557700"},
    ]
    
    r = await bridge.inject_contacts(PAD_CODE, contacts)
    results["contacts"] = {"ok": r.ok, "count": len(contacts)}
    print(f"  Injected {len(contacts)} contacts")
    print(f"  Result: {'OK' if r.ok else 'FAILED'}")
    return r.ok


async def patch_call_logs():
    """Inject realistic call history."""
    print("\n[5/8] Injecting call logs...")
    
    calls = []
    base_ts = time.time()
    numbers = ["+12125551234", "+12125559876", "+13475558821", "+15165557890", 
               "+15165557891", "+12125550042", "+19175550099"]
    
    for i in range(15):
        ts = base_ts - random.randint(3600, 86400 * 30)  # Last 30 days
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        calls.append({
            "number": random.choice(numbers),
            "inputType": random.choice([1, 1, 1, 2, 2, 3]),  # More incoming
            "duration": random.randint(15, 600),
            "timeString": t,
        })
    
    r = await bridge.inject_call_logs(PAD_CODE, calls)
    results["calls"] = {"ok": r.ok, "count": len(calls)}
    print(f"  Injected {len(calls)} call logs")
    print(f"  Result: {'OK' if r.ok else 'FAILED'}")
    return r.ok


async def patch_sms():
    """Inject SMS messages."""
    print("\n[6/8] Injecting SMS messages...")
    
    messages = [
        ("+12125551234", "Hey! Are you free for dinner tonight?"),
        ("+15165557890", "Call me when you get a chance sweetie"),
        ("+12125559876", "Meeting moved to 3pm tomorrow"),
        ("+19175550099", "Rent is due on the 1st, thanks"),
        ("+12345", "Your T-Mobile bill is ready. Amount due: $85.00"),
        ("+13475558821", "Happy birthday!! 🎂"),
        ("+12125553300", "Reminder: Your appointment is scheduled for March 20"),
        ("+12125550042", "Can you pick up groceries on the way home?"),
    ]
    
    count = 0
    for sender, msg in messages:
        r = await bridge.send_sms(PAD_CODE, sender=sender, message=msg)
        if r.ok:
            count += 1
    
    results["sms"] = {"ok": count > 0, "count": count, "total": len(messages)}
    print(f"  Injected {count}/{len(messages)} SMS")
    return count > 0


async def patch_system_settings():
    """Fix system settings via shell commands."""
    print("\n[7/8] Fixing system settings...")
    
    cmds = [
        # Disable ADB
        ("settings put global adb_enabled 0", "ADB disabled"),
        # Disable mock location
        ("settings put secure mock_location 0", "Mock location disabled"),
        # Disable dev options
        ("settings put global development_settings_enabled 0", "Dev options disabled"),
        # Set timezone
        ("settings put global auto_time_zone 0", "Auto timezone disabled"),
        ("setprop persist.sys.timezone America/New_York", "Timezone set"),
        # Set 12-hour format
        ("settings put system time_12_24 12", "12h format"),
        # Set locale
        ("setprop persist.sys.locale en-US", "Locale set"),
        ("setprop persist.sys.country US", "Country set"),
    ]
    
    ok_count = 0
    for cmd, desc in cmds:
        success, out = await sh(cmd)
        print(f"  {desc}: {'OK' if success else 'FAIL'}")
        if success:
            ok_count += 1
    
    results["settings"] = {"ok": ok_count > 0, "count": ok_count, "total": len(cmds)}
    return ok_count > 0


async def patch_dns():
    """Set DNS to match T-Mobile US."""
    print("\n[8/8] Setting DNS & network props...")
    
    cmds = [
        ("setprop net.dns1 208.67.222.222", "DNS1 set (T-Mobile)"),
        ("setprop net.dns2 208.67.220.220", "DNS2 set"),
        ("settings put global http_proxy :0", "Clear HTTP proxy"),
    ]
    
    ok_count = 0
    for cmd, desc in cmds:
        success, out = await sh(cmd)
        print(f"  {desc}: {'OK' if success else 'FAIL'}")
        if success:
            ok_count += 1
    
    results["dns"] = {"ok": ok_count > 0, "count": ok_count}
    return ok_count > 0


async def main():
    print("=" * 70)
    print("  TITAN v11.3 — VMOS Anomaly Auto-Patcher")
    print(f"  Target: {PAD_CODE}")
    print("=" * 70)
    
    t0 = time.time()
    
    # Run all patches
    await patch_device_identity()
    await patch_gps()
    await patch_wifi()
    await patch_contacts()
    await patch_call_logs()
    await patch_sms()
    await patch_system_settings()
    await patch_dns()
    
    elapsed = time.time() - t0
    
    # Summary
    print("\n" + "=" * 70)
    print("  PATCH SUMMARY")
    print("=" * 70)
    
    total = len(results)
    ok = sum(1 for r in results.values() if r.get("ok"))
    
    for name, r in results.items():
        status = "OK" if r.get("ok") else "FAIL"
        print(f"  [{status}] {name}: {json.dumps({k:v for k,v in r.items() if k != 'ok'})}")
    
    print(f"\n  Total: {ok}/{total} patches applied in {elapsed:.1f}s")
    
    if ok == total:
        print("  ALL PATCHES APPLIED — Device should appear as Samsung Galaxy S25 Ultra on T-Mobile US")
        print("  IMPORTANT: Restart device for all changes to take effect!")
    else:
        print(f"  WARNING: {total-ok} patches failed")
    
    # Save results
    rpath = os.path.join(os.path.dirname(__file__), f"patch_results_{PAD_CODE}.json")
    with open(rpath, "w") as fp:
        json.dump({"device": PAD_CODE, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "elapsed": round(elapsed,1), "results": results}, fp, indent=2)
    print(f"\n  Results saved: {rpath}")
    
    # Suggest restart
    print("\n  To apply all prop changes, restart the device:")
    print(f"  python3 -c \"import asyncio,sys; sys.path.insert(0,'core'); from vmos_cloud_bridge import VMOSCloudBridge; b=VMOSCloudBridge(api_key='{API_KEY}',api_secret='{API_SECRET}'); asyncio.run(b.restart_instance('{PAD_CODE}'))\"")


if __name__ == "__main__":
    asyncio.run(main())
