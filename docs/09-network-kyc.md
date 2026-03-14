# 09 — Network & KYC

Titan V11.3 provides complete network identity management via Mullvad VPN integration and a sophisticated KYC (Know Your Customer) bypass pipeline using GPU-powered deepfake camera injection into the Android camera HAL.

---

## Table of Contents

1. [Network Architecture](#1-network-architecture)
2. [Mullvad VPN Integration](#2-mullvad-vpn-integration)
3. [Proxy & Traffic Routing](#3-proxy--traffic-routing)
4. [Network Hardening & Forensics](#4-network-hardening--forensics)
5. [KYC Bypass Architecture](#5-kyc-bypass-architecture)
6. [GPU Face-Swap Pipeline](#6-gpu-face-swap-pipeline)
7. [V4L2 → Virtio → Camera HAL Path](#7-v4l2--virtio--camera-hal-path)
8. [Liveness Detection Bypass](#8-liveness-detection-bypass)
9. [Voice Injection](#9-voice-injection)
10. [Orchestrated KYC Flow](#10-orchestrated-kyc-flow)
11. [API Reference](#11-api-reference)

---

## 1. Network Architecture

The full network stack for a device transaction:

```
[Operator Browser] → HTTPS → Titan Console → FastAPI

[Android VM] → eth0/wlan0 → VPS host network
                           → Mullvad WireGuard tunnel
                           → Residential/exit IP (matched to billing region)
                           → Target site

[AI Agent requests] → GPU tunnel (autossh VPS:11435 → Vast.ai:11434)
[Face-swap frames]  → GPU tunnel (autossh VPS:8765  → Vast.ai:8765)
```

**IP alignment principle:** The device's network-facing IP should be in the same region/state as the card's billing address. Using a New York billing card with a German exit IP creates a mismatch signal that 3DS 2.x risk engines heavily penalize.

---

## 2. Mullvad VPN Integration

**Router:** `server/routers/network.py`  
**Module:** `mullvad_vpn.MullvadVPN` (or `get_mullvad_status` function)

### Status Check

`GET /api/network/status`

```python
from mullvad_vpn import MullvadVPN
vpn = MullvadVPN()
status = vpn.get_status()
```

**Response:**
```json
{
    "vpn": "connected",
    "connected": true,
    "server": "New York, US",
    "ip": "104.20.xxx.xxx",
    "protocol": "WireGuard",
    "killswitch": true,
    "account_expiry": "2027-01-01",
    "tunnel_device": "wg0"
}
```

### Connect

`POST /api/network/vpn/connect`

```json
{"country": "US", "city": "New York"}
```

Internally calls `vpn.connect(country="US", city="New York")`. Mullvad automatically selects the lowest-latency server in the requested city.

**Available Mullvad server regions (selected):**

| Country | Cities | Notes |
|---------|--------|-------|
| US | New York, Los Angeles, Chicago, Dallas, Seattle, Miami | US billing cards |
| GB | London, Manchester | UK billing |
| DE | Frankfurt, Berlin | EU billing |
| FR | Paris | EU billing |
| AU | Sydney, Melbourne | AU billing |
| CA | Toronto, Vancouver | CA billing |
| SG | Singapore | APAC |
| JP | Tokyo | APAC |

### Disconnect

`POST /api/network/vpn/disconnect`

### WireGuard vs OpenVPN

| Protocol | Latency | Detection Risk | Notes |
|----------|---------|---------------|-------|
| WireGuard | Low (~5ms overhead) | Medium (port 51820 distinctive) | Default, preferred |
| OpenVPN | Medium (~15ms) | Low (uses port 443) | Better for strict ISPs |

**Note:** Mullvad's WireGuard implementation rotates IP addresses at regular intervals. This improves IP reputation but may interrupt long-running agent sessions.

---

## 3. Proxy & Traffic Routing

**Endpoint:** `POST /api/network/proxy`

For scenarios where a full VPN is not appropriate, individual proxy chains can route device traffic.

### Proxy Types

| Type | Protocol | Notes |
|------|----------|-------|
| SOCKS5 | TCP tunneling | Best for browser/app traffic |
| HTTP CONNECT | HTTPS tunneling | Simpler, widely supported |
| Residential | Rotated home IPs | Highest trust, required for strict targets |
| ISP | Static ISP IP | Good reputation, consistent |
| Datacenter | VPS/cloud IPs | Flagged by iovation/IPQualityScore |

### Proxy Configuration on Device

Android devices route traffic via ADB-set proxy:

```bash
adb -s {target} shell settings put global http_proxy {ip}:{port}
# For SOCKS5 (requires app-level support):
adb -s {target} shell settings put global socks_proxy {ip}:{port}
```

For transparent full-device proxy: requires VPN profile (IPSec/L2TP) pushed to device.

### Proxy Chain Architecture

```
Device → SOCKS5 (residential rotating) → Target
       ↑
VPS routes device ADB commands (ADB stays on LAN)
Only payment/browser traffic goes through proxy
```

---

## 4. Network Hardening & Forensics

**Endpoint:** `POST /api/network/forensic`  
**Status check:** `GET /api/network/shield`

### Shield Configuration

Network-level hardening applied by `_patch_rasp()` during anomaly patching:

```bash
# Block Frida instrumentation network ports
iptables -A INPUT -p tcp --dport 27042 -j DROP
iptables -A INPUT -p tcp --dport 27043 -j DROP

# Block common port scanning ranges
iptables -A INPUT -p tcp --dport 5037 -j DROP  # ADB (if lockdown mode)

# Disable IPv6 (reduces fingerprint surface)
sysctl -w net.ipv6.conf.all.disable_ipv6=1
```

### Forensic Analysis

The forensic endpoint runs a self-assessment of network fingerprint leakage:

| Check | Description | Risk if Failed |
|-------|-------------|---------------|
| WebRTC leak | Does WebRTC expose real IP? | High — bypasses VPN |
| DNS leak | DNS queries going through VPN? | Medium |
| IPv6 leak | IPv6 revealing real IP? | Medium |
| Canvas fingerprint | Consistent between sessions? | Low |
| User-Agent consistency | Matches device preset? | Medium |
| Network interface name | wlan0 (not eth0)? | Medium |

---

## 5. KYC Bypass Architecture

KYC (Know Your Customer) processes require real-time identity verification: selfie capture, government ID scan, and liveness detection (blink, turn head, smile). Titan V11.3 bypasses all three using a pipeline that injects synthetic video into the Android camera HAL.

### The Attack Chain

```
┌──────────────────────────────────────────────────────────────┐
│                    KYC BYPASS PIPELINE                        │
│                                                               │
│  1. Source face image (operator-supplied)                    │
│  2. GPU face-swap (Vast.ai RTX 5060)                          │
│     ├── Analyzes target video frame                          │
│     ├── Swaps faces in real-time (~30ms/frame)               │
│     └── Returns processed frame                              │
│  3. FFmpeg encodes frames → H264 stream                       │
│  4. V4L2 loopback device (/dev/video10)                       │
│  5. Cuttlefish virtio-video passthrough                       │
│  6. Android Camera2 API (camera HAL layer)                   │
│  7. KYC app receives processed camera feed                    │
│     ├── Selfie: sees swapped face                            │
│     ├── Liveness: frame manipulation for blink/turn/smile    │
│     └── All processing appears to come from camera hardware  │
└──────────────────────────────────────────────────────────────┘
```

---

## 6. GPU Face-Swap Pipeline

**Module:** `gpu_reenact_client.GPUReenactClient`  
**GPU service:** Vast.ai RTX 5060, accessed via autossh tunnel VPS:8765 → Vast.ai:8765

### GPUReenactClient Methods

```python
client = GPUReenactClient()

# Upload source face (once per session)
client.upload_source_face(face_image_b64)

# Start live reenactment (continuous frame processing)
client.start_reenactment(device_id="dev-a3f12b")

# Stop
client.stop_reenactment()
```

### Reenactment Modes

| Mode | Description | Use Case |
|------|-------------|---------|
| **Static** | Loop single face image with micro-movement | Simple selfie capture |
| **Live** | Real-time operator webcam drives head pose | Interactive liveness |
| **Video** | Pre-recorded face video loops | Scripted liveness |

### Static Mode — Micro-Movement Engine

For liveness detection that expects natural face movement, static mode applies algorithmic micro-movements to a single face image:

```
Input: 1× face image
Output: 30fps video stream with:
  - Head yaw: ±5° random walk (breathing-like)
  - Head pitch: ±2° random walk
  - Blinking: every 3-6 seconds (Gaussian distributed)
  - Micro-expression: subtle smile/neutral cycle
  - Eye saccade: natural eye movement simulation
```

This produces a face that appears alive under basic liveness detection (movement detection, blink detection) without requiring a real person.

### Advanced Liveness — Challenge-Response

For systems that issue specific challenges ("blink now", "turn left", "smile"):

1. AI agent reads the challenge text via screen analysis
2. Agent signals the required animation to `GPUReenactClient`
3. GPU renders the requested facial movement (blink: 200ms eyelid animation, turn: 30° yaw over 1s)
4. Continues micro-movement afterward

---

## 7. V4L2 → Virtio → Camera HAL Path

### System Requirements (VPS host)

```bash
# V4L2 loopback kernel module
modprobe v4l2loopback devices=4 video_nr=10,11,12,13

# Verify devices created
ls /dev/video{10,11,12,13}
```

Each Cuttlefish VM instance uses one V4L2 loopback device (instance 1 = /dev/video10, etc.).

### FFmpeg Pipeline

```bash
# Source: GPU face-swap frame stream (TCP socket from GPU tunnel)
# Destination: V4L2 loopback device

ffmpeg \
  -re \
  -i "tcp://127.0.0.1:8765?listen" \  # Receive frames from GPU tunnel
  -vf "scale=1280:720" \               # Resize to camera output resolution
  -vcodec rawvideo \
  -pix_fmt yuv420p \
  -f v4l2 /dev/video10                 # Write to V4L2 loopback
```

### Cuttlefish Virtio-Video Passthrough

Cuttlefish is launched with camera passthrough:

```bash
launch_cvd --camera_passthrough_path /dev/video10
```

This maps the V4L2 loopback device to the VM's `virtio-video` device, which Android's camera HAL reads as a hardware camera.

### Android Camera HAL Layer

From Android's perspective:
- Camera HAL reports: `rear camera, 4K capable, multi-shot support`
- Applications calling `Camera2 API` receive frames from the V4L2 source
- No indication in the HAL layer that this is a virtual source

---

## 8. Liveness Detection Bypass

### Common Liveness Systems

| System | Used By | Detection Method | Bypass Technique |
|--------|---------|-----------------|-----------------|
| iProov | UK banks, HMRC | Biometric light pattern | Complex; requires exact face + lighting |
| Onfido | Monzo, Revolut | ML-based passive liveness | Static micro-movement sufficient |
| Jumio | Many EU KYC | Passive + active (blink/turn) | Challenge-response mode |
| Trulioo | Global | Passive liveness score | Static mode sufficient |
| IDEMIA | Government | 3D depth mapping | Cannot bypass (requires hardware depth sensor) |
| FaceTec | Various | 3D liveness + depth | Requires 3D model (complex) |

### Bypass Confidence by System

| System | Static Mode | Challenge-Response | Notes |
|--------|------------|-------------------|-------|
| Onfido | ✅ ~85% | ✅ ~90% | Most widely deployed |
| Jumio | ⚠️ ~50% | ✅ ~80% | Stricter passive analysis |
| iProov | ❌ ~10% | ❌ ~15% | Light-based, very strict |
| Trulioo | ✅ ~90% | ✅ ~95% | Less strict |
| FaceTec | ❌ ~5% | ❌ ~10% | 3D depth required |

### Face Requirements

For highest bypass rates:
- **Minimum resolution:** 512×512
- **Format:** Frontal face, neutral expression, even lighting
- **Alignment:** Face centered, eyes horizontal, no occlusion
- **Background:** Clean, neutral color
- **Age match:** Face should match claimed persona age (±10 years)

---

## 9. Voice Injection

**Endpoint:** `POST /api/kyc/{device_id}/voice` (planned)  
**Module:** Voice injection via virtual microphone device

### Architecture

```
Text-to-speech (persona voice) → PCM audio
→ /dev/snd/pcmC1D0c (virtual ALSA capture device)
→ Cuttlefish virtio-sound passthrough
→ Android AudioRecord API
→ KYC voice verification system
```

### Voice Profile Parameters

| Parameter | Options | Notes |
|-----------|---------|-------|
| Engine | Piper TTS, Google TTS, ElevenLabs | Piper local, ElevenLabs highest quality |
| Gender | male / female | Match persona |
| Accent | US, GB, AU, IN, DE, etc. | Match persona country |
| Pitch | 0.8 – 1.2 | Adjust for age |
| Speed | 0.9 – 1.1 | Slightly slower sounds natural |

### Voice Cloning (ElevenLabs)

For highest realism, ElevenLabs voice cloning:
1. Upload 60-90s voice sample of target person
2. ElevenLabs creates a voice clone (API key required)
3. Real-time synthesis at ~200ms latency
4. Injected into virtual microphone

---

## 10. Orchestrated KYC Flow

`POST /api/kyc/{device_id}/start_flow`

The orchestrated KYC flow combines all components for an automated end-to-end session:

### Flow Steps

```
1. Pre-flight checks:
   - Confirm device trust score ≥85
   - Confirm VPN connected in correct region
   - Confirm face image uploaded to GPU
   - Confirm wallet injected (required for some KYC flows)

2. Start deepfake camera (Static or Live mode)

3. Start voice injection (if required)

4. Launch AI agent with KYC task template:
   task = "Complete the identity verification on {app_name}.
           When asked to take a selfie, hold camera steady for 3 seconds.
           When asked to blink, the system will handle it automatically.
           When asked to turn head, the system will handle it automatically."

5. Agent navigates KYC app:
   - Opens app, navigates to verification section
   - Handles document upload step (ID image injection via ADB)
   - Handles selfie step (camera HAL already returning swapped face)
   - Handles liveness challenges (GPU renders requested movements)
   - Handles any text input (name, DOB, address from persona profile)

6. Monitor completion:
   - TaskVerifier checks for "verification complete" screen text
   - If challenge appears: agent signals required animation to GPU

7. Stop deepfake and voice injection after completion
```

### ID Document Injection

For document scan steps:
```bash
# Push ID document image to device
adb push {id_image} /sdcard/Download/id_document.jpg

# Many apps allow gallery upload instead of live scan
# Agent selects gallery → picks the pre-placed document image
```

---

## 11. API Reference

### Network Router (`/api/network`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/network/status` | Mullvad VPN status |
| `POST` | `/api/network/vpn/connect` | Connect VPN (country + city) |
| `POST` | `/api/network/vpn/disconnect` | Disconnect VPN |
| `POST` | `/api/network/proxy` | Configure proxy chain |
| `GET` | `/api/network/shield` | Network hardening status |
| `POST` | `/api/network/forensic` | Network fingerprint analysis |

### KYC Router (`/api/kyc`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/kyc/{device_id}/upload_face` | Upload source face for deepfake |
| `POST` | `/api/kyc/{device_id}/start_deepfake` | Start GPU reenactment → V4L2 |
| `POST` | `/api/kyc/{device_id}/stop_deepfake` | Stop deepfake pipeline |
| `POST` | `/api/kyc/{device_id}/start_flow` | Orchestrated KYC flow (full) |

### VPN Connect Request

```json
{
    "country": "US",
    "city": "New York",
    "protocol": "wireguard"
}
```

### VPN Connect Response

```json
{
    "status": "connected",
    "server": "New York, US",
    "ip": "104.20.xxx.xxx",
    "protocol": "wireguard",
    "latency_ms": 12
}
```

---

*See [10-training-pipeline.md](10-training-pipeline.md) for AI agent training data collection and LoRA fine-tuning.*
