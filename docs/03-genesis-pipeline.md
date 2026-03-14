# 03 — Genesis Pipeline

The Genesis Pipeline is the complete behavioral identity synthesis system. It forges a full Android device persona — 90 to 365 days of lived-in data — and injects it into a Cuttlefish VM via ADB, producing a device that passes behavioral, temporal, and statistical analysis by anti-fraud systems.

---

## Table of Contents

1. [Pipeline Overview](#1-pipeline-overview)
2. [Stage 1: Profile Forge](#2-stage-1-profile-forge)
3. [Circadian Weighting Algorithm](#3-circadian-weighting-algorithm)
4. [Persona Archetypes](#4-persona-archetypes)
5. [Country & Locale Support](#5-country--locale-support)
6. [The 10 Data Categories](#6-the-10-data-categories)
7. [SmartForge — AI-Driven Persona Generation](#7-smartforge--ai-driven-persona-generation)
8. [Stage 2: Profile Injection](#8-stage-2-profile-injection)
9. [Stage 3: Trust Score Computation](#9-stage-3-trust-score-computation)
10. [Stage 4: Aging Report](#10-stage-4-aging-report)
11. [Profile JSON Schema](#11-profile-json-schema)
12. [API Endpoints](#12-api-endpoints)

---

## 1. Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 1: FORGE                                                  │
│  POST /api/genesis/create  (or /smartforge)                      │
│  AndroidProfileForge.forge()    ~instant                         │
│  ├── Persona generation (name, email, phone, DOB, address)       │
│  ├── Circadian-weighted event distribution                        │
│  ├── 10 data categories (see §6)                                 │
│  └── Save → /opt/titan/data/profiles/{id}.json                   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  STAGE 2: INJECT                                                 │
│  POST /api/genesis/inject/{device_id}                            │
│  ProfileInjector.inject_full_profile()    ~200-280s              │
│  ├── Google account (accounts_ce.db + Chrome prefs)              │
│  ├── Chrome: cookies, history, autofill                          │
│  ├── Contacts + Call logs + SMS                                  │
│  ├── Gallery (EXIF-dated JPEGs)                                  │
│  ├── App install dates (backdated)                               │
│  ├── WalletProvisioner (4 targets)                               │
│  └── AppDataForger (30+ app SharedPrefs + DBs)                   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  STAGE 3: VERIFY                                                 │
│  GET /api/genesis/trust-score/{device_id}                        │
│  13-point scoring system    0-100                                │
│  → Grade: A+ (≥90) / A (≥80) / B (≥65) / C (≥50) / F           │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  STAGE 4: AGING REPORT                                           │
│  AgingReporter.generate(device_id)                               │
│  Combines trust + patch + wallet + agent tasks                   │
│  → overall_grade + recommendations                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Stage 1: Profile Forge

`AndroidProfileForge` (`core/android_profile_forge.py`) is the data generation engine.

```python
forge = AndroidProfileForge()
profile = forge.forge(
    persona_name    = "Alex Mercer",          # "" = auto-generate
    persona_email   = "alex.mercer@gmail.com",# "" = auto-generate
    persona_phone   = "+12125551234",         # "" = auto-generate
    country         = "US",
    archetype       = "professional",
    age_days        = 90,                     # Profile history depth
    carrier         = "tmobile_us",
    location        = "nyc",
    device_model    = "samsung_s25_ultra",
)
# profile["id"] = "TITAN-0A4314A9"
# profile["stats"] = {"contacts": 22, "sms": 58, "calls": 142, ...}
```

### Auto-Generated Persona Fields

When fields are left empty, the forge auto-generates them from locale-appropriate pools:

| Field | Generation Method |
|-------|-----------------|
| `persona_name` | `NAME_POOLS[country]["first_male/female"]` + `["last"]` |
| `persona_email` | `{firstname}.{lastname}{random}@gmail.com` (or yahoo/outlook) |
| `persona_phone` | Area code from `NAME_POOLS[country]["area_codes"]` + 7 random digits |
| `persona_dob` | Archetype-appropriate age range |
| `persona_address` | City + state + ZIP from location profile |

### Name Pools (by Country)

| Country | Male Names (sample) | Female Names (sample) | Last Names (sample) |
|---------|--------------------|-----------------------|-------------------|
| US | James, Robert, Michael, David | Mary, Patricia, Jennifer, Sarah | Smith, Johnson, Williams, Garcia |
| GB | Oliver, George, Harry, Jack | Olivia, Amelia, Isla, Ava | Smith, Jones, Williams, Taylor |
| DE | Maximilian, Alexander, Paul | Sophie, Emma, Mia, Anna | Müller, Schmidt, Schneider, Fischer |
| AU | Oliver, William, Jack, Noah | Charlotte, Olivia, Isla, Mia | Smith, Jones, Williams, Brown |
| IN | Arjun, Rohan, Rahul, Vikram | Priya, Anjali, Divya, Kavya | Sharma, Patel, Singh, Kumar |
| BR | Miguel, Arthur, Bernardo | Sofia, Helena, Alice, Valentina | Silva, Santos, Oliveira, Costa |

---

## 3. Circadian Weighting Algorithm

All events are distributed using a **circadian weighting model** that mirrors real human activity patterns. This prevents anti-fraud systems from detecting "bursty" synthetic activity.

### Hour Weight Table

| Hour Range | Weight | Behavioral Context |
|-----------|--------|-------------------|
| 00:00–05:59 | 0.01–0.05 | Deep sleep; near-zero activity |
| 06:00–07:59 | 0.05–0.10 | Wake-up; brief phone check |
| 08:00–11:59 | 0.12–0.18 | Morning commute + work start |
| 12:00–13:59 | 0.20–0.22 | Lunch peak; social browsing |
| 14:00–17:59 | 0.14–0.18 | Afternoon work; moderate activity |
| 18:00–19:59 | 0.22–0.28 | Evening peak; social media surge |
| 20:00–22:59 | 0.25–0.35 | Prime time; highest activity |
| 23:00–23:59 | 0.08–0.15 | Wind-down; light browsing |

### How It Works

```python
def _circadian_weighted_time(self, base_time: float, spread_days: int) -> float:
    """Generate a timestamp within spread_days of base_time, weighted by hour."""
    for _ in range(20):  # Try up to 20 times to find valid weighted slot
        offset_s = random.uniform(-spread_days * 86400, 0)
        candidate = base_time + offset_s
        hour = datetime.fromtimestamp(candidate).hour
        weight = HOUR_WEIGHTS[hour]
        if random.random() < weight:
            return candidate
    return base_time + offset_s  # Fallback after max attempts
```

Events are generated backwards from `now` over the profile age window. Each event gets a circadian-weighted timestamp, ensuring call logs, SMS, and browsing are concentrated during waking hours — exactly as they would be for a real user.

### Weekend vs Weekday

Additional multipliers apply on weekends (Saturday/Sunday):
- **Weekday morning (08:00–09:00)**: higher weight (commute)
- **Weekend morning (09:00–10:00)**: lower weight (sleeping in)
- **Weekend evening (19:00–23:00)**: higher weight (leisure)

---

## 4. Persona Archetypes

Archetypes shape what data categories are emphasized and what apps/sites are browsed:

| Archetype | Age Range | Key Behaviors | Top Apps |
|-----------|----------|---------------|---------|
| `professional` | 25–50 | LinkedIn, work email, banking, travel | Chase, LinkedIn, Slack, Uber |
| `student` | 18–26 | Social media, gaming, campus apps | Instagram, TikTok, Spotify, Discord |
| `retiree` | 60–80 | News, family comms, health, shopping | Facebook, Amazon, WebMD |
| `gamer` | 16–35 | Gaming, Discord, Twitch, YouTube | Discord, Steam, YouTube |
| `freelancer` | 22–45 | Gig apps, finance, social | Upwork, PayPal, Instagram |
| `small_business_owner` | 28–60 | Banking, B2B tools, merchant apps | QuickBooks, Square, Wells Fargo |
| `teacher` | 24–60 | Education, communication, planning | Google Classroom, Zoom, Amazon |
| `retail_worker` | 18–45 | Budget apps, social, shopping | Venmo, Amazon, TikTok |

---

## 5. Country & Locale Support

| Country | Locale | SMS Templates | Browser Patterns | Phone Format |
|---------|--------|--------------|-----------------|-------------|
| US | en-US | English, US slang | .com, Amazon, Reddit | +1 (XXX) XXX-XXXX |
| GB | en-GB | British English | .co.uk, BBC, Guardian | +44 7XXX XXXXXX |
| DE | de-DE | German | .de, SPIEGEL, Amazon.de | +49 1XX XXXXXXXX |
| AU | en-AU | Australian English | .com.au, news.com.au | +61 4XX XXX XXX |
| IN | en-IN | Indian English | .in, Flipkart, Jio | +91 9XXXXXXXXX |
| CA | en-CA | Canadian English | .ca, CBC, Amazon.ca | +1 (XXX) XXX-XXXX |
| FR | fr-FR | French | .fr, Le Monde, FNAC | +33 6XX XXX XXX |
| BR | pt-BR | Portuguese | .com.br, Mercado Livre | +55 11 9XXXX-XXXX |

---

## 6. The 10 Data Categories

### 1. Contacts (17–35 generated)

Persona-tied contacts: real colleagues, family, friends. Each contact includes:
- Name (same locale as persona)
- Phone number (valid format for country)
- Email (optional, ~60% have one)
- Company/label (for professional archetype)

### 2. Call Logs (100–400 generated)

```python
# For each call log entry:
{
    "number": "+12125551234",
    "type": 1,          # 1=incoming, 2=outgoing, 3=missed
    "duration": 147,    # seconds (0 for missed)
    "date": 1710000000  # circadian-weighted timestamp
}
```

Distribution: ~45% outgoing, ~40% incoming, ~15% missed. Duration follows a log-normal distribution (most calls 1–5 min, occasional long calls 15–60 min).

### 3. SMS Threads (30–80 messages generated)

Realistic conversation templates by relationship type:

| Template Type | Example Exchange |
|--------------|-----------------|
| Casual friend | "Hey are you free Saturday?" / "Yeah! What time?" |
| Family | "Did you see the game last night?" / "Yes! Crazy ending 😂" |
| Work colleague | "Can you send me the Q3 report?" / "Sending now" |
| Bank OTP | "Your Chase verification code is 847291" (from 96109) |
| Delivery notification | "Your Amazon package arriving today 3-5pm" |

Bank SMS messages are sent from short codes (5–6 digit numbers) matching real financial institutions.

### 4. Chrome Cookies (50–200 generated)

Trust-anchor cookies from high-reputation domains:

| Domain | Cookie Names | Purpose |
|--------|-------------|---------|
| .google.com | SSID, HSID, APISID, NID | Google auth trust |
| .amazon.com | session-id, ubid-main, x-main | Commerce trust |
| .facebook.com | c_user, xs, datr | Social trust |
| .twitter.com | auth_token, ct0, twid | Social trust |
| .netflix.com | SecureNetflixId, nfvdid | Streaming trust |
| .instagram.com | sessionid, csrftoken | Social trust |
| .reddit.com | reddit_session, token_v2 | Social trust |
| .spotify.com | sp_t, sp_dc | Media trust |
| .paypal.com | PHPSESSID, l7_az | Payment trust |

Each cookie is backdated by up to `max_age` seconds (default 1 year) from now, with randomized creation/expiry times.

### 5. Chrome Browsing History (200–800 entries, capped at 200 for injection)

URL patterns matched to archetype and locale. Examples:
- `https://www.amazon.com/dp/B09X...` (product pages)
- `https://www.reddit.com/r/technology/...` (forum browsing)
- `https://maps.google.com/search?...` (location searches)
- `https://www.youtube.com/watch?v=...` (video history)
- Locale-specific news sites, bank portals, social feeds

Visit counts range 1–12 per URL, reflecting realistic repeat visit patterns.

### 6. Gallery Photos (8–20 placeholder JPEGs)

EXIF-dated JPEG stubs pushed to `/sdcard/DCIM/Camera/`:
- Filenames: `IMG_YYYYMMDD_HHMMSS.jpg`
- EXIF timestamps: circadian-weighted, spread over profile age
- File content: valid minimal JPEG (not blank), small file size (~50KB each)
- GPS EXIF metadata: coordinates matching location profile

### 7. WiFi Saved Networks (4–10 networks)

```xml
<WifiConfiguration>
  <string name="SSID">&quot;NETGEAR72-5G&quot;</string>
  <string name="BSSID">A4:50:46:AB:CD:EF</string>
  <string name="SecurityType">WPA2</string>
  <boolean name="HiddenSSID" value="false" />
</WifiConfiguration>
```

Includes home network (strong signal, many connections) and work/public networks.

### 8. App Install Dates

`pm set-install-time {package} {timestamp}` backdates when apps appear to have been installed:
- Core apps (Chrome, Maps, Gmail): 6–12 months ago
- Banking apps: 3–6 months ago
- Social apps: 1–4 months ago
- Recently added apps: 1–30 days ago

This prevents the "all apps installed at exactly the same time" detection pattern.

### 9. Purchase History

Via `PurchaseHistoryBridge` (`core/purchase_history_bridge.py`):
- Chrome History entries for order confirmation pages (amazon.com/orders, paypal.com/activity)
- Commerce session cookies with aged timestamps
- Chrome Autofill CC + address data matching the persona
- Email receipt notification artifacts (for Gmail injection path)

### 10. Autofill Data

```python
{
    "first_name": "Alex",
    "last_name": "Mercer",
    "email": "alex.mercer@gmail.com",
    "phone": "+12125551234",
    "address": "742 Evergreen Terrace",
    "city": "New York",
    "state": "NY",
    "zip": "10001",
    "country": "US",
}
```

Injected into Chrome's `Web Data` SQLite database as an `autofill_profiles` entry.

---

## 7. SmartForge — AI-Driven Persona Generation

`POST /api/genesis/smartforge` provides an AI-powered forge mode that generates more contextually coherent personas:

```python
class SmartForgeBody(BaseModel):
    occupation: str   = "software_engineer"
    country: str      = "US"
    age: int          = 30
    gender: str       = "auto"
    target_site: str  = "amazon.com"  # Optimizes persona for this target
    use_ai: bool      = False          # True = call LLM for enrichment
    age_days: int     = 0              # 0 = archetype-appropriate default
    # Optional overrides:
    name: str = ""; email: str = ""; phone: str = ""
    dob: str = ""; street: str = ""; city: str = ""
    state: str = ""; zip: str = ""
    card_number: str = ""; card_exp: str = ""; card_cvv: str = ""
```

### SmartForge Engine (v11-release bridge)

`smartforge_bridge.py` imports `smartforge_engine` from the v11-release codebase (PYTHONPATH: `/root/titan-v11-release/core`). If unavailable, falls back to local deterministic generator.

**Occupation → Archetype Mapping:**

| Occupation | Archetype | Implied Age Range | Implied Income |
|-----------|----------|-----------------|---------------|
| `software_engineer` | professional | 22–45 | high |
| `university_student` | student | 18–26 | low |
| `doctor` | professional | 28–65 | high |
| `retail_worker` | retail_worker | 18–45 | low |
| `retiree` | retiree | 55–80 | medium |
| `freelancer` | freelancer | 22–50 | variable |
| `gamer` | gamer | 16–35 | low-medium |
| `small_business_owner` | small_business_owner | 28–60 | high |
| `teacher` | teacher | 24–60 | medium |
| `government_worker` | professional | 28–60 | medium |

### Target-Site Optimization

When `target_site` is specified, SmartForge:
1. Includes the target in Chrome browsing history (multiple visits)
2. Adds the target's cookies to the cookie set
3. Adjusts archetype browsing patterns toward the target's user demographic
4. Ensures autofill CC + address data is compatible with the target's checkout flow

---

## 8. Stage 2: Profile Injection

See [04-profile-injector.md](04-profile-injector.md) for detailed injection mechanics.

**Injection sequence timing:**

| Phase | Duration | Notes |
|-------|---------|-------|
| Google account injection | ~15s | accounts_ce.db + accounts_de.db + prefs |
| Chrome cookies (200 entries) | ~25s | SQLite tempfile push |
| Chrome history (200 entries) | ~30s | Batched 50/call |
| Chrome autofill | ~5s | Single DB push |
| Contacts (22 entries) | ~18s | Content provider, 1/s throttled |
| Call logs (370 entries) | ~35s | Content provider batched |
| SMS (58 messages) | ~20s | Content provider |
| Gallery (15 photos) | ~20s | adb push × 15 |
| App install dates | ~10s | pm set-install-time × 30 apps |
| Wallet injection | ~40s | 4 targets + verification |
| App data (30+ apps) | ~25s | SharedPrefs + DB per app |
| **Total** | **~243–280s** | |

**Job status polling:**

```
GET /api/genesis/inject-status/{job_id}
→ {"status": "running", "elapsed": 45.2}
→ {"status": "completed", "elapsed": 267.1, "result": {...}}
→ {"status": "failed", "error": "...", "elapsed": 12.0}
```

---

## 9. Stage 3: Trust Score Computation

`GET /api/genesis/trust-score/{device_id}` computes a 100-point score across 13 checks:

| Check | Points | Threshold | Method |
|-------|--------|-----------|--------|
| `google_account` | 15 | `accounts_ce.db` exists | `ls` check |
| `contacts` | 8 | ≥5 contacts | `content query` count |
| `chrome_cookies` | 8 | Cookies DB exists | `ls` check |
| `chrome_history` | 8 | History DB exists | `ls` check |
| `gallery` | 5 | ≥3 photos | `ls *.jpg` count |
| `google_pay` | 12 | `tapandpay.db` + ≥1 token | `sqlite3 COUNT(*)` |
| `play_store_library` | 8 | `library.db` exists | `ls` check |
| `wifi_networks` | 4 | `WifiConfigStore.xml` exists | `ls` check |
| `sms` | 7 | ≥5 messages | `content query` count |
| `call_logs` | 7 | ≥10 calls | `content query` count |
| `app_data` | 8 | Instagram SharedPrefs exist | `ls` check |
| `chrome_signin` | 5 | Chrome Preferences exists | `ls` check |
| `autofill` | 5 | `Web Data` exists | `ls` check |
| **Maximum** | **100** | | |

### Additional Informational Checks (0 points, diagnostic only)

| Check | Description |
|-------|-------------|
| `nfc_tap_pay` | NFC prefs present (wallet readiness) |
| `gms_billing_sync` | GMS wallet_instrument_prefs.xml present |
| `keybox` | `persist.titan.keybox.loaded=1` |

### Grade Scale

| Score | Grade | Meaning |
|-------|-------|---------|
| 90–100 | A+ | Full trust, ready for all targets |
| 80–89 | A | High trust, minor gaps |
| 65–79 | B | Acceptable for most targets |
| 50–64 | C | Notable gaps, limited targets |
| 30–49 | D | Significant gaps, limited use |
| 0–29 | F | Injection failed or incomplete |

---

## 10. Stage 4: Aging Report

`AgingReporter.generate(device_id)` produces a comprehensive device state report combining all pipeline outputs:

```python
@dataclass
class AgingReport:
    device_id: str
    report_time: str
    persona: Dict          # name, email, phone, archetype
    profile_id: str
    profile_age_days: int
    trust_score: Dict      # Full 13-check trust score result
    patch_score: Dict      # Last AnomalyPatcher.full_patch() report
    verify_score: Dict     # WalletVerifier 13-check result
    apps_installed: List   # Detected installed packages
    apps_signed_in: List   # Apps with active account prefs
    wallet: Dict           # tapandpay tokens + COIN.xml + GMS state
    injection_results: Dict# Per-category injection success/fail
    agent_tasks: List      # Recent DeviceAgent task history
    overall_grade: str     # "A+" through "F"
    overall_score: float   # Weighted combination
    recommendations: List  # Actionable items to improve score
```

**Recommendations engine:**

If `keybox_loaded=False`: *"Install keybox.xml for Play Integrity Strong — required for Google Pay NFC"*
If `google_pay.tokens=0`: *"Re-run wallet provisioning — no tokens in tapandpay.db"*
If `trust_score < 80`: *"Run genesis inject for device {id} — missing {N} data categories"*
If `patch_score < 90`: *"Re-run anomaly patcher — {N} vectors failing"*

---

## 11. Profile JSON Schema

Profiles are saved as JSON at `/opt/titan/data/profiles/{id}.json`:

```json
{
  "id": "TITAN-0A4314A9",
  "persona_name": "Alex Mercer",
  "persona_email": "alex.mercer57@gmail.com",
  "persona_phone": "+12125554821",
  "persona_dob": "1991-03-22",
  "country": "US",
  "archetype": "professional",
  "age_days": 90,
  "carrier": "tmobile_us",
  "location": "nyc",
  "device_model": "samsung_s25_ultra",
  "created_at": "2026-03-14T05:00:00Z",
  "stats": {
    "contacts": 22,
    "call_logs": 370,
    "sms": 58,
    "cookies": 127,
    "history": 200,
    "gallery": 15,
    "wifi_networks": 6
  },
  "contacts": [...],
  "call_logs": [...],
  "sms": [...],
  "cookies": [...],
  "history": [...],
  "gallery_paths": [...],
  "wifi_networks": [...],
  "autofill": {...},
  "app_installs": {...}
}
```

---

## 12. API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/genesis/create` | Forge a new profile (deterministic) |
| `POST` | `/api/genesis/smartforge` | AI-powered occupation-driven forge |
| `GET` | `/api/genesis/profiles` | List all saved profiles |
| `GET` | `/api/genesis/profiles/{id}` | Get full profile JSON |
| `DELETE` | `/api/genesis/profiles/{id}` | Delete a profile |
| `POST` | `/api/genesis/inject/{device_id}` | Start async injection |
| `GET` | `/api/genesis/inject-status/{job_id}` | Poll injection job status |
| `GET` | `/api/genesis/trust-score/{device_id}` | Compute 13-point trust score |

### Create Profile Request

```json
{
  "name": "Alex Mercer",
  "email": "alex.mercer@gmail.com",
  "country": "US",
  "archetype": "professional",
  "age_days": 90,
  "carrier": "tmobile_us",
  "location": "nyc",
  "device_model": "samsung_s25_ultra",
  "cc_number": "4111111111111111",
  "cc_exp_month": 12,
  "cc_exp_year": 2028,
  "cc_cvv": "123",
  "cc_cardholder": "Alex Mercer"
}
```

### Trust Score Response

```json
{
  "device_id": "dev-a3f12b",
  "trust_score": 96,
  "max_score": 100,
  "grade": "A+",
  "checks": {
    "google_account": {"present": true, "weight": 15},
    "contacts": {"count": 22, "weight": 8},
    "google_pay": {"present": true, "tokens": 1, "valid": true, "weight": 12},
    "keybox": {"loaded": true, "weight": 0},
    "nfc_tap_pay": {"present": true, "weight": 0},
    "gms_billing_sync": {"present": true, "weight": 0}
  }
}
```

---

*See [04-profile-injector.md](04-profile-injector.md) for detailed injection target mechanics.*
