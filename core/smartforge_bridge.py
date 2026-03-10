"""
Titan V11.3 — SmartForge Bridge
Thin adapter that imports the v11-release SmartForge engine and adapts its output
for the Android device genesis pipeline (AndroidProfileForge + ProfileInjector).

The v11-release core is on PYTHONPATH via systemd/docker-compose, so we can
import directly. If unavailable, falls back to a local deterministic generator.
"""

import logging
import os
import random
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.smartforge-bridge")

# ═══════════════════════════════════════════════════════════════════════
# IMPORT v11-release SmartForge (graceful fallback)
# ═══════════════════════════════════════════════════════════════════════

_V11_CORE = os.environ.get("TITAN_V11_CORE", "/root/titan-v11-release/core")
if _V11_CORE not in sys.path:
    sys.path.insert(0, _V11_CORE)

_SMARTFORGE_OK = False
try:
    from smartforge_engine import (
        smart_forge,
        generate_deterministic_profile,
        get_occupation_list,
        get_country_list,
        OCCUPATIONS,
        COUNTRY_PROFILES,
    )
    _SMARTFORGE_OK = True
    logger.info("SmartForge engine loaded from v11-release")
except ImportError as e:
    logger.warning(f"SmartForge engine not available: {e} — using local fallback")
    OCCUPATIONS = {}
    COUNTRY_PROFILES = {}


# ═══════════════════════════════════════════════════════════════════════
# LOCAL FALLBACK (minimal, if v11-release not on path)
# ═══════════════════════════════════════════════════════════════════════

_FALLBACK_OCCUPATIONS = [
    {"key": "university_student", "label": "University Student", "age_range": (18, 28)},
    {"key": "software_engineer", "label": "Software Engineer", "age_range": (22, 45)},
    {"key": "government_worker", "label": "Government Worker", "age_range": (28, 60)},
    {"key": "doctor", "label": "Doctor", "age_range": (28, 65)},
    {"key": "retail_worker", "label": "Retail Worker", "age_range": (18, 45)},
    {"key": "freelancer", "label": "Freelancer", "age_range": (22, 50)},
    {"key": "retiree", "label": "Retiree", "age_range": (55, 80)},
    {"key": "small_business_owner", "label": "Small Business Owner", "age_range": (28, 60)},
    {"key": "teacher", "label": "Teacher", "age_range": (24, 60)},
    {"key": "gamer", "label": "Gamer", "age_range": (16, 35)},
]

_FALLBACK_COUNTRIES = [
    {"key": "US", "label": "United States", "currency": "USD"},
    {"key": "GB", "label": "United Kingdom", "currency": "GBP"},
    {"key": "CA", "label": "Canada", "currency": "CAD"},
    {"key": "AU", "label": "Australia", "currency": "AUD"},
    {"key": "DE", "label": "Germany", "currency": "EUR"},
    {"key": "FR", "label": "France", "currency": "EUR"},
    {"key": "JP", "label": "Japan", "currency": "JPY"},
    {"key": "BR", "label": "Brazil", "currency": "BRL"},
    {"key": "NL", "label": "Netherlands", "currency": "EUR"},
    {"key": "IT", "label": "Italy", "currency": "EUR"},
    {"key": "ES", "label": "Spain", "currency": "EUR"},
    {"key": "SE", "label": "Sweden", "currency": "SEK"},
    {"key": "CH", "label": "Switzerland", "currency": "CHF"},
    {"key": "PL", "label": "Poland", "currency": "PLN"},
    {"key": "SG", "label": "Singapore", "currency": "SGD"},
    {"key": "IN", "label": "India", "currency": "INR"},
    {"key": "TR", "label": "Turkey", "currency": "TRY"},
    {"key": "KR", "label": "South Korea", "currency": "KRW"},
    {"key": "MX", "label": "Mexico", "currency": "MXN"},
    {"key": "BE", "label": "Belgium", "currency": "EUR"},
]


def _fallback_profile(occupation: str, country: str, age: int, gender: str = "auto") -> dict:
    """Minimal deterministic profile when v11-release is unavailable."""
    if gender == "auto":
        gender = random.choice(["M", "F"])
    first = random.choice(["James", "Michael", "Sarah", "Emily"] if gender == "M"
                          else ["Sarah", "Emily", "Jessica", "Amanda"])
    last = random.choice(["Smith", "Johnson", "Williams", "Brown", "Davis"])
    email = f"{first.lower()}.{last.lower()}{random.randint(10, 99)}@gmail.com"
    phone = f"+1212{random.randint(1000000, 9999999)}"
    profile_age = max(30, int(age * 3 + random.randint(0, 90)))

    return {
        "name": f"{first} {last}",
        "first_name": first,
        "last_name": last,
        "email": email,
        "phone": phone,
        "dob": f"{datetime.now().year - age}-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
        "age": age,
        "gender": gender,
        "occupation": occupation,
        "occupation_key": occupation,
        "street": f"{random.randint(100, 9999)} Main St",
        "city": "New York",
        "state": "NY",
        "zip": str(random.randint(10001, 14999)),
        "country": country,
        "country_label": country,
        "card_number": "",
        "card_last4": "",
        "card_network": "visa",
        "card_exp": f"{random.randint(1,12):02d}/{random.randint(26,29)}",
        "card_cvv": str(random.randint(100, 999)),
        "card_tier": "debit",
        "profile_age_days": profile_age,
        "avg_spend": random.randint(20, 300),
        "currency": "USD",
        "locale": "en-US",
        "timezone": "America/New_York",
        "archetype": occupation,
        "browsing_sites": ["google.com", "youtube.com", "amazon.com", "reddit.com"],
        "cookie_sites": ["google.com", "youtube.com", "amazon.com"],
        "search_terms": ["best deals online", "weather today"],
        "purchase_categories": ["electronics", "clothing"],
        "social_platforms": ["instagram", "facebook"],
        "device_profile": "mid_range_phone",
        "hour_weights": [1]*24,
        "smartforge": False,
    }


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API — Android Genesis Bridge
# ═══════════════════════════════════════════════════════════════════════

def smartforge_for_android(
    occupation: str = "software_engineer",
    country: str = "US",
    age: int = 30,
    gender: str = "auto",
    target_site: str = "amazon.com",
    use_ai: bool = False,
    identity_override: dict = None,
    age_days: int = 0,
) -> Dict[str, Any]:
    """
    Generate a SmartForge profile and adapt it for the Android genesis pipeline.

    Returns a dict compatible with AndroidProfileForge.forge() + ProfileInjector,
    including: persona identity, behavioral vectors, card data, and device config.

    Args:
        occupation: Occupation key (e.g. "software_engineer", "doctor")
        country: Country code (e.g. "US", "GB", "DE")
        age: Person's age
        gender: "M", "F", or "auto"
        target_site: Target e-commerce site
        use_ai: Use Ollama AI enrichment (requires Ollama running)
        identity_override: Dict with real identity to overlay (name, email, phone, card_number, etc.)
        age_days: Override profile age in days (0 = auto from occupation/age)
    """
    if _SMARTFORGE_OK:
        # Use full v11-release SmartForge
        forge_config = smart_forge(
            occupation=occupation,
            country=country,
            age=age,
            gender=gender,
            target_site=target_site,
            use_ai=use_ai,
            identity_override=identity_override,
        )
    else:
        # Fallback
        forge_config = _fallback_profile(occupation, country, age, gender)
        if identity_override:
            for k, v in identity_override.items():
                if v:
                    forge_config[k] = v

    # Override age_days if specified
    if age_days > 0:
        forge_config["profile_age_days"] = age_days
        forge_config["age_days"] = age_days
    else:
        forge_config["age_days"] = forge_config.get("profile_age_days", 90)

    # ── Adapt for Android genesis ──────────────────────────────────────
    android_config = {
        # Identity (for AndroidProfileForge + ProfileInjector)
        "persona_name": forge_config.get("name", ""),
        "persona_email": forge_config.get("email", ""),
        "persona_phone": forge_config.get("phone", ""),
        "country": forge_config.get("country", "US"),
        "archetype": forge_config.get("archetype", occupation),
        "age_days": forge_config.get("age_days", 90),
        "device_model": _occupation_to_device(occupation),

        # Carrier + location (auto from country)
        "carrier": _country_to_carrier(country),
        "location": _country_to_location(country),

        # Card data (for wallet provisioning)
        "card_data": None,

        # SmartForge behavioral vectors (for enriched forging)
        "browsing_sites": forge_config.get("browsing_sites", []),
        "cookie_sites": forge_config.get("cookie_sites", []),
        "search_terms": forge_config.get("search_terms", []),
        "purchase_categories": forge_config.get("purchase_categories", []),
        "social_platforms": forge_config.get("social_platforms", []),
        "hour_weights": forge_config.get("hour_weights", [1]*24),

        # Full SmartForge config for reference
        "smartforge_config": forge_config,

        # Metadata
        "smartforge": True,
        "ai_enriched": forge_config.get("ai_enriched", False),
        "osint_enriched": forge_config.get("osint_enriched", False),
        "occupation": forge_config.get("occupation", occupation),
        "occupation_key": forge_config.get("occupation_key", occupation),
        "gender": forge_config.get("gender", "auto"),
        "age": age,
        "dob": forge_config.get("dob", ""),
        "locale": forge_config.get("locale", "en-US"),
        "timezone": forge_config.get("timezone", "America/New_York"),
        "currency": forge_config.get("currency", "USD"),

        # Address (for autofill)
        "street": forge_config.get("street", ""),
        "city": forge_config.get("city", ""),
        "state": forge_config.get("state", ""),
        "zip": forge_config.get("zip", ""),
    }

    # Build card_data if CC present in forge_config
    card_num = forge_config.get("card_number", "")
    if card_num and len(card_num) >= 13:
        exp = forge_config.get("card_exp", "12/27")
        parts = exp.split("/")
        android_config["card_data"] = {
            "number": card_num,
            "exp_month": int(parts[0]) if len(parts) >= 2 else 12,
            "exp_year": int("20" + parts[1]) if len(parts) >= 2 and len(parts[1]) == 2
                        else int(parts[1]) if len(parts) >= 2 else 2027,
            "cvv": forge_config.get("card_cvv", "123"),
            "cardholder": forge_config.get("name", ""),
        }

    return android_config


def _occupation_to_device(occupation: str) -> str:
    """Map occupation archetype to realistic device model."""
    device_map = {
        "university_student": random.choice(["samsung_a55", "pixel_8a", "xiaomi_14"]),
        "software_engineer": random.choice(["pixel_9_pro", "samsung_s25_ultra"]),
        "government_worker": random.choice(["samsung_s24", "pixel_9_pro"]),
        "doctor": random.choice(["samsung_s25_ultra", "pixel_9_pro"]),
        "retail_worker": random.choice(["samsung_a15", "xiaomi_redmi_note_14_pro"]),
        "freelancer": random.choice(["pixel_9_pro", "oneplus_13"]),
        "retiree": random.choice(["samsung_s24", "samsung_a55"]),
        "small_business_owner": random.choice(["samsung_s25_ultra", "pixel_9_pro"]),
        "teacher": random.choice(["samsung_a55", "pixel_8a"]),
        "gamer": random.choice(["oneplus_13", "samsung_s25_ultra"]),
    }
    return device_map.get(occupation, "samsung_s25_ultra")


def _country_to_carrier(country: str) -> str:
    """Map country to default carrier."""
    carrier_map = {
        "US": "tmobile_us", "GB": "ee_uk", "CA": "rogers_ca",
        "AU": "telstra_au", "DE": "tmobile_de", "FR": "orange_fr",
        "JP": "docomo_jp", "BR": "vivo_br", "NL": "kpn_nl",
        "IT": "tim_it", "ES": "movistar_es", "SE": "telia_se",
        "CH": "swisscom_ch", "PL": "play_pl", "SG": "singtel_sg",
        "IN": "jio_in", "TR": "turkcell_tr", "KR": "skt_kr",
        "MX": "telcel_mx", "BE": "proximus_be",
    }
    return carrier_map.get(country, "tmobile_us")


def _country_to_location(country: str) -> str:
    """Map country to default city/location key."""
    loc_map = {
        "US": "nyc", "GB": "london", "CA": "toronto",
        "AU": "sydney", "DE": "berlin", "FR": "paris",
        "JP": "tokyo", "BR": "sao_paulo", "NL": "amsterdam",
        "IT": "milan", "ES": "madrid", "SE": "stockholm",
        "CH": "zurich", "PL": "warsaw", "SG": "singapore",
        "IN": "mumbai", "TR": "istanbul", "KR": "seoul",
        "MX": "mexico_city", "BE": "brussels",
    }
    return loc_map.get(country, "nyc")


def get_occupations() -> List[dict]:
    """Return occupation list for API/UI."""
    if _SMARTFORGE_OK:
        return get_occupation_list()
    return _FALLBACK_OCCUPATIONS


def get_countries() -> List[dict]:
    """Return country list for API/UI."""
    if _SMARTFORGE_OK:
        return get_country_list()
    return _FALLBACK_COUNTRIES
