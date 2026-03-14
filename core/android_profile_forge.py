"""
Titan V11.3 — Android Device Profile Forge
Generates complete, persona-consistent Android device profile data
for injection into Cuttlefish Android VMs via ProfileInjector.

Unlike the V11 genesis_core (browser-only), this forges the FULL device:
  - Contacts (persona-tied names + locale-matched phone numbers)
  - Call logs (circadian-weighted, in/out/missed over profile age)
  - SMS threads (realistic conversation snippets with contacts)
  - Chrome mobile cookies (trust anchors + commerce + social)
  - Chrome mobile history (locale-aware, mobile-pattern browsing)
  - Gallery photos (EXIF-dated placeholder JPEGs)
  - App install dates (backdated for bundled apps)
  - WiFi saved networks (matching location profile)
  - Autofill data (name, email, phone, address)
  - Purchase history (email receipts, order confirmations)

All data is temporally distributed across the profile age using
circadian weighting so the device looks genuinely lived-in.

Usage:
    forge = AndroidProfileForge()
    profile = forge.forge(
        persona_name="Alex Mercer",
        persona_email="alex.mercer@gmail.com",
        persona_phone="+12125551234",
        country="US",
        archetype="professional",
        age_days=90,
        carrier="tmobile_us",
        location="nyc",
    )
    # profile dict has: cookies, history, contacts, call_logs, sms,
    #                   gallery_paths, autofill, wifi_networks, app_installs
"""

import hashlib
import json
import logging
import os
import random
import secrets
import string
import struct
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.android-forge")

TITAN_DATA = Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))


# ═══════════════════════════════════════════════════════════════════════
# PERSONA NAME POOLS (by locale)
# ═══════════════════════════════════════════════════════════════════════

NAME_POOLS = {
    "US": {
        "first_male": ["James", "Robert", "John", "Michael", "David", "William",
                       "Richard", "Joseph", "Thomas", "Christopher", "Daniel", "Matthew",
                       "Anthony", "Mark", "Andrew", "Steven", "Brian", "Kevin", "Jason", "Ryan"],
        "first_female": ["Mary", "Patricia", "Jennifer", "Linda", "Barbara", "Elizabeth",
                         "Susan", "Jessica", "Sarah", "Karen", "Lisa", "Nancy",
                         "Betty", "Margaret", "Sandra", "Ashley", "Emily", "Donna", "Michelle", "Carol"],
        "last": ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
                 "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
                 "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
                 "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Lewis"],
        "area_codes": ["212", "646", "718", "917", "310", "323", "415", "312",
                       "713", "214", "404", "305", "202", "617", "503", "206"],
    },
    "GB": {
        "first_male": ["Oliver", "George", "Harry", "Jack", "Charlie", "Thomas",
                       "James", "William", "Daniel", "Henry", "Alexander", "Edward"],
        "first_female": ["Olivia", "Amelia", "Isla", "Ava", "Emily", "Sophia",
                         "Grace", "Mia", "Poppy", "Ella", "Lily", "Jessica"],
        "last": ["Smith", "Jones", "Williams", "Taylor", "Brown", "Davies", "Evans",
                 "Wilson", "Thomas", "Roberts", "Johnson", "Lewis", "Walker", "Robinson"],
        "area_codes": ["020", "0121", "0131", "0141", "0161", "0113", "0117", "01onal"],
    },
    "DE": {
        "first_male": ["Lukas", "Leon", "Finn", "Jonas", "Noah", "Elias", "Paul",
                       "Ben", "Felix", "Max", "Liam", "Moritz"],
        "first_female": ["Emma", "Mia", "Hannah", "Sofia", "Lina", "Emilia",
                         "Marie", "Lea", "Anna", "Lena", "Clara", "Ella"],
        "last": ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer",
                 "Wagner", "Becker", "Schulz", "Hoffmann", "Koch", "Richter"],
        "area_codes": ["030", "089", "040", "0221", "069", "0211", "0711", "0341"],
    },
    "FR": {
        "first_male": ["Gabriel", "Louis", "Raphaël", "Jules", "Adam", "Lucas",
                       "Léo", "Hugo", "Arthur", "Nathan", "Liam", "Ethan"],
        "first_female": ["Emma", "Jade", "Louise", "Alice", "Chloé", "Lina",
                         "Rose", "Léa", "Anna", "Mila", "Ambre", "Julia"],
        "last": ["Martin", "Bernard", "Thomas", "Petit", "Robert", "Richard",
                 "Durand", "Dubois", "Moreau", "Laurent", "Simon", "Michel"],
        "area_codes": ["01", "04", "06", "09"],
    },
}

# ═══════════════════════════════════════════════════════════════════════
# SMS CONVERSATION TEMPLATES
# ═══════════════════════════════════════════════════════════════════════

SMS_TEMPLATES = {
    "casual": [
        ("Hey, you free tonight?", "in"),
        ("Yeah what's up?", "out"),
        ("Want to grab dinner? That new place on Main St", "in"),
        ("Sure, 7pm?", "out"),
        ("Perfect see you there", "in"),
    ],
    "work": [
        ("Can you send me the updated report?", "in"),
        ("Just sent it to your email", "out"),
        ("Got it, thanks!", "in"),
    ],
    "family": [
        ("Hi sweetie, are you coming for dinner Sunday?", "in"),
        ("Yes! What time should I be there?", "out"),
        ("Around 2pm. Dad is grilling", "in"),
        ("Sounds great, I'll bring dessert", "out"),
        ("Love you ❤️", "in"),
    ],
    "delivery": [
        ("Your DoorDash order is on the way!", "in"),
        ("Driver is arriving in 5 minutes", "in"),
    ],
    "bank": [
        ("Alert: Purchase of $47.82 at WALMART approved on card ending 4521", "in"),
        ("Alert: Purchase of $12.99 at SPOTIFY approved on card ending 4521", "in"),
    ],
    "otp": [
        ("Your verification code is 847291. Don't share it with anyone.", "in"),
        ("Your code is 529163. Expires in 10 minutes.", "in"),
    ],
    "friend_plan": [
        ("Bro did you see the game last night??", "in"),
        ("Yeah that last quarter was insane", "out"),
        ("We should watch the next one at Dave's", "in"),
        ("I'm down, what day?", "out"),
        ("Saturday 6pm", "in"),
        ("👍", "out"),
    ],
    "appointment": [
        ("Reminder: Your appointment is tomorrow at 10:30 AM", "in"),
        ("Thank you, I'll be there", "out"),
    ],
}

# ═══════════════════════════════════════════════════════════════════════
# MOBILE BROWSING DOMAINS (locale-aware)
# ═══════════════════════════════════════════════════════════════════════

MOBILE_DOMAINS = {
    "global": [
        ("youtube.com", "YouTube"),
        ("instagram.com", "Instagram"),
        ("twitter.com", "X (formerly Twitter)"),
        ("reddit.com", "Reddit"),
        ("tiktok.com", "TikTok"),
        ("facebook.com", "Facebook"),
        ("linkedin.com", "LinkedIn"),
        ("whatsapp.com", "WhatsApp Web"),
        ("maps.google.com", "Google Maps"),
        ("gmail.com", "Gmail"),
        ("drive.google.com", "Google Drive"),
        ("docs.google.com", "Google Docs"),
        ("wikipedia.org", "Wikipedia"),
        ("stackoverflow.com", "Stack Overflow"),
    ],
    "US": [
        ("amazon.com", "Amazon"),
        ("walmart.com", "Walmart"),
        ("target.com", "Target"),
        ("doordash.com", "DoorDash"),
        ("ubereats.com", "Uber Eats"),
        ("weather.com", "The Weather Channel"),
        ("cnn.com", "CNN"),
        ("espn.com", "ESPN"),
        ("chase.com", "Chase"),
        ("venmo.com", "Venmo"),
        ("zillow.com", "Zillow"),
        ("yelp.com", "Yelp"),
    ],
    "GB": [
        ("amazon.co.uk", "Amazon UK"),
        ("bbc.co.uk", "BBC"),
        ("deliveroo.co.uk", "Deliveroo"),
        ("monzo.com", "Monzo"),
        ("rightmove.co.uk", "Rightmove"),
        ("sky.com", "Sky"),
        ("tesco.com", "Tesco"),
    ],
    "DE": [
        ("amazon.de", "Amazon DE"),
        ("spiegel.de", "Spiegel"),
        ("lieferando.de", "Lieferando"),
        ("n26.com", "N26"),
        ("idealo.de", "Idealo"),
    ],
    "FR": [
        ("amazon.fr", "Amazon FR"),
        ("lemonde.fr", "Le Monde"),
        ("leboncoin.fr", "Leboncoin"),
        ("deliveroo.fr", "Deliveroo"),
    ],
}

# Mobile-specific paths (people browse differently on phones)
MOBILE_PATHS = [
    "/", "/search", "/login", "/account", "/orders", "/cart",
    "/notifications", "/messages", "/feed", "/trending", "/explore",
    "/settings", "/profile", "/app/download",
]

# ═══════════════════════════════════════════════════════════════════════
# TRUST ANCHOR COOKIES (Android Chrome)
# ═══════════════════════════════════════════════════════════════════════

COOKIE_ANCHORS = {
    "google.com": [
        ("SID", 32), ("HSID", 16), ("SSID", 16), ("APISID", 16),
        ("SAPISID", 16), ("NID", 64),
        ("1P_JAR", 0),  # 0 = date-formatted
    ],
    "youtube.com": [
        ("VISITOR_INFO1_LIVE", 16), ("YSC", 8), ("PREF", 0),
    ],
    "facebook.com": [
        ("c_user", 0), ("xs", 32), ("fr", 24), ("datr", 16),
    ],
    "instagram.com": [
        ("sessionid", 32), ("csrftoken", 24), ("mid", 16),
    ],
    "twitter.com": [
        ("auth_token", 24), ("ct0", 32), ("guest_id", 0),
    ],
}

COMMERCE_COOKIES = [
    (".stripe.com", "__stripe_mid", 32),
    (".stripe.com", "__stripe_sid", 16),
    (".paypal.com", "TLTSID", 32),
    (".paypal.com", "ts", 16),
    (".shopify.com", "_shopify_y", 32),
    (".amazon.com", "at-main", 40),
    (".amazon.com", "session-id", 16),
    (".amazon.com", "ubid-main", 16),
    (".klarna.com", "klarna_client_id", 0),
]


# ═══════════════════════════════════════════════════════════════════════
# ARCHETYPE-DRIVEN CIRCADIAN PROFILES
# ═══════════════════════════════════════════════════════════════════════

# Per-archetype activity patterns replace the single static CIRCADIAN_WEIGHTS
# Each array: 24 hourly weights (0=midnight). ±15% random perturbation
# is applied per profile instance for macro-diversity.

ARCHETYPE_PROFILES = {
    "professional": [
        0.03, 0.02, 0.01, 0.01, 0.01, 0.03,   # 00-05 (sleeping)
        0.08, 0.18, 0.25, 0.22, 0.18, 0.15,   # 06-11 (morning commute + work)
        0.28, 0.20, 0.16, 0.14, 0.15, 0.18,   # 12-17 (lunch + afternoon)
        0.25, 0.30, 0.28, 0.18, 0.10, 0.05,   # 18-23 (evening wind-down)
    ],
    "student": [
        0.12, 0.08, 0.05, 0.02, 0.01, 0.01,   # 00-05 (late night active)
        0.02, 0.05, 0.10, 0.15, 0.20, 0.22,   # 06-11 (late morning ramp)
        0.18, 0.15, 0.20, 0.25, 0.18, 0.15,   # 12-17 (afternoon classes)
        0.20, 0.28, 0.35, 0.38, 0.30, 0.20,   # 18-23 (evening peak)
    ],
    "night_shift": [
        0.25, 0.28, 0.30, 0.28, 0.25, 0.20,   # 00-05 (active at work)
        0.15, 0.08, 0.03, 0.02, 0.02, 0.03,   # 06-11 (going to sleep)
        0.02, 0.02, 0.03, 0.05, 0.08, 0.10,   # 12-17 (waking up)
        0.15, 0.18, 0.20, 0.22, 0.25, 0.28,   # 18-23 (evening prep + commute)
    ],
    "retiree": [
        0.02, 0.01, 0.01, 0.01, 0.02, 0.05,   # 00-05 (early to bed)
        0.15, 0.25, 0.28, 0.25, 0.22, 0.20,   # 06-11 (early riser)
        0.22, 0.18, 0.15, 0.12, 0.10, 0.12,   # 12-17 (afternoon quiet)
        0.15, 0.12, 0.08, 0.05, 0.03, 0.02,   # 18-23 (early evening taper)
    ],
    "gamer": [
        0.15, 0.10, 0.05, 0.02, 0.01, 0.01,   # 00-05 (late night gaming)
        0.02, 0.05, 0.08, 0.10, 0.12, 0.14,   # 06-11 (slow morning)
        0.16, 0.15, 0.14, 0.16, 0.18, 0.20,   # 12-17 (afternoon sessions)
        0.25, 0.32, 0.38, 0.35, 0.30, 0.22,   # 18-23 (peak gaming hours)
    ],
}

# Legacy fallback
CIRCADIAN_WEIGHTS = ARCHETYPE_PROFILES["professional"]


def _get_archetype_weights(archetype: str, rng: random.Random) -> List[float]:
    """Get circadian weights for an archetype with ±15% random perturbation."""
    base = ARCHETYPE_PROFILES.get(archetype, ARCHETYPE_PROFILES["professional"])
    # Apply per-instance macro-diversity
    perturbed = [max(0.001, w * rng.uniform(0.85, 1.15)) for w in base]
    return perturbed


def _circadian_hour(rng: random.Random, weights: Optional[List[float]] = None) -> int:
    """Pick an hour weighted by circadian rhythm."""
    if weights is None:
        weights = CIRCADIAN_WEIGHTS
    return rng.choices(range(24), weights=weights, k=1)[0]


def _random_datetime(rng: random.Random, base: datetime, days_ago_min: int,
                     days_ago_max: int, weights: Optional[List[float]] = None,
                     tz_offset_hours: float = 0.0) -> datetime:
    """Generate a random datetime within a day range, circadian-weighted.

    Args:
        tz_offset_hours: UTC offset for the profile's locale (e.g. -5 for EST).
            Circadian weights are applied in local time.
    """
    day_offset = rng.randint(days_ago_min, days_ago_max)
    # Pick hour in local time, then convert to UTC
    local_hour = _circadian_hour(rng, weights)
    utc_hour = int((local_hour - tz_offset_hours) % 24)
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    dt = base - timedelta(days=day_offset)
    return dt.replace(hour=utc_hour, minute=minute, second=second)


# ═══════════════════════════════════════════════════════════════════════
# ANDROID PROFILE FORGE
# ═══════════════════════════════════════════════════════════════════════

class AndroidProfileForge:
    """Forges complete Android device profiles tied to a persona."""

    def __init__(self):
        self._rng: Optional[random.Random] = None

    def forge(self,
              persona_name: str = "Alex Mercer",
              persona_email: str = "alex.mercer@gmail.com",
              persona_phone: str = "+12125551234",
              country: str = "US",
              archetype: str = "professional",
              age_days: int = 90,
              carrier: str = "tmobile_us",
              location: str = "nyc",
              device_model: str = "samsung_s25_ultra",
              persona_address: Optional[Dict[str, str]] = None,
              persona_area_code: str = "",
              city_area_codes: Optional[List[str]] = None,
              ) -> Dict[str, Any]:
        """
        Forge a complete Android device profile.

        Returns a dict containing all data needed by ProfileInjector:
            cookies, history, contacts, call_logs, sms, gallery_paths,
            autofill, wifi_networks, app_installs, local_storage
        """
        # Seed RNG from persona for deterministic output
        seed_str = f"{persona_name}:{persona_email}:{age_days}"
        seed = int(hashlib.sha256(seed_str.encode()).hexdigest()[:16], 16)
        self._rng = random.Random(seed)

        profile_id = f"TITAN-{secrets.token_hex(4).upper()}"
        now = datetime.now()
        profile_birth = now - timedelta(days=age_days)

        logger.info(f"Forging Android profile: {profile_id} for {persona_name}")
        logger.info(f"  Country: {country}, Age: {age_days}d, Archetype: {archetype}")

        # Compute archetype-driven circadian weights with per-instance diversity
        circadian_weights = _get_archetype_weights(archetype, self._rng)

        # Timezone offset for locale-aware datetime generation
        TZ_OFFSETS = {
            "US": -5.0, "GB": 0.0, "DE": 1.0, "FR": 1.0,
        }
        tz_offset = TZ_OFFSETS.get(country.upper()[:2], -5.0)

        # Parse persona
        parts = persona_name.split(None, 1)
        first_name = parts[0] if parts else "Alex"
        last_name = parts[1] if len(parts) > 1 else "Mercer"

        locale = country.upper()[:2]
        name_pool = NAME_POOLS.get(locale, NAME_POOLS["US"])

        # ─── Generate contacts (with persona area codes) ──────────────
        extra_area_codes = []
        if persona_area_code:
            extra_area_codes.append(persona_area_code)
        if city_area_codes:
            extra_area_codes.extend(city_area_codes[:4])
        contacts = self._forge_contacts(name_pool, locale, age_days, extra_area_codes=extra_area_codes)

        # ─── Generate call logs ───────────────────────────────────────
        call_logs = self._forge_call_logs(contacts, now, age_days,
                                           circadian_weights, tz_offset)

        # ─── Generate SMS ─────────────────────────────────────────────
        sms = self._forge_sms(contacts, now, age_days, circadian_weights, tz_offset)

        # ─── Generate Chrome mobile cookies ───────────────────────────
        cookies = self._forge_cookies(now, profile_birth, locale)

        # ─── Generate Chrome mobile history ───────────────────────────
        history = self._forge_history(now, age_days, locale)

        # ─── Generate gallery photos ──────────────────────────────────
        gallery_paths = self._forge_gallery(now, age_days)

        # ─── Generate autofill (use persona's real address if provided) ─
        if persona_address and persona_address.get("address"):
            address = persona_address
        else:
            address = self._forge_address(locale)
        autofill = {
            "name": persona_name,
            "first_name": first_name,
            "last_name": last_name,
            "email": persona_email,
            "phone": persona_phone,
            "address": address,
        }

        # ─── WiFi networks ───────────────────────────────────────────
        wifi_networks = self._forge_wifi(locale, location)

        # ─── App install timestamps ───────────────────────────────────
        app_installs = self._forge_app_installs(now, age_days, locale)

        # ─── Play Store purchase history ─────────────────────────────
        play_purchases = self._forge_play_purchases(now, age_days, persona_email, locale)

        # ─── App usage stats ─────────────────────────────────────────
        app_usage = self._forge_app_usage(now, age_days, locale)

        # ─── Notification history ────────────────────────────────────
        notifications = self._forge_notifications(now, age_days, locale)

        # ─── Email receipts ──────────────────────────────────────────
        email_receipts = self._forge_email_receipts(now, age_days, persona_email, locale)

        # ─── Build final profile ──────────────────────────────────────
        profile = {
            "id": profile_id,
            "uuid": profile_id,
            "persona_name": persona_name,
            "persona_email": persona_email,
            "persona_phone": persona_phone,
            "country": country,
            "archetype": archetype,
            "age_days": age_days,
            "carrier": carrier,
            "location": location,
            "device_model": device_model,
            "created_at": now.isoformat(),
            "profile_birth": profile_birth.isoformat(),
            # Injection data
            "contacts": contacts,
            "call_logs": call_logs,
            "sms": sms,
            "cookies": cookies,
            "history": history,
            "gallery_paths": gallery_paths,
            "autofill": autofill,
            "wifi_networks": wifi_networks,
            "app_installs": app_installs,
            "play_purchases": play_purchases,
            "app_usage": app_usage,
            "notifications": notifications,
            "email_receipts": email_receipts,
            "local_storage": {},
            # Stats
            "stats": {
                "contacts": len(contacts),
                "call_logs": len(call_logs),
                "sms": len(sms),
                "cookies": len(cookies),
                "history": len(history),
                "gallery": len(gallery_paths),
                "apps": len(app_installs),
                "wifi": len(wifi_networks),
                "play_purchases": len(play_purchases),
                "app_usage": len(app_usage),
                "notifications": len(notifications),
                "email_receipts": len(email_receipts),
            },
        }

        # Save to disk
        self._save_profile(profile)

        logger.info(f"Profile forged: {profile_id}")
        logger.info(f"  Contacts: {len(contacts)}, Calls: {len(call_logs)}, SMS: {len(sms)}")
        logger.info(f"  Cookies: {len(cookies)}, History: {len(history)}, Gallery: {len(gallery_paths)}")
        return profile

    # ─── CONTACTS ─────────────────────────────────────────────────────

    def _forge_contacts(self, name_pool: dict, locale: str, age_days: int,
                         extra_area_codes: Optional[List[str]] = None) -> List[Dict]:
        """Generate persona-consistent contacts with persona's area codes."""
        rng = self._rng
        num_contacts = rng.randint(10, 22)
        area_codes = name_pool.get("area_codes", ["212", "646", "718"])
        # Mix in persona's area codes (from their phone + city)
        if extra_area_codes:
            area_codes = list(extra_area_codes) + [c for c in area_codes if c not in extra_area_codes]
        contacts = []

        # Mix of male and female names
        for i in range(num_contacts):
            if rng.random() < 0.5:
                first = rng.choice(name_pool.get("first_male", ["John"]))
            else:
                first = rng.choice(name_pool.get("first_female", ["Jane"]))
            last = rng.choice(name_pool.get("last", ["Smith"]))

            area = rng.choice(area_codes)
            if locale == "US":
                phone = f"+1{area}{''.join([str(rng.randint(0,9)) for _ in range(7)])}"
            elif locale == "GB":
                phone = f"+44{area[1:]}{''.join([str(rng.randint(0,9)) for _ in range(7)])}"
            elif locale == "DE":
                phone = f"+49{area[1:]}{''.join([str(rng.randint(0,9)) for _ in range(7)])}"
            elif locale == "FR":
                phone = f"+33{area}{''.join([str(rng.randint(0,9)) for _ in range(8)])}"
            else:
                phone = f"+1{area}{''.join([str(rng.randint(0,9)) for _ in range(7)])}"

            email = ""
            if rng.random() < 0.4:  # 40% have email
                email_user = f"{first.lower()}.{last.lower()}{rng.randint(1,99)}"
                email = f"{email_user}@{rng.choice(['gmail.com', 'yahoo.com', 'outlook.com', 'icloud.com'])}"

            contacts.append({
                "name": f"{first} {last}",
                "phone": phone,
                "email": email,
                "relationship": rng.choice(["friend", "friend", "friend", "family", "work", "work", "other"]),
            })

        # Add special contacts
        contacts.append({"name": "Mom", "phone": contacts[0]["phone"].replace(contacts[0]["phone"][-4:], str(rng.randint(1000,9999))), "email": "", "relationship": "family"})
        contacts.append({"name": "Voicemail", "phone": "*86", "email": "", "relationship": "other"})

        return contacts

    # ─── CALL LOGS ────────────────────────────────────────────────────

    def _forge_call_logs(self, contacts: List[Dict], now: datetime, age_days: int,
                          circadian_weights: Optional[List[float]] = None,
                          tz_offset: float = 0.0) -> List[Dict]:
        """Generate realistic call history spread over profile age."""
        rng = self._rng
        # ~1.5 calls/day on average
        _lo = max(20, age_days)
        _hi = max(_lo, min(age_days * 3, 1500))
        num_calls = rng.randint(_lo, _hi)
        logs = []

        # Weight: more calls to frequent contacts (Pareto)
        contact_weights = [1.0 / (i + 1) ** 0.8 for i in range(len(contacts))]

        for _ in range(num_calls):
            contact = rng.choices(contacts, weights=contact_weights[:len(contacts)], k=1)[0]
            dt = _random_datetime(rng, now, 0, age_days, circadian_weights, tz_offset)
            call_type = rng.choices([1, 2, 3], weights=[35, 45, 20], k=1)[0]  # in/out/missed

            duration = 0
            if call_type == 1:  # incoming
                duration = rng.choices(
                    [rng.randint(5, 30), rng.randint(30, 180), rng.randint(180, 900)],
                    weights=[40, 40, 20], k=1
                )[0]
            elif call_type == 2:  # outgoing
                duration = rng.choices(
                    [rng.randint(5, 20), rng.randint(20, 120), rng.randint(120, 600)],
                    weights=[30, 50, 20], k=1
                )[0]
            # missed = 0

            logs.append({
                "number": contact["phone"],
                "type": call_type,
                "duration": duration,
                "date": int(dt.timestamp() * 1000),
            })

        logs.sort(key=lambda x: x["date"], reverse=True)
        return logs

    # ─── SMS ──────────────────────────────────────────────────────────

    def _forge_sms(self, contacts: List[Dict], now: datetime, age_days: int,
                    circadian_weights: Optional[List[float]] = None,
                    tz_offset: float = 0.0) -> List[Dict]:
        """Generate SMS conversation threads with Poisson burst clustering."""
        rng = self._rng
        messages = []

        # Pick 4-8 contacts to have SMS threads with
        sms_contacts = rng.sample(contacts[:min(12, len(contacts))], min(rng.randint(4, 8), len(contacts)))

        for contact in sms_contacts:
            # Pick 1-3 conversation templates for this contact
            relationship = contact.get("relationship", "friend")
            if relationship == "family":
                templates = rng.sample(["family", "casual", "appointment"], min(2, 3))
            elif relationship == "work":
                templates = rng.sample(["work", "appointment"], min(1, 2))
            else:
                templates = rng.sample(["casual", "friend_plan", "otp", "delivery"], min(2, 4))

            for tmpl_key in templates:
                tmpl = SMS_TEMPLATES.get(tmpl_key, SMS_TEMPLATES["casual"])
                thread_start = _random_datetime(rng, now, 1, min(age_days, 60),
                                                 circadian_weights, tz_offset)

                # Relational dialogue: messages in a thread are sequential
                # with natural inter-message timing (1-15 minutes)
                for idx, (body, direction) in enumerate(tmpl):
                    msg_time = thread_start + timedelta(minutes=idx * rng.randint(1, 15))
                    msg_type = 1 if direction == "in" else 2  # 1=received, 2=sent

                    messages.append({
                        "address": contact["phone"],
                        "body": body,
                        "type": msg_type,
                        "date": int(msg_time.timestamp() * 1000),
                    })

            # Poisson burst: 20% chance of a rapid-fire burst with this contact
            if rng.random() < 0.20:
                burst_size = rng.randint(5, 25)
                burst_start = _random_datetime(rng, now, 0, min(age_days, 30),
                                                circadian_weights, tz_offset)
                for b in range(burst_size):
                    # 15-120 second gaps within a burst
                    msg_time = burst_start + timedelta(seconds=b * rng.randint(15, 120))
                    direction = rng.choice(["in", "out"])
                    # Quick burst messages
                    burst_bodies = [
                        "lol", "yeah", "ok", "😂", "no way", "fr", "bet",
                        "omg", "same", "haha", "facts", "wya", "otw",
                        "yep", "nah", "👍", "bruh", "one sec", "?",
                    ]
                    messages.append({
                        "address": contact["phone"],
                        "body": rng.choice(burst_bodies),
                        "type": 1 if direction == "in" else 2,
                        "date": int(msg_time.timestamp() * 1000),
                    })

        # Add bank/OTP messages from short codes
        for _ in range(rng.randint(3, 8)):
            tmpl = rng.choice([SMS_TEMPLATES["bank"], SMS_TEMPLATES["otp"]])
            for body, direction in tmpl:
                dt = _random_datetime(rng, now, 0, min(age_days, 30),
                                       circadian_weights, tz_offset)
                messages.append({
                    "address": rng.choice(["72000", "33663", "89203", "22395", "CHASE", "PAYPAL"]),
                    "body": body,
                    "type": 1,
                    "date": int(dt.timestamp() * 1000),
                })

        messages.sort(key=lambda x: x["date"], reverse=True)
        return messages

    # ─── CHROME COOKIES ───────────────────────────────────────────────

    def _forge_cookies(self, now: datetime, birth: datetime, locale: str) -> List[Dict]:
        """Generate Chrome mobile trust anchor + commerce cookies."""
        rng = self._rng
        cookies = []

        # Trust anchors
        for domain, cookie_defs in COOKIE_ANCHORS.items():
            for name, hex_len in cookie_defs:
                if hex_len == 0:
                    if name == "1P_JAR":
                        value = f"{now.year}-{now.month:02d}-{now.day:02d}-{rng.randint(10,23)}"
                    elif name == "c_user":
                        value = str(rng.randint(100000000, 999999999))
                    elif name == "guest_id":
                        value = f"v1%3A{int(now.timestamp() * 1000)}"
                    elif name == "PREF":
                        value = f"tz=America.New_York&f6={rng.randint(10000,99999)}"
                    elif name == "klarna_client_id":
                        value = str(uuid.uuid4())
                    else:
                        value = secrets.token_hex(16)
                else:
                    value = secrets.token_hex(hex_len)

                creation_days_ago = rng.randint(7, min(90, max(7, int(
                    (now - birth).days * 0.8
                ))))

                cookies.append({
                    "domain": f".{domain}",
                    "name": name,
                    "value": value,
                    "path": "/",
                    "secure": True,
                    "httponly": name not in ("1P_JAR", "PREF", "guest_id"),
                    "samesite": -1,
                    "max_age": 31536000,
                    "creation_days_ago": creation_days_ago,
                })

        # Commerce cookies (pick 5-8 randomly)
        selected_commerce = rng.sample(COMMERCE_COOKIES, min(rng.randint(5, 8), len(COMMERCE_COOKIES)))
        for domain, name, hex_len in selected_commerce:
            value = str(uuid.uuid4()) if hex_len == 0 else secrets.token_hex(hex_len)
            cookies.append({
                "domain": domain,
                "name": name,
                "value": value,
                "path": "/",
                "secure": True,
                "httponly": False,
                "samesite": -1,
                "max_age": 31536000,
                "creation_days_ago": rng.randint(14, min(60, max(14, int((now - birth).days * 0.6)))),
            })

        return cookies

    # ─── CHROME HISTORY ───────────────────────────────────────────────

    def _forge_history(self, now: datetime, age_days: int, locale: str) -> List[Dict]:
        """Generate Chrome mobile browsing history."""
        rng = self._rng
        entries = []

        # Combine global + locale-specific domains
        domains = MOBILE_DOMAINS["global"] + MOBILE_DOMAINS.get(locale, MOBILE_DOMAINS["US"])

        # Pareto: 80% of visits go to 20% of domains
        top_domains = domains[:max(3, len(domains) // 5)]
        other_domains = domains[len(top_domains):]

        # ~8-15 mobile browsing sessions per day
        lo = max(100, age_days * 5)
        hi = max(lo, min(age_days * 15, 800))
        target_entries = rng.randint(lo, hi)

        for _ in range(target_entries):
            # 80% from top domains, 20% from others
            if rng.random() < 0.8 and top_domains:
                domain, title_base = rng.choice(top_domains)
            elif other_domains:
                domain, title_base = rng.choice(other_domains)
            else:
                domain, title_base = rng.choice(domains)

            path = rng.choice(MOBILE_PATHS)
            dt = _random_datetime(rng, now, 0, age_days)
            visits = rng.choices([1, 2, 3, 5, 8], weights=[30, 30, 20, 15, 5], k=1)[0]

            entries.append({
                "url": f"https://www.{domain}{path}",
                "title": f"{title_base} - {path.strip('/').replace('/', ' ').title() or 'Home'}",
                "visits": visits,
                "timestamp": int(dt.timestamp()),
            })

        entries.sort(key=lambda x: x["timestamp"], reverse=True)
        return entries

    # ─── GALLERY PHOTOS ───────────────────────────────────────────────

    def _forge_gallery(self, now: datetime, age_days: int) -> List[str]:
        """Generate placeholder JPEG photos with realistic names."""
        rng = self._rng
        num_photos = rng.randint(12, 30)
        gallery_dir = TITAN_DATA / "forge_gallery"
        gallery_dir.mkdir(parents=True, exist_ok=True)

        paths = []
        for i in range(num_photos):
            dt = _random_datetime(rng, now, 1, age_days)
            fname = f"IMG_{dt.strftime('%Y%m%d')}_{rng.randint(100000, 999999)}.jpg"
            fpath = gallery_dir / fname

            # Create a minimal JPEG placeholder (real deployment uses stock photos)
            if not fpath.exists():
                self._create_placeholder_jpeg(fpath, dt)

            paths.append(str(fpath))

        return paths

    def _create_placeholder_jpeg(self, path: Path, dt: datetime):
        """Create a minimal JPEG file with EXIF date and GPS metadata."""
        try:
            # SOI marker
            data = b'\xff\xd8'
            # APP0 JFIF
            data += b'\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'

            # APP1 EXIF header with DateTimeOriginal and GPS
            exif_data = self._build_exif_segment(dt)
            data += exif_data

            # DQT
            data += b'\xff\xdb\x00C\x00'
            data += bytes([8] * 64)
            # SOF0 (1x1, 1 component)
            data += b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
            # DHT (minimal)
            data += b'\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b'
            # SOS + data + EOI
            data += b'\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x7b\x40'
            data += b'\xff\xd9'

            # Add random bytes to vary file size (look more like real photos)
            padding_size = self._rng.randint(30000, 80000)
            data = data[:-2] + os.urandom(padding_size) + data[-2:]

            path.write_bytes(data)
        except Exception:
            # Fallback: just write random bytes
            path.write_bytes(os.urandom(self._rng.randint(30000, 80000)))

    def _build_exif_segment(self, dt: datetime) -> bytes:
        """Build a minimal EXIF APP1 segment with DateTimeOriginal."""
        # EXIF date string: "YYYY:MM:DD HH:MM:SS"
        date_str = dt.strftime("%Y:%m:%d %H:%M:%S").encode("ascii") + b'\x00'

        # Build TIFF IFD0 with DateTimeOriginal tag (0x9003)
        # Minimal EXIF: just enough to pass forensic checks
        # Tag 0x9003 = DateTimeOriginal, Type=ASCII(2), Count=20
        ifd_entry = struct.pack(">HHI", 0x9003, 2, 20)
        # Value offset: 8 (TIFF header) + 2 (count) + 12 (entry) + 4 (next) = 26
        ifd_entry += struct.pack(">I", 26)

        # TIFF structure: byte order + magic + offset + count + entry + next IFD + data
        tiff = b'MM'                          # Big-endian
        tiff += struct.pack(">H", 42)         # TIFF magic
        tiff += struct.pack(">I", 8)          # Offset to IFD0
        tiff += struct.pack(">H", 1)          # 1 entry
        tiff += ifd_entry                     # The DateTimeOriginal entry
        tiff += struct.pack(">I", 0)          # Next IFD: none
        tiff += date_str                      # DateTimeOriginal value

        # APP1 segment: marker + length + "Exif\0\0" + TIFF
        exif_header = b'Exif\x00\x00'
        payload = exif_header + tiff
        segment = b'\xff\xe1' + struct.pack(">H", len(payload) + 2) + payload
        return segment

    # ─── AUTOFILL ADDRESS ─────────────────────────────────────────────

    def _forge_address(self, locale: str) -> Dict[str, str]:
        """Generate a realistic billing/shipping address."""
        rng = self._rng
        if locale == "US":
            streets = ["Oak St", "Main St", "Maple Ave", "Cedar Ln", "Park Blvd",
                       "Washington Ave", "Broadway", "Market St", "Pine St", "Elm Dr"]
            cities = [("New York", "NY", "10001"), ("Los Angeles", "CA", "90001"),
                      ("Chicago", "IL", "60601"), ("Houston", "TX", "77001"),
                      ("Miami", "FL", "33101"), ("Seattle", "WA", "98101"),
                      ("San Francisco", "CA", "94102"), ("Austin", "TX", "78701")]
            city, state, zip_base = rng.choice(cities)
            return {
                "address": f"{rng.randint(100, 9999)} {rng.choice(streets)}",
                "apt": f"Apt {rng.randint(1, 12)}{'ABCDEF'[rng.randint(0,5)]}" if rng.random() < 0.3 else "",
                "city": city, "state": state,
                "zip": f"{int(zip_base) + rng.randint(0, 99):05d}",
                "country": "US",
            }
        elif locale == "GB":
            return {
                "address": f"{rng.randint(1, 200)} {rng.choice(['High Street', 'Church Road', 'Station Road', 'Victoria Street'])}",
                "city": rng.choice(["London", "Manchester", "Birmingham", "Leeds"]),
                "state": "", "zip": f"{''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=2))}{rng.randint(1,9)} {rng.randint(1,9)}{''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=2))}",
                "country": "GB",
            }
        else:
            return {"address": f"{rng.randint(1, 100)} Hauptstr.", "city": "Berlin",
                    "state": "", "zip": f"{rng.randint(10000, 99999)}", "country": locale}

    # ─── WIFI NETWORKS ────────────────────────────────────────────────

    def _forge_wifi(self, locale: str, location: str) -> List[Dict]:
        """Generate saved WiFi network list."""
        rng = self._rng

        home_ssids = {
            "US": ["NETGEAR72-5G", "Xfinity-Home", "ATT-FIBER-5G", "Spectrum-5G-Plus",
                   "Google-Fiber", "Verizon-5G-Home", "TP-Link_5G_A3B2"],
            "GB": ["BT-Hub6-5G", "Sky-WiFi-Home", "Virgin-Media-5G", "TalkTalk-5G"],
            "DE": ["FRITZ!Box-7590", "Telekom-5G", "Vodafone-Home-5G", "o2-WLAN"],
            "FR": ["Livebox-5G", "Freebox-5G", "SFR-Home", "Bouygues-5G"],
        }

        ssid_pool = home_ssids.get(locale, home_ssids["US"])
        networks = [
            {"ssid": rng.choice(ssid_pool), "type": "home", "frequency": "5GHz"},
            {"ssid": f"Starbucks-{rng.choice(['Guest', 'WiFi', 'Free'])}", "type": "public", "frequency": "2.4GHz"},
        ]

        if rng.random() < 0.6:
            networks.append({"ssid": f"{''.join(rng.choices(string.ascii_uppercase, k=4))}-Office", "type": "work", "frequency": "5GHz"})
        if rng.random() < 0.3:
            networks.append({"ssid": f"Airport-Free-WiFi", "type": "public", "frequency": "2.4GHz"})

        return networks

    # ─── APP INSTALLS ─────────────────────────────────────────────────

    def _forge_app_installs(self, now: datetime, age_days: int, locale: str) -> List[Dict]:
        """Generate backdated app install timestamps."""
        rng = self._rng

        # Core apps that come with the device (day 0)
        core_apps = [
            ("com.android.chrome", "Chrome", 0),
            ("com.google.android.gms", "Google Play services", 0),
            ("com.android.vending", "Play Store", 0),
            ("com.google.android.youtube", "YouTube", 0),
            ("com.google.android.apps.maps", "Maps", 0),
            ("com.google.android.gm", "Gmail", 0),
        ]

        # User-installed apps (installed over time)
        user_apps_us = [
            ("com.instagram.android", "Instagram", rng.randint(1, 10)),
            ("com.whatsapp", "WhatsApp", rng.randint(1, 5)),
            ("com.snapchat.android", "Snapchat", rng.randint(3, 20)),
            ("com.venmo", "Venmo", rng.randint(5, 30)),
            ("com.squareup.cash", "Cash App", rng.randint(10, 40)),
            ("com.ubercab", "Uber", rng.randint(5, 25)),
            ("com.dd.doordash", "DoorDash", rng.randint(7, 35)),
            ("com.spotify.music", "Spotify", rng.randint(2, 15)),
            ("com.amazon.mShop.android.shopping", "Amazon", rng.randint(3, 20)),
            ("com.chase.sig.android", "Chase", rng.randint(5, 25)),
            ("org.telegram.messenger", "Telegram", rng.randint(10, 40)),
        ]

        user_apps_gb = [
            ("com.instagram.android", "Instagram", rng.randint(1, 10)),
            ("com.whatsapp", "WhatsApp", rng.randint(1, 3)),
            ("com.monzo.android", "Monzo", rng.randint(5, 20)),
            ("com.revolut.revolut", "Revolut", rng.randint(5, 25)),
            ("com.deliveroo.orderapp", "Deliveroo", rng.randint(7, 30)),
            ("com.spotify.music", "Spotify", rng.randint(2, 15)),
            ("com.bbc.iplayer", "BBC iPlayer", rng.randint(3, 20)),
        ]

        app_pool = user_apps_us if locale == "US" else user_apps_gb if locale == "GB" else user_apps_us

        # Not everyone installs all apps — pick 6-10
        selected = rng.sample(app_pool, min(rng.randint(6, 10), len(app_pool)))

        installs = []
        for pkg, name, install_day in core_apps:
            dt = now - timedelta(days=min(age_days, age_days))
            installs.append({
                "package": pkg, "name": name,
                "install_time": int(dt.timestamp() * 1000),
                "is_system": True,
            })

        for pkg, name, install_day_offset in selected:
            actual_day = min(install_day_offset, age_days - 1)
            dt = now - timedelta(days=age_days - actual_day)
            installs.append({
                "package": pkg, "name": name,
                "install_time": int(dt.timestamp() * 1000),
                "is_system": False,
            })

        return installs

    # ─── PLAY STORE PURCHASES ──────────────────────────────────────────

    def _forge_play_purchases(self, now: datetime, age_days: int,
                              persona_email: str, locale: str) -> List[Dict]:
        """Generate Play Store purchase history (apps, subscriptions, IAPs)."""
        rng = self._rng
        purchases = []

        # Free app installs (lots of these — 30-80 over profile age)
        free_apps = [
            ("com.whatsapp", "WhatsApp Messenger", 0),
            ("com.instagram.android", "Instagram", 0),
            ("com.spotify.music", "Spotify: Music and Podcasts", 0),
            ("com.netflix.mediaclient", "Netflix", 0),
            ("com.twitter.android", "X", 0),
            ("com.zhiliaoapp.musically", "TikTok", 0),
            ("com.snapchat.android", "Snapchat", 0),
            ("com.ubercab", "Uber - Request a ride", 0),
            ("com.dd.doordash", "DoorDash - Food Delivery", 0),
            ("com.weather.Weather", "The Weather Channel", 0),
            ("com.shazam.android", "Shazam: Find Music & Concerts", 0),
            ("com.duolingo", "Duolingo: Language Lessons", 0),
            ("com.google.android.apps.fitness", "Google Fit", 0),
            ("com.amazon.mShop.android.shopping", "Amazon Shopping", 0),
            ("com.ebay.mobile", "eBay: Online Shopping Deals", 0),
            ("org.telegram.messenger", "Telegram", 0),
            ("com.google.android.keep", "Google Keep", 0),
            ("com.google.android.apps.photos", "Google Photos", 0),
        ]

        num_free = rng.randint(30, min(80, len(free_apps) + 60))
        selected_free = rng.sample(free_apps, min(num_free, len(free_apps)))
        for pkg, name, _ in selected_free:
            install_day = rng.randint(1, max(2, age_days - 1))
            dt = now - timedelta(days=install_day)
            purchases.append({
                "account": persona_email,
                "doc_id": pkg,
                "doc_type": 1,  # app
                "title": name,
                "offer_type": 1,  # free
                "price_micros": 0,
                "currency": "USD" if locale == "US" else "GBP" if locale == "GB" else "EUR",
                "purchase_time": int(dt.timestamp() * 1000),
            })

        # Paid app purchases (1-4)
        paid_apps = [
            ("com.weather.forecast.channel.smart", "Weather Forecast Pro", 299),
            ("com.nianticlabs.pokemongo", "Pokémon GO (coins)", 999),
            ("com.mojang.minecraftpe", "Minecraft", 699),
            ("org.videolan.vlc", "VLC for Android (donate)", 199),
            ("com.teslacoilsw.launcher.prime", "Nova Launcher Prime", 499),
        ]
        num_paid = rng.randint(1, min(4, len(paid_apps)))
        for pkg, name, price in rng.sample(paid_apps, num_paid):
            dt = _random_datetime(rng, now, 5, min(age_days, 60))
            purchases.append({
                "account": persona_email,
                "doc_id": pkg,
                "doc_type": 1,
                "title": name,
                "offer_type": 2,  # paid
                "price_micros": price * 1000,
                "currency": "USD" if locale == "US" else "GBP" if locale == "GB" else "EUR",
                "purchase_time": int(dt.timestamp() * 1000),
            })

        # Subscriptions (1-3)
        subs = [
            ("com.spotify.music", "Spotify Premium", 999, 30),
            ("com.google.android.youtube", "YouTube Premium", 1399, 30),
            ("com.google.android.apps.subscriptions.red", "Google One (100GB)", 199, 30),
        ]
        num_subs = rng.randint(1, min(3, len(subs)))
        for pkg, name, price, interval in rng.sample(subs, num_subs):
            # First purchase backdated, then recurring
            first_dt = now - timedelta(days=rng.randint(min(30, age_days), max(30, min(age_days, 90))))
            purchases.append({
                "account": persona_email,
                "doc_id": f"{pkg}:subs",
                "doc_type": 4,  # subscription
                "title": name,
                "offer_type": 3,  # subscription
                "price_micros": price * 1000,
                "currency": "USD" if locale == "US" else "GBP" if locale == "GB" else "EUR",
                "purchase_time": int(first_dt.timestamp() * 1000),
                "auto_renewing": True,
                "renewal_interval_days": interval,
            })

        purchases.sort(key=lambda x: x["purchase_time"], reverse=True)
        return purchases

    # ─── APP USAGE STATS ───────────────────────────────────────────────

    def _forge_app_usage(self, now: datetime, age_days: int, locale: str) -> List[Dict]:
        """Generate per-app usage statistics (daily open counts, screen time)."""
        rng = self._rng

        # App usage patterns: (package, avg_daily_minutes, open_frequency)
        usage_patterns = [
            ("com.android.chrome", rng.randint(15, 45), 0.85),
            ("com.instagram.android", rng.randint(20, 60), 0.75),
            ("com.whatsapp", rng.randint(15, 40), 0.90),
            ("com.google.android.youtube", rng.randint(20, 50), 0.70),
            ("com.google.android.gm", rng.randint(5, 15), 0.80),
            ("com.google.android.apps.maps", rng.randint(3, 10), 0.30),
            ("com.spotify.music", rng.randint(30, 90), 0.60),
            ("com.android.vending", rng.randint(2, 8), 0.40),
        ]

        if locale == "US":
            usage_patterns.extend([
                ("com.venmo", rng.randint(2, 8), 0.25),
                ("com.dd.doordash", rng.randint(3, 10), 0.20),
                ("com.amazon.mShop.android.shopping", rng.randint(5, 15), 0.35),
                ("com.chase.sig.android", rng.randint(2, 5), 0.30),
            ])
        elif locale == "GB":
            usage_patterns.extend([
                ("com.monzo.android", rng.randint(2, 8), 0.35),
                ("com.deliveroo.orderapp", rng.randint(3, 8), 0.20),
                ("com.revolut.revolut", rng.randint(2, 5), 0.25),
            ])

        usage_stats = []
        for pkg, avg_minutes, frequency in usage_patterns:
            # Generate daily stats for the last 14 days
            daily_stats = []
            for day_offset in range(min(14, age_days)):
                if rng.random() > frequency:
                    continue  # Didn't use app that day
                dt = now - timedelta(days=day_offset)
                opens = rng.randint(1, max(2, int(avg_minutes / 5)))
                minutes = max(1, int(avg_minutes * rng.uniform(0.3, 1.8)))
                daily_stats.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "opens": opens,
                    "minutes": minutes,
                    "last_open": int(dt.replace(
                        hour=_circadian_hour(rng),
                        minute=rng.randint(0, 59),
                    ).timestamp() * 1000),
                })

            if daily_stats:
                total_minutes = sum(d["minutes"] for d in daily_stats)
                total_opens = sum(d["opens"] for d in daily_stats)
                usage_stats.append({
                    "package": pkg,
                    "total_minutes": total_minutes,
                    "total_opens": total_opens,
                    "avg_daily_minutes": total_minutes // max(len(daily_stats), 1),
                    "days_active": len(daily_stats),
                    "last_used": max(d["last_open"] for d in daily_stats),
                    "daily": daily_stats,
                })

        usage_stats.sort(key=lambda x: x["total_minutes"], reverse=True)
        return usage_stats

    # ─── NOTIFICATION HISTORY ──────────────────────────────────────────

    def _forge_notifications(self, now: datetime, age_days: int, locale: str) -> List[Dict]:
        """Generate recent notification records (last 7 days)."""
        rng = self._rng
        notifications = []

        # Notification templates: (package, title_template, body_template, frequency_per_day)
        notif_templates = [
            ("com.google.android.gm", "New email from {sender}",
             "{subject}", 3.0),
            ("com.whatsapp", "{contact}: {message}",
             "", 5.0),
            ("com.instagram.android", "{user} liked your photo",
             "", 2.0),
            ("com.android.vending", "Update available",
             "{app} update ready to install", 0.5),
        ]

        if locale == "US":
            notif_templates.extend([
                ("com.chase.sig.android", "Transaction alert",
                 "Purchase of ${amount} at {merchant} approved", 0.8),
                ("com.dd.doordash", "Your order is on the way!",
                 "Estimated arrival: {time}", 0.3),
                ("com.venmo", "{person} paid you ${amount}",
                 "", 0.2),
            ])
        elif locale == "GB":
            notif_templates.extend([
                ("com.monzo.android", "Payment",
                 "You spent £{amount} at {merchant}", 0.8),
                ("com.deliveroo.orderapp", "Your food is being prepared",
                 "Estimated delivery: {time}", 0.3),
            ])

        # Generic fillers
        senders = ["Sarah", "Mike", "Amazon", "LinkedIn", "DoorDash", "Mom", "Work"]
        subjects = ["Meeting tomorrow", "Your order shipped", "Weekly summary",
                    "New connection request", "Receipt for your purchase"]
        contacts = ["Mom", "Sarah", "Mike", "Dave", "Work Group"]
        merchants = ["WALMART", "STARBUCKS", "TARGET", "AMAZON", "SHELL", "UBER"]
        apps_to_update = ["Instagram", "WhatsApp", "Chrome", "YouTube", "Spotify"]

        for day_offset in range(min(7, age_days)):
            dt_base = now - timedelta(days=day_offset)
            for pkg, title_tmpl, body_tmpl, freq in notif_templates:
                # Poisson-like: some days more, some less
                count = max(0, int(freq * rng.uniform(0.2, 2.0)))
                for _ in range(count):
                    dt = dt_base.replace(
                        hour=_circadian_hour(rng),
                        minute=rng.randint(0, 59),
                        second=rng.randint(0, 59),
                    )
                    title = title_tmpl.format(
                        sender=rng.choice(senders),
                        contact=rng.choice(contacts),
                        user=rng.choice(contacts),
                        person=rng.choice(contacts),
                        message="Hey! Are you free?",
                        app=rng.choice(apps_to_update),
                        amount=f"{rng.randint(5, 200)}.{rng.randint(0, 99):02d}",
                        merchant=rng.choice(merchants),
                        time=f"{rng.randint(15, 45)} min",
                        subject=rng.choice(subjects),
                    )
                    body = body_tmpl.format(
                        sender=rng.choice(senders),
                        subject=rng.choice(subjects),
                        amount=f"{rng.randint(5, 200)}.{rng.randint(0, 99):02d}",
                        merchant=rng.choice(merchants),
                        time=f"{rng.randint(15, 45)} min",
                        app=rng.choice(apps_to_update),
                    ) if body_tmpl else ""

                    notifications.append({
                        "package": pkg,
                        "title": title,
                        "body": body,
                        "timestamp": int(dt.timestamp() * 1000),
                        "seen": rng.random() < 0.8,
                    })

        notifications.sort(key=lambda x: x["timestamp"], reverse=True)
        return notifications

    # ─── EMAIL RECEIPTS ────────────────────────────────────────────────

    def _forge_email_receipts(self, now: datetime, age_days: int,
                              persona_email: str, locale: str) -> List[Dict]:
        """Generate purchase confirmation email records for cross-validation."""
        rng = self._rng
        receipts = []

        if locale == "US":
            merchants = [
                ("Amazon.com", "order@amazon.com", "Your Amazon.com order of {item}",
                 ["Echo Dot", "USB-C Cable", "Phone Case", "Bluetooth Earbuds", "Kindle Book"]),
                ("DoorDash", "no-reply@doordash.com", "Your DoorDash order receipt",
                 ["Chipotle", "McDonald's", "Panda Express", "Subway", "Pizza Hut"]),
                ("Uber", "uber.us@uber.com", "Your trip with Uber",
                 ["Trip to Downtown", "Trip to Airport", "Trip to Home"]),
                ("Google Play", "googleplay-noreply@google.com", "Your Google Play receipt",
                 ["Spotify Premium", "YouTube Premium", "Google One", "In-app purchase"]),
                ("Walmart", "help@walmart.com", "Your Walmart order confirmation",
                 ["Groceries", "Electronics", "Household items"]),
            ]
        elif locale == "GB":
            merchants = [
                ("Amazon.co.uk", "order@amazon.co.uk", "Your Amazon.co.uk order of {item}",
                 ["Phone Case", "USB Cable", "Kindle Book", "Echo Dot"]),
                ("Deliveroo", "no-reply@deliveroo.co.uk", "Your Deliveroo receipt",
                 ["Nando's", "Wagamama", "Domino's", "McDonald's"]),
                ("Google Play", "googleplay-noreply@google.com", "Your Google Play receipt",
                 ["Spotify Premium", "YouTube Premium"]),
            ]
        else:
            merchants = [
                ("Amazon", "order@amazon.com", "Your order of {item}",
                 ["Phone Case", "USB Cable", "Book"]),
                ("Google Play", "googleplay-noreply@google.com", "Your Google Play receipt",
                 ["Spotify Premium", "YouTube Premium"]),
            ]

        # Generate 5-15 receipts spread over profile age
        num_receipts = rng.randint(5, min(15, age_days // 5 + 3))
        for _ in range(num_receipts):
            merchant = rng.choice(merchants)
            item = rng.choice(merchant[3])
            dt = _random_datetime(rng, now, 1, min(age_days, 90))

            if locale == "US":
                amount = f"${rng.randint(5, 150)}.{rng.randint(0, 99):02d}"
                currency = "USD"
            elif locale == "GB":
                amount = f"£{rng.randint(5, 100)}.{rng.randint(0, 99):02d}"
                currency = "GBP"
            else:
                amount = f"€{rng.randint(5, 120)}.{rng.randint(0, 99):02d}"
                currency = "EUR"

            receipts.append({
                "from": merchant[1],
                "to": persona_email,
                "merchant": merchant[0],
                "subject": merchant[2].format(item=item),
                "item": item,
                "amount": amount,
                "currency": currency,
                "date": dt.isoformat(),
                "timestamp": int(dt.timestamp() * 1000),
                "order_id": f"#{rng.randint(100, 999)}-{rng.randint(1000000, 9999999)}",
            })

        receipts.sort(key=lambda x: x["timestamp"], reverse=True)
        return receipts

    # ─── SAVE ─────────────────────────────────────────────────────────

    def _save_profile(self, profile: Dict[str, Any]):
        """Save profile JSON to disk."""
        profiles_dir = TITAN_DATA / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)
        profile_file = profiles_dir / f"{profile['id']}.json"

        # Don't save gallery_paths in JSON (they're file paths)
        save_data = {k: v for k, v in profile.items() if k != "gallery_paths"}
        save_data["gallery_count"] = len(profile.get("gallery_paths", []))

        profile_file.write_text(json.dumps(save_data, indent=2, default=str))
        logger.info(f"Profile saved: {profile_file}")
