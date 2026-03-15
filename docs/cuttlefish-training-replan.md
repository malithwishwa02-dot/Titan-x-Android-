# Titan V11.3 — Cuttlefish-Only Training Data Replan

## Executive Summary

This document replans the AI model training strategy after the previous Vast.ai training session failed with a **CUDA Out of Memory (OOM)** error on an RTX 3060 (12GB VRAM). The plan focuses exclusively on **Cuttlefish Android 15** as the sole device backend, deprecating VMOS Cloud and Redroid.

**Key decisions:**
1. Use a **larger Vast.ai GPU instance** (24GB+ VRAM) for training
2. After training, export GGUF models and deploy to a **budget Vast.ai instance** for inference
3. Replan training data categories optimized for Cuttlefish's capabilities
4. Destroy the training instance after export to minimize cost

---

## 1. Codebase Analysis

### 1.1 Architecture Overview

| Component | File | Purpose | Device-Specific? |
|---|---|---|---|
| Training Script | `scripts/train_titan_models.py` | LoRA fine-tuning + GGUF export | No |
| Device Agent | `core/device_agent.py` | See→Think→Act LLM loop | No (ADB-based) |
| Scenario Runner | `core/scenario_runner.py` | Batch trajectory generation | No |
| Trajectory Logger | `core/trajectory_logger.py` | Training data collection | No |
| Screen Analyzer | `core/screen_analyzer.py` | Screenshot + UI hierarchy | No (ADB-based) |
| Touch Simulator | `core/touch_simulator.py` | Human-like input | No (ADB-based) |
| Sensor Simulator | `core/sensor_simulator.py` | OADEV IMU noise model | No |
| Device Manager | `core/device_manager.py` | CVD lifecycle (launch/stop) | **Cuttlefish-only** |
| Anomaly Patcher | `core/anomaly_patcher.py` | 103+ vector stealth patching | **Cuttlefish-only** |
| Profile Injector | `core/profile_injector.py` | Chrome/contacts/SMS/wallet | No (ADB push) |
| Wallet Provisioner | `core/wallet_provisioner.py` | Google Pay/Play Store billing | No (ADB push) |

### 1.2 Deprecated Code (Safe to Ignore)

| Path | Description | Status |
|---|---|---|
| `core/_deprecated/vmos_cloud_bridge.py` | VMOS Cloud API adapter | Deprecated |
| `core/_deprecated/vmos_agent_adapter.py` | VMOS touch jitter adapter | Deprecated |
| `core/_deprecated/vmos_cloud_patcher.py` | VMOS setprop-based patcher | Deprecated |
| `core/_deprecated/vmos_screen_agent.py` | VMOS screen agent fallback | Deprecated |
| `docker/_deprecated/` | Redroid Docker configs | Deprecated |

**Conclusion:** The active codebase is already Cuttlefish-native. All VMOS/Redroid code is isolated in `_deprecated/` folders. No code changes needed.

### 1.3 Two Training Models

1. **ACTION model** (text-only LoRA)
   - Base: `Qwen/Qwen2.5-7B-Instruct`
   - Input: screen context + action history → Output: JSON action
   - Training format: SFT chat (system/user/assistant turns)

2. **VISION model** (multimodal LoRA)
   - Base: `Qwen/Qwen2-VL-7B-Instruct`
   - Input: screenshot image + prompt → Output: UI element descriptions
   - Used as fallback when UIAutomator returns 0 elements

---

## 2. Previous Training Session (Failed)

| Parameter | Value |
|---|---|
| Instance | Vast.ai RTX 3060 (12GB VRAM) |
| Model | Qwen/Qwen2.5-7B-Instruct (action model) |
| Quantization | 4-bit QLoRA via bitsandbytes |
| Batch size | 2 |
| Gradient accumulation | 4 |
| Training data | 453 trajectories, 3908 successful steps |
| Error | `torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 1.62 GiB` |

### Root Cause

Qwen2.5-7B with 4-bit quantization + LoRA adapters + optimizer states requires ~10-14GB VRAM. The RTX 3060's 12GB is insufficient with batch_size=2 and max_seq_len=2048. The model weights alone consume ~4GB in 4-bit, but activation memory and optimizer states push total above 12GB.

---

## 3. Vast.ai Instance Strategy

### 3.1 Training Instance (Temporary)

| Requirement | Recommendation |
|---|---|
| **GPU** | RTX 4090 (24GB) or A6000 (48GB) |
| **Min VRAM** | 24GB (comfortable for 7B 4-bit LoRA) |
| **Disk** | 100GB+ (model weights + training data + checkpoints) |
| **Duration** | ~4-6 hours for action model, ~6-8 hours for vision model |
| **Cost estimate** | RTX 4090: ~$0.30-0.50/hr → ~$5-8 total |

**Training parameters (adjusted for 24GB):**
```
--batch-size 4          # was 2
--grad-accum 4          # keep same
--max-seq-len 2048      # keep same
--rank 16               # keep same
--epochs 3              # keep same
```

Effective batch size: 4 × 4 = 16 (was 8). Better gradient estimates → faster convergence.

### 3.2 Inference Instance (Long-running, Budget)

| Requirement | Recommendation |
|---|---|
| **GPU** | RTX 3060 (12GB) or RTX 4060 Ti (16GB) |
| **Min VRAM** | 8GB (Q4_K_M GGUF inference only ~4-5GB) |
| **Disk** | 50GB (GGUF model + Ollama cache) |
| **Services** | Ollama serving titan-agent:7b + titan-screen:7b |
| **Cost estimate** | RTX 3060: ~$0.10-0.15/hr |

**Post-training workflow:**
1. Train on large instance → export LoRA adapter
2. Merge LoRA + export to GGUF (Q4_K_M quantization)
3. Register in Ollama: `ollama create titan-agent:7b -f Modelfile`
4. Transfer GGUF to budget instance via `scp` or Vast.ai template
5. **Destroy training instance** to stop billing

### 3.3 SSH Tunnel Architecture

```
Budget Vast.ai (Ollama, ports 11434/11435)
    ↑ SSH tunnel
Hostinger VPS (72.62.72.48)
    ↓ ADB
Cuttlefish on OVH (51.68.33.34:6520)
   or Oracle (140.245.44.110:6520)
```

---

## 4. Current Training Data Analysis

### 4.1 Existing Data (from previous Vast.ai instance)

| Category | Trajectories | % of Total |
|---|---|---|
| sign_in | 225 | 49.7% |
| aging | 117 | 25.8% |
| install | 54 | 11.9% |
| wallet | 36 | 7.9% |
| browse | 18 | 4.0% |
| **Total** | **453** | **100%** |

- **3908 successful steps** across all trajectories
- **95.4% step success rate**
- Categories are heavily skewed toward sign_in

### 4.2 Task Templates Available (24 total)

| Category | Templates | Count |
|---|---|---|
| sign_in | google_signin, chrome_signin, login_app, paypal_signin, venmo_signin, cashapp_signin, bank_app_signin, instagram_signin, facebook_signin, tiktok_signin, whatsapp_setup, telegram_signin, snapchat_signin, twitter_signin, crypto_signin, amazon_signin, create_account | 17 |
| install | install_app, install_batch, play_purchase, app_update | 4 |
| wallet | wallet_verify, wallet_add_card_ui, play_store_add_payment | 3 |
| aging | warmup_device, warmup_youtube, warmup_maps, warmup_social, gmail_compose, settings_tweak, handle_permissions | 7 |
| browse | browse_url, search_google | 2 |

### 4.3 Scenario Presets (8 total)

`play_store_installs`, `warmup_browse`, `warmup_youtube`, `full_aging`, `sign_in_all`, `wallet_setup`, `social_warmup`, `maps_explore`, `email_activity`

---

## 5. Cuttlefish-Only Training Data Replan

### 5.1 Cuttlefish Advantages over VMOS/Redroid

| Feature | Cuttlefish | VMOS Cloud | Redroid |
|---|---|---|---|
| Android version | 15 (AOSP latest) | 12-13 | 14 |
| UIAutomator | ✅ Full support | ⚠️ Often returns 0 elements | ✅ Works |
| ADB root | ✅ Always | ❌ No root | ✅ Via container |
| sqlite3 binary | ✅ Available | ❌ Not available | ✅ Available |
| KVM acceleration | ✅ Near-native | ❌ Cloud API | ❌ Container |
| Google Play Services | ✅ Full GMS | ⚠️ Limited | ⚠️ OpenGApps |
| Sensor injection | ✅ Via /dev paths | ⚠️ asyncCmd only | ❌ No sensors |
| Multi-instance | ✅ Up to 8 per host | ❌ 1 per pad | ✅ Multiple containers |

**Key implication:** Since UIAutomator works reliably on Cuttlefish, the VISION model is less critical. The ACTION model is the priority — it drives the See→Think→Act loop using structured UI element data.

### 5.2 Revised Category Distribution

**Target: 800+ trajectories, 6000+ successful steps**

| Category | Target Trajs | % | Priority | Rationale |
|---|---|---|---|---|
| **sign_in** | 240 | 30% | HIGH | Core monetization flow. Keep as largest but reduce % share. |
| **aging** | 160 | 20% | HIGH | Device warmup drives trust scores. Critical for stealth. |
| **install** | 120 | 15% | HIGH | Play Store navigation is fundamental. Currently underrepresented. |
| **browse** | 120 | 15% | MEDIUM | Chrome/web is most common Android activity. Currently very weak (4%). |
| **wallet** | 80 | 10% | MEDIUM | Payment flows. Needs more variety (card add, verify, Play billing). |
| **navigation** | 40 | 5% | LOW | Settings, notification handling, permission dialogs. New category. |
| **multi_app** | 40 | 5% | LOW | Cross-app workflows (share, copy-paste). New category. |
| **Total** | **800** | **100%** | | |

### 5.3 New Trajectories Needed

| Category | Have | Need | Delta | How to Generate |
|---|---|---|---|---|
| sign_in | 225 | 240 | +15 | Run `sign_in_all` preset on OVH Cuttlefish |
| aging | 117 | 160 | +43 | Run `full_aging`, `warmup_youtube`, `warmup_browse` |
| install | 54 | 120 | +66 | Run `play_store_installs` with expanded app list |
| browse | 18 | 120 | +102 | Run `warmup_browse` + new search queries |
| wallet | 36 | 80 | +44 | Run `wallet_setup` + manual card add flows |
| navigation | 0 | 40 | +40 | New templates: settings_tweak, handle_permissions |
| multi_app | 0 | 40 | +40 | New templates needed (share content, copy-paste) |
| **Total** | **453** | **800** | **+350** | |

### 5.4 New Task Templates to Add

```python
# ── NAVIGATION / SYSTEM ──────────────────────────────────────────
"notification_interact": {
    "prompt": "Pull down the notification shade. Read any notifications visible. "
              "Tap on the first notification to open it. Then go back to home screen.",
    "params": [],
    "category": "navigation",
},
"settings_deep": {
    "prompt": "Open Settings. Navigate to About Phone. Scroll down and note the "
              "build number and Android version. Go back. Navigate to Display settings "
              "and toggle Dark Mode. Go back to home screen.",
    "params": [],
    "category": "navigation",
},
"quick_settings": {
    "prompt": "Swipe down from top to open Quick Settings. Toggle Wi-Fi off then on. "
              "Toggle Bluetooth. Check battery percentage. Close quick settings.",
    "params": [],
    "category": "navigation",
},

# ── MULTI-APP WORKFLOWS ──────────────────────────────────────────
"share_photo": {
    "prompt": "Open Gallery or Files app. Select a photo. Tap Share button. "
              "Choose Gmail from share menu. Compose email to {to_email} with "
              "subject 'Check this out'. Send the email.",
    "params": ["to_email"],
    "category": "multi_app",
},
"copy_paste_cross_app": {
    "prompt": "Open Chrome. Go to google.com and search for '{query}'. "
              "Long-press to select and copy the first search result title text. "
              "Open Gmail and compose new email. Paste the copied text into the body. "
              "Discard the draft.",
    "params": ["query"],
    "category": "multi_app",
},
```

### 5.5 Trajectory Generation Plan

**Phase 1: Generate missing data on OVH Cuttlefish** (2-3 hours)
1. Start Cuttlefish on OVH: `launch_cvd` with 4GB RAM, 4 CPUs
2. Run scenario presets via API:
   - `POST /api/training/scenarios/run` with preset `play_store_installs` → +10 install trajs
   - `POST /api/training/scenarios/run` with preset `warmup_browse` → +8 browse trajs
   - `POST /api/training/scenarios/run` with preset `warmup_youtube` → +5 aging trajs
   - Custom batch for new browse queries → +40 browse trajs
   - Custom batch for install (expanded app list) → +30 install trajs
3. Each scenario uses DeviceAgent with hermes3:8b (via GPU tunnel)

**Phase 2: Generate on Oracle Cuttlefish** (parallel, 2-3 hours)
1. Same approach but targeting 140.245.44.110
2. Focus on wallet and sign_in scenarios
3. Different persona data for variety

**Phase 3: Transfer all trajectories to training instance**
```bash
# From OVH
scp -r -i /root/.ssh/id_ed25519 root@51.68.33.34:/opt/titan/data/trajectories/ ./trajs-ovh/

# From Oracle
scp -r -i /root/.ssh/oracle_cvd.pem ubuntu@140.245.44.110:~/titan/data/trajectories/ ./trajs-oracle/

# Merge and upload to Vast.ai training instance
rsync -avz ./trajs-*/ root@ssh.vast.ai:/opt/titan/data/trajectories/
```

---

## 6. Training Execution Plan

### 6.1 Pre-Training Checklist

- [ ] Rent RTX 4090 or A6000 on Vast.ai
- [ ] Upload training data (800+ trajectories)
- [ ] Install dependencies: `pip install unsloth trl transformers datasets peft bitsandbytes`
- [ ] Verify VRAM: `nvidia-smi` should show 24GB+
- [ ] Copy training script: `scripts/train_titan_models.py`
- [ ] Copy core module: `core/trajectory_logger.py` (needed for data export)

### 6.2 Training Commands

```bash
# Step 1: Check data stats
python train_titan_models.py --task stats --data /opt/titan/data/trajectories

# Step 2: Train ACTION model (priority — this is what the agent uses)
python train_titan_models.py --task action \
    --data /opt/titan/data/trajectories \
    --output /opt/titan/models/titan-agent-7b-lora \
    --epochs 3 --lr 2e-4 --rank 16 --alpha 32 \
    --batch-size 4 --grad-accum 4 --max-seq-len 2048

# Step 3: Train VISION model (optional, lower priority)
python train_titan_models.py --task vision \
    --data /opt/titan/data/trajectories \
    --output /opt/titan/models/titan-screen-7b-lora \
    --epochs 3 --lr 2e-4 --rank 16 --alpha 32 \
    --batch-size 2 --grad-accum 8 --max-seq-len 2048

# Step 4: Export ACTION model to GGUF
python train_titan_models.py --task export \
    --model /opt/titan/models/titan-agent-7b-lora \
    --output /opt/titan/models/titan-agent-7b-gguf \
    --quantization q4_k_m

# Step 5: Export VISION model to GGUF (if trained)
python train_titan_models.py --task export \
    --model /opt/titan/models/titan-screen-7b-lora \
    --output /opt/titan/models/titan-screen-7b-gguf \
    --quantization q4_k_m
```

### 6.3 OOM Prevention (24GB GPU)

| Setting | 12GB (failed) | 24GB (planned) | Why |
|---|---|---|---|
| batch_size | 2 | 4 | 2x headroom |
| grad_accum | 4 | 4 | Same effective batch |
| max_seq_len | 2048 | 2048 | Keep same |
| quantization | 4-bit | 4-bit | Keep same |
| gradient_checkpointing | unsloth | unsloth | Saves VRAM |
| fp16 | True | True | Keep same |

**Estimated VRAM usage on 24GB:**
- Model weights (4-bit): ~4GB
- LoRA adapters: ~0.5GB
- Optimizer states: ~2GB
- Activations (batch=4, seq=2048): ~6-8GB
- **Total: ~12-15GB** → 9-12GB headroom

### 6.4 Post-Training Deployment

```bash
# On training instance — register in Ollama to verify
ollama create titan-agent:7b -f /opt/titan/models/titan-agent-7b-gguf/Modelfile
ollama run titan-agent:7b "What action should I take on a login screen?"

# Transfer GGUF files to budget instance
scp /opt/titan/models/titan-agent-7b-gguf/*.gguf budget-instance:/opt/titan/models/
scp /opt/titan/models/titan-agent-7b-gguf/Modelfile budget-instance:/opt/titan/models/

# On budget instance — register and serve
ollama create titan-agent:7b -f /opt/titan/models/Modelfile
ollama serve  # port 11434

# Destroy training instance via Vast.ai API
curl -X DELETE https://console.vast.ai/api/v0/instances/{instance_id}/ \
    -H "Authorization: Bearer $VAST_API_KEY"
```

---

## 7. Cost Estimate

| Phase | Instance | Duration | Cost/hr | Total |
|---|---|---|---|---|
| Training (action) | RTX 4090 24GB | ~4-5 hrs | $0.40 | ~$2.00 |
| Training (vision) | RTX 4090 24GB | ~6-8 hrs | $0.40 | ~$3.20 |
| Export + transfer | RTX 4090 24GB | ~1 hr | $0.40 | ~$0.40 |
| Inference (ongoing) | RTX 3060 12GB | ongoing | $0.12 | ~$2.88/day |
| **Total training** | | **~12-14 hrs** | | **~$5.60** |

---

## 8. Timeline

| Day | Task |
|---|---|
| **Day 1** | Generate additional trajectories on OVH + Oracle Cuttlefish devices |
| **Day 1** | Transfer existing + new trajectories, verify 800+ total |
| **Day 2** | Rent RTX 4090, upload data, train ACTION model (~5 hrs) |
| **Day 2** | Train VISION model (~7 hrs, can overlap or skip initially) |
| **Day 3** | Export GGUF, test on training instance, transfer to budget instance |
| **Day 3** | Register in Ollama, update GPU tunnel on Hostinger VPS |
| **Day 3** | Destroy training instance, verify inference pipeline end-to-end |

---

## 9. Success Criteria

- [ ] ACTION model trained without OOM on 24GB GPU
- [ ] GGUF exported and registered in Ollama as `titan-agent:7b`
- [ ] Budget inference instance serving at <500ms/query latency
- [ ] DeviceAgent auto-detects and uses trained model (via `_detect_best_model`)
- [ ] End-to-end test: run a scenario on OVH Cuttlefish using trained model
- [ ] Training instance destroyed, only budget instance running
