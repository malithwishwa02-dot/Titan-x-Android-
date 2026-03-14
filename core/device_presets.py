"""
Titan V11.3 — Device Presets (30+ Android Device Identities)
Complete build.prop, IMEI TAC, MAC OUI, GPU string for each device.
Used by Cuttlefish launch config and anomaly patcher to make VMs
indistinguishable from real hardware.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class DevicePreset:
    name: str
    brand: str
    manufacturer: str
    model: str
    device: str
    product: str
    fingerprint: str
    android_version: str
    sdk_version: str
    security_patch: str
    build_id: str
    hardware: str
    board: str
    bootloader: str
    baseband: str
    lcd_density: str
    screen_width: int
    screen_height: int
    tac_prefix: str          # First 8 digits of IMEI (Type Allocation Code)
    mac_oui: str             # First 3 octets of WiFi MAC
    gpu_renderer: str        # OpenGL ES renderer string
    gpu_vendor: str          # OpenGL ES vendor string
    gpu_version: str         # OpenGL ES version string
    build_type: str = "user"
    build_tags: str = "release-keys"


@dataclass
class CarrierProfile:
    name: str
    mcc: str
    mnc: str
    country: str
    spn: str
    iso: str


# ═══════════════════════════════════════════════════════════════════════
# CARRIER DATABASE
# ═══════════════════════════════════════════════════════════════════════

CARRIERS: Dict[str, CarrierProfile] = {
    "tmobile_us": CarrierProfile("T-Mobile", "310", "260", "US", "T-Mobile", "us"),
    "att_us": CarrierProfile("AT&T", "310", "410", "US", "AT&T", "us"),
    "verizon_us": CarrierProfile("Verizon", "311", "480", "US", "Verizon", "us"),
    "uscellular_us": CarrierProfile("US Cellular", "311", "580", "US", "US Cellular", "us"),
    "ee_uk": CarrierProfile("EE", "234", "30", "GB", "EE", "gb"),
    "vodafone_uk": CarrierProfile("Vodafone UK", "234", "15", "GB", "Vodafone UK", "gb"),
    "three_uk": CarrierProfile("Three", "234", "20", "GB", "3", "gb"),
    "o2_uk": CarrierProfile("O2 - UK", "234", "10", "GB", "O2 - UK", "gb"),
    "telekom_de": CarrierProfile("Telekom.de", "262", "01", "DE", "Telekom.de", "de"),
    "vodafone_de": CarrierProfile("Vodafone.de", "262", "02", "DE", "Vodafone.de", "de"),
    "orange_fr": CarrierProfile("Orange F", "208", "01", "FR", "Orange F", "fr"),
}


# ═══════════════════════════════════════════════════════════════════════
# LOCATION DATABASE
# ═══════════════════════════════════════════════════════════════════════

LOCATIONS = {
    "nyc": {"lat": 40.7580, "lon": -73.9855, "tz": "America/New_York", "wifi": "Spectrum-5G", "locale": "en-US"},
    "la": {"lat": 34.0522, "lon": -118.2437, "tz": "America/Los_Angeles", "wifi": "ATT-5G-Home", "locale": "en-US"},
    "chicago": {"lat": 41.8781, "lon": -87.6298, "tz": "America/Chicago", "wifi": "Xfinity-5G", "locale": "en-US"},
    "houston": {"lat": 29.7604, "lon": -95.3698, "tz": "America/Chicago", "wifi": "NETGEAR72-5G", "locale": "en-US"},
    "miami": {"lat": 25.7617, "lon": -80.1918, "tz": "America/New_York", "wifi": "ATT-FIBER-5G", "locale": "en-US"},
    "sf": {"lat": 37.7749, "lon": -122.4194, "tz": "America/Los_Angeles", "wifi": "Google-Fiber", "locale": "en-US"},
    "seattle": {"lat": 47.6062, "lon": -122.3321, "tz": "America/Los_Angeles", "wifi": "CenturyLink5G", "locale": "en-US"},
    "london": {"lat": 51.5074, "lon": -0.1278, "tz": "Europe/London", "wifi": "BT-Hub6-5G", "locale": "en-GB"},
    "manchester": {"lat": 53.4808, "lon": -2.2426, "tz": "Europe/London", "wifi": "Sky-5G-Home", "locale": "en-GB"},
    "berlin": {"lat": 52.5200, "lon": 13.4050, "tz": "Europe/Berlin", "wifi": "FRITZ!Box-7590", "locale": "de-DE"},
    "paris": {"lat": 48.8566, "lon": 2.3522, "tz": "Europe/Paris", "wifi": "Livebox-5G", "locale": "fr-FR"},
}


# ═══════════════════════════════════════════════════════════════════════
# 30 DEVICE PRESETS
# ═══════════════════════════════════════════════════════════════════════

DEVICE_PRESETS: Dict[str, DevicePreset] = {

    # ── Samsung ───────────────────────────────────────────────────────
    "samsung_s25_ultra": DevicePreset(
        name="Samsung Galaxy S25 Ultra",
        brand="samsung", manufacturer="samsung",
        model="SM-S938U", device="e3q", product="e3qsq",
        fingerprint="samsung/e3qsq/e3q:15/AP4A.250205.004/S938USQS1AXL1:user/release-keys",
        android_version="15", sdk_version="35", security_patch="2025-02-05",
        build_id="AP4A.250205.004", hardware="qcom", board="kalama",
        bootloader="S938USQS1AXL1", baseband="S938USQS1AXL1",
        lcd_density="600", screen_width=1440, screen_height=3120,
        tac_prefix="35369611", mac_oui="E8:50:8B",
        gpu_renderer="Adreno (TM) 830", gpu_vendor="Qualcomm", gpu_version="OpenGL ES 3.2 V@0702.0",
    ),
    "samsung_s24": DevicePreset(
        name="Samsung Galaxy S24",
        brand="samsung", manufacturer="samsung",
        model="SM-S921U", device="e1q", product="e1qsq",
        fingerprint="samsung/e1qsq/e1q:14/UP1A.231005.007/S921USQS2AXK1:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-11-01",
        build_id="UP1A.231005.007", hardware="qcom", board="sun",
        bootloader="S921USQS2AXK1", baseband="S921USQS2AXK1",
        lcd_density="480", screen_width=1080, screen_height=2340,
        tac_prefix="35847611", mac_oui="E8:50:8B",
        gpu_renderer="Adreno (TM) 750", gpu_vendor="Qualcomm", gpu_version="OpenGL ES 3.2 V@0606.0",
    ),
    "samsung_a55": DevicePreset(
        name="Samsung Galaxy A55 5G",
        brand="samsung", manufacturer="samsung",
        model="SM-A556E", device="a55x", product="a55xns",
        fingerprint="samsung/a55xns/a55x:14/UP1A.231005.007/A556EXXU2AXJ1:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-10-01",
        build_id="UP1A.231005.007", hardware="exynos", board="s5e8845",
        bootloader="A556EXXU2AXJ1", baseband="A556EXXU2AXJ1",
        lcd_density="420", screen_width=1080, screen_height=2340,
        tac_prefix="35278911", mac_oui="E8:50:8B",
        gpu_renderer="Mali-G68 MC4", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.r44p0",
    ),
    "samsung_a15": DevicePreset(
        name="Samsung Galaxy A15",
        brand="samsung", manufacturer="samsung",
        model="SM-A156U", device="a15x", product="a15xsq",
        fingerprint="samsung/a15xsq/a15x:14/UP1A.231005.007/A156USQU1AXH1:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-08-01",
        build_id="UP1A.231005.007", hardware="mt6835", board="mt6835",
        bootloader="A156USQU1AXH1", baseband="MOLY.LR13.R1.MP.V259.3",
        lcd_density="420", screen_width=1080, screen_height=2340,
        tac_prefix="35413011", mac_oui="E8:50:8B",
        gpu_renderer="Mali-G57 MC2", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.r38p1",
    ),

    # ── Google Pixel ──────────────────────────────────────────────────
    "pixel_9_pro": DevicePreset(
        name="Google Pixel 9 Pro",
        brand="google", manufacturer="Google",
        model="Pixel 9 Pro", device="caiman", product="caiman",
        fingerprint="google/caiman/caiman:15/AP4A.250205.004/12650793:user/release-keys",
        android_version="15", sdk_version="35", security_patch="2025-02-05",
        build_id="AP4A.250205.004", hardware="tensor", board="caiman",
        bootloader="slider-1.0-11528163", baseband="g5300q-241129-250103-B-12514417",
        lcd_density="480", screen_width=1280, screen_height=2856,
        tac_prefix="35360412", mac_oui="94:E6:86",
        gpu_renderer="Mali-G715 Immortalis MC10", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.r46p0",
    ),
    "pixel_8a": DevicePreset(
        name="Google Pixel 8a",
        brand="google", manufacturer="Google",
        model="Pixel 8a", device="akita", product="akita",
        fingerprint="google/akita/akita:14/AP2A.240805.005/12025142:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-08-05",
        build_id="AP2A.240805.005", hardware="tensor", board="akita",
        bootloader="slider-1.0-11316379", baseband="g5300g-240712-240812-B-11982074",
        lcd_density="420", screen_width=1080, screen_height=2400,
        tac_prefix="35512621", mac_oui="94:E6:86",
        gpu_renderer="Mali-G715 Immortalis MC10", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.r44p0",
    ),
    "pixel_7": DevicePreset(
        name="Google Pixel 7",
        brand="google", manufacturer="Google",
        model="Pixel 7", device="panther", product="panther",
        fingerprint="google/panther/panther:14/AP2A.240805.005/12025142:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-08-05",
        build_id="AP2A.240805.005", hardware="tensor", board="panther",
        bootloader="slider-1.0-10071206", baseband="g5123b-230505-230828-B-10541553",
        lcd_density="420", screen_width=1080, screen_height=2400,
        tac_prefix="35397012", mac_oui="94:E6:86",
        gpu_renderer="Mali-G710 MC10", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.r38p1",
    ),

    # ── OnePlus ───────────────────────────────────────────────────────
    "oneplus_ace3": DevicePreset(
        name="OnePlus Ace 3",
        brand="OnePlus", manufacturer="OnePlus",
        model="PKX110", device="OP60F5L1", product="PKX110",
        fingerprint="OnePlus/PKX110/OP60F5L1:15/AP3A.240617.008/V.1a42e08_42cb7b_428e83:user/release-keys",
        android_version="15", sdk_version="35", security_patch="2024-06-17",
        build_id="AP3A.240617.008", hardware="qcom", board="sun",
        bootloader="unknown", baseband="1.0",
        lcd_density="480", screen_width=1264, screen_height=2780,
        tac_prefix="86742103", mac_oui="AC:D6:18",
        gpu_renderer="Adreno (TM) 830", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.g25p0",
    ),
    "oneplus_13": DevicePreset(
        name="OnePlus 13",
        brand="OnePlus", manufacturer="OnePlus",
        model="CPH2653", device="taro", product="CPH2653",
        fingerprint="OnePlus/CPH2653/taro:15/AP4A.250205.004/T.1234567:user/release-keys",
        android_version="15", sdk_version="35", security_patch="2025-02-05",
        build_id="AP4A.250205.004", hardware="qcom", board="taro",
        bootloader="unknown", baseband="1.1",
        lcd_density="480", screen_width=1440, screen_height=3168,
        tac_prefix="86712204", mac_oui="AC:D6:18",
        gpu_renderer="Adreno (TM) 830", gpu_vendor="Qualcomm", gpu_version="OpenGL ES 3.2 V@0702.0",
    ),
    "oneplus_12": DevicePreset(
        name="OnePlus 12",
        brand="OnePlus", manufacturer="OnePlus",
        model="CPH2583", device="waffle", product="CPH2583",
        fingerprint="OnePlus/CPH2583/waffle:14/UP1A.231005.007/T.1234567:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-10-01",
        build_id="UP1A.231005.007", hardware="qcom", board="kalama",
        bootloader="unknown", baseband="1.1",
        lcd_density="480", screen_width=1440, screen_height=3168,
        tac_prefix="86890104", mac_oui="AC:D6:18",
        gpu_renderer="Adreno (TM) 750", gpu_vendor="Qualcomm", gpu_version="OpenGL ES 3.2 V@0606.0",
    ),
    "oneplus_nord": DevicePreset(
        name="OnePlus Nord CE 4",
        brand="OnePlus", manufacturer="OnePlus",
        model="CPH2613", device="larry", product="CPH2613",
        fingerprint="OnePlus/CPH2613/larry:14/UP1A.231005.007/T.1234567:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-09-01",
        build_id="UP1A.231005.007", hardware="qcom", board="holi",
        bootloader="unknown", baseband="1.1",
        lcd_density="420", screen_width=1080, screen_height=2412,
        tac_prefix="86892004", mac_oui="AC:D6:18",
        gpu_renderer="Adreno (TM) 710", gpu_vendor="Qualcomm", gpu_version="OpenGL ES 3.2 V@0570.0",
    ),

    # ── Xiaomi ────────────────────────────────────────────────────────
    "xiaomi_15": DevicePreset(
        name="Xiaomi 15",
        brand="Xiaomi", manufacturer="Xiaomi",
        model="24129PN74G", device="dada", product="dada_global",
        fingerprint="Xiaomi/dada_global/dada:15/AP4A.250205.004/V816.0.5.0.VNCINXM:user/release-keys",
        android_version="15", sdk_version="35", security_patch="2025-02-05",
        build_id="AP4A.250205.004", hardware="qcom", board="kalama",
        bootloader="unknown", baseband="1.0",
        lcd_density="440", screen_width=1080, screen_height=2400,
        tac_prefix="86258804", mac_oui="28:6C:07",
        gpu_renderer="Adreno (TM) 830", gpu_vendor="Qualcomm", gpu_version="OpenGL ES 3.2 V@0702.0",
    ),
    "xiaomi_14": DevicePreset(
        name="Xiaomi 14",
        brand="Xiaomi", manufacturer="Xiaomi",
        model="2311DRK48G", device="houji", product="houji_global",
        fingerprint="Xiaomi/houji_global/houji:14/UP1A.231005.007/V816.0.3.0.UNCINXM:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-11-01",
        build_id="UP1A.231005.007", hardware="qcom", board="kalama",
        bootloader="unknown", baseband="1.0",
        lcd_density="440", screen_width=1080, screen_height=2400,
        tac_prefix="86475304", mac_oui="28:6C:07",
        gpu_renderer="Adreno (TM) 750", gpu_vendor="Qualcomm", gpu_version="OpenGL ES 3.2 V@0606.0",
    ),
    "redmi_note_14": DevicePreset(
        name="Redmi Note 14 Pro",
        brand="Redmi", manufacturer="Xiaomi",
        model="24108RN04Y", device="beryl", product="beryl_global",
        fingerprint="Redmi/beryl_global/beryl:14/UP1A.231005.007/V816.0.2.0.UOEINXM:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-10-01",
        build_id="UP1A.231005.007", hardware="mt6897", board="mt6897",
        bootloader="unknown", baseband="MOLY.LR15A.R2.MP",
        lcd_density="420", screen_width=1220, screen_height=2712,
        tac_prefix="86378504", mac_oui="28:6C:07",
        gpu_renderer="Mali-G615 MC6", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.r44p0",
    ),

    # ── Vivo ──────────────────────────────────────────────────────────
    "vivo_v2183a": DevicePreset(
        name="Vivo V2183A",
        brand="vivo", manufacturer="vivo",
        model="V2183A", device="PD2183", product="PD2183",
        fingerprint="vivo/PD2183/PD2183:15/AP4A.250205.004/compiler1124181214:user/release-keys",
        android_version="15", sdk_version="35", security_patch="2025-02-05",
        build_id="AP4A.250205.004", hardware="mt6893", board="mt6893",
        bootloader="unknown", baseband="MOLY.LR13.R1.MP.V153.5",
        lcd_density="480", screen_width=1080, screen_height=2400,
        tac_prefix="86140103", mac_oui="D0:17:69",
        gpu_renderer="Mali-G57 MC3", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.r32p1",
    ),
    "vivo_x200": DevicePreset(
        name="Vivo V2408A",
        brand="vivo", manufacturer="vivo",
        model="V2408A", device="PD2408", product="PD2408",
        fingerprint="vivo/PD2408/PD2408:15/AP3A.240905.015.A2/compiler2:user/release-keys",
        android_version="15", sdk_version="35", security_patch="2024-09-05",
        build_id="AP3A.240905.015.A2", hardware="mt6985", board="mt6985",
        bootloader="unknown", baseband="MOLY.LR15A.R3.MP",
        lcd_density="480", screen_width=1260, screen_height=2800,
        tac_prefix="86454004", mac_oui="D0:17:69",
        gpu_renderer="Immortalis-G925 MC12", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.r48p0",
    ),

    # ── OPPO ──────────────────────────────────────────────────────────
    "oppo_find_x8": DevicePreset(
        name="OPPO Find X8",
        brand="OPPO", manufacturer="OPPO",
        model="CPH2645", device="oplus_salami", product="CPH2645",
        fingerprint="OPPO/CPH2645/oplus_salami:14/UP1A.231005.007/T.R4T3.1234567:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-12-01",
        build_id="UP1A.231005.007", hardware="mt6991", board="mt6991",
        bootloader="unknown", baseband="1.0",
        lcd_density="480", screen_width=1264, screen_height=2780,
        tac_prefix="86730804", mac_oui="E4:C7:67",
        gpu_renderer="Immortalis-G925 MC12", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.r48p0",
    ),
    "oppo_reno_12": DevicePreset(
        name="OPPO Reno 12",
        brand="OPPO", manufacturer="OPPO",
        model="CPH2605", device="oplus_oscar", product="CPH2605",
        fingerprint="OPPO/CPH2605/oplus_oscar:14/UP1A.231005.007/T.R4T3.1234567:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-09-01",
        build_id="UP1A.231005.007", hardware="mt6878", board="mt6878",
        bootloader="unknown", baseband="MOLY.LR15A.R2.MP",
        lcd_density="420", screen_width=1080, screen_height=2412,
        tac_prefix="86705504", mac_oui="E4:C7:67",
        gpu_renderer="Mali-G615 MC6", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.r44p0",
    ),

    # ── Nothing ───────────────────────────────────────────────────────
    "nothing_phone_2a": DevicePreset(
        name="Nothing Phone (2a)",
        brand="Nothing", manufacturer="Nothing",
        model="A142P", device="Pacman", product="Pacman",
        fingerprint="Nothing/Pacman/Pacman:14/UP1A.231005.007/2405211815:user/release-keys",
        android_version="14", sdk_version="34", security_patch="2024-08-01",
        build_id="UP1A.231005.007", hardware="mt6878", board="mt6878",
        bootloader="unknown", baseband="MOLY.LR15A.R2.MP",
        lcd_density="420", screen_width=1080, screen_height=2412,
        tac_prefix="86891004", mac_oui="50:1A:A5",
        gpu_renderer="Mali-G615 MC6", gpu_vendor="ARM", gpu_version="OpenGL ES 3.2 v1.r44p0",
    ),
}


# ═══════════════════════════════════════════════════════════════════════
# COUNTRY DEFAULTS
# ═══════════════════════════════════════════════════════════════════════

COUNTRY_DEFAULTS = {
    "US": {"carrier": "tmobile_us", "location": "nyc", "locale": "en-US"},
    "GB": {"carrier": "ee_uk", "location": "london", "locale": "en-GB"},
    "DE": {"carrier": "telekom_de", "location": "berlin", "locale": "de-DE"},
    "FR": {"carrier": "orange_fr", "location": "paris", "locale": "fr-FR"},
}


def get_preset(name: str) -> DevicePreset:
    if name not in DEVICE_PRESETS:
        raise ValueError(f"Unknown preset: {name}. Available: {list(DEVICE_PRESETS.keys())}")
    return DEVICE_PRESETS[name]


def list_preset_names() -> list:
    return [{"key": k, "name": v.name, "brand": v.brand, "model": v.model}
            for k, v in DEVICE_PRESETS.items()]
