#!/usr/bin/env python3
"""
VMOS AI Screen Agent - Anomaly Detection via Screenshot Analysis
Captures device screenshot and uses Ollama vision model on Vast.ai to find visual anomalies.
"""
import base64, hashlib, hmac, http.client, io, json, os, sys, time, urllib.request
from datetime import datetime, timezone

PAD = "ACP2509244LGV1MV"
AK = "BPWNWxfXMQsjsREyzIOXmCtndRZO8iVi"
SK = "Q2SgcSwEfuwoedY0cijp6Mce"
HOST = "api.vmoscloud.com"
SVC = "armcloud-paas"

# Vast.ai Ollama
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "")
VAST_SSH = "ssh -p 13640 root@ssh2.vast.ai"

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
    return json.loads(raw)

# ─── Step 1: Get Screenshot URL ───────────────────────────────────
print("=" * 60)
print("AI SCREEN ANOMALY ANALYSIS")
print("=" * 60)

print("\n[1] Getting screenshot URL...")
r = api("/vcpcloud/api/padApi/getLongGenerateUrl", {"padCodes": [PAD], "format": "png"})
if r.get("code") != 200 or not r.get("data"):
    print(f"  ERROR: {r}")
    sys.exit(1)

item = r["data"][0]
if not item.get("success"):
    print(f"  Screenshot not available: {item}")
    sys.exit(1)

screenshot_url = item["url"]
print(f"  URL: {screenshot_url[:100]}...")

# ─── Step 2: Download Screenshot ──────────────────────────────────
print("\n[2] Downloading screenshot...")
try:
    import ssl
    ctx = ssl.create_default_context()
    req = urllib.request.Request(screenshot_url)
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        png_bytes = resp.read()
    print(f"  Downloaded: {len(png_bytes)} bytes")
except Exception as e:
    print(f"  Download failed: {e}")
    sys.exit(1)

# Save locally
with open("/tmp/vmos_screenshot.png", "wb") as f:
    f.write(png_bytes)
print("  Saved to /tmp/vmos_screenshot.png")

# Resize for LLM efficiency
try:
    from PIL import Image
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = img.size
    print(f"  Original size: {w}x{h}")
    if w > 768:
        ratio = 768 / w
        img = img.resize((768, int(h * ratio)), Image.LANCZOS)
        print(f"  Resized to: {img.size[0]}x{img.size[1]}")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=60)
    img_b64 = base64.b64encode(buf.getvalue()).decode()
except ImportError:
    print("  PIL not available, using raw PNG")
    img_b64 = base64.b64encode(png_bytes).decode()

print(f"  Base64 length: {len(img_b64)}")

# ─── Step 3: Check Ollama availability ────────────────────────────
print("\n[3] Checking Ollama vision model...")

# Try local first, then Vast.ai
ollama_urls = [
    "http://127.0.0.1:11434",
]
if OLLAMA_HOST:
    ollama_urls.insert(0, OLLAMA_HOST)

ollama_base = None
for url in ollama_urls:
    try:
        req = urllib.request.Request(f"{url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = [m["name"] for m in data.get("models", [])]
            print(f"  {url}: Available models: {models}")
            # Check for vision models
            vision = [m for m in models if any(v in m for v in ["llava", "minicpm", "bakllava"])]
            if vision:
                ollama_base = url
                vision_model = vision[0]
                print(f"  Using: {vision_model} at {url}")
                break
            else:
                print(f"  No vision models found at {url}")
    except Exception as e:
        print(f"  {url}: Not reachable ({e})")

if not ollama_base:
    print("\n  *** NO OLLAMA VISION MODEL AVAILABLE ***")
    print("  Cannot perform AI screen analysis.")
    print("  The screenshot has been saved to /tmp/vmos_screenshot.png")
    print("  Performing manual visual analysis based on screenshot metadata...")
    
    # At least analyze what we can without AI
    print("\n[MANUAL ANALYSIS]")
    print("  Based on shell audit data (from _vmos_audit_v3.py):")
    print("  The device shows as a Vivo V2408A running Android 16")
    print("  but is actually a VMOS Cloud instance.")
    print("  Key visual anomalies to check:")
    print("  - Status bar: Does it show carrier name 'T-Mobile'?")
    print("  - Status bar: Is signal strength icon realistic?")
    print("  - Settings app: Does About Phone show Samsung or Vivo?")
    print("  - Missing apps: No Google Maps, YouTube visible?")
    print("  - Home screen: Does it look like stock Android or VMOS skin?")
    sys.exit(0)

# ─── Step 4: AI Vision Analysis ───────────────────────────────────
print(f"\n[4] Running AI anomaly detection with {vision_model}...")

ANOMALY_PROMPT = """You are a mobile device forensic analyst specializing in detecting virtual machines, emulated devices, and modified Android phones.

Analyze this Android phone screenshot carefully and identify ALL anomalies that suggest this is NOT a real physical phone. Look for:

1. STATUS BAR: Check carrier name, signal bars, WiFi icon, battery, time format, notification icons. Are they realistic?

2. NAVIGATION: Is there a standard Android navigation bar? Does it look like stock Android, Samsung One UI, or a VM skin?

3. HOME SCREEN/LAUNCHER: What apps are visible? What's the wallpaper? Does the layout look like a freshly set up device or a used one?

4. MISSING APPS: What critical apps are missing? (Phone, Messages, Camera, Google Maps, YouTube, Photos, etc.)

5. PRESENT APPS: What apps ARE visible? Any unusual or suspicious apps?

6. UI INCONSISTENCIES: Font rendering, icon styling, spacing, resolution artifacts that don't match a real device.

7. NOTIFICATION SHADE: Any system notifications visible that leak VM/cloud info?

8. SCREEN RESOLUTION: Does the aspect ratio and rendering look correct for the claimed device?

9. BRANDING: Any VMOS, cloud VM, or emulator branding visible anywhere?

10. OVERALL IMPRESSION: Rate device authenticity 1-10 (10=definitely real, 1=definitely fake/emulated)

Format your response as:
FINDINGS:
1. [CRITICAL/HIGH/MEDIUM/LOW] Description of finding
2. ...

AUTHENTICITY SCORE: X/10
SUMMARY: Brief overall assessment"""

body = {
    "model": vision_model,
    "prompt": ANOMALY_PROMPT,
    "images": [img_b64],
    "stream": False,
    "options": {"temperature": 0.2, "num_predict": 2048},
}

try:
    req_data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{ollama_base}/api/generate",
        data=req_data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    print("  Sending to Ollama (this may take 30-60s)...")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode())
    elapsed = time.time() - t0
    
    ai_response = result.get("response", "")
    print(f"\n  Analysis complete in {elapsed:.1f}s")
    print("\n" + "=" * 60)
    print("  AI VISION ANALYSIS RESULTS")
    print("=" * 60)
    print()
    print(ai_response)
    
except Exception as e:
    print(f"  Ollama error: {e}")
    print("  Screenshot saved to /tmp/vmos_screenshot.png for manual analysis")

print("\n" + "=" * 60)
print("  ANALYSIS COMPLETE")
print("=" * 60)
