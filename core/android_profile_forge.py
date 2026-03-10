"""
Titan V11.3 — Android Device Profile Forge
Generates complete, persona-consistent Android device profile data
for injection into Redroid containers via ProfileInjector.

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
# CIRCADIAN WEIGHTING
# ═══════════════════════════════════════════════════════════════════════

# Hour weights — peaks at 8am, 12pm, 8pm; trough at 3am
CIRCADIAN_WEIGHTS = [
    0.05, 0.03, 0.02, 0.01, 0.01, 0.02,   # 00-05 (sleeping)
    0.05, 0.12, 0.20, 0.18, 0.15, 0.14,   # 06-11 (morning commute + work)
    0.22, 0.18, 0.14, 0.15, 0.16, 0.18,   # 12-17 (lunch + afternoon)
    0.25, 0.30, 0.35, 0.28, 0.18, 0.10,   # 18-23 (evening peak)
]


def _circadian_hour(rng: random.Random) -> int:
    """Pick an hour weighted by circadian rhythm."""
    return rng.choices(range(24), weights=CIRCADIAN_WEIGHTS, k=1)[0]


def _random_datetime(rng: random.Random, base: datetime, days_ago_min: int,
                     days_ago_max: int) -> datetime:
    """Generate a random datetime within a day range, circadian-weighted."""
    day_offset = rng.randint(days_ago_min, days_ago_max)
    hour = _circadian_hour(rng)
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    dt = base - timedelta(days=day_offset)
    return dt.replace(hour=hour, minute=minute, second=second)


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

        # Parse persona
        parts = persona_name.split(None, 1)
        first_name = parts[0] if parts else "Alex"
        last_name = parts[1] if len(parts) > 1 else "Mercer"

        locale = country.upper()[:2]
        name_pool = NAME_POOLS.get(locale, NAME_POOLS["US"])

        # ─── Generate contacts ────────────────────────────────────────
        contacts = self._forge_contacts(name_pool, locale, age_days)

        # ─── Generate call logs ───────────────────────────────────────
        call_logs = self._forge_call_logs(contacts, now, age_days)

        # ─── Generate SMS ─────────────────────────────────────────────
        sms = self._forge_sms(contacts, now, age_days)

        # ─── Generate Chrome mobile cookies ───────────────────────────
        cookies = self._forge_cookies(now, profile_birth, locale)

        # ─── Generate Chrome mobile history ───────────────────────────
        history = self._forge_history(now, age_days, locale)

        # ─── Generate gallery photos ──────────────────────────────────
        gallery_paths = self._forge_gallery(now, age_days)

        # ─── Generate autofill ────────────────────────────────────────
        autofill = {
            "name": persona_name,
            "first_name": first_name,
            "last_name": last_name,
            "email": persona_email,
            "phone": persona_phone,
            "address": self._forge_address(locale),
        }

        # ─── WiFi networks ───────────────────────────────────────────
        wifi_networks = self._forge_wifi(locale, location)

        # ─── App install timestamps ───────────────────────────────────
        app_installs = self._forge_app_installs(now, age_days, locale)

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
            },
        }

        # Save to disk
        self._save_profile(profile)

        logger.info(f"Profile forged: {profile_id}")
        logger.info(f"  Contacts: {len(contacts)}, Calls: {len(call_logs)}, SMS: {len(sms)}")
        logger.info(f"  Cookies: {len(cookies)}, History: {len(history)}, Gallery: {len(gallery_paths)}")
        return profile

    # ─── CONTACTS ─────────────────────────────────────────────────────

    def _forge_contacts(self, name_pool: dict, locale: str, age_days: int) -> List[Dict]:
        """Generate persona-consistent contacts."""
        rng = self._rng
        num_contacts = rng.randint(10, 22)
        area_codes = name_pool.get("area_codes", ["212", "646", "718"])
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

    def _forge_call_logs(self, contacts: List[Dict], now: datetime, age_days: int) -> List[Dict]:
        """Generate realistic call history spread over profile age."""
        rng = self._rng
        # ~1.5 calls/day on average
        num_calls = rng.randint(max(20, age_days), min(age_days * 3, 200))
        logs = []

        # Weight: more calls to frequent contacts (Pareto)
        contact_weights = [1.0 / (i + 1) ** 0.8 for i in range(len(contacts))]

        for _ in range(num_calls):
            contact = rng.choices(contacts, weights=contact_weights[:len(contacts)], k=1)[0]
            dt = _random_datetime(rng, now, 0, age_days)
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

    def _forge_sms(self, contacts: List[Dict], now: datetime, age_days: int) -> List[Dict]:
        """Generate SMS conversation threads."""
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
                thread_start = _random_datetime(rng, now, 1, min(age_days, 60))

                for idx, (body, direction) in enumerate(tmpl):
                    msg_time = thread_start + timedelta(minutes=idx * rng.randint(1, 15))
                    msg_type = 1 if direction == "in" else 2  # 1=received, 2=sent

                    messages.append({
                        "address": contact["phone"],
                        "body": body,
                        "type": msg_type,
                        "date": int(msg_time.timestamp() * 1000),
                    })

        # Add some bank/OTP messages from short codes
        for _ in range(rng.randint(3, 8)):
            tmpl = rng.choice([SMS_TEMPLATES["bank"], SMS_TEMPLATES["otp"]])
            for body, direction in tmpl:
                dt = _random_datetime(rng, now, 0, min(age_days, 30))
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
        target_entries = rng.randint(max(100, age_days * 5), min(age_days * 15, 800))

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
        """Create a minimal JPEG file with EXIF date."""
        try:
            # Minimal valid JPEG: SOI + APP0 + basic scan + EOI
            # This creates a 1x1 pixel JPEG (~631 bytes)
            import struct
            # SOI marker
            data = b'\xff\xd8'
            # APP0 JFIF
            data += b'\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
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
