# Titan V11.3 — Antidetect Device Platform

Unified web console controlling fully undetectable Redroid Android devices. Converts all 10 PyQt6 desktop apps (62 tabs) into a single web-based platform deployed on Hostinger KVM 8.

## Architecture

```
Web Console (any browser)
    │  HTTPS :443
    ▼
Nginx → Titan API (FastAPI :8080) → Redroid Containers (Android 14/15)
         ├── /api/devices/*     Device CRUD, streaming, screenshots
         ├── /api/stealth/*     53+ vector anomaly patcher
         ├── /api/genesis/*     Profile forge + device injection
         ├── /api/intel/*       AI copilot, 3DS, recon, dark web
         ├── /api/network/*     VPN, shield, forensic, proxy
         ├── /api/cerberus/*    Card validation, BIN testing
         ├── /api/targets/*     OSINT analyzer, WAF, SSL, DNS
         ├── /api/kyc/*         Deepfake camera injection
         ├── /api/admin/*       Services, automation, diagnostics
         ├── /api/ai/*          AI task routing, metrics
         ├── /api/dashboard/*   Live ops feed, heatmaps
         └── /api/settings/*    System configuration
```

## Quick Start

### 1. Format VPS (optional — wipes everything)
```bash
python3 scripts/format_vps.py --confirm
```

### 2. Deploy to VPS
```bash
scp -r . root@72.62.72.48:/opt/titan-v11.3-device/
ssh root@72.62.72.48 'bash /opt/titan-v11.3-device/scripts/deploy_titan_v11.3.sh'
```

### 3. Open Console
```
https://72.62.72.48/
```

## Project Structure

```
titan-v11.3-device/
├── console/                  Web console (SPA)
│   ├── index.html           Main console (all 10 app sections)
│   ├── mobile.html          PWA mobile device view
│   └── manifest.json        PWA manifest
├── core/                     Core Python modules
│   ├── device_manager.py    Redroid container management
│   ├── device_presets.py    20+ device identities (Samsung, Pixel, OnePlus, etc.)
│   ├── anomaly_patcher.py   53+ detection vector patcher
│   └── app_bundles.py       7 country app bundles
├── server/                   API server
│   ├── titan_api.py         FastAPI backend (all routes)
│   └── requirements.txt     Python dependencies
├── docker/                   Docker config
│   ├── Dockerfile.titan-api API server image
│   ├── Dockerfile.redroid-gms Custom Redroid with GMS
│   ├── docker-compose.yml   Full stack compose
│   ├── nginx.conf           Reverse proxy config
│   └── init.d/              Boot patch scripts for containers
├── scripts/                  Deployment scripts
│   ├── deploy_titan_v11.3.sh Full VPS deployment
│   └── format_vps.py        Hostinger API VPS format
└── README.md
```

## Device Presets (20+)

| Brand | Models |
|-------|--------|
| Samsung | Galaxy S25 Ultra, S24, A55, A15 |
| Google | Pixel 9 Pro, 8a, 7 |
| OnePlus | 13, 12, Nord CE 4 |
| Xiaomi | 15, 14, Redmi Note 14 Pro |
| Vivo | V2183A, X200 Pro |
| OPPO | Find X8, Reno 12 |
| Nothing | Phone (2a) |

## Genuine Device — 53+ Vectors Patched

- **Device Identity**: Fingerprint, model, IMEI, serial, MAC, DRM ID
- **SIM/Telephony**: Carrier, MCC/MNC, SIM READY state, cell towers
- **Anti-Emulator**: No qemu/goldfish/Docker/cgroup traces
- **Build Verification**: Locked bootloader, verified boot green, SELinux
- **Root/RASP**: su hidden, Magisk hidden, Frida blocked, ADB disabled
- **Location**: GPS + timezone + locale + WiFi SSID consistent
- **Media History**: Contacts, call logs, gallery, realistic boot count/uptime
- **GMS**: Play Store functional, Play Integrity passing

## VPS Requirements

- **Target**: 72.62.72.48 (KVM 8: 8 CPU, 32GB RAM, 400GB disk)
- **OS**: Ubuntu 24.04 LTS
- **Devices**: 4-8 simultaneous Redroid instances (~3GB RAM each)
- **GPU**: Vast.ai RTX 3090 via SSH tunnel (for deepfake)
