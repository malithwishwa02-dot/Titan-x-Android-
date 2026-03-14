# 07 — Titan Console

The Titan Console is a single-page web application (Alpine.js + Tailwind CSS) served at `https://72.62.72.48/`. It provides a unified interface for managing the entire Titan V11.3 platform across 12 API sections and 62+ functional tabs.

---

## Table of Contents

1. [Console Architecture](#1-console-architecture)
2. [Section 1 — Dashboard](#2-section-1--dashboard)
3. [Section 2 — Devices](#3-section-2--devices)
4. [Section 3 — Stealth](#4-section-3--stealth)
5. [Section 4 — Genesis](#5-section-4--genesis)
6. [Section 5 — Intelligence](#6-section-5--intelligence)
7. [Section 6 — Network](#7-section-6--network)
8. [Section 7 — Cerberus](#8-section-7--cerberus)
9. [Section 8 — Targets](#9-section-8--targets)
10. [Section 9 — KYC](#10-section-9--kyc)
11. [Section 10 — AI Agent](#11-section-10--ai-agent)
12. [Section 11 — Training](#12-section-11--training)
13. [Section 12 — Admin](#13-section-12--admin)
14. [Mobile Viewer](#14-mobile-viewer)

---

## 1. Console Architecture

```
/console/
├── index.html       Main console SPA (12 sections, 62 tabs)
├── mobile.html      PWA mobile device viewer + AI agent panel
└── manifest.json    PWA manifest (offline-capable)
```

**Frontend stack:**
- Alpine.js — reactive state management, tab switching, API calls
- Tailwind CSS — utility-first styling, dark theme
- WebSocket — live device logs and agent step streaming
- Fetch API — REST calls to FastAPI backend on :8080

**URL routing:**
- `https://72.62.72.48/` → Main console (via Nginx proxy to :8080 static)
- `https://72.62.72.48/scrcpy/` → ws-scrcpy H264 stream
- `https://72.62.72.48/mobile#dev-a3f12b` → Mobile PWA viewer for specific device

---

## 2. Section 1 — Dashboard

**API base:** `/api/dashboard`

The dashboard provides a real-time fleet overview — the first thing visible when the console loads.

### Tab: Fleet Overview

- **Device cards** — One card per active Cuttlefish VM showing:
  - Device ID and model name (e.g., "Samsung S25 Ultra")
  - Stealth score ring chart (0–100, color-coded: green≥90, yellow≥70, red<70)
  - Screen thumbnail (fetched via `/api/devices/{id}/screenshot`)
  - State badge: `running` / `patched` / `ready` / `error`
  - Last inject time and trust grade (A+/A/B/C/F)
  - Active agent task indicator (spinning icon if agent running)
  - Wallet status: `✅ Google Pay` or `⚠️ No wallet`

- **Quick Actions** per device card:
  - 🔧 Patch (opens Stealth tab with device pre-selected)
  - 💉 Inject (opens Genesis inject form)
  - 🤖 Start Agent (opens AI tab with device pre-selected)
  - 🗑️ Destroy device

### Tab: Live Operations Feed

- Scrolling log of recent operations across all devices
- Events: patch completed, inject started, inject completed, trust score, agent step, wallet verified
- Each event: timestamp, device ID, operation, result (pass/fail), score
- Auto-scrolls, max 200 events in buffer

### Tab: Fleet Statistics

- **Score distribution chart** — Bar chart of stealth scores across fleet
- **Trust score heatmap** — Per-device, per-check grid (green=pass, red=fail)
- **Wallet state summary** — Count of devices with Google Pay active
- **Agent task history** — Count of completed/failed tasks last 24h

---

## 3. Section 2 — Devices

**API base:** `/api/devices`

Manages the Cuttlefish VM fleet lifecycle.

### Tab: Device List

- Table of all active devices: ID, model, ADB target, state, created time, stealth score
- **Create Device** button → opens creation form
- Per-row actions: View details, Patch, Destroy
- Empty state: "No devices. Create your first device to get started."

### Tab: Create Device

Form fields:
| Field | Default | Notes |
|-------|---------|-------|
| Device Model | `samsung_s25_ultra` | Dropdown of 18+ presets |
| Country | `US` | Sets default carrier/location |
| Carrier | `tmobile_us` | Carrier profile selector |
| Location | `nyc` | GPS/locale/SSID location |
| Android Version | `14` | 13 / 14 / 15 |
| Memory (MB) | `4096` | 2048 / 4096 / 8192 |
| CPUs | `4` | 2 / 4 / 8 |

**Create flow:**
1. Submit form → `POST /api/devices`
2. Loading spinner while `launch_cvd` boots (~40s)
3. Card appears in Device List with `state=running`
4. Optional: auto-patch after creation (checkbox)

### Tab: Device Config

For a selected device:
- View current config: model, ADB target, VNC port, CVD home, instance number
- Edit memory/CPU (requires device restart)
- View raw DeviceInstance JSON
- ADB shell terminal (text input → `POST /api/devices/{id}/shell` → output display)

### Tab: Screen Stream

- Embedded H264 stream via ws-scrcpy WebSocket
- Live display of selected device screen
- **Interactive mode**: click on stream → sends tap via ADB
- **Input bar**: type text → sends via ADB input
- Resolution selector: 720p / 1080p
- FPS indicator and latency display
- Fullscreen button

---

## 4. Section 3 — Stealth

**API base:** `/api/stealth`  
**Router:** `server/routers/stealth.py`

Controls the anomaly patcher — the 21-phase stealth engine.

### Tab: Patch Device

- **Device selector** — Dropdown of active devices
- **Preset** — Device model preset (default: current device config)
- **Carrier** — Carrier profile
- **Location** — GPS/locale location
- **Lockdown mode** — Checkbox to also conceal ADB (for production)

**Run Patch** button → `POST /api/stealth/{device_id}/patch`

Results display:
```
✅ Patch Complete — Score: 97/100

Phase Results:
  ✅ prop:ro.product.model    SM-S938U
  ✅ prop:ro.build.fingerprint  samsung/p3qxxx/p3q:14/UP1A...
  ✅ imei                     355819081234565
  ✅ keybox_loaded             hash=a1b2c3d4, paths=3/3
  ✅ gsf_checkin_aligned       deviceId=a1b2c3d4e5f6a7b8
  ⚠️ sensor_noise_init        OADEV init timed out (non-critical)
  ...
```

Color-coded per result. Expandable detail view per phase. Score ring chart in top right.

### Tab: Audit

Real-time audit of current device state without making changes.

`GET /api/stealth/{device_id}/audit`

Displays 20 checks in a grid:
```
qemu_hidden              ✅  ro.kernel.qemu=0
virtual_hidden           ✅  ro.hardware.virtual=0
debuggable_off           ✅  ro.debuggable=0
secure_on                ✅  ro.secure=1
build_type_user          ✅  ro.build.type=user
release_keys             ✅  release-keys in build.tags
proc_cmdline_sterile     ✅  sterile file bind-mount active
proc_cgroup_sterile      ✅  sterile file bind-mount active
verified_boot_green      ✅  green
bootloader_locked        ✅  1
sim_ready                ✅  READY
carrier_set              ✅  T-Mobile
network_lte              ✅  LTE
fingerprint_set          ✅  samsung/p3qxxx/...
model_set                ✅  SM-S938U
serial_set               ✅  R5CR12B4KTR
adb_disabled             ⚠️  ADB still enabled (expected if not lockdown)
keybox_loaded            ✅  persist.titan.keybox.loaded=1
gsf_aligned              ✅  CheckinService.xml present
```

Score: **18/20 (90%)** — displayed as ring chart with pass/fail breakdown.

### Tab: Wallet Verify

Deep 13-check wallet state verification.

`GET /api/stealth/{device_id}/wallet-verify`

```
Wallet Verification — Score: 12/13 (92%) Grade: A

  ✅ tapandpay_db_exists         Found: /data/.../tapandpay.db
  ✅ tapandpay_token_count        Token count: 1
  ✅ token_provisioning_status   PROVISIONED
  ✅ nfc_prefs_enabled            nfc_enabled=true
  ✅ coin_xml_payment_method     COIN.xml has payment method
  ✅ coin_auth_disabled           purchase_requires_auth=false
  ✅ chrome_webdata_exists        Chrome Web Data present
  ✅ gms_wallet_synced            wallet_setup_complete=true
  ✅ gms_payment_profile_synced  payment_methods_synced=true
  ❌ keybox_loaded                Keybox NOT loaded
     ↳ Remediation: Place keybox.xml at /opt/titan/data/keybox.xml
  ✅ gsf_fingerprint_aligned     GSF CheckinService aligned
  ✅ tapandpay_ownership          Owner: u0_a145 (correct)
  ✅ system_nfc_enabled           System NFC: enabled

ℹ️ Samsung Pay: NOT supported (Knox TEE e-fuse hardware barrier)
```

---

## 5. Section 4 — Genesis

**API base:** `/api/genesis`  
**Router:** `server/routers/genesis.py`

The full Genesis pipeline: forge → inject → verify.

### Tab: Forge Profile

Create a new forged persona and device profile.

Form fields:
| Field | Default | Notes |
|-------|---------|-------|
| Name | (auto) | Leave blank to auto-generate |
| Email | (auto) | Leave blank to auto-generate |
| Phone | (auto) | Leave blank to auto-generate |
| Country | `US` | Locale for name pools, SMS templates, browser patterns |
| Archetype | `professional` | Shapes what data is generated |
| Profile Age | `90` days | How far back data is created |
| Carrier | `tmobile_us` | For telco-specific SMS |
| Location | `nyc` | GPS, WiFi SSIDs, locale |
| Device Model | `samsung_s25_ultra` | For device-specific data |
| CC Number | — | Optional: inject wallet at same time |
| CC Expiry | — | MM/YYYY |
| CC CVV | — | 3-4 digits |
| CC Cardholder | — | Full name on card |

**Forge** button → `POST /api/genesis/create`

Response shows profile summary card:
```
Profile Created: TITAN-0A4314A9
Persona: Alex Mercer (alex.mercer57@gmail.com)
Stats: 22 contacts | 370 calls | 58 SMS | 127 cookies | 200 history
       15 gallery | 6 wifi networks
```

### Tab: SmartForge

AI-driven occupation-based persona generator for more contextually coherent identities.

Form fields:
| Field | Default | Notes |
|-------|---------|-------|
| Occupation | `software_engineer` | Shapes archetype, age range, browsing |
| Country | `US` | |
| Age | `30` | Approximate target age |
| Gender | `auto` | male / female / auto |
| Target Site | `amazon.com` | Optimizes persona for this site |
| Use AI | `false` | LLM enrichment (slower but richer) |
| Profile Age | (auto from occupation) | |
| Override fields | — | Name, email, phone, DOB, address, CC |

Occupation → archetype mapping table displayed inline.

### Tab: Profiles

Library of all saved forged profiles.

Table view:
```
ID              | Persona Name | Country | Archetype | Age | Device | Created
TITAN-0A4314A9  | Alex Mercer  | US      | professional | 90d | Samsung S25 | Mar 14
TITAN-B2C8D91F  | Emma Johnson | GB      | student    | 30d | Pixel 9 Pro | Mar 12
```

Per-row actions:
- 👁️ View full profile JSON
- 💉 Inject (opens Inject tab with this profile pre-selected)
- 🗑️ Delete

Search/filter by: country, archetype, device model, created date.

### Tab: Inject

Inject a saved profile into a Cuttlefish device.

Form fields:
| Field | Notes |
|-------|-------|
| Device | Dropdown of active devices |
| Profile | Dropdown of saved profiles (or paste profile ID) |
| CC Number | Optional: override/add CC data |
| CC fields | exp_month, exp_year, cvv, cardholder |

**Inject** button → `POST /api/genesis/inject/{device_id}`

Live progress display:
```
🔄 Injection in progress... (47s)

  ✅ Google account         15.2s
  ✅ Chrome cookies          8.1s — 127 entries
  ✅ Chrome history         12.4s — 200 entries
  ✅ Chrome autofill         2.1s
  ✅ Contacts               18.3s — 22 entries
  ✅ Call logs              35.1s — 370 entries
  ✅ SMS                    20.2s — 58 messages
  🔄 Gallery...            (injecting 15 photos)
```

Final result shows `InjectionResult` summary with per-target pass/fail.

### Tab: Trust Score

Compute and display the 13-point trust score for any device.

`GET /api/genesis/trust-score/{device_id}`

```
Trust Score: 96/100  Grade: A+

  ✅ google_account    15pts  accounts_ce.db found
  ✅ contacts           8pts  22 contacts
  ✅ chrome_cookies     8pts  Cookies DB found
  ✅ chrome_history     8pts  History DB found
  ✅ gallery            5pts  15 photos
  ✅ google_pay        12pts  1 token, PROVISIONED
  ✅ play_library       8pts  library.db found
  ✅ wifi               4pts  WifiConfigStore.xml found
  ✅ sms                7pts  58 messages
  ✅ call_logs          7pts  370 calls
  ✅ app_data           8pts  Instagram prefs found
  ✅ chrome_signin      5pts  Preferences found
  ⚠️ autofill          0pts  Web Data not found

  ──────────────────────────────
  ℹ️ NFC tap-pay:      ✅ enabled
  ℹ️ GMS billing:      ✅ synced
  ℹ️ Keybox:           ✅ loaded
```

---

## 6. Section 5 — Intelligence

**API base:** `/api/intel`  
**Router:** `server/routers/intel.py`

AI-powered intelligence and OSINT tools.

### Tab: AI Copilot

Free-form AI query powered by `AIIntelligenceEngine.orchestrate_operation_intel()`.

- Text prompt input field
- Submit → `POST /api/intel/copilot`
- Streamed response displayed in chat-style panel
- Example queries:
  - "What are the 3DS bypass strategies for Amazon US?"
  - "Analyze the fraud signals on Stripe payment processor"
  - "How does Chase bank detect virtual devices?"
  - "Recommend the best carrier for high-trust financial transactions"

### Tab: OSINT

Multi-tool OSINT orchestration via `OSINTOrchestrator`.

Input fields:
| Field | Purpose |
|-------|---------|
| Name | Full name lookup (Pipl-style) |
| Email | Email reverse lookup (Holehe — 120+ sites) |
| Username | Username search (Sherlock — 300+ sites) |
| Phone | Phone OSINT (PhoneInfoga) |
| Domain | Domain OSINT (WHOIS, DNS, breaches) |

**Run OSINT** → `POST /api/intel/osint`

Results displayed in expandable sections:
- Sites where account exists (Sherlock/Maigret)
- Email breach history (HaveIBeenPwned)
- Phone carrier + location
- Domain registration history

### Tab: 3DS Strategy

Card-specific 3DS bypass strategy advisor.

Input: BIN number or full card details

`POST /api/intel/3ds-strategy`

Output:
```
BIN: 411111 (Visa, Chase Sapphire, US)
3DS Version: 3DS 2.0
EMV 3DS Challenge Rate: ~15% (low friction issuer)

Recommended Strategy:
  1. Use US IP matching card BIN country
  2. Device fingerprint: pixel_9_pro or samsung_s25_ultra
  3. Trust score ≥85 before transaction attempt
  4. Behavioral: 3-5 minute session before checkout
  5. Velocity: max 1 transaction per device per 6h
```

### Tab: Dark Web (stub)

Dark web search interface — requires external dark web search module.

`POST /api/intel/dark-web`

Status: Module integration point. Currently returns stub response.

### Tab: Recon

Domain reconnaissance via `target_intelligence.get_target_intel()`.

Input: domain name (e.g., `amazon.com`)

`POST /api/intel/recon`

Output: WHOIS, DNS records, technology stack, security headers, CDN detection.

---

## 7. Section 6 — Network

**API base:** `/api/network`  
**Router:** `server/routers/network.py`

VPN, proxy, and network forensics.

### Tab: VPN Status

`GET /api/network/status`

```
Mullvad VPN Status
  Connected: ✅ Yes
  Server: New York, US (104.20.x.x)
  Protocol: WireGuard
  Killswitch: Enabled
  Account: expiry 2027-01-01
```

### Tab: VPN Connect

`POST /api/network/vpn/connect`

```json
{"country": "US", "city": "New York"}
```

- Country/city selectors
- Protocol: WireGuard (default) / OpenVPN
- Relay list auto-populated from Mullvad API

### Tab: VPN Disconnect

`POST /api/network/vpn/disconnect`

Simple button, confirms disconnection.

### Tab: Proxy

`POST /api/network/proxy`

Proxy chain configuration for device traffic routing:
- SOCKS5 proxy entry
- HTTP proxy entry
- Proxy chain ordering
- Test proxy connectivity button

### Tab: Shield

Network hardening rules display:
- Active iptables rules (Frida port blocks: 27042, 27043)
- `settings put global development_settings_enabled 0` status
- Network interface status (wlan0 confirmed)
- DNS leak test result

### Tab: Forensic

`POST /api/network/forensic`

Traffic analysis report:
- Request pattern scoring
- Header fingerprint assessment
- WebRTC leak check
- Canvas fingerprint (via browser)
- Font fingerprint analysis

---

## 8. Section 7 — Cerberus

**API base:** `/api/cerberus`  
**Router:** `server/routers/cerberus.py`  
**Engine:** `cerberus_core.CerberusValidator` (from v11-release)

Card validation and BIN intelligence.

### Tab: Validate Card

Single card validation.

Input: Card string (formats: `4111111111111111|12|2028|123` or JSON)

`POST /api/cerberus/validate`

Output:
```
Card Validation Result

  Status:      ✅ VALID
  BIN:         411111
  Network:     Visa
  Type:        Credit
  Level:       Signature
  Issuer:      Chase Bank USA, N.A.
  Country:     United States 🇺🇸
  Currency:    USD

  Expiry:      12/2028 ✅ (not expired)
  CVV:         123 (format valid)
  Luhn:        ✅ passed

  3DS Risk:    Low (Visa 3DS 2.0, ~15% challenge rate)
  Velocity:    Unknown (first check)
```

### Tab: Batch Validate

Multi-card validation via CSV upload or paste.

`POST /api/cerberus/batch`

```
Upload .txt file (one card per line) or paste:
4111111111111111|12|2028|123
5500005555555559|01|2027|456
341111111111111|05|2026|7890
```

Results table: Card (masked), Status, BIN, Network, Issuer, Level, Country.

Export as CSV button.

### Tab: BIN Intelligence

BIN-only lookup for issuer/network/country information.

`POST /api/cerberus/bin`

Input: 6-8 digit BIN number

Output:
```
BIN: 541156
Network:     Mastercard
Type:        Debit
Level:       Standard
Issuer:      Wells Fargo Bank
Country:     United States 🇺🇸
Currency:    USD
3DS:         Mastercard SecureCode 2.0
```

---

## 9. Section 8 — Targets

**API base:** `/api/targets`  
**Router:** `server/routers/targets.py`

Website and payment processor analysis.

### Tab: Site Analysis

Comprehensive target site analysis via `WebCheckEngine.full_analysis()`.

`POST /api/targets/analyze`

Input: domain (e.g., `amazon.com`)

Output (12-factor analysis):
```
Target: amazon.com

  🛡️ WAF:           Imperva Incapsula (confidence: 95%)
  🔒 SSL:            A+ (TLS 1.3, HSTS, HPKP)
  🌐 CDN:            CloudFront + Fastly
  📡 Rate Limit:     Yes (429 after ~15 req/s)
  🔐 3DS:            3DS 2.x (Cardinal Commerce)
  📊 Fraud Score:    Medium-High (device fingerprinting active)
  🤖 Bot Detection:  PerimeterX + reCAPTCHA v3
  📍 Geo-blocking:   None detected
  📦 Technologies:   React, Node.js, AWS
  🔑 Auth:           OAuth2 + OTP
  💳 Payments:       Stripe + Chase Orbital
  📧 Notifications:  SES (email) + SNS (SMS)
```

### Tab: WAF Detection

`POST /api/targets/waf`

Rapid WAF fingerprinting via `WAFDetector.detect()`:
- Cloudflare, Imperva, Akamai, F5 BIG-IP, Sucuri, AWS WAF, Fastly
- Confidence score per detected WAF

### Tab: DNS Intelligence

`POST /api/targets/dns`

Full DNS record dump via `DNSIntel.get_all_records()`:
- A/AAAA (IP addresses)
- MX (mail servers)
- NS (nameservers)
- TXT (SPF, DKIM, DMARC, verification tokens)
- CNAME, SOA records

### Tab: Target Profiler

`POST /api/targets/profiler`

Advanced target profile via `TitanTargetProfiler.profile()`:
- Anti-fraud stack identification
- Device fingerprinting aggressiveness score
- Session replay detection
- Behavioral analytics detection
- Recommended approach strategy

---

## 10. Section 9 — KYC

**API base:** `/api/kyc`  
**Router:** `server/routers/kyc.py`

Real-time deepfake camera injection for KYC/identity verification bypass.

### Tab: Face Upload

`POST /api/kyc/{device_id}/upload_face`

- Upload a source face image (JPG/PNG, minimum 512×512)
- Face is sent to GPU reenactment server via `GPUReenactClient`
- **Status:** `face_uploaded: true, gpu_connected: true/false`

### Tab: Start Deepfake

`POST /api/kyc/{device_id}/start_deepfake`

Starts GPU real-time face-swap injection:

```
Deepfake Pipeline:
  Source face → GPU server (Vast.ai RTX 5060)
              → Face-swap inference (~30ms/frame @ 30fps)
              → Encoded H264 frames
              → VPS:8765 tunnel
              → FFmpeg → /dev/video{N} (V4L2 loopback)
              → Cuttlefish virtio-video device
              → Android camera HAL
              → KYC app camera input
```

**Modes:**
- **Static**: Loop a single face image with micro-movement (head rotation ±5°)
- **Live**: Real-time GPU reenactment driven by operator webcam
- **Video**: Pre-recorded face video loop

### Tab: Stop Deepfake

`POST /api/kyc/{device_id}/stop_deepfake`

Stops the FFmpeg → V4L2 pipeline, returns camera to normal.

### Tab: Liveness

Liveness video injection for liveness detection bypass.

- Upload or select a pre-recorded liveness video (blink, turn head, smile)
- Video injected via V4L2 loopback at correct FPS
- Synchronized playback timing with KYC session

### Tab: Voice

TTS persona voice injection:

- Voice profile: gender, accent, pitch, speaking rate
- Persona-consistent voice (matched to name/country)
- Audio injected via virtual microphone device
- Test utterance playback

### Tab: KYC Flow

Orchestrated automated KYC session:

1. Start deepfake camera
2. Start voice injection
3. Launch AI agent with KYC-specific task template
4. Agent navigates KYC flow (selfie, ID scan, liveness)
5. Automatic handling of: face framing, turn-head prompts, blink detection

---

## 11. Section 10 — AI Agent

**API base:** `/api/ai`  
**Router:** `server/routers/ai.py`

Full AI device agent control panel.

### Tab: Screen Agent

Interactive AI task launcher.

- **Device selector** — Choose target device
- **Task prompt** — Free-form task description
- **Max steps** — Slider: 10–50 steps
- **Start Task** → `POST /api/ai/{device_id}/task`

**Live step viewer** (WebSocket):
```
Step 1  [0.8s]  open_app com.android.chrome
         Reason: "Opening Chrome browser to navigate to task URL"
         Screenshot: [thumbnail]

Step 2  [2.1s]  type "amazon.com"
         Reason: "Typing target URL in address bar"

Step 3  [1.4s]  tap (540, 1200)
         Reason: "Tapping search results link"
...

✅ Task completed in 18 steps (142s)
```

### Tab: Faceswap

GPU face-swap API (image-to-image, not live):

- Upload source face image
- Upload target image/frame
- `POST /api/ai/{device_id}/faceswap`
- Returns swapped result image (base64 PNG)
- Used for static ID document face replacement

### Tab: Vision

Screenshot visual analysis:

- Capture current screen → `POST /api/ai/{device_id}/screenshot`
- Send to vision model → `GET /api/ai/{device_id}/vision`
- LLM describes what it sees and suggests next actions
- Debug tool for understanding why agent made certain decisions

### Tab: Models

AI model status and management:

`GET /api/ai/status`

```
GPU Ollama (11435):    ✅ Connected (41 tok/s)
CPU Ollama (11434):    ✅ Connected (4 tok/s)

Available Models:
  Action:  titan-agent:7b ★ (preferred) | hermes3:8b | qwen2.5:7b
  Vision:  titan-screen:7b ★ | minicpm-v:8b | llava:7b

Active Tasks:  2 running
Completed:     147 (last 24h)
Failed:        12 (last 24h)
```

---

## 12. Section 11 — Training

**API base:** `/api/training`  
**Router:** `server/routers/training.py`

Training data collection and export for LLM fine-tuning.

### Tab: Demo Record

Human-annotated demonstration recording.

1. Select device from dropdown
2. **Start Recording** → `POST /api/training/demo/start/{device_id}`
   - Enter task prompt and category
3. Control device via Screen Stream tab
4. After each action, click **Record Action**:
   - Action type: tap / type / swipe / back / home / wait
   - Coordinates (auto-populated from last screen click)
   - Reason annotation (brief description)
5. **Stop Recording** → `POST /api/training/demo/stop/{device_id}`

Session info:
```
Demo Session: demo-xyz (active 3m 42s)
Actions recorded: 14
Screenshot captures: 14
```

### Tab: Trajectories

Browse all recorded trajectory files.

`GET /api/training/trajectories`

Table:
```
Task ID      | Source  | Steps | Duration | Model | Date    | Actions
t-abc123     | agent   | 18    | 142s     | hermes3 | Mar14  | View | Delete
demo-xyz     | human   | 14    | 222s     | —      | Mar13  | View | Delete
```

- Click **View** → Opens JSONL viewer with screenshot thumbnails and action log
- Filter by: source (agent/human), model, date range, task category

### Tab: Export

Export trajectories as ChatML JSONL for Ollama LoRA fine-tuning.

`POST /api/training/export`

Options:
- **Format**: ChatML (Ollama), Alpaca, ShareGPT
- **Filter**: all / human-only / agent-only / by model
- **Vision**: Include screenshot base64 (multimodal)
- **Date range**: Last N days

Download button → JSONL file (~500 steps per file for optimal batch size).

**Fine-tuning command** (shown after export):
```bash
# On Vast.ai GPU instance:
ollama create titan-agent:7b -f ./Modelfile
# Modelfile: FROM hermes3:8b + ADAPTER ./titan-trajectories.jsonl
```

### Tab: Scenarios

Batch scenario runner for automated training data generation.

`POST /api/training/scenarios/run`

```json
{
  "device_ids": ["dev-a3f12b", "dev-b4c9d1"],
  "templates": ["warmup_device", "search_google", "browse_amazon"],
  "params_sets": [
    {"query": "best headphones"},
    {"query": "running shoes size 10"}
  ],
  "max_steps": 30,
  "retries": 1
}
```

Progress display:
```
Batch: batch-456 (running)
Progress: 4/6 scenarios complete

  ✅ dev-a3f12b + warmup_device       18 steps
  ✅ dev-a3f12b + search_google(q1)   12 steps
  🔄 dev-b4c9d1 + browse_amazon(q2)  (step 8/30)
  ❌ dev-a3f12b + search_google(q2)   failed (step 3)
  ⏳ dev-b4c9d1 + warmup_device       pending
  ⏳ dev-b4c9d1 + search_google(q1)   pending
```

---

## 13. Section 12 — Admin

**API base:** `/api/admin`  
**Router:** `server/routers/admin.py`

System health and operations.

### Tab: Services

`GET /api/admin/services`

```
Service Status

  titan-v11-api    ✅ active
  ws-scrcpy        ✅ active
  nginx            ✅ active
  titan-gpu-tunnel ✅ active (Vast.ai RTX 5060 connected)
```

Restart buttons per service (requires confirmation modal).

### Tab: Health

`GET /api/admin/health`

```
System Health

  Status:         ✅ ok
  Active Devices: 3 / 8 max
  Devices Ready:  2
  API Uptime:     14h 32m
  CPU Load:       42% (nominal)
  Memory:         12.4GB / 32GB
```

### Tab: CPU Monitor

`GET /api/admin/cpu` (streaming)

Live CPU usage chart — important for monitoring Hostinger's throttle threshold:
- Per-core usage bars
- **Throttle risk indicator**: green < 70%, yellow 70-85%, red > 85%
- Warning at >180 min sustained high load (Hostinger throttle trigger)
- Automatic recommendation to reduce active VM count if at risk

---

## 14. Mobile Viewer

**URL:** `https://72.62.72.48/mobile#dev-a3f12b`

`console/mobile.html` is a PWA-optimized view for mobile operators:

- **Device selector** — Compact dropdown or URL hash
- **Screen stream** — Full-width H264 stream (ws-scrcpy WebSocket)
- **Touch passthrough** — Tap on stream → sends via ADB
- **Quick action bar**:
  - 🤖 Start Agent task
  - 💉 Quick inject
  - 🔧 Quick patch
  - 📊 Trust score
- **Wallet status chip** — Google Pay verified / not verified
- **Compact agent log** — Last 5 agent steps

**PWA features:**
- Add to home screen (manifest.json)
- Offline-capable (service worker caches SPA assets)
- Works on iOS Safari and Android Chrome

---

*See [08-intelligence-tools.md](08-intelligence-tools.md) for detailed OSINT and intelligence tool documentation.*
