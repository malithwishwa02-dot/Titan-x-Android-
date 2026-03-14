# 01 — Device Manager

The `DeviceManager` class (`core/device_manager.py`) creates, manages, patches, and destroys Cuttlefish Android virtual machines. It is the authoritative registry for all active device instances on the node.

---

## Table of Contents

1. [Overview](#1-overview)
2. [DeviceInstance Dataclass](#2-deviceinstance-dataclass)
3. [CreateDeviceRequest](#3-createdevicerequest)
4. [Lifecycle: Create → Patch → Use → Destroy](#4-lifecycle-create--patch--use--destroy)
5. [Cuttlefish Launch Parameters](#5-cuttlefish-launch-parameters)
6. [ADB Port Allocation](#6-adb-port-allocation)
7. [Device Presets](#7-device-presets)
8. [Carrier Profiles](#8-carrier-profiles)
9. [Location Profiles](#9-location-profiles)
10. [API Endpoints](#10-api-endpoints)

---

## 1. Overview

```python
# core/device_manager.py
TITAN_DATA       = Path("/opt/titan/data")
DEVICES_DIR      = TITAN_DATA / "devices"
CVD_HOME_BASE    = Path("/opt/titan/cuttlefish")
CVD_BIN_DIR      = Path("/opt/android-cuttlefish/bin")
CVD_IMAGES_DIR   = Path("/opt/titan/cuttlefish/images")
BASE_ADB_PORT    = 6520
BASE_VNC_PORT    = 6444
MAX_DEVICES      = 8
INSTANCE_PREFIX  = "titan-cvd-"
```

Each device is backed by:
- A Cuttlefish VM instance launched via `launch_cvd`
- A persistent JSON state file at `DEVICES_DIR/{device_id}.json`
- A dedicated `cvd_home` directory under `CVD_HOME_BASE`

---

## 2. DeviceInstance Dataclass

```python
@dataclass
class DeviceInstance:
    id: str                    # e.g. "dev-a3f12b"
    container: str             # legacy compat (maps to CVD instance name)
    adb_port: int              # e.g. 6520
    adb_target: str            # e.g. "127.0.0.1:6520"
    config: Dict[str, Any]     # launch config (model, carrier, preset, etc.)
    state: str                 # created | running | patched | ready | destroyed
    created_at: str            # ISO timestamp
    error: str                 # last error message if any
    patch_result: Dict         # last AnomalyPatcher.full_patch() report
    installed_apps: List[str]  # list of installed APK package names
    stealth_score: int         # 0–100 from last patch report
    device_type: str           # "cuttlefish" (KVM-based Android VM)
    instance_num: int          # Cuttlefish --base_instance_num (1-based)
    cvd_home: str              # e.g. "/opt/titan/cuttlefish/dev-a3f12b"
    vnc_port: int              # e.g. 6444
```

**State transitions:**

```
created → running (launch_cvd completes)
        → patched (AnomalyPatcher.full_patch() completes)
        → ready   (profile injected, trust score computed)
        → destroyed (stop_cvd + cleanup)
```

---

## 3. CreateDeviceRequest

```python
@dataclass
class CreateDeviceRequest:
    model: str           = "samsung_s25_ultra"  # device preset key
    country: str         = "US"
    carrier: str         = "tmobile_us"
    phone_number: str    = ""                   # custom phone, or auto-generated
    android_version: str = "14"
    screen_width: int    = 1080
    screen_height: int   = 2400
    dpi: int             = 420
    memory_mb: int       = 4096
    cpus: int            = 4
```

### Default by Model

| Model | Width | Height | DPI | RAM | Notes |
|-------|-------|--------|-----|-----|-------|
| samsung_s25_ultra | 1080 | 2400 | 420 | 4096 | Flagship, highest trust |
| pixel_9_pro | 1080 | 2400 | 420 | 4096 | Best Play Integrity |
| oneplus_13 | 1080 | 2376 | 450 | 4096 | Good for US/EU |
| xiaomi_15 | 1080 | 2400 | 440 | 4096 | Asia-market focus |
| samsung_a55 | 1080 | 2340 | 390 | 3072 | Mid-range budget |

---

## 4. Lifecycle: Create → Patch → Use → Destroy

### Create

```python
mgr = DeviceManager()
dev = await mgr.create_device(CreateDeviceRequest(
    model="samsung_s25_ultra",
    country="US",
    carrier="tmobile_us",
))
# dev.id = "dev-a3f12b"
# dev.adb_target = "127.0.0.1:6520"
# dev.state = "running"
```

Internally, `create_device()`:
1. Allocates a unique `instance_num` (finds next free port from 6520)
2. Generates a device ID: `dev-{secrets.token_hex(3)}`
3. Creates `cvd_home` directory
4. Builds `extra_bootconfig_args` from the device preset (bakes all `ro.*` props)
5. Invokes `launch_cvd --base_instance_num N --memory_mb M --cpus C ...`
6. Waits up to 120s for ADB to become responsive (`adb -s target shell echo ok`)
7. Saves `DeviceInstance` to `DEVICES_DIR/{id}.json`

### Patch

```python
await mgr.patch_device(dev.id, preset="samsung_s25_ultra",
                        carrier="tmobile_us", location="nyc")
# Runs AnomalyPatcher.full_patch() — 21 phases, ~45-90s
# Updates dev.patch_result and dev.stealth_score
```

### Inject Profile

```python
# Via API:
POST /api/genesis/inject/{device_id}
{"profile_id": "TITAN-0A4314A9", "cc_number": "4111..."}
# ~280s background job
```

### Destroy

```python
await mgr.destroy_device(dev.id)
# stop_cvd --base_instance_num N
# Removes cvd_home directory
# Removes device JSON file
# Frees ADB port for reuse
```

---

## 5. Cuttlefish Launch Parameters

`launch_cvd` is invoked with the following key arguments:

```bash
launch_cvd \
  --base_instance_num 1 \
  --memory_mb 4096 \
  --cpus 4 \
  --x_res 1080 \
  --y_res 2400 \
  --dpi 420 \
  --extra_bootconfig_args "
    androidboot.hardware=qcom
    ro.product.model=SM-S938U
    ro.product.brand=samsung
    ro.product.manufacturer=samsung
    ro.build.fingerprint=samsung/p3qxxx/p3q:14/UP1A.231005.007/S938USQU1BWK2:user/release-keys
    ro.build.version.release=14
    ro.build.version.sdk=34
    ro.build.version.security_patch=2026-01-01
    ro.build.type=user
    ro.build.tags=release-keys
    ro.hardware=qcom
    ro.kernel.qemu=0
    ro.hardware.virtual=0
    ro.boot.verifiedbootstate=green
    ro.boot.flash.locked=1
  " \
  --home_dir /opt/titan/cuttlefish/dev-a3f12b
```

**Why boot-time baking matters:** The `ro.*` namespace is read-only at runtime on production Android. Setting these via `extra_bootconfig_args` mirrors exactly how real devices initialize, making them indistinguishable from genuine hardware by property-check tools.

---

## 6. ADB Port Allocation

```
Instance 1: ADB 127.0.0.1:6520, VNC :6444
Instance 2: ADB 127.0.0.1:6521, VNC :6445
Instance 3: ADB 127.0.0.1:6522, VNC :6446
...
Instance 8: ADB 127.0.0.1:6527, VNC :6451
```

`DeviceManager` tracks active ports and automatically allocates the lowest free port. Port information is persisted in the device JSON so it survives API restarts.

**Connect after reboot:**
```bash
adb connect 127.0.0.1:6520
adb -s 127.0.0.1:6520 shell getprop ro.product.model
# SM-S938U
```

---

## 7. Device Presets

All presets are defined in `core/device_presets.py` as `DevicePreset` dataclasses.

### Complete Preset List

| Key | Brand | Model | SoC | Android | SDK |
|-----|-------|-------|-----|---------|-----|
| `samsung_s25_ultra` | Samsung | SM-S938U | Snapdragon 8 Gen 3 (qcom) | 15 | 35 |
| `samsung_s24` | Samsung | SM-S926B | Snapdragon 8 Gen 3 (qcom) | 14 | 34 |
| `samsung_a55` | Samsung | SM-A556B | Exynos 1480 | 14 | 34 |
| `samsung_a15` | Samsung | SM-A155F | MediaTek Helio G99 | 14 | 34 |
| `pixel_9_pro` | Google | Pixel 9 Pro | Tensor G4 (tensor) | 15 | 35 |
| `pixel_8a` | Google | Pixel 8a | Tensor G3 (tensor) | 14 | 34 |
| `pixel_7` | Google | Pixel 7 | Tensor G2 (tensor) | 14 | 34 |
| `oneplus_13` | OnePlus | CPH2673 | Snapdragon 8 Gen 3 (qcom) | 15 | 35 |
| `oneplus_12` | OnePlus | CPH2573 | Snapdragon 8 Gen 3 (qcom) | 14 | 34 |
| `oneplus_nord_ce4` | OnePlus | CPH2613 | Snapdragon 7s Gen 2 | 14 | 34 |
| `xiaomi_15` | Xiaomi | 2411DRN5CG | Snapdragon 8 Gen 3 (qcom) | 15 | 35 |
| `xiaomi_14` | Xiaomi | 23127PN0CC | Snapdragon 8 Gen 3 (qcom) | 14 | 34 |
| `redmi_note_14_pro` | Xiaomi | 24117RK66G | MediaTek Dimensity 7300 (mt6897) | 14 | 34 |
| `vivo_v2183a` | Vivo | V2183A | MediaTek Dimensity 9400 (mt6991) | 14 | 34 |
| `vivo_x200_pro` | Vivo | V2411 | Dimensity 9400 (mt6991) | 14 | 34 |
| `oppo_find_x8` | OPPO | PHX110 | Dimensity 9400 (mt6991) | 14 | 34 |
| `oppo_reno_12` | OPPO | CPH2613 | Dimensity 7300 (mt6897) | 14 | 34 |
| `nothing_phone_2a` | Nothing | A142 | Dimensity 7200 Pro (mt6897) | 14 | 34 |

### DevicePreset Fields

```python
@dataclass
class DevicePreset:
    name: str                # Human-readable name
    model: str               # ro.product.model (e.g. "SM-S938U")
    brand: str               # ro.product.brand
    manufacturer: str        # ro.product.manufacturer
    product: str             # ro.product.name
    device: str              # ro.product.device
    hardware: str            # ro.hardware (SoC family)
    board: str               # ro.board.platform
    fingerprint: str         # ro.build.fingerprint (full, from Google)
    build_id: str            # ro.build.display.id
    android_version: str     # ro.build.version.release
    sdk_version: str         # ro.build.version.sdk
    security_patch: str      # ro.build.version.security_patch
    build_type: str          # "user"
    build_tags: str          # "release-keys"
    bootloader: str          # ro.bootloader
    baseband: str            # ro.baseband
    tac_prefix: str          # IMEI TAC (first 8 digits) for Luhn generation
    mac_oui: str             # WiFi MAC OUI (e.g. "A4:50:46")
    gpu_renderer: str        # OpenGL ES renderer string
    gpu_vendor: str          # OpenGL ES vendor string
    color: int               # Card art color for wallet DB
```

**Highest trust fingerprints for wallet injection:**
1. `pixel_9_pro` — native Google hardware, best Play Integrity pass chain
2. `samsung_s25_ultra` — highest market share, robust attestation
3. `oneplus_13` — modern Snapdragon, clean fingerprint history

---

## 8. Carrier Profiles

```python
@dataclass
class CarrierProfile:
    name: str    # Display name (e.g. "T-Mobile")
    mcc: str     # Mobile Country Code
    mnc: str     # Mobile Network Code
    iso: str     # ISO country code
    country: str # Human-readable country
```

### Supported Carriers

| Key | Name | MCC | MNC | Country |
|-----|------|-----|-----|---------|
| `tmobile_us` | T-Mobile | 310 | 260 | US |
| `att_us` | AT&T | 310 | 410 | US |
| `verizon_us` | Verizon | 311 | 480 | US |
| `vodafone_uk` | Vodafone UK | 234 | 15 | UK |
| `ee_uk` | EE | 234 | 30 | UK |
| `o2_uk` | O2 UK | 234 | 10 | UK |
| `telekom_de` | Deutsche Telekom | 262 | 01 | Germany |
| `vodafone_de` | Vodafone DE | 262 | 02 | Germany |
| `telstra_au` | Telstra | 505 | 01 | Australia |
| `jio_in` | Jio | 405 | 840 | India |
| `airtel_in` | Airtel | 404 | 10 | India |
| `rogers_ca` | Rogers | 302 | 720 | Canada |
| `bell_ca` | Bell | 302 | 610 | Canada |

---

## 9. Location Profiles

Locations are defined in `LOCATIONS` dict in `device_presets.py`:

```python
LOCATIONS = {
    "nyc": {
        "city": "New York", "state": "NY", "country": "US",
        "lat": 40.7128, "lon": -74.0060,
        "timezone": "America/New_York",
        "locale": "en-US",
        "postal": "10001",
    },
    "la": {
        "city": "Los Angeles", "state": "CA", "country": "US",
        "lat": 34.0522, "lon": -118.2437,
        "timezone": "America/Los_Angeles",
        "locale": "en-US",
    },
    "london": { "city": "London", "country": "GB", "locale": "en-GB", ... },
    "berlin": { "city": "Berlin", "country": "DE", "locale": "de-DE", ... },
    "sydney": { "city": "Sydney", "country": "AU", "locale": "en-AU", ... },
    "mumbai": { "city": "Mumbai", "country": "IN", "locale": "en-IN", ... },
    "toronto": { "city": "Toronto", "country": "CA", "locale": "en-CA", ... },
    ...
}
```

Used by `AnomalyPatcher._patch_location()` to set GPS coordinates, timezone, locale, and SSID pools.

---

## 10. API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/devices` | Create a new Cuttlefish device |
| `GET` | `/api/devices` | List all active devices |
| `GET` | `/api/devices/{id}` | Get device details |
| `DELETE` | `/api/devices/{id}` | Destroy device and free resources |
| `POST` | `/api/devices/{id}/patch` | Run full anomaly patch |
| `GET` | `/api/devices/{id}/screenshot` | Capture device screenshot (PNG) |
| `POST` | `/api/devices/{id}/shell` | Execute ADB shell command |
| `GET` | `/api/devices/{id}/apps` | List installed packages |

### Create Device Request Body

```json
{
  "model": "samsung_s25_ultra",
  "country": "US",
  "carrier": "tmobile_us",
  "android_version": "14",
  "memory_mb": 4096,
  "cpus": 4
}
```

### Create Device Response

```json
{
  "id": "dev-a3f12b",
  "adb_target": "127.0.0.1:6520",
  "state": "running",
  "stealth_score": 0,
  "created_at": "2026-03-14T05:00:00Z"
}
```

---

*See [02-anomaly-patcher.md](02-anomaly-patcher.md) for the patching process that follows device creation.*
