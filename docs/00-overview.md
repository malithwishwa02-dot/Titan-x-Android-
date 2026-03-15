# 00 — Platform Overview

Titan V11.3 is a full-stack Android cloud device platform that deploys undetectable, high-fidelity virtual Android environments on KVM infrastructure, complete with AI-driven behavioral automation, wallet injection, and identity synthesis.

---

## Table of Contents

1. [What Titan V11.3 Is](#1-what-titan-v113-is)
2. [Architecture](#2-architecture)
3. [Infrastructure](#3-infrastructure)
4. [Service Map](#4-service-map)
5. [Migration History](#5-migration-history)
6. [Key File Paths](#6-key-file-paths)
7. [Environment Variables](#7-environment-variables)
8. [Python Stack](#8-python-stack)
9. [Capability Summary](#9-capability-summary)

---

## 1. What Titan V11.3 Is

Titan V11.3 is a platform for orchestrating a fleet of cloud-resident Android virtual machines that are indistinguishable from physical handsets. The platform provides:

- **Device Virtualization** — Full Android 14/15 KVM VMs via Google Cuttlefish, with ARM translation and GMS
- **Identity Synthesis** — 20+ device presets with accurate fingerprints, baked at VM boot time
- **Anomaly Suppression** — 26-phase patcher covering 103+ detection vectors used by fraud systems, RASP, and Play Integrity
- **Genesis Profile Forge** — AI-driven persona generation with 90–365 days of circadian-weighted behavioral data
- **Wallet Injection** — Google Pay, Play Store billing, Chrome autofill CC injection with post-verification
- **AI Device Agent** — LLM-powered autonomous Android control (See→Think→Act loop via Ollama, with crash/ANR auto-dismiss and retry+fallback)
- **Deepfake KYC** — Real-time GPU face-swap injection into the Android camera HAL for liveness bypass
- **Intelligence Suite** — OSINT, Cerberus card validation, BIN intelligence, 3DS strategy, target analysis

The platform is designed for large-scale, simultaneous operation of 4–8 device instances per VPS node with sub-300ms remote screen streaming via ws-scrcpy.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     OPERATOR BROWSER                             │
│              https://72.62.72.48/  (Alpine.js + Tailwind SPA)    │
└───────────────────────────┬──────────────────────────────────────┘
                            │ HTTPS :443 (WebSocket + REST)
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Nginx Reverse Proxy (Docker)                    │
│          SSL termination · WebSocket upgrade · Static SPA        │
└──────┬──────────────────────────────────────────┬───────────────┘
       │ :8080 REST/WS                             │ :8000 scrcpy
       ▼                                           ▼
┌──────────────────────┐              ┌────────────────────────────┐
│  Titan API (FastAPI) │              │  ws-scrcpy (Docker)        │
│  12 API sections     │              │  H264 screen streaming     │
│  62 functional tabs  │              └────────────────────────────┘
│  systemd titan-v11   │
└──────┬───────────────┘
       │ ADB TCP
       ▼
┌──────────────────────────────────────────────────────────────────┐
│          Cuttlefish Android VMs (KVM, up to 8 instances)         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │  titan-cvd-1 │  │  titan-cvd-2 │  │  titan-cvd-N │           │
│  │  ADB :6520   │  │  ADB :6521   │  │  ADB :652N   │           │
│  │  VNC :6444   │  │  VNC :6445   │  │  VNC :644N   │           │
│  │  Android 14/15│  │  Android 14/15│  │  Android 14/15│           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└──────────────────────────────────────────────────────────────────┘
       │ autossh tunnel
       ▼
┌──────────────────────────────────────────────────────────────────┐
│         Vast.ai GPU Instance (RTX 3060 12GB, Quebec CA)           │
│  VPS:11435 → GPU:11434  (Ollama — titan-agent:7b, minicpm-v:8b)   │
│  VPS:18080 → GPU:8080   (Titan API mirror)                       │
│  VPS:8765  → GPU:8765   (GPU face-swap inference server)         │
└──────────────────────────────────────────────────────────────────┘
```

### Data Flow — Genesis Inject

```
POST /api/genesis/create
  → AndroidProfileForge.forge()         # Generate persona + 10 data categories
  → Save profile JSON to /opt/titan/data/profiles/{id}.json

POST /api/genesis/inject/{device_id}
  → ProfileInjector.inject_full_profile()
     ├── GoogleAccountInjector           # accounts_ce.db + Chrome prefs
     ├── Chrome cookies/history/autofill # SQLite push via ADB
     ├── Contacts + SMS + Call logs      # content provider insert
     ├── Gallery JPEGs (EXIF-tagged)     # adb push (GPS, camera model, DateTimeOriginal)
     ├── WalletProvisioner               # tapandpay.db + COIN.xml + GMS
     └── AppDataForger                   # 30+ app SharedPrefs + DBs
  → Background thread (~280s)
  → Return job_id → poll inject-status
```

---

## 3. Infrastructure

### Hostinger KVM 8

| Spec | Value |
|------|-------|
| CPU | AMD EPYC 9354P (8 vCores dedicated) |
| RAM | 32 GB |
| Storage | 400 GB NVMe |
| Network | 1 Gbps / 32 TB |
| OS | Ubuntu 24.04 LTS (kernel 6.8+) |
| KVM | `/dev/kvm` (hardware virtualization) |
| VPS IP | `72.62.72.48` |
| VPS ID | `1400969` |

**Capacity:** 4–8 simultaneous Cuttlefish VMs (~4 GB RAM each).

**CPU Throttle Warning:** Hostinger throttles CPU by 25%/hr if sustained >180min high load. Each VM should be limited to 4 vCPUs to keep fleet total under 80% sustained.

### Vast.ai GPU (Optional, for AI inference)

| Spec | Value |
|------|-------|
| GPU | RTX 5060 Ti (16 GB VRAM) |
| CPU | 24 vCPU (Ryzen 9 3900X) |
| RAM | 128 GB |
| Location | Quebec, CA |
| Cost | ~$0.11/hr |
| Ollama perf | 41 tok/s warm (GPU mode) |

### Kernel Modules Required on VPS Host

```bash
modprobe vhost_vsock
modprobe vhost_net
modprobe binder_linux devices="binder,hwbinder,vndbinder"
modprobe v4l2loopback devices=4 video_nr=10,11,12,13
```

---

## 4. Service Map

| Service | Type | Port | Description |
|---------|------|------|-------------|
| `titan-v11-api` | systemd | 8080 | FastAPI backend, all API routes |
| `titan-nginx` | Docker | 80/443 | Nginx SSL reverse proxy |
| `ws-scrcpy` | Docker | 8000 | H264 Android screen streaming |
| `cuttlefish` | KVM (launch_cvd) | 6520 | Cuttlefish Android 15 VM |
| `titan-gpu-tunnel` | systemd | — | autossh → Vast.ai GPU tunnels |
| Ollama (CPU) | Docker | 11434 | Local CPU fallback (qwen2.5:7b, hermes3:8b) |
| Ollama (GPU) | Vast.ai | 11435 (tunnel) | titan-agent:7b, titan-specialist:7b, minicpm-v:8b |
| `/health` | FastAPI | 8080 | Health check endpoint (ADB, Ollama, disk, memory) |

**After VPS reboot:**
```bash
modprobe vhost_vsock
cd /opt/titan/cuttlefish/cf && HOME=$PWD ./bin/launch_cvd --daemon --cpus=2 --memory_mb=4096 --gpu_mode=guest_swiftshader --start_webrtc=true --report_anonymous_usage_stats=n
systemctl start titan-api
adb connect 127.0.0.1:6520
```

---

## 5. Migration History

| Version | Backend | Status | Notes |
|---------|---------|--------|-------|
| V9–V10 | Redroid (Android-in-Docker) | Removed | Docker container, no KVM, limited hardware fidelity |
| V11.0–V11.2 | VMOS Cloud | Removed | Cloud Android API, unreliable, asyncCmd 2KB buffer limit |
| **V11.3** | **Cuttlefish (KVM)** | **Active** | Full VM, ARM translation, boot-time identity baking |

### Why Cuttlefish

1. **Identity baking** — `ro.product.*` and `ro.build.*` properties set via `extra_bootconfig_args` at VM launch, identical to real hardware boot flow
2. **ARM translation** — `libndk_translation` native bridge enables ARM-only banking APKs on x86_64 hosts
3. **KVM isolation** — Fully independent kernel per VM, required for `binder_linux` device access
4. **Hardware fidelity** — Virtio devices for display/audio/camera, vsock for host communication
5. **Magisk/root support** — Can push `su` and module paths without container privilege limits

### Legacy Code Removal (V11.3.2)

All VMOS and Redroid code has been removed from active code paths. Legacy modules (`vmos_cloud_bridge.py`, `vmos_cloud_patcher.py`, `vmos_agent_adapter.py`, `vmos_screen_agent.py`) and VMOS scripts have been moved to `_deprecated/` directories for archival reference. The `_run_inject_job_vmos()` and `_trust_score_vmos()` functions have been deleted from `genesis.py`. All active code uses the ADB/Cuttlefish path exclusively.

---

## 6. Key File Paths

| Path | Purpose |
|------|---------|
| `/opt/titan-v11.3-device/` | Codebase root |
| `/opt/titan-v11.3-device/core/` | Python modules |
| `/opt/titan-v11.3-device/server/` | FastAPI server + routers |
| `/opt/titan-v11.3-device/console/` | Web SPA (Alpine.js + Tailwind) |
| `/opt/titan/data/` | Runtime data root (`TITAN_DATA`) |
| `/opt/titan/data/profiles/` | Forged Genesis profile JSONs |
| `/opt/titan/data/devices/` | Device instance state JSONs |
| `/opt/titan/data/trajectories/` | AI agent training trajectories |
| `/opt/titan/data/forge_gallery/` | Gallery JPEG stubs for injection |
| `/opt/titan/data/keybox.xml` | Hardware keybox for Play Integrity Strong |
| `/opt/titan/cuttlefish/` | Cuttlefish VM home directories |
| `/opt/titan/cuttlefish/images/` | Android system images |
| `/opt/android-cuttlefish/bin/` | `launch_cvd`, `stop_cvd`, `cvd` binaries |
| `/data/local.prop` | (on device) Persistent prop overrides |
| `/system/etc/init.d/99-titan-patch.sh` | (on device) Boot persistence script |
| `/data/adb/service.d/99-titan-patch.sh` | (on device) Magisk-style boot script |

---

## 7. Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TITAN_DATA` | `/opt/titan/data` | Runtime data root |
| `TITAN_KEYBOX_PATH` | `/opt/titan/data/keybox.xml` | Hardware keybox path |
| `TITAN_GPU_OLLAMA` | `http://127.0.0.1:11435` | GPU Ollama endpoint |
| `TITAN_CPU_OLLAMA` | `http://127.0.0.1:11434` | CPU Ollama fallback |
| `TITAN_AGENT_MODEL` | `titan-agent:7b` | Default AI agent model |
| `TITAN_AGENT_MAX_STEPS` | `50` | Max steps per agent task |
| `TITAN_TRAINED_ACTION` | `titan-agent:7b` | Fine-tuned action model |
| `TITAN_TRAINED_VISION` | `minicpm-v:8b` | Vision model for screen analysis |
| `CVD_HOME_BASE` | `/opt/titan/cuttlefish` | Cuttlefish VM home base |
| `CVD_BIN_DIR` | `/opt/android-cuttlefish/bin` | CVD binary directory |
| `CVD_IMAGES_DIR` | `/opt/titan/cuttlefish/images` | Android image directory |
| `PYTHONPATH` | (see below) | Module discovery path |

**Required PYTHONPATH:**
```
/opt/titan-v11.3-device/server:/opt/titan-v11.3-device/core:/root/titan-v11-release/core
```

---

## 8. Python Stack

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11+ | Runtime |
| FastAPI | Latest | Async web framework |
| uvicorn | Latest | ASGI server |
| pydantic | v2 | Request/response validation |
| sqlite3 | stdlib | Device database manipulation |
| subprocess | stdlib | ADB command execution |
| aiofiles | Latest | Async file I/O |

**ADB version requirement:** Android Platform Tools 34+ (for `content` provider commands).

---

## 9. Capability Summary

| Capability | Status | Success Rate |
|-----------|--------|-------------|
| Cuttlefish VM creation | ✅ Active | ~100% |
| Device identity spoofing (103+ vectors) | ✅ Active | 95-100% |
| Genesis profile forge (10 categories) | ✅ Active | 100% |
| Full profile injection | ✅ Active | ~97% |
| Google Pay wallet injection | ✅ Active | ~100% file inject |
| Play Integrity Basic | ✅ Active | 100% |
| Play Integrity Device | ✅ Active | ~95% |
| Play Integrity Strong (keybox) | ⚠️ Requires keybox | ~75% |
| Samsung Pay | ❌ Impossible | 0% (Knox hardware) |
| AI device agent (simple tasks) | ✅ Active | ~90% |
| AI device agent (form fill) | ✅ Active | ~75% |
| Deepfake KYC camera | ✅ Active | GPU-dependent |
| H264 screen streaming | ✅ Active | ~100% |
| OSINT / BIN intelligence | ✅ Active | Module-dependent |

---

*See [01-device-manager.md](01-device-manager.md) for device lifecycle details.*
