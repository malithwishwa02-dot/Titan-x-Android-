#!/usr/bin/env python3
"""Quick VMOS API diagnostic - find why 500 errors, try different endpoints."""
import hashlib, hmac, json, time, urllib.request
from datetime import datetime, timezone

PAD1 = "ACP2509244LGV1MV"
PAD2 = "ACP251008CRDQZPF"
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
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"code": e.code, "msg": f"HTTP {e.code}: {body[:300]}"}
    except Exception as e:
        return {"code": -1, "msg": str(e)}

print("=" * 60)
print("VMOS API DIAGNOSTIC")
print("=" * 60)

# 1. Try listing all instances (no specific device needed)
print("\n1. List instances (infos with both padCodes)...")
r = api("/vcpcloud/api/padApi/infos", {"padCodes": [PAD1, PAD2]})
print(f"   Code: {r.get('code')}, Msg: {r.get('msg', 'ok')}")
if r.get("code") == 200:
    for d in r.get("data", []):
        print(f"   → {d.get('padCode')}: status={d.get('padStatus')} online={d.get('onlineStatus')} model={d.get('padModel')}")

# 2. Try with just the second device
print("\n2. Info for PAD2 only...")
r = api("/vcpcloud/api/padApi/infos", {"padCodes": [PAD2]})
print(f"   Code: {r.get('code')}, Msg: {r.get('msg', 'ok')}")
if r.get("code") == 200:
    for d in r.get("data", []):
        print(f"   → {d.get('padCode')}: {json.dumps(d, indent=2)[:400]}")

# 3. Try properties on PAD2
print("\n3. Properties PAD2...")
r = api("/vcpcloud/api/padApi/padProperties", {"padCode": PAD2})
print(f"   Code: {r.get('code')}, Msg: {r.get('msg', 'ok')}")
if r.get("code") == 200:
    data = r.get("data", {})
    if isinstance(data, dict):
        for k in ["ro.product.brand", "ro.product.model", "ro.build.fingerprint"]:
            print(f"   {k} = {data.get(k, '(not set)')}")

# 4. Try shell on PAD2
print("\n4. Shell on PAD2 (echo test)...")
r = api("/vcpcloud/api/padApi/asyncCmd", {"padCodes": [PAD2], "scriptContent": "echo alive"})
print(f"   Code: {r.get('code')}, Msg: {r.get('msg', 'ok')}")
if r.get("code") == 200:
    tasks = r.get("data", [])
    if tasks:
        tid = tasks[0].get("taskId", 0)
        print(f"   TaskID: {tid}")
        if tid:
            time.sleep(3)
            d = api("/vcpcloud/api/padApi/padTaskDetail", {"taskIds": [tid]})
            if d.get("data"):
                t = d["data"][0]
                print(f"   Status: {t.get('taskStatus')}, Result: {t.get('taskResult', '')[:200]}")

# 5. Try properties on PAD1 (the one that was having issues)
print("\n5. Properties PAD1...")
r = api("/vcpcloud/api/padApi/padProperties", {"padCode": PAD1})
print(f"   Code: {r.get('code')}, Msg: {r.get('msg', 'ok')}")
if r.get("code") == 200:
    data = r.get("data", {})
    if isinstance(data, dict):
        for k in ["ro.product.brand", "ro.product.model", "persist.sys.timezone"]:
            print(f"   {k} = {data.get(k, '(not set)')}")

# 6. Try shell on PAD1
print("\n6. Shell on PAD1 (echo test)...")
r = api("/vcpcloud/api/padApi/asyncCmd", {"padCodes": [PAD1], "scriptContent": "echo alive_pad1"})
print(f"   Code: {r.get('code')}, Msg: {r.get('msg', 'ok')}")
if r.get("code") == 200:
    tasks = r.get("data", [])
    if tasks:
        tid = tasks[0].get("taskId", 0)
        print(f"   TaskID: {tid}")
        if tid:
            time.sleep(3)
            d = api("/vcpcloud/api/padApi/padTaskDetail", {"taskIds": [tid]})
            if d.get("data"):
                t = d["data"][0]
                print(f"   Status: {t.get('taskStatus')}, Result: {t.get('taskResult', '')[:200]}")

# 7. Try screenshot on PAD1
print("\n7. Screenshot PAD1...")
r = api("/vcpcloud/api/padApi/getLongGenerateUrl", {"padCodes": [PAD1], "format": "png"})
print(f"   Code: {r.get('code')}, Msg: {r.get('msg', 'ok')}")
if r.get("code") == 200:
    items = r.get("data", [])
    if items:
        url = items[0].get("url", "")
        print(f"   URL: {url[:100]}...")

# 8. Check if there's a task list/cancel API
print("\n8. Try to list recent tasks for PAD1...")
# Try padTaskDetail with a known task ID range
# The last known taskId was 1694719356 (restart from last session)
old_tid = 1694719356
r = api("/vcpcloud/api/padApi/padTaskDetail", {"taskIds": [old_tid]})
print(f"   Old task {old_tid}: Code={r.get('code')}")
if r.get("code") == 200 and r.get("data"):
    t = r["data"][0]
    print(f"   Status: {t.get('taskStatus')}, Type: {t.get('taskType')}, Error: {t.get('errorMsg', '')[:200]}")

print("\n" + "=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)
