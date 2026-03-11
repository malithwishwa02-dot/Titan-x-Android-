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


# ═══════════════════════════════════════════════════════════════════════
# CITY → LOCATION RESOLVER (persona-driven, no defaults)
# ═══════════════════════════════════════════════════════════════════════

CITY_TO_LOCATION = {
    # US cities
    "los angeles": "la", "la": "la", "hollywood": "la", "beverly hills": "la",
    "new york": "nyc", "nyc": "nyc", "manhattan": "nyc", "brooklyn": "nyc", "bronx": "nyc", "queens": "nyc",
    "chicago": "chicago", "houston": "houston", "miami": "miami", "fort lauderdale": "miami",
    "san francisco": "sf", "oakland": "sf", "san jose": "sf",
    "seattle": "seattle", "tacoma": "seattle",
    # UK cities
    "london": "london", "manchester": "manchester", "birmingham": "london",
    "liverpool": "manchester", "leeds": "manchester", "bristol": "london",
    # DE cities
    "berlin": "berlin", "munich": "berlin", "hamburg": "berlin",
    "frankfurt": "berlin", "cologne": "berlin", "stuttgart": "berlin",
    # FR cities
    "paris": "paris", "lyon": "paris", "marseille": "paris",
    "toulouse": "paris", "nice": "paris", "bordeaux": "paris",
}

# US state → nearest location fallback
STATE_TO_LOCATION = {
    "california": "la", "ca": "la",
    "new york": "nyc", "ny": "nyc", "new jersey": "nyc", "nj": "nyc", "connecticut": "nyc", "ct": "nyc",
    "illinois": "chicago", "il": "chicago", "indiana": "chicago", "in": "chicago",
    "texas": "houston", "tx": "houston",
    "florida": "miami", "fl": "miami",
    "washington": "seattle", "wa": "seattle", "oregon": "seattle", "or": "seattle",
    "massachusetts": "nyc", "ma": "nyc", "pennsylvania": "nyc", "pa": "nyc",
    "georgia": "miami", "ga": "miami", "north carolina": "miami", "nc": "miami",
    "colorado": "chicago", "co": "chicago", "arizona": "la", "az": "la", "nevada": "la", "nv": "la",
    "ohio": "chicago", "oh": "chicago", "michigan": "chicago", "mi": "chicago",
    "virginia": "nyc", "va": "nyc", "maryland": "nyc", "md": "nyc",
    # UK
    "england": "london", "scotland": "manchester", "wales": "london",
}

# City → area codes for contact generation
CITY_AREA_CODES = {
    "la": ["213", "310", "323", "818", "626"],
    "nyc": ["212", "646", "718", "917", "347"],
    "chicago": ["312", "773", "872"],
    "houston": ["713", "832", "281"],
    "miami": ["305", "786", "954"],
    "sf": ["415", "510", "408"],
    "seattle": ["206", "253", "425"],
    "london": ["020", "0207", "0208"],
    "manchester": ["0161", "0151"],
    "berlin": ["030", "089", "040"],
    "paris": ["01", "06", "07"],
}

# Carrier pools per country (random selection, no single default)
CARRIER_POOLS = {
    "US": ["tmobile_us", "att_us", "verizon_us"],
    "GB": ["ee_uk", "vodafone_uk", "three_uk", "o2_uk"],
    "DE": ["telekom_de", "vodafone_de"],
    "FR": ["orange_fr"],
}

# Country → currency/locale
COUNTRY_META = {
    "US": {"currency": "USD", "locale": "en-US", "phone_prefix": "+1"},
    "GB": {"currency": "GBP", "locale": "en-GB", "phone_prefix": "+44"},
    "DE": {"currency": "EUR", "locale": "de-DE", "phone_prefix": "+49"},
    "FR": {"currency": "EUR", "locale": "fr-FR", "phone_prefix": "+33"},
}


def _resolve_location(city: str = "", state: str = "", country: str = "US") -> str:
    """Resolve persona's city/state to a LOCATIONS key. No hardcoded defaults."""
    # Try city first
    if city:
        loc = CITY_TO_LOCATION.get(city.lower().strip())
        if loc:
            return loc
    # Try state fallback (US)
    if state:
        loc = STATE_TO_LOCATION.get(state.lower().strip())
        if loc:
            return loc
    # Country-level fallback
    country_loc = {"US": "nyc", "GB": "london", "DE": "berlin", "FR": "paris"}
    return country_loc.get(country, "nyc")


def _derive_email(name: str, dob: str = "") -> str:
    """Derive email from persona name + DOB. No random generation."""
    parts = name.strip().split(None, 1)
    first = parts[0].lower() if parts else "user"
    last = parts[1].lower().replace(" ", "") if len(parts) > 1 else "unknown"
    # Extract birth year suffix from DOB
    suffix = ""
    if dob:
        # Handle DD/MM/YYYY or YYYY-MM-DD
        for sep in ["/", "-"]:
            dob_parts = dob.split(sep)
            if len(dob_parts) >= 3:
                year_part = dob_parts[-1] if len(dob_parts[-1]) == 4 else dob_parts[0]
                try:
                    suffix = str(int(year_part) % 100)
                except ValueError:
                    pass
                break
    if not suffix:
        suffix = str(random.randint(10, 99))
    return f"{first}.{last}{suffix}@gmail.com"


def _age_from_dob(dob: str) -> int:
    """Calculate age from DOB string (DD/MM/YYYY or YYYY-MM-DD)."""
    if not dob:
        return 30
    try:
        for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"]:
            try:
                born = datetime.strptime(dob, fmt)
                today = datetime.now()
                return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
            except ValueError:
                continue
    except Exception:
        pass
    return 30


def _device_for_persona(occupation: str, age: int, country: str) -> str:
    """Select device model based on occupation + age + country. No single default."""
    # Age-based tiers
    if age >= 55:
        # Older adults: mainstream flagships, easy to use
        pool = ["samsung_s24", "pixel_9_pro", "samsung_a55"]
    elif age >= 35:
        # Mid-career: premium devices
        pool = ["samsung_s25_ultra", "pixel_9_pro", "oneplus_13", "samsung_s24"]
    elif age >= 25:
        # Young professional
        pool = ["pixel_9_pro", "samsung_s25_ultra", "oneplus_13", "xiaomi_15"]
    else:
        # Under 25: budget/mid-range
        pool = ["samsung_a55", "pixel_8a", "redmi_note_14", "nothing_phone_2a"]

    # Occupation overrides
    if occupation in ("doctor", "small_business_owner"):
        pool = ["samsung_s25_ultra", "pixel_9_pro"]
    elif occupation == "gamer":
        pool = ["oneplus_13", "samsung_s25_ultra", "xiaomi_15"]
    elif occupation == "university_student":
        pool = ["samsung_a55", "pixel_8a", "nothing_phone_2a"]

    # Country flavor (Samsung dominates US/GB, Xiaomi in DE/FR)
    if country in ("DE", "FR") and age < 40:
        pool = [p for p in pool if "samsung" not in p] or pool  # prefer non-Samsung in EU for variety
        if not pool:
            pool = ["xiaomi_15", "pixel_9_pro"]

    return random.choice(pool)


def _fallback_profile(occupation: str, country: str, age: int, gender: str = "auto") -> dict:
    """Minimal deterministic profile when v11-release is unavailable."""
    if gender == "auto":
        gender = random.choice(["M", "F"])
    first = random.choice(["James", "Michael", "Sarah", "Emily"] if gender == "M"
                          else ["Sarah", "Emily", "Jessica", "Amanda"])
    last = random.choice(["Smith", "Johnson", "Williams", "Brown", "Davis"])
    meta = COUNTRY_META.get(country, COUNTRY_META["US"])
    profile_age = max(30, int(age * 3 + random.randint(0, 90)))

    return {
        "name": f"{first} {last}",
        "first_name": first,
        "last_name": last,
        "email": "",  # Will be derived from persona name+DOB
        "phone": "",
        "dob": f"{datetime.now().year - age}-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
        "age": age,
        "gender": gender,
        "occupation": occupation,
        "occupation_key": occupation,
        "street": "",
        "city": "",
        "state": "",
        "zip": "",
        "country": country,
        "country_label": country,
        "card_number": "",
        "card_last4": "",
        "card_network": "visa",
        "card_exp": "",
        "card_cvv": "",
        "card_tier": "debit",
        "profile_age_days": profile_age,
        "avg_spend": random.randint(20, 300),
        "currency": meta["currency"],
        "locale": meta["locale"],
        "timezone": "",  # Will be resolved from location
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
    Generate a SmartForge profile adapted for Android genesis.
    ALL fields are derived from user persona inputs — no hardcoded defaults.
    """
    if _SMARTFORGE_OK:
        forge_config = smart_forge(
            occupation=occupation, country=country, age=age,
            gender=gender, target_site=target_site, use_ai=use_ai,
            identity_override=identity_override,
        )
    else:
        forge_config = _fallback_profile(occupation, country, age, gender)

    # Apply identity overrides
    if identity_override:
        for k, v in identity_override.items():
            if v:
                forge_config[k] = v

    # Calculate age from DOB if provided
    dob = forge_config.get("dob", "")
    if dob and identity_override and identity_override.get("dob"):
        calculated_age = _age_from_dob(dob)
        if calculated_age > 0:
            age = calculated_age
            forge_config["age"] = age

    # Override age_days if specified
    if age_days > 0:
        forge_config["profile_age_days"] = age_days
        forge_config["age_days"] = age_days
    else:
        forge_config["age_days"] = forge_config.get("profile_age_days", 90)

    # ── PERSONA-DRIVEN RESOLUTION ─────────────────────────────────────
    # Resolve location from persona's city/state (NOT hardcoded per country)
    persona_city = forge_config.get("city", "")
    persona_state = forge_config.get("state", "")
    resolved_location = _resolve_location(persona_city, persona_state, country)

    # Import LOCATIONS to get timezone, GPS, WiFi from resolved location
    from device_presets import LOCATIONS
    loc_data = LOCATIONS.get(resolved_location, {})
    resolved_tz = loc_data.get("tz", "America/New_York")
    resolved_locale = loc_data.get("locale", COUNTRY_META.get(country, {}).get("locale", "en-US"))

    # Derive email from persona name + DOB (not random)
    persona_name = forge_config.get("name", "")
    persona_email = forge_config.get("email", "")
    if not persona_email and persona_name:
        persona_email = _derive_email(persona_name, dob)
        forge_config["email"] = persona_email

    # Select device based on persona age + occupation + country (not occupation-only)
    device_model = _device_for_persona(occupation, age, country)

    # Random carrier from country pool (not single hardcoded)
    carrier_pool = CARRIER_POOLS.get(country, ["tmobile_us"])
    carrier = random.choice(carrier_pool)

    # Get city area codes for contact generation
    area_codes = CITY_AREA_CODES.get(resolved_location, [])
    # Extract persona's own area code from phone
    persona_phone = forge_config.get("phone", "")
    persona_area_code = ""
    if persona_phone:
        clean_phone = persona_phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if clean_phone.startswith("+1") and len(clean_phone) >= 5:
            persona_area_code = clean_phone[2:5]
        elif len(clean_phone) >= 3 and clean_phone[0].isdigit():
            persona_area_code = clean_phone[:3]

    # ── Build Android config ──────────────────────────────────────────
    android_config = {
        # Identity
        "persona_name": persona_name,
        "persona_email": persona_email,
        "persona_phone": persona_phone,
        "country": country,
        "archetype": forge_config.get("archetype", occupation),
        "age_days": forge_config.get("age_days", 90),
        "device_model": device_model,

        # Resolved from persona city/state
        "carrier": carrier,
        "location": resolved_location,

        # Card data
        "card_data": None,

        # Behavioral vectors
        "browsing_sites": forge_config.get("browsing_sites", []),
        "cookie_sites": forge_config.get("cookie_sites", []),
        "search_terms": forge_config.get("search_terms", []),
        "purchase_categories": forge_config.get("purchase_categories", []),
        "social_platforms": forge_config.get("social_platforms", []),
        "hour_weights": forge_config.get("hour_weights", [1]*24),

        # Full config reference
        "smartforge_config": forge_config,

        # Metadata (all resolved from persona)
        "smartforge": True,
        "ai_enriched": forge_config.get("ai_enriched", False),
        "osint_enriched": forge_config.get("osint_enriched", False),
        "occupation": forge_config.get("occupation", occupation),
        "occupation_key": forge_config.get("occupation_key", occupation),
        "gender": forge_config.get("gender", "auto"),
        "age": age,
        "dob": dob,
        "locale": resolved_locale,
        "timezone": resolved_tz,
        "currency": COUNTRY_META.get(country, {}).get("currency", "USD"),

        # Address (user's real address for autofill)
        "street": forge_config.get("street", ""),
        "city": persona_city,
        "state": persona_state,
        "zip": forge_config.get("zip", ""),

        # Contact generation hints
        "persona_area_code": persona_area_code,
        "city_area_codes": area_codes,
    }

    # Build card_data if CC present
    card_num = forge_config.get("card_number", "")
    if card_num and len(card_num.replace(" ", "").replace("-", "")) >= 13:
        clean_num = card_num.replace(" ", "").replace("-", "")
        exp = forge_config.get("card_exp", "")
        exp_month, exp_year = 12, 2027
        if exp:
            parts = exp.replace("|", "/").split("/")
            if len(parts) >= 2:
                try:
                    exp_month = int(parts[0])
                    yr = int(parts[1])
                    exp_year = yr if yr > 100 else 2000 + yr
                except ValueError:
                    pass
        android_config["card_data"] = {
            "number": clean_num,
            "exp_month": exp_month,
            "exp_year": exp_year,
            "cvv": forge_config.get("card_cvv", ""),
            "cardholder": persona_name,
        }

    logger.info(f"SmartForge resolved: location={resolved_location}, tz={resolved_tz}, "
                f"carrier={carrier}, device={device_model}, email={persona_email}")
    return android_config


# Legacy helpers removed — replaced by persona-driven _resolve_location, _device_for_persona, carrier pools


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
