# 02 — Anomaly Patcher

The `AnomalyPatcher` class (`core/anomaly_patcher.py`) is the stealth core of Titan V11.3. It executes a 21-phase pipeline covering 70+ detection vectors to make a Cuttlefish Android VM indistinguishable from a real physical device — defeating emulator checks, RASP systems, Play Integrity attestation, and behavioral analytics engines.

---

## Table of Contents

1. [Overview](#1-overview)
2. [How Detection Works (Adversary Model)](#2-how-detection-works-adversary-model)
3. [All 21 Phases — Complete Reference](#3-all-21-phases--complete-reference)
4. [Sterile /proc Technique](#4-sterile-proc-technique)
5. [Reboot Persistence](#5-reboot-persistence)
6. [Audit Function](#6-audit-function)
7. [PatchReport Structure](#7-patchreport-structure)
8. [Real-World Success Rates](#8-real-world-success-rates)
9. [Common Failure Modes](#9-common-failure-modes)
10. [API Endpoints](#10-api-endpoints)

---

## 1. Overview

```python
patcher = AnomalyPatcher(adb_target="127.0.0.1:6520")
report  = patcher.full_patch(
    preset_name="samsung_s25_ultra",
    carrier_name="tmobile_us",
    location_name="nyc",
    lockdown=False,  # True = also conceal ADB
)
# report.score   = 97
# report.passed  = 68
# report.total   = 70
```

The patcher communicates exclusively via `adb shell` subprocess calls. All property setting uses batched `setprop` calls (multiple props per ADB round-trip) to minimize execution time. Full patch runs in **45–90 seconds** depending on device responsiveness.

### Key Identifiers

```python
class AnomalyPatcher:
    def __init__(self, adb_target: str = "127.0.0.1:6520", container: str = ""):
        self.target    = adb_target
        self._results  = []   # List[PatchResult]
```

### Generator Functions

| Function | Purpose |
|----------|---------|
| `generate_imei(tac_prefix)` | Luhn-valid 15-digit IMEI from TAC prefix |
| `generate_iccid(carrier)` | ITU E.118 ICCID: `89{cc}{issuer}{account}{luhn}` |
| `generate_serial(brand)` | Brand-consistent serial: Samsung=`R{10}`, Google=`{12hex}` |
| `generate_android_id()` | 16-hex random android_id |
| `generate_mac(oui)` | Realistic MAC: `{OUI}:{xx}:{xx}:{xx}` |
| `generate_drm_id()` | SHA-256 of 32 random bytes, first 32 chars |
| `generate_gaid()` | UUID4 Google Advertising ID |

---

## 2. How Detection Works (Adversary Model)

Modern fraud and RASP systems detect virtual environments through four signal categories:

### Category A — System Property Fingerprinting
Apps call `getprop ro.product.model`, `ro.build.fingerprint`, `ro.kernel.qemu` etc. A value of `generic`, `sdk_phone_x86`, `Cuttlefish` or `Android SDK` instantly flags emulation.

### Category B — /proc File System Analysis
`/proc/cmdline` contains `androidboot.hardware=cutf_cvm` on Cuttlefish. `/proc/1/cgroup` contains `cuttlefish` container path. `/proc/mounts` reveals bind-mounts if `/dev/null` was used naively. These files cannot be overwritten (kernel-managed virtual filesystem) — they must be **masked via bind-mount**.

### Category C — Runtime Behaviour
- Battery always 100% on AC power → virtual
- eth0 interface instead of wlan0 → virtual
- No Bluetooth paired devices → likely fresh VM
- Sensor data is exactly 0 or completely static → fake
- Boot count is 1 and uptime is under 60s → freshly booted VM

### Category D — Hardware Attestation
Play Integrity API requests a cryptographic attestation from the TrustZone TEE. Without a valid hardware keybox, the VM can only achieve Software Integrity (Basic), not Strong. Google Pay NFC requires Device or Strong integrity.

---

## 3. All 21 Phases — Complete Reference

### Phase 1 — Device Identity (`_patch_device_identity`)

**Vectors patched: ~15**

All `ro.*` properties are baked into Cuttlefish via `extra_bootconfig_args` at launch time (identical to how real devices work). The patcher records them as passed and additionally sets runtime values:

| Property | Example Value | Method |
|----------|--------------|--------|
| `ro.product.model` | `SM-S938U` | Baked at boot |
| `ro.product.brand` | `samsung` | Baked at boot |
| `ro.product.manufacturer` | `samsung` | Baked at boot |
| `ro.product.name` | `p3qxxx` | Baked at boot |
| `ro.product.device` | `p3q` | Baked at boot |
| `ro.build.fingerprint` | `samsung/p3qxxx/p3q:14/UP1A...` | Baked at boot |
| `ro.build.display.id` | `UP1A.231005.007` | Baked at boot |
| `ro.build.version.release` | `14` | Baked at boot |
| `ro.build.version.sdk` | `34` | Baked at boot |
| `ro.build.version.security_patch` | `2026-01-01` | Baked at boot |
| `ro.build.type` | `user` | Baked at boot |
| `ro.build.tags` | `release-keys` | Baked at boot |
| `ro.hardware` | `qcom` | Baked at boot |
| `ro.serialno` | `R5CR12B4KTR` | `setprop` (random per run) |
| `ro.boot.serialno` | `R5CR12B4KTR` | `setprop` (same as above) |

**Why boot-baking:** Apps using `SystemProperties.get()` via reflection will see baked props. Apps using `Build.*` Java API also read these from init. Runtime `setprop` alone is insufficient for all vectors.

---

### Phase 2 — SIM & Telephony (`_patch_telephony`)

**Vectors patched: ~10**

```python
imei  = generate_imei(preset.tac_prefix)     # e.g. "355819081234565"
iccid = generate_iccid(carrier)               # e.g. "89131026012345678901"
```

| Property | Value | Description |
|----------|-------|-------------|
| `gsm.sim.operator.alpha` | `T-Mobile` | Carrier display name |
| `gsm.sim.operator.numeric` | `310260` | MCC+MNC |
| `gsm.sim.operator.iso-country` | `us` | ISO country |
| `gsm.sim.state` | `READY` | SIM card inserted and unlocked |
| `gsm.network.type` | `LTE` | Active network technology |
| `persist.sys.cloud.modem.imei` | `355819...` | IMEI (Luhn valid) |
| `persist.sys.cloud.modem.iccid` | `891310...` | ICCID (ITU E.118) |

**IMEI Generation:** TAC prefix comes from `DevicePreset.tac_prefix` (brand-specific). The patcher appends 6 random digits then applies the Luhn checksum algorithm to produce a valid 15-digit IMEI. Samsung prefixes: `35`, `35281`, `35338`; Google Pixel: `35293`, `35294`.

---

### Phase 3 — Anti-Emulator (`_patch_anti_emulator`)

**Vectors patched: ~12 — most complex phase**

#### A. Cuttlefish Property Masking
```
ro.kernel.qemu=0           # Baked — was "1" on stock Cuttlefish
ro.hardware.virtual=0      # Baked
ro.boot.qemu=0             # Baked
init.svc.goldfish-logcat=  # Runtime clear
init.svc.goldfish-setup=   # Runtime clear
```

#### B. Sterile /proc/cmdline Bind-Mount

Stock Cuttlefish `/proc/cmdline` contains:
```
androidboot.hardware=cutf_cvm androidboot.slot_suffix=_a ... cuttlefish ...
```

**The technique:** Read the file, strip all tokens containing `cuttlefish`, `vsoc`, `virtio`, `cutf_cvm`, `goldfish`. Write the clean version to `/data/titan/proc_cmdline_clean`. Bind-mount the clean file over `/proc/cmdline`:
```bash
mount -o bind /data/titan/proc_cmdline_clean /proc/cmdline
```

This is **not** using `/dev/null` (detectable via `/proc/mounts`) but a real file with legitimate-looking contents.

#### C. Sterile /proc/1/cgroup

Same technique for `/proc/1/cgroup` — strips Cuttlefish/vsoc/system.slice references, writes `0::/` as fallback.

#### D. /proc/mounts Scrubbing

After bind-mounting, `/proc/mounts` and `/proc/self/mountinfo` would show the bind-mounts. The patcher also masks these:
```bash
cat /proc/mounts | grep -v '/proc/cmdline' | grep -v '/proc/1/cgroup' \
  > /data/titan/mounts_clean
mount -o bind /data/titan/mounts_clean /proc/mounts
```

#### E. Virtio PCI Vendor ID Masking

Virtio devices have PCI vendor ID `0x1af4` (Red Hat). The patcher scans `/sys/devices` and overwrites any matching vendor files with `0x0000`.

#### F. Network Interface Rename

Real Android phones never have `eth0` — only `wlan0`. Cuttlefish creates `eth0` by default:
```bash
ip link set eth0 down
ip link set eth0 name wlan0
ip link set wlan0 up
```

---

### Phase 4 — Build Verification (`_patch_build_verification`)

**Vectors patched: ~6**

| Property | Required Value | Significance |
|----------|---------------|-------------|
| `ro.boot.verifiedbootstate` | `green` | Locked, unmodified boot |
| `ro.boot.flash.locked` | `1` | Bootloader locked |
| `ro.secure` | `1` | Production secure mode |
| `ro.debuggable` | `0` | Non-debug build |
| `ro.build.type` | `user` | Production (not `userdebug`) |
| `ro.build.tags` | `release-keys` | Signed with OEM release key |

These are checked by Google Play Protect, banking apps, and DRM systems.

---

### Phase 5 — RASP Evasion (`_patch_rasp`)

**Vectors patched: ~8**

RASP (Runtime Application Self-Protection) checks look for root access, instrumentation frameworks, and developer mode.

```bash
# Hide su binary (chmod 000 = no execute, no read)
for su_path in /system/bin/su /system/xbin/su /sbin/su /su/bin/su; do
    chmod 000 $su_path 2>/dev/null
done

# Block Frida instrumentation ports
iptables -A INPUT -p tcp --dport 27042 -j DROP
iptables -A INPUT -p tcp --dport 27043 -j DROP

# Disable developer options
settings put global development_settings_enabled 0
settings put secure mock_location 0

# Disable ADB (appears consumer-configured)
settings put global adb_enabled 0
```

---

### Phase 6 — GPU Identity (`_patch_gpu`)

**Vectors patched: ~5**

Apps accessing OpenGL ES renderer/vendor strings via `GLES20.glGetString()` can identify emulation:

| Device | GPU Renderer | GPU Vendor |
|--------|-------------|-----------|
| Samsung S25 Ultra | `Adreno (TM) 830` | `Qualcomm` |
| Samsung S24 | `Adreno (TM) 750` | `Qualcomm` |
| Pixel 9 Pro | `Mali-G715` | `ARM` |
| OnePlus 13 | `Adreno (TM) 830` | `Qualcomm` |
| Xiaomi 15 | `Adreno (TM) 830` | `Qualcomm` |

Set via:
```bash
setprop persist.titan.gpu.renderer "Adreno (TM) 830"
setprop persist.titan.gpu.vendor "Qualcomm"
```

---

### Phase 7 — Battery Simulation (`_patch_battery`)

**Vectors patched: ~4**

Virtual devices are permanently at 100% on AC power. Real devices fluctuate:

```bash
dumpsys battery set level {random 62-87}   # Realistic charge level
dumpsys battery set status 3               # Discharging (3 = not charging)
dumpsys battery set ac 0                   # AC charger disconnected
dumpsys battery set usb 0                  # USB charger disconnected
```

---

### Phase 8 — Location & Locale (`_patch_location`)

**Vectors patched: ~5**

```bash
# GPS coordinates (NYC)
settings put secure location_providers_allowed gps,network
setprop persist.titan.gps.lat "40.7128"
setprop persist.titan.gps.lon "-74.0060"

# Timezone
setprop persist.sys.timezone "America/New_York"

# Locale
setprop persist.sys.locale "en-US"
setprop persist.sys.language "en"
setprop persist.sys.country "US"
```

---

### Phase 9 — Media History (`_patch_media_history`)

**Vectors patched: ~4**

Fresh devices have zero activity history — a strong fraud signal.

```bash
# Boot count (realistic: 40-200 for a "used" device)
settings put global boot_count {random 40-200}

# Screen-on time (accumulated usage)
settings put global screen_on_time_ms {random 500h-2000h in ms}

# Last boot timestamp — backdated to look established
setprop persist.titan.last_boot_time {now - random 1-14 days}
```

---

### Phase 10 — Network Identity (`_patch_network`)

**Vectors patched: ~5**

```bash
# WiFi SSID (consistent with location)
settings put global wifi_ssid "NETGEAR72-5G"
settings put global wifi_bssid "A4:50:46:xx:xx:xx"

# Assigned WiFi MAC (from preset OUI)
setprop wifi.interface wlan0
ip link set wlan0 address A4:50:46:AB:CD:EF
```

---

### Phase 11 — GMS Patching (`_patch_gms`)

**Vectors patched: ~6**

```bash
setprop ro.com.google.clientidbase    "android-samsung"
setprop ro.com.google.gmsversion      "230112045"
setprop ro.com.google.services.version "230112045"
setprop persist.google.play.clientid  "android-samsung-us"
```

Also forces Play Store to report the correct GMS core version matching the device preset.

---

### Phase 11b — Keybox Injection (`_patch_keybox`)

**Vectors patched: 3 (critical for Google Pay)**

The `keybox.xml` is a hardware attestation credential that proves the device has a genuine hardware TEE (Trusted Execution Environment). Without it, Play Integrity can only pass "Basic" or "Device" but not "Strong" — and Google Pay NFC requires at minimum Device Integrity.

```python
keybox_path = os.environ.get("TITAN_KEYBOX_PATH", "/opt/titan/data/keybox.xml")
```

**Device paths pushed to:**
```
/data/adb/tricky_store/keybox.xml           # TrickyStore module
/data/adb/modules/playintegrityfix/keybox.xml  # PlayIntegrityFork module
/data/adb/modules/tricky_store/keybox.xml   # TrickyStore alt path
```

**Permissions:** `chmod 600` — only root readable.

**Status props set:**
```bash
setprop persist.titan.keybox.loaded "1"       # or "0" if file not found
setprop persist.titan.keybox.hash   "{sha256_first16}"
setprop persist.titan.keybox.paths  "3"       # number of successful pushes
```

**Setup requirement:** Place your hardware keybox at `/opt/titan/data/keybox.xml` **before** running the patcher. Keyboxes obtained from compromised OEM firmware signing chains. A revoked keybox will still load but Play Integrity will reject it server-side.

---

### Phase 11c — GSF Fingerprint Alignment (`_patch_gsf_alignment`)

**Vectors patched: 3**

Google Services Framework (GSF) maintains its own device identity separate from system properties. If the GSF `deviceId` doesn't match the Android `android_id`, Google's backend detects identity incoherence during checkin/sync — causing Play Integrity failures and wallet provisioning rejections.

**Files written:**

`/data/data/com.google.android.gms/shared_prefs/CheckinService.xml`:
```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="deviceId">a1b2c3d4e5f6a7b8</string>
    <long name="lastCheckinTimeMs" value="1710384000000" />
    <string name="digest">1-{random_40hex}</string>
</map>
```

`/data/data/com.google.android.gms/shared_prefs/GservicesSettings.xml`:
```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="android_id">a1b2c3d4e5f6a7b8</string>
    <string name="digest">1-{random_40hex}</string>
    <long name="lastSyncTimeMs" value="1710384000000" />
</map>
```

Both files get `chown {gms_uid}:{gms_uid}`, `chmod 660`, and `restorecon -R` for correct SELinux labeling.

---

### Phase 12 — Sensor Data (`_patch_sensors`)

**Vectors patched: ~7**

MEMS sensors on real devices produce characteristic noise patterns. A static-zero sensor reading is trivially detected.

**OADEV noise model** (Allan Deviation-based, real MEMS datasheets):

| Brand | Accel Noise Floor | Gyro Bias | Magnetometer |
|-------|------------------|-----------|--------------|
| Samsung (Bosch BMI323) | 0.18 mg/√Hz | 0.008 °/s/√Hz | ±1.5 µT |
| Google (InvenSense ICM-42688) | 0.16 mg/√Hz | 0.007 °/s/√Hz | ±1.0 µT |
| Qualcomm default | 0.20 mg/√Hz | 0.010 °/s/√Hz | ±2.0 µT |

**Sensor props set:**
```bash
setprop persist.titan.sensor.accelerometer "1"
setprop persist.titan.sensor.gyroscope     "1"
setprop persist.titan.sensor.proximity     "1"
setprop persist.titan.sensor.light         "1"
setprop persist.titan.sensor.magnetometer  "1"
setprop persist.titan.sensor.barometer     "1"   # Samsung only
setprop persist.titan.sensor.step_counter  "1"
```

`SensorSimulator.start_background_noise()` then injects continuous low-amplitude noise via ADB into the sensor virtual device files.

---

### Phase 13 — Bluetooth Paired Devices (`_patch_bluetooth`)

**Vectors patched: 2**

A device with zero Bluetooth history looks unused. The patcher creates 2–4 realistic paired device entries in `/data/misc/bluedroid/bt_config.conf`:

```
AA:BB:CC:DD:EE:FF Galaxy Buds2 Pro
11:22:33:44:55:66 JBL Flip 6
77:88:99:AA:BB:CC Car Audio
```

Random MACs, selection from: Galaxy Buds2 Pro, JBL Flip 6, Car Audio, Pixel Buds A-Series, AirPods Pro, Sony WH-1000XM5, Bose QC45.

---

### Phase 14 — /proc/cpuinfo & /proc/meminfo Spoofing (`_patch_proc_info`)

**Vectors patched: 3**

```python
soc_map = {
    "qcom":    ("Qualcomm Technologies, Inc SM8650", "Snapdragon 8 Gen 3", 8),
    "tensor":  ("Google Tensor G4", "Tensor G4", 8),
    "exynos":  ("Samsung Exynos 1480", "Exynos 1480", 8),
    "mt6991":  ("MediaTek Dimensity 9400", "MT6991", 8),
}
```

Props:
```bash
setprop persist.titan.soc.name  "Qualcomm Technologies, Inc SM8650"
setprop persist.titan.soc.cores "8"
setprop ro.board.platform       "qcom"
setprop persist.titan.ram_gb    "12"   # 12GB for Ultra/Pro, 8GB for others
```

---

### Phase 15 — Camera Hardware Identity (`_patch_camera_info`)

**Vectors patched: 4**

Camera sensor model strings are checked by KYC and identity verification apps:

| Brand | Main Camera | Ultrawide | Front |
|-------|------------|-----------|-------|
| Samsung | ISOCELL HP2 200MP | ISOCELL HM3 108MP | IMX374 12MP |
| Google | Samsung GNK 50MP | Sony IMX858 48MP | Samsung 3J1 10.5MP |
| Default | Sony IMX890 50MP | Sony IMX858 48MP | Sony IMX615 32MP |

---

### Phase 16 — NFC & Storage Identity (`_patch_nfc_storage`)

**Vectors patched: 3**

```bash
# NFC presence (for tap-and-pay)
setprop ro.hardware.nfc          "nfc"
setprop persist.titan.nfc.enabled "1"

# Storage size (256GB for Ultra/Pro, 128GB for others)
setprop persist.titan.storage_gb "256"
```

---

### Phase 17 — WiFi Scan Results (`_patch_wifi_scan`)

**Vectors patched: 3**

Locale-aware SSID pools — ISP-specific router names by region:

| Region | Typical SSIDs |
|--------|--------------|
| US | NETGEAR72-5G, Xfinity-Home, ATT-FIBER, Spectrum-5G, Google-Fiber |
| GB | BT-Hub6-5G, Sky-WiFi-Home, Virgin-Media-5G, EE-Home-5G |
| DE | FRITZ!Box-7590, Telekom-5G, Vodafone-Home-5G, 1und1-WLAN |
| AU | Telstra-Wi-Fi, Optus-Home-5G, TPG-5G |
| IN | JioFiber-5G, Airtel-5G-Home, BSNL-Fiber |

The patcher writes a fake `WifiConfigStore.xml` with 5–10 area SSIDs and their signal strengths, consistent with the device's location profile.

---

### Phase 18 — SELinux & Accessibility (`_patch_selinux_accessibility`)

**Vectors patched: 2**

```bash
# Ensure SELinux is enforcing (not permissive — a root indicator)
setenforce 1

# Accessibility settings (production device defaults)
settings put secure accessibility_enabled 0
settings put secure enabled_accessibility_services ""
```

---

### Phase 21 — Reboot Persistence (`_persist_patches`)

**Vectors patched: 2**

Cuttlefish VMs lose runtime `setprop` values on reboot. The patcher writes two persistence scripts:

**`/system/etc/init.d/99-titan-patch.sh`** (requires remount-rw):
```bash
#!/system/bin/sh
# Titan V11.3 — Boot persistence patch (21 phases)
setprop gsm.sim.state READY
setprop gsm.network.type LTE
# ... all runtime props
mount -o bind /data/titan/proc_cmdline_clean /proc/cmdline
mount -o bind /data/titan/cgroup_clean /proc/1/cgroup
ip link set eth0 down; ip link set eth0 name wlan0; ip link set wlan0 up
# ... RASP, battery, etc.
```

**`/data/adb/service.d/99-titan-patch.sh`** (Magisk-style, survives OTA):
Same content, second location for redundancy.

Both scripts are `chmod 755`.

---

### Optional — ADB Concealment (`_patch_adb_concealment`, lockdown=True)

When `lockdown=True` is passed to `full_patch()`:

```bash
setprop service.adb.tcp.port 41337   # Move ADB to non-standard port
settings put global adb_enabled 0    # Disable via settings DB
```

Used for production devices that should appear consumer-configured.

---

## 4. Sterile /proc Technique

### Why `/dev/null` Bind-Mounts Fail

Early implementations masked `/proc/cmdline` by bind-mounting `/dev/null`:
```bash
mount --bind /dev/null /proc/cmdline   # DETECTABLE
```

This is trivially detected by examining `/proc/self/mountinfo`:
```
/dev/null /proc/cmdline  ← shows source is /dev/null
```

### Titan's Approach: Sterile Real File

```python
def _create_sterile_proc_file(self, source, dest, strip_patterns, fallback):
    # 1. Read actual /proc/cmdline from device
    ok, content = self._sh(f"cat {source}")
    
    # 2. Strip all tokens containing suspicious patterns
    for pattern in strip_patterns:
        parts = [p for p in content.split() if pattern.lower() not in p.lower()]
        content = " ".join(parts)
    
    # 3. Write clean version to /data/titan/
    self._sh(f"echo '{content}' > {dest}")
    
    # 4. Bind-mount the clean REAL file (source is a legitimate path)
    self._sh(f"mount -o bind {dest} {source}")
```

`/proc/self/mountinfo` now shows:
```
/data/titan/proc_cmdline_clean /proc/cmdline  ← legitimate-looking path
```

This evades all known `/dev/null` bind-mount detectors.

---

## 5. Reboot Persistence

**Three-layer persistence:**

| Layer | Path | Mechanism |
|-------|------|-----------|
| Runtime props | `/data/local.prop` | Android reads at boot before init |
| Init script | `/system/etc/init.d/99-titan-patch.sh` | Executed by Android init.d framework |
| Magisk service | `/data/adb/service.d/99-titan-patch.sh` | Executed by Magisk's service.d runner |

**local.prop** is written with all `persist.*` props that must survive reboot without root execution at boot time. Init.d and service.d handle dynamic operations (mount, ip, setprop) that require root execution.

---

## 6. Audit Function

`patcher.audit()` performs a **non-destructive read-only check** of the current device state:

```python
checks = patcher.audit()
# Returns:
{
    "passed": 18,
    "total": 20,
    "score": 90,
    "checks": {
        "qemu_hidden":           True,
        "virtual_hidden":        True,
        "debuggable_off":        True,
        "secure_on":             True,
        "build_type_user":       True,
        "release_keys":          True,
        "proc_cmdline_sterile":  True,
        "proc_cgroup_sterile":   True,
        "verified_boot_green":   True,
        "bootloader_locked":     True,
        "sim_ready":             True,
        "carrier_set":           True,
        "network_lte":           True,
        "fingerprint_set":       True,
        "model_set":             True,
        "serial_set":            True,
        "adb_disabled":          False,   # ADB still enabled
        "keybox_loaded":         True,
        "gsf_aligned":           True,
    }
}
```

**Note:** `adb_disabled=False` is expected unless `lockdown=True` was used — ADB must remain enabled for the platform to function.

---

## 7. PatchReport Structure

```python
@dataclass
class PatchReport:
    preset: str          # "samsung_s25_ultra"
    carrier: str         # "tmobile_us"
    location: str        # "nyc"
    total: int           # Total patch attempts (typically 68-72)
    passed: int          # Successful patches
    failed: int          # Failed patches
    score: int           # 0-100 percentage
    results: List[Dict]  # Per-result: {"name": str, "ok": bool, "detail": str}
```

**Example result entry:**
```json
{
    "name": "keybox_loaded",
    "ok": true,
    "detail": "hash=a1b2c3d4e5f6a7b8, paths=3/3"
}
```

---

## 8. Real-World Success Rates

| Phase | Typical Success | Failure Cause |
|-------|----------------|--------------|
| Phase 1 (Identity) | 100% | Props baked at boot |
| Phase 2 (Telephony) | 100% | setprop always works |
| Phase 3 (Anti-emu) | 92-98% | SELinux may block bind-mount on some images |
| Phase 4 (Build verify) | 100% | Baked at boot |
| Phase 5 (RASP) | 100% | chmod + iptables reliable |
| Phase 6 (GPU) | 100% | setprop |
| Phase 7 (Battery) | 99% | dumpsys occasionally flaky |
| Phase 11b (Keybox) | 100% if file exists, 0% if missing | Keybox file at TITAN_KEYBOX_PATH |
| Phase 11c (GSF) | 95% | GMS package UID mismatch occasionally |
| Phase 12 (Sensors) | 85% | SensorSimulator init can time out |
| Phase 21 (Persist) | 90% | /system remount-rw may fail on some images |

**Overall score distribution:**
- With valid keybox.xml: **95–100/100**
- Without keybox: **82–92/100**
- Play Integrity Basic: **100%** (trivial with patched props)
- Play Integrity Device: **~95%** (correct fingerprint + boot baking)
- Play Integrity Strong: **~75%** (requires valid non-revoked keybox)

---

## 9. Common Failure Modes

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `keybox_loaded=false` | No keybox.xml at TITAN_KEYBOX_PATH | Place keybox.xml at `/opt/titan/data/keybox.xml` |
| `/proc/cmdline` not sterile | SELinux blocks bind-mount in enforcing mode | Boot with `androidboot.selinux=permissive` or apply policy |
| `gsf_aligned=false` | GMS not installed or UID mismatch | Ensure GMS image; check `/data/data/com.google.android.gms` exists |
| Sensor noise init fails | SensorSimulator can't write to sensor device | Requires `/dev/sensor` write permission; check SELinux policy |
| Persist script not executing | `/system` remount failed (read-only ext4) | Use `/data/adb/service.d/` path only (doesn't need remount) |
| Battery shows 100% AC | `dumpsys battery` command rejected | Check `STATUS_UNKNOWN` — some images require `adb root` |

---

## 10. API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/stealth/{device_id}/patch` | Run full_patch (preset, carrier, location) |
| `GET` | `/api/stealth/{device_id}/audit` | Non-destructive state audit (20 checks) |
| `GET` | `/api/stealth/{device_id}/wallet-verify` | Deep wallet state verification (13 checks) |
| `GET` | `/api/stealth/presets` | List all available device presets |
| `GET` | `/api/stealth/carriers` | List all carrier profiles |
| `GET` | `/api/stealth/locations` | List all location profiles |

### Patch Request Body

```json
{
  "preset": "samsung_s25_ultra",
  "carrier": "tmobile_us",
  "location": "nyc"
}
```

### Patch Response

```json
{
  "preset": "samsung_s25_ultra",
  "carrier": "tmobile_us",
  "location": "nyc",
  "total": 70,
  "passed": 68,
  "failed": 2,
  "score": 97,
  "results": [
    {"name": "prop:ro.product.model", "ok": true, "detail": "SM-S938U"},
    {"name": "keybox_loaded", "ok": true, "detail": "hash=a1b2c3d4, paths=3/3"},
    ...
  ]
}
```

---

*See [03-genesis-pipeline.md](03-genesis-pipeline.md) for the behavioral data injection that complements stealth patching.*
