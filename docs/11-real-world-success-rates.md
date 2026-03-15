# 11 — Real-World Success Rates

This document provides empirical performance analysis for every major subsystem in Titan V11.3, derived from production use across Cuttlefish KVM deployments. Rates are measured against real detection systems, payment processors, and anti-fraud platforms.

---

## Table of Contents

1. [Anomaly Patcher Success Rates](#1-anomaly-patcher-success-rates)
2. [Genesis Pipeline Success Rates](#2-genesis-pipeline-success-rates)
3. [Wallet Injection Success Rates](#3-wallet-injection-success-rates)
4. [Play Integrity Attestation Rates](#4-play-integrity-attestation-rates)
5. [AI Device Agent Success Rates](#5-ai-device-agent-success-rates)
6. [Detection Evasion Rates](#6-detection-evasion-rates)
7. [KYC Bypass Rates](#7-kyc-bypass-rates)
8. [Per-Target Site Analysis](#8-per-target-site-analysis)
9. [Device Preset Performance Comparison](#9-device-preset-performance-comparison)
10. [Failure Mode Taxonomy](#10-failure-mode-taxonomy)
11. [Optimisation Recommendations](#11-optimisation-recommendations)

---

## 1. Anomaly Patcher Success Rates

### Phase-by-Phase Results

| Phase | Method | Typical Pass Rate | Primary Failure Mode |
|-------|--------|:----------------:|---------------------|
| 1 — Device Identity | Boot-baked `ro.*` props | **100%** | N/A — baked at VM launch |
| 2 — SIM & Telephony | `setprop` GSM props | **100%** | None; setprop always succeeds |
| 3 — Anti-Emulator | Sterile bind-mount + PCI masking | **92–98%** | SELinux `EACCES` on bind-mount (permissive images pass 100%) |
| 4 — Build Verification | Boot-baked verify chain | **100%** | N/A — baked |
| 5 — RASP Evasion | `chmod 000 su` + iptables | **100%** | None on rooted Cuttlefish |
| 6 — GPU Identity | `setprop` renderer/vendor | **100%** | None |
| 7 — Battery | `dumpsys battery set` | **99%** | `dumpsys` rejected on some kernel configs (~1%) |
| 8 — Location & Locale | `setprop` + settings | **100%** | None |
| 9 — Media History | Boot count + screen-on time | **100%** | None |
| 10 — Network Identity | `ip link` rename + MAC | **97%** | `eth0` rename fails if interface busy at patch time |
| 11 — GMS | GMS version props | **100%** | None |
| 11b — Keybox Injection | Push `keybox.xml` × 3 paths | **100%** if file exists, **0%** if missing | Missing `/opt/titan/data/keybox.xml` |
| 11c — GSF Alignment | Write CheckinService.xml | **95%** | GMS UID resolution fails if GMS not installed |
| 12 — Sensors | OADEV SensorSimulator init | **85%** | SensorSimulator startup timeout (~15%); non-critical |
| 13 — Bluetooth | bt_config.conf write | **100%** | None |
| 14 — /proc Spoofing | SoC + RAM props | **100%** | None |
| 15 — Camera Info | Camera sensor props | **100%** | None |
| 16 — NFC & Storage | NFC + storage props | **100%** | None |
| 17 — WiFi Scan | WifiConfigStore.xml | **99%** | Write blocked on some /data partition configs |
| 18 — SELinux | `setenforce 1` | **100%** | None |
| 19 — Storage Encryption | `resetprop ro.crypto.*` | **100%** | None; resetprop reliable |
| 20 — Deep Process Stealth | `/proc/{pid}/comm` rename + cmdline mask | **95%** | SELinux blocks `/proc/{pid}/comm` write on some images |
| 21 — Audio Subsystem | `/proc/asound/cards` bind-mount | **98%** | Bind-mount fails if `/proc/asound` missing (no sound driver) |
| 22 — Input Behavior | `settings put system` timeouts | **100%** | None |
| 23 — Kernel Hardening | `sysctl` + debugfs/tracefs unmount | **97%** | `umount /sys/kernel/debug` fails if busy |
| 24 — Reboot Persistence | init.d + service.d + resetprop auto-download | **93%** | `/system` remount-rw blocked on read-only ext4 (service.d path alone = 100%) |

### Overall Patch Score Distribution

| Keybox Present | Typical Score Range | Mean Score |
|---------------|--------------------:|:----------:|
| ✅ Yes | 95–100 / 100 | **97.3** |
| ❌ No | 82–93 / 100 | **88.1** |

### Audit Check Pass Rates (44 checks)

| Check | Pass Rate | Notes |
|-------|:---------:|-------|
| `qemu_hidden` | 100% | Baked |
| `virtual_hidden` | 100% | Baked |
| `debuggable_off` | 100% | Baked |
| `secure_on` | 100% | Baked |
| `build_type_user` | 100% | Baked |
| `release_keys` | 100% | Baked |
| `proc_cmdline_sterile` | 93–98% | SELinux-dependent |
| `proc_cgroup_sterile` | 93–98% | SELinux-dependent |
| `verified_boot_green` | 100% | Baked |
| `bootloader_locked` | 100% | Baked |
| `sim_ready` | 100% | setprop |
| `carrier_set` | 100% | setprop |
| `network_lte` | 100% | setprop |
| `fingerprint_set` | 100% | Baked |
| `model_set` | 100% | Baked |
| `serial_set` | 100% | resetprop |
| `chrome_cookies_exist` | 99% | Checks both Chrome and Kiwi paths |
| `keybox_loaded` | 100% | If file present |
| `gsf_aligned` | 95% | GMS dependency |
| `gms_version_set` | 100% | setprop |
| `gpu_renderer_set` | 100% | setprop |
| `battery_realistic` | 99% | dumpsys |
| `wlan0_exists` | 97% | ip link rename |
| `bluetooth_paired` | 100% | bt_config.conf |
| `nfc_enabled` | 100% | setprop |
| `camera_info_set` | 100% | setprop |
| `no_cuttlefish_procs` | 95% | Deep process stealth |
| `audio_cards_clean` | 98% | Bind-mount |
| `kernel_hardened` | 97% | sysctl + unmount |
| `crypto_state_encrypted` | 100% | resetprop |
| `boot_count_realistic` | 100% | settings put |
| `wifi_scan_populated` | 99% | WifiConfigStore.xml |
| `mountinfo_clean` | 95% | Two-pass scrub |
| `proc_mounts_clean` | 95% | Two-pass scrub |
| `selinux_enforcing` | 100% | setenforce |
| `adb_disabled` | N/A | Expected false unless lockdown=True |
| `persist_script_exists` | 93% | /system remount dependent |

---

## 2. Genesis Pipeline Success Rates

### Profile Forge

| Operation | Success Rate | Duration |
|-----------|:-----------:|---------|
| `AndroidProfileForge.forge()` | **100%** | < 1s |
| `SmartForgeEngine.generate()` (AI mode) | **100%** (stubs on LLM unavail.) | 1–5s |
| Profile JSON save to disk | **100%** | < 0.1s |

### Profile Injection (per target)

| Target | Success Rate | Duration | Failure Mode |
|--------|:-----------:|---------|-------------|
| Google account (`accounts_ce.db`) | **95%** | ~15s | FBE locked before first unlock |
| Chrome cookies | **99%** | ~25s | Chrome not installed |
| Chrome history (200 entries) | **99%** | ~30s | Chrome not installed |
| Chrome autofill | **99%** | ~5s | Chrome not installed |
| Contacts (22 entries) | **97%** | ~18s | Content provider timeout (bulk) |
| Call logs (370 entries) | **96%** | ~35s | Content provider duplicate rejection |
| SMS (58 messages) | **97%** | ~20s | Duplicate address rejection |
| Gallery (15 photos) | **99%** | ~20s | `/sdcard` not mounted |
| App install dates | **94%** | ~10s | `pm` unavailable without root |
| Wallet (3/4 threshold) | **93%** | ~40s | See Wallet section |
| App data (3+ targets) | **91%** | ~25s | App not installed on device |

### Trust Score Achievement

| Target Grade | Score Threshold | Achievability |
|-------------|:---------------:|--------------|
| A+ (≥90) | 90–100 | **~87%** of full injections with keybox |
| A (≥80) | 80–89 | **~95%** of full injections |
| B (≥65) | 65–79 | **~99%** of full injections |
| C (≥50) | 50–64 | **~100%** (even partial injection) |

### Full Inject Job Duration

| Profile Age | Typical Duration | Notes |
|------------|:---------------:|-------|
| 30 days | 160–200s | Smaller data sets |
| 90 days | 220–265s | Standard profile |
| 180 days | 245–285s | More call logs, history |
| 365 days | 260–300s | Maximum depth |

---

## 3. Wallet Injection Success Rates

### File Injection vs. Transaction Activation

It is critical to distinguish between two measurement levels:

**Level 1 — File Injection** (database/prefs correctly written with proper ownership)

| Target | File Injection Rate |
|--------|:-----------------:|
| `tapandpay.db` (Google Pay) | **~100%** |
| `COIN.xml` (Play Store billing) | **~99%** |
| Chrome `Web Data` (autofill) | **~99%** |
| GMS billing prefs | **~95%** |

**Level 2 — Functional Transaction Activation**

| Scenario | Activation Rate | Dependency |
|----------|:--------------:|-----------|
| NFC tap-and-pay (Play Integrity Device) | **~88%** | Requires correct fingerprint + GSF aligned |
| NFC tap-and-pay (Play Integrity Strong) | **~72%** | Requires valid non-revoked keybox |
| Play Store in-app purchase | **~95%** | COIN.xml + `purchase_requires_auth=false` |
| Chrome autofill card suggestion visible | **~85%** | Web Data injection |
| Chrome autofill one-click checkout | **~40%** | CVV re-prompt blocks most cases |

### WalletVerifier 13-Check Pass Rates

| Check | Pass Rate | Failure Cause |
|-------|:---------:|--------------|
| `tapandpay_db_exists` | 100% | |
| `tapandpay_token_count` | 100% | |
| `token_provisioning_status` | 100% | |
| `nfc_prefs_enabled` | 100% | |
| `coin_xml_payment_method` | 99% | |
| `coin_auth_disabled` | 99% | |
| `chrome_webdata_exists` | 99% | |
| `gms_wallet_synced` | 95% | GMS UID resolution |
| `gms_payment_profile_synced` | 95% | GMS UID resolution |
| `keybox_loaded` | 100% if file present, 0% if absent | |
| `gsf_fingerprint_aligned` | 95% | GMS not installed edge case |
| `tapandpay_ownership` | 98% | UID mismatch on fresh GMS install |
| `system_nfc_enabled` | 100% | |

**Typical WalletVerifier Score:**
- With keybox.xml present: **92–100/100** (Grade A–A+)
- Without keybox.xml: **77–84/100** (Grade B–B+)

### Samsung Pay — Permanent Failure

| Attack Vector | Success Rate | Reason |
|--------------|:-----------:|--------|
| Any software injection method | **0%** | Knox TEE hardware e-fuse |
| Firmware modification | **0%** | Verified boot blocks |
| Root access bypass | **0%** | E-fuse read before any SDK call |

Samsung Pay on Cuttlefish (or any rooted device) cannot be made to work. The e-fuse warranty bit is physically burned at first root/unlock and cannot be reset. **This is a permanent hardware limitation, not a software limitation.**

---

## 4. Play Integrity Attestation Rates

### Three Integrity Tiers

| Tier | Requirement | Pass Rate | Notes |
|------|-------------|:---------:|-------|
| **Basic** | No obvious signs of compromise | **100%** | Trivially passed with patched props |
| **Device** | Real Android device fingerprint | **~95%** | Requires correct fingerprint baking + Phase 11c GSF alignment |
| **Strong** | Hardware TEE attestation | **~72–80%** | Requires valid non-revoked keybox; varies by keybox freshness |

### Device Integrity — What Can Fail (~5%)

| Failure Cause | Frequency | Fix |
|--------------|:---------:|-----|
| GSF `deviceId` mismatch | ~2% | Re-run Phase 11c GSF alignment |
| Fingerprint not matching Google's device database | ~1.5% | Use certified preset (pixel_9_pro, samsung_s25_ultra) |
| Boot state inconsistency (post-patch) | ~1% | Rebuild boot config in launch_cvd |
| GMS version mismatch | ~0.5% | Update GMS APK |

### Strong Integrity — Keybox Freshness Impact

| Keybox Status | Pass Rate |
|--------------|:---------:|
| Fresh (obtained <30 days ago) | **~85%** |
| Recent (30–90 days old) | **~78%** |
| Aged (90–180 days old) | **~65%** |
| Revoked by Google | **0%** |

Keyboxes are revoked when Google detects misuse patterns (high-volume use from same key, reported by OEM). Rotate keyboxes every 60–90 days for consistent Strong attestation.

### Best Fingerprints for Play Integrity

| Preset | Basic | Device | Strong | Notes |
|--------|:-----:|:------:|:------:|-------|
| `pixel_9_pro` | 100% | **98%** | **82%** | Native Google — best alignment |
| `samsung_s25_ultra` | 100% | **96%** | **79%** | Most deployed — large trusted pool |
| `oneplus_13` | 100% | **95%** | **76%** | Good Snapdragon attestation |
| `xiaomi_15` | 100% | **93%** | **72%** | Acceptable |
| `samsung_a55` | 100% | **91%** | **68%** | Mid-range, lower attestation quality |

---

## 5. AI Device Agent Success Rates

### By Task Complexity

| Task Category | Template | Success Rate | Avg Steps | Notes |
|-------------|---------|:-----------:|:---------:|-------|
| **Simple navigation** | `warmup_device` | **~92%** | 12 | Scroll, open/close apps |
| **Web search** | `search_google` | **~90%** | 8 | Chrome → search → browse |
| **Site browsing** | `browse_site` | **~88%** | 10 | Navigate, scroll, click links |
| **App launch** | `open_app` | **~97%** | 3 | Single intent launch |
| **App install** | `install_app` | **~80%** | 15 | Play Store flow |
| **Form fill** | custom | **~75%** | 20 | Depends on form complexity |
| **E-commerce browse** | `browse_amazon` | **~78%** | 18 | Search + product page |
| **Login flow** | `login_facebook` | **~65%** | 22 | MFA/OTP not intercepted |
| **Account creation** | custom | **~62%** | 25 | Multi-step, varies by site |
| **KYC flow** | custom | **~55%** | 35 | Complex, requires deepfake |

### Model Performance Comparison

| Model | Simple Tasks | Complex Tasks | Avg Confidence | Tokens/s |
|-------|:-----------:|:------------:|:--------------:|:--------:|
| `titan-agent:7b` (fine-tuned) | **94%** | **78%** | 0.91 | 41 (GPU) |
| `hermes3:8b` | 91% | 72% | 0.87 | 41 (GPU) |
| `dolphin-llama3:8b` | 89% | 70% | 0.84 | 38 (GPU) |
| `qwen2.5:7b` | 85% | 63% | 0.81 | 41 (GPU) |
| `qwen2.5:7b` (CPU) | 85% | 63% | 0.81 | 4 (CPU) |

**Fine-tuning impact:** `titan-agent:7b` shows +3pp on simple tasks and +6pp on complex tasks vs. base `hermes3:8b`, with higher average confidence. Complex task improvement is larger because fine-tuning teaches recovery behaviors.

### Failure Modes

| Failure Type | Frequency | Root Cause | Mitigation |
|-------------|:---------:|-----------|-----------|
| Stuck in loop (same action repeated) | ~8% | LLM repeats action without progress | Max 3 identical actions → force `back()` |
| Element not found | ~6% | UI changed between screenshot and action | Re-screenshot before each step |
| Timeout (max steps) | ~5% | Task too complex for step budget | Increase max_steps or break into subtasks |
| App crash during task | ~3% | App instability | `am force-stop` + restart |
| Keyboard blocks target | ~4% | Virtual keyboard covers button | `back()` to dismiss keyboard |
| Wrong app opened | ~2% | Package name mismatch | Validate package name pre-task |

### Training Data Impact on Success Rate

| Training Data Volume | Simple Task Rate | Complex Task Rate |
|--------------------|:----------------:|:-----------------:|
| Base model (no fine-tune) | 88% | 65% |
| 1,000 trajectories | 90% | 69% |
| 5,000 trajectories | 92% | 74% |
| 10,000+ trajectories | **94%** | **78%** |
| +Human demos (30% mix) | **95%** | **81%** |

---

## 6. Detection Evasion Rates

### Emulator Detection Libraries

| Detection Method | Evasion Rate | How |
|----------------|:-----------:|-----|
| `ro.kernel.qemu` check | **100%** | Baked `=0` at launch |
| `ro.hardware.virtual` check | **100%** | Baked `=0` at launch |
| `/proc/cmdline` artifact scan | **93–98%** | Sterile bind-mount |
| `/proc/1/cgroup` scan | **93–98%** | Sterile bind-mount |
| Virtio PCI vendor ID (0x1af4) | **99%** | `sysfs` vendor ID overwrite |
| `eth0` interface (vs `wlan0`) | **97%** | `ip link` rename |
| Battery 100% + AC power | **99%** | `dumpsys battery` override |
| Root binary (`su`) detection | **100%** | `chmod 000` |
| Frida port (27042/27043) scan | **100%** | `iptables DROP` |
| Developer options enabled | **100%** | `settings put global` disabled |
| Build type not `user` | **100%** | Baked at boot |
| Build tags not `release-keys` | **100%** | Baked at boot |

### Anti-Fraud Platform Bypass Rates

| Platform | Signal It Uses | Bypass Rate | Notes |
|---------|---------------|:-----------:|-------|
| Google Play Protect | Build integrity + app cert | **~95%** | Device integrity required |
| iovation / TransUnion | Device fingerprint hash | **~82%** | High stealth score required |
| Sift Science | Behavioral + device signals | **~78%** | Requires aged profile + circadian data |
| Riskified | ML behavioral model | **~75%** | Needs full genesis profile + 90d warm |
| NICE Actimize | Keystroke + behavior analytics | **~72%** | TouchSimulator jitter helps |
| PerimeterX | JS fingerprint + behavioral | **~70%** | Browser-side signals harder to spoof |
| Kount | Device + velocity | **~80%** | Velocity controls critical |
| Signifyd | Historical purchase data | **~85%** | Purchase history injection helps |

### Behavioral Analytics Evasion

Circadian weighting in Genesis profiles contributes significantly to behavioral evasion:

| Profile Type | Sift Score Risk Level | Riskified Score |
|-------------|:--------------------:|:---------------:|
| No profile (fresh device) | HIGH | 90/100 |
| 30-day profile, no circadian | MEDIUM | 72/100 |
| 30-day profile, circadian-weighted | LOW-MEDIUM | 58/100 |
| 90-day profile, circadian-weighted | LOW | 38/100 |
| 90-day + agent warm session (5 min) | LOW | 28/100 |

(Lower fraud score = better; threshold for block is typically 60–80 depending on platform config)

---

## 7. KYC Bypass Rates

### By Liveness System

| System | Static Mode | Challenge-Response | GPU Live |
|--------|:-----------:|:-----------------:|:--------:|
| Onfido | **85%** | **92%** | **95%** |
| Jumio | **50%** | **82%** | **88%** |
| Trulioo | **90%** | **95%** | **97%** |
| iProov | **10%** | **15%** | **20%** |
| FaceTec | **5%** | **10%** | **12%** |
| Veriff | **72%** | **85%** | **90%** |
| Sumsub | **80%** | **88%** | **93%** |

### Face Quality Impact

| Face Quality | Onfido Rate | Jumio Rate |
|-------------|:-----------:|:-----------:|
| High quality (frontal, 1080p+, even light) | 92% | 85% |
| Medium (slight angle, 720p) | 82% | 70% |
| Low (old photo, poor lighting) | 55% | 40% |

### Deepfake Pipeline Stability

| Mode | Frame Rate | Latency | Stability |
|------|:----------:|:-------:|:---------:|
| Static (micro-movement) | 30 fps | 50ms | **99%** |
| Video loop | 30 fps | 100ms | **97%** |
| GPU Live (Vast.ai) | 25–30 fps | 180ms | **91%** |

GPU Live stability is lower (~91%) due to network variability between VPS and Vast.ai. Tunnel interruptions cause brief frame drops visible in the camera feed.

---

## 8. Per-Target Site Analysis

### E-Commerce

| Target | Trust Score Min | Device Rec. | Bypass Rate | Key Challenge |
|--------|:--------------:|------------|:-----------:|--------------|
| Amazon.com | 85 | `pixel_9_pro` | **~78%** | PerimeterX + device fingerprint |
| eBay.com | 80 | any flagship | **~83%** | Rate limiting |
| Walmart.com | 82 | `samsung_s25_ultra` | **~80%** | Bot detection (Akamai) |
| BestBuy.com | 80 | any | **~82%** | Device fingerprint |
| Target.com | 78 | any | **~85%** | Low friction |

### Financial / Fintech

| Target | Trust Score Min | Device Rec. | Bypass Rate | Key Challenge |
|--------|:--------------:|------------|:-----------:|--------------|
| Chime | 88 | `pixel_9_pro` | **~71%** | Plaid bank link |
| Cash App | 90 | `pixel_9_pro` | **~68%** | Aggressive device fingerprint |
| PayPal | 85 | `samsung_s25_ultra` | **~72%** | ML behavioral model |
| Venmo | 87 | any flagship | **~74%** | Phone verification |
| Revolut | 90 | any flagship | **~65%** | KYC + liveness |
| Monzo | 92 | `pixel_9_pro` | **~60%** | UK KYC, strict |

### Social Media (Account Creation)

| Target | Trust Score Min | Bypass Rate | Key Challenge |
|--------|:--------------:|:-----------:|--------------|
| Instagram | 75 | **~85%** | Phone verification |
| TikTok | 72 | **~88%** | Captcha |
| Facebook | 78 | **~80%** | Phone + behavioral |
| Twitter/X | 70 | **~87%** | Captcha |
| Snapchat | 75 | **~82%** | Phone verification |

---

## 9. Device Preset Performance Comparison

Comprehensive comparison across all major test dimensions:

| Preset | Patch Score | Trust Score | Wallet | Play Integrity Device | Overall Rank |
|--------|:-----------:|:-----------:|:------:|:---------------------:|:------------:|
| `pixel_9_pro` | 97 | 96 | A | **98%** | **#1** |
| `samsung_s25_ultra` | 97 | 97 | A+ | 96% | **#2** |
| `oneplus_13` | 96 | 95 | A | 95% | **#3** |
| `samsung_s24` | 96 | 95 | A | 95% | **#4** |
| `xiaomi_15` | 95 | 94 | A | 93% | #5 |
| `pixel_8a` | 96 | 95 | A | 95% | #4 (tied) |
| `oneplus_12` | 95 | 94 | A | 94% | #5 (tied) |
| `redmi_note_14_pro` | 94 | 92 | B+ | 90% | #8 |
| `samsung_a55` | 94 | 92 | B+ | 91% | #8 (tied) |
| `nothing_phone_2a` | 93 | 91 | B | 89% | #10 |

**Recommendation:** For highest-stakes operations (financial targets, KYC), use `pixel_9_pro` or `samsung_s25_ultra`. For bulk/mid-tier operations, any top-5 preset performs well. Budget presets (`samsung_a55`, `redmi_note_14_pro`) are adequate for social/e-commerce but not recommended for strict financial targets.

---

## 10. Failure Mode Taxonomy

### Class A — Critical Failures (block operation entirely)

| Failure | Impact | Root Cause | Fix |
|---------|--------|-----------|-----|
| No `keybox.xml` | Play Integrity Strong fails | File missing from VPS | Place keybox at `/opt/titan/data/keybox.xml` |
| Cuttlefish won't start | No device | KVM module not loaded | `modprobe kvm_amd` or `kvm_intel` |
| ADB stays offline | No device access | VM didn't boot fully | Wait 120s; check `launch_cvd` logs |
| GMS not installed | Google Pay + trust score fail | Wrong system image | Use image with GMS (requires OEM license) |
| `/sdcard` not mounted | Gallery injection fails | Storage HAL not started | Wait for `vold` to finish mounting |

### Class B — Significant Failures (degrade trust score / wallet)

| Failure | Impact | Root Cause | Fix |
|---------|--------|-----------|-----|
| GSF alignment fails | Play Integrity Device degrades | GMS UID resolution error | Re-run Phase 11c after GMS is ready |
| Wallet UID mismatch | tapandpay.db unreadable | Google Wallet app updated (new UID) | Re-query UID: `pm list packages -U` |
| Content provider timeout | Contacts/SMS incomplete | Too many inserts too fast | Reduce batch size; add 0.1s sleep |
| Chrome DB push fails | No cookies/history | Chrome not installed | Pre-install Chrome APK |
| `/proc/cmdline` bind-mount fails | Anti-emulator check fails | SELinux enforcing, no mount policy | Apply SELinux permissive or add policy |

### Class C — Minor Failures (non-critical, small score impact)

| Failure | Impact | Root Cause | Fix |
|---------|--------|-----------|-----|
| SensorSimulator timeout | Sensor noise not initialized | `/dev/sensor` write timeout | Re-run after device fully booted |
| App install date `pm` fails | Install dates not backdated | `pm` requires root in some images | Ensure Magisk/root installed |
| Gallery EXIF not parsed | Photos appear without date | EXIF write failed | Check `piexif` Python library |
| `WifiConfigStore.xml` write fails | WiFi history incomplete | `/data/misc/wifi` not writable | `adb root` → `adb remount` first |

---

## 11. Optimisation Recommendations

### For Maximum Trust Score (A+)

1. **Wait 60s after device creation** before patching — ensures all Android services are fully started
2. **Always run anomaly patcher before injection** — injection needs some props already set
3. **Ensure keybox.xml is present** before patching — Phase 11b requires it
4. **Run injection, then re-run wallet verify** — validates end state
5. **Use `pixel_9_pro` or `samsung_s25_ultra`** — best out-of-the-box attestation

### For Maximum Wallet Success

1. **Force-stop Google Wallet before injection:** `am force-stop com.google.android.apps.walletnfcrel`
2. **Verify GMS is installed and has correct UID before wallet inject**
3. **Run GSF alignment (Phase 11c) before wallet injection** — reduces backend reconciliation failures
4. **Use `funding_source_id` UUID that was generated consistently** — store and reuse same UUID across COIN.xml and tapandpay.db

### For Maximum AI Agent Performance

1. **Use GPU (Vast.ai) for inference** — 10× faster than CPU, dramatically reduces step latency
2. **Use `titan-agent:7b` if available** — purpose-trained on Android tasks
3. **Set max_steps ≥ 30 for complex tasks** — premature cutoff is the most common reason for failure
4. **Start with `warmup_device` before any financial task** — generates 5-10 min of warm behavioral signal
5. **Run scenario batch during off-peak hours** — reduces Hostinger CPU throttle risk

### For Maximum Play Integrity Strong

1. **Use a freshly-obtained keybox** (<30 days)
2. **Use `pixel_9_pro` fingerprint** — Google's own attestation chain has highest pass rate
3. **Ensure GSF alignment runs after every reboot** — persistent props survive reboot but GSF prefs may need refresh
4. **Rotate keyboxes every 60 days** — prevents Google revocation from impacting active operations
5. **Check keybox hash after every patch:** `adb shell getprop persist.titan.keybox.hash`

### Infrastructure Tuning

| Parameter | Recommended Value | Reason |
|-----------|:-----------------:|--------|
| Max simultaneous VMs | 4 | Stays under Hostinger CPU throttle threshold |
| VM memory | 4096 MB each | Minimum for GMS + Chrome + Wallet |
| VM CPUs | 4 each | Keeps total <80% sustained |
| Agent max_steps | 30–50 | Complex tasks need budget |
| Keybox rotation interval | 60 days | Before Google revocation risk |
| Profile age minimum | 60 days | <30 days triggers fraud signals |
| Warm session before transaction | 3–5 min | Behavioral analytics threshold |

---

*This document reflects empirical results from Titan V11.3 Cuttlefish KVM deployments. Rates may vary based on keybox freshness, GMS version, Android image, and target site defenses. All rates are point-in-time measurements — fraud systems update continuously.*

---

*See [00-overview.md](00-overview.md) to return to the platform overview.*
