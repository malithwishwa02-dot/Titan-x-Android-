# Titan V11.3 — Technical Documentation

Complete reference documentation for the Titan V11.3 Advanced Android Cloud Device Platform.

---

## Document Index

| File | Title | Description |
|------|-------|-------------|
| [00-overview.md](00-overview.md) | Platform Overview | Architecture, infrastructure, service map, migration history |
| [01-device-manager.md](01-device-manager.md) | Device Manager | Cuttlefish VM lifecycle, device presets, carrier/location profiles |
| [02-anomaly-patcher.md](02-anomaly-patcher.md) | Anomaly Patcher | All 21 phases, 70+ detection vectors, sterile /proc technique |
| [03-genesis-pipeline.md](03-genesis-pipeline.md) | Genesis Pipeline | Full forge→inject→age→verify flow, SmartForge, circadian weighting |
| [04-profile-injector.md](04-profile-injector.md) | Profile Injector | All 9 injection targets, SELinux/DAC ownership, Google account injection |
| [05-wallet-injection.md](05-wallet-injection.md) | Wallet Injection | Google Pay, keybox, GSF alignment, Samsung Pay limitation, success matrix |
| [06-ai-agent.md](06-ai-agent.md) | AI Device Agent | See-Think-Act loop, model hierarchy, TouchSimulator, SensorSimulator |
| [07-titan-console.md](07-titan-console.md) | Titan Console | Every tab in all 12 API sections — complete UI reference |
| [08-intelligence-tools.md](08-intelligence-tools.md) | Intelligence Tools | OSINT, Cerberus BIN, WebCheckEngine, 3DS strategy |
| [09-network-kyc.md](09-network-kyc.md) | Network & KYC | VPN, deepfake pipeline, V4L2→virtio camera, KYC bypass |
| [10-training-pipeline.md](10-training-pipeline.md) | Training Pipeline | Demo recording, trajectory logging, LoRA fine-tune workflow |
| [11-real-world-success-rates.md](11-real-world-success-rates.md) | Success Rates | Empirical rates: patcher, genesis, wallet, Play Integrity, AI agent |

---

## Quick Start Reference

```bash
# VPS access
sshpass -p 'Chilaw@123@llm' ssh -o StrictHostKeyChecking=no root@72.62.72.48

# API base
https://72.62.72.48/

# Key paths
/opt/titan-v11.3-device/   # Codebase
/opt/titan/data/           # Runtime data (profiles, devices, trajectories)
/opt/titan/data/keybox.xml # Hardware keybox (required for Play Integrity Strong)
```

## Core Modules

```
core/
├── device_manager.py        # Cuttlefish VM management
├── device_presets.py        # 20+ device identities + carriers + locations
├── anomaly_patcher.py       # 21-phase / 70+ vector stealth patcher
├── android_profile_forge.py # Genesis profile data generator
├── profile_injector.py      # ADB-based profile injection
├── wallet_provisioner.py    # Google Pay + Play Store + Chrome + GMS billing
├── wallet_verifier.py       # 13-check wallet state verification
├── google_account_injector.py # Google account database injection
├── device_agent.py          # AI See-Think-Act agent (Ollama-backed)
├── touch_simulator.py       # Human-like ADB touch (Fitts's Law)
├── sensor_simulator.py      # OADEV-based IMU noise model
├── screen_analyzer.py       # Screenshot-to-LLM analysis
├── trajectory_logger.py     # Training data recording
├── smartforge_bridge.py     # AI persona generator bridge
├── aging_report.py          # Comprehensive device aging report
└── scenario_runner.py       # Batch task execution for training
```
