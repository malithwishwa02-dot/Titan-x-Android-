# 08 — Intelligence Tools

Titan V11.3 integrates a suite of intelligence and reconnaissance tools accessible via the `/api/intel`, `/api/cerberus`, and `/api/targets` API sections. These tools provide OSINT capability, card validation, BIN intelligence, 3DS strategy advisory, and site analysis.

---

## Table of Contents

1. [AI Intelligence Copilot](#1-ai-intelligence-copilot)
2. [OSINT Orchestrator](#2-osint-orchestrator)
3. [Cerberus Card Validator](#3-cerberus-card-validator)
4. [BIN Intelligence Database](#4-bin-intelligence-database)
5. [Target Site Analyzer (WebCheckEngine)](#5-target-site-analyzer-webcheckengine)
6. [WAF Detector](#6-waf-detector)
7. [DNS Intelligence](#7-dns-intelligence)
8. [Target Profiler](#8-target-profiler)
9. [3DS Strategy Advisor](#9-3ds-strategy-advisor)
10. [API Reference](#10-api-reference)

---

## 1. AI Intelligence Copilot

**Endpoint:** `POST /api/intel/copilot`  
**Engine:** `AIIntelligenceEngine.orchestrate_operation_intel()` (from v11-release)

The AI Copilot is a free-form intelligence query interface powered by the GPU-hosted Ollama model. It can answer questions about fraud systems, recommend operational strategies, analyze security postures, and provide technical intelligence.

### Request

```json
{"query": "What are the best strategies for bypassing Chase bank's device fingerprinting?"}
```

### Response

```json
{
    "result": "Chase uses a combination of iovation (TransUnion) and NICE Actimize...",
    "stub": false
}
```

### Example Queries

| Query Type | Example |
|-----------|---------|
| Fraud system analysis | "How does Stripe detect virtual Android devices?" |
| 3DS strategy | "What's the challenge rate for Visa Classic US cards?" |
| Device strategy | "Which device fingerprint has the highest trust on PayPal?" |
| Carrier strategy | "Which US carrier generates the least fraud flags for new accounts?" |
| Site reconnaissance | "What anti-fraud stack does Amazon use in 2026?" |
| Mitigation advice | "How do I reduce velocity flags on Apple Pay?" |

### Fallback Behavior

If `ai_intelligence_engine` module is not available (v11-release not on PYTHONPATH), returns:
```json
{"result": "AI engine not available. Query: {query}", "stub": true}
```

---

## 2. OSINT Orchestrator

**Endpoint:** `POST /api/intel/osint`  
**Engine:** `OSINTOrchestrator` (from v11-release)

The OSINT orchestrator runs multiple open-source intelligence tools simultaneously against a target persona to gather publicly available information.

### Request

```json
{
    "name":     "Alex Mercer",
    "email":    "alex.mercer@gmail.com",
    "username": "alexmercer57",
    "phone":    "+12125554821",
    "domain":   ""
}
```

### Tools Invoked

| Tool | Purpose | Target Field |
|------|---------|-------------|
| **Sherlock** | Username search across 300+ sites | `username` |
| **Maigret** | Advanced username search + person profiling | `username` |
| **Holehe** | Email account existence on 120+ sites | `email` |
| **PhoneInfoga** | Phone number OSINT (carrier, location, reputation) | `phone` |
| **HaveIBeenPwned** | Email breach history check | `email` |
| **EmailRep** | Email reputation scoring | `email` |

### Response Structure

```json
{
    "result": {
        "email_breaches": [
            {"site": "linkedin.com", "date": "2021-06", "data_types": ["email", "password"]}
        ],
        "email_accounts": ["github.com", "twitter.com", "spotify.com"],
        "username_accounts": ["reddit.com", "instagram.com", "twitch.tv"],
        "phone": {
            "carrier": "T-Mobile",
            "location": "New York, US",
            "valid": true,
            "disposable": false
        },
        "reputation_score": 72
    }
}
```

### OSINT in Genesis Context

OSINT results feed back into the persona validation pipeline:
- If a real person matches the persona email → flag for persona conflict
- If persona email has breach history → strengthen password/account injection
- Phone carrier consistency check against injected carrier profile

---

## 3. Cerberus Card Validator

**Endpoint:** `POST /api/cerberus/validate`  
**Engine:** `CerberusValidator` (from v11-release codebase)

Cerberus validates card data against BIN databases, Luhn algorithm, expiry checks, and enriches with issuer/network intelligence.

### Input Formats Accepted

```
# Pipe-delimited (most common)
4111111111111111|12|2028|123

# Space-delimited
4111111111111111 12 2028 123

# JSON object
{"number": "4111111111111111", "exp_month": 12, "exp_year": 2028, "cvv": "123"}

# With cardholder
4111111111111111|12|2028|123|John Smith
```

### Validation Checks Performed

| Check | Method | Notes |
|-------|--------|-------|
| Luhn algorithm | Standard checksum | Catches typos, invalid card numbers |
| BIN lookup | Internal BIN database + API fallback | Identifies issuer/country/type |
| Expiry validity | Date comparison | Months since 2000, 2-digit year normalized |
| CVV format | Length check | 3 digits (Visa/MC/Discover), 4 digits (Amex) |
| Card number length | 13-19 digits | Varies by network |

### Full Validation Response

```json
{
    "status": "VALID",
    "card": {
        "number_masked": "411111******1111",
        "last_four": "1111",
        "expiry": "12/2028",
        "expiry_status": "valid",
        "luhn": true,
        "cvv_format": "valid"
    },
    "bin": {
        "bin": "411111",
        "network": "Visa",
        "type": "Credit",
        "level": "Signature",
        "prepaid": false,
        "corporate": false,
        "issuer": "Chase Bank USA, N.A.",
        "country": "US",
        "country_name": "United States",
        "currency": "USD",
        "bank_phone": "+1-800-524-3880",
        "bank_url": "www.chase.com"
    },
    "risk": {
        "3ds_version": "2.0",
        "challenge_rate": "low",
        "velocity_risk": "unknown",
        "recommended_device": "pixel_9_pro"
    }
}
```

### Batch Validation

`POST /api/cerberus/batch`

```json
{
    "cards": [
        "4111111111111111|12|2028|123",
        "5500005555555559|01|2027|456",
        "341111111111111|05|2026|7890"
    ]
}
```

Returns array of validation results. Invalid cards marked with `"status": "INVALID"` and `"reason"`.

---

## 4. BIN Intelligence Database

**Endpoint:** `POST /api/cerberus/bin`

BIN (Bank Identification Number) lookup — the first 6-8 digits of a card number identify the issuing bank, card network, type, and country.

### BIN Database Coverage

- **Primary:** Internal BIN database (updated monthly, 500K+ BINs)
- **Fallback 1:** binlist.net API
- **Fallback 2:** Cached lookup from previous validations

### BIN Record Structure

```json
{
    "bin": "541156",
    "network": "Mastercard",
    "type": "Debit",
    "sub_type": "Prepaid Debit",
    "level": "Standard",
    "prepaid": true,
    "corporate": false,
    "issuer": "Wells Fargo Bank",
    "issuer_phone": "+1-800-869-3557",
    "issuer_website": "wellsfargo.com",
    "country": "US",
    "country_name": "United States",
    "country_flag": "🇺🇸",
    "currency": "USD",
    "3ds_support": "Mastercard SecureCode 2.0",
    "typical_challenge_rate": "medium"
}
```

### Card Network Identification

| BIN Range | Network |
|-----------|---------|
| 4xxxxx | Visa |
| 51–55xxxx | Mastercard |
| 222100–272099 | Mastercard (new range) |
| 34xxxx, 37xxxx | American Express |
| 6011xx, 644–649xx, 65xxxx | Discover |
| 3528–3589 | JCB |
| 3000–3059, 3600–3699, 3800–3899 | Diners Club |

### Level Identification (Visa)

| Level | Typical Features |
|-------|----------------|
| Classic | Basic rewards, low credit limit |
| Platinum | Enhanced rewards, travel benefits |
| Signature | Premium rewards, higher limit |
| Infinite | Ultra-premium, concierge, no preset limit |

---

## 5. Target Site Analyzer (WebCheckEngine)

**Endpoint:** `POST /api/targets/analyze`  
**Engine:** `WebCheckEngine.full_analysis()` (from v11-release)

Comprehensive 12-factor analysis of a target website's security, fraud detection, and anti-bot infrastructure.

### Analysis Factors

| Factor | What's Detected | Tools |
|--------|----------------|-------|
| **WAF** | Cloudflare, Imperva, Akamai, F5, AWS WAF, Sucuri | Header analysis, challenge page fingerprinting |
| **SSL/TLS** | TLS version, cipher suite, HSTS, certificate chain | SSL Labs-style check |
| **CDN** | CloudFront, Fastly, Cloudflare, Akamai CDN | DNS + header analysis |
| **Rate Limiting** | Request threshold, throttle behavior | Probe with controlled requests |
| **Bot Detection** | PerimeterX, Kasada, DataDome, reCAPTCHA, hCaptcha | JavaScript challenge detection |
| **3DS** | 3DS version, integration (Cardinal, Adyen, Stripe) | Payment flow analysis |
| **Fraud Scoring** | Sift, Riskified, Kount, Signifyd | Pixel/SDK detection |
| **Geo-blocking** | Country restrictions, IP reputation | GeoIP probes |
| **Session Replay** | FullStory, Hotjar, LogRocket | JavaScript SDK detection |
| **Technologies** | React, Angular, Next.js, Shopify, Magento | Wappalyzer-style detection |
| **Authentication** | OAuth2, SAML, OTP, Passkeys | Login flow analysis |
| **Payments** | Stripe, Braintree, Adyen, Chase Orbital | Payment SDK detection |

### Response

```json
{
    "domain": "amazon.com",
    "score": 78,
    "difficulty": "high",
    "factors": {
        "waf": {"detected": "Imperva Incapsula", "confidence": 0.95},
        "ssl": {"grade": "A+", "tls_version": "1.3", "hsts": true},
        "cdn": {"providers": ["CloudFront", "Fastly"]},
        "rate_limit": {"detected": true, "threshold": "~15 req/s"},
        "bot_detection": {"providers": ["PerimeterX", "reCAPTCHA v3"]},
        "3ds": {"version": "2.x", "provider": "Cardinal Commerce"},
        "fraud_scoring": {"providers": ["Sift Science"]},
        "geo_blocking": {"detected": false},
        "technologies": ["React", "Node.js", "AWS"],
        "auth": {"methods": ["OAuth2", "OTP"]},
        "payments": {"providers": ["Stripe", "Chase Orbital"]}
    },
    "recommendations": [
        "Use residential proxy for IP reputation",
        "Ensure Trust Score ≥85 before checkout",
        "Warm session 3-5 min before transaction",
        "Device: pixel_9_pro preferred for Amazon"
    ]
}
```

---

## 6. WAF Detector

**Endpoint:** `POST /api/targets/waf`  
**Engine:** `WAFDetector.detect()`

Rapid WAF identification using passive header analysis and active probe responses.

### Detection Methods

| Method | How It Works |
|--------|-------------|
| **Response headers** | `Server`, `X-CDN`, `X-Powered-By`, `CF-RAY`, `X-Sucuri-ID` headers |
| **Cookie analysis** | WAF-specific cookies (`__cfduid`, `incap_ses_*`, `visid_incap_*`) |
| **Challenge page fingerprinting** | HTML/JS content of 403/503 challenge pages |
| **Error response analysis** | Custom error page patterns |
| **DNS record analysis** | CNAME to WAF service hostnames |

### Detected WAFs

| WAF | Confidence Signal |
|-----|-----------------|
| Cloudflare | `CF-RAY` header, `__cf_bm` cookie |
| Imperva Incapsula | `incap_ses_*` cookie, `X-Iinfo` header |
| Akamai | `AkamaiGHost` in headers, Edge server CNAME |
| AWS WAF | `x-amzn-requestid`, CloudFront + WAF rules |
| F5 BIG-IP ASM | `TS01` cookie pattern |
| Sucuri | `X-Sucuri-ID`, `sucuri-cache` header |
| Barracuda | `barra_counter_session` cookie |
| Fastly | `Fastly-*` headers |

---

## 7. DNS Intelligence

**Endpoint:** `POST /api/targets/dns`  
**Engine:** `DNSIntel.get_all_records()`

Full DNS enumeration for a target domain.

### Records Retrieved

```json
{
    "domain": "amazon.com",
    "records": {
        "A": ["54.239.28.85", "54.239.17.6", "52.94.236.248"],
        "AAAA": [],
        "MX": [
            {"priority": 10, "host": "amazon-smtp.amazon.com"},
            {"priority": 5, "host": "forcedmx.amazon.com"}
        ],
        "NS": ["ns1.p31.dynect.net", "pdns1.ultradns.net"],
        "TXT": [
            "v=spf1 include:_spf.amazon.com ~all",
            "google-site-verification=...",
            "MS=ms12345678"
        ],
        "CNAME": {"www.amazon.com": "tp.9e9fb43e1.amazon.com"},
        "SOA": {
            "mname": "ns1.p31.dynect.net",
            "rname": "dns-admin.amazon.com",
            "serial": 2026031400
        },
        "CAA": [{"flags": 0, "tag": "issue", "value": "amazontrust.com"}]
    },
    "security": {
        "dnssec": false,
        "spf": "valid",
        "dmarc": "p=reject",
        "dkim": "detected"
    }
}
```

### Subdomain Enumeration

When `enumerate_subdomains=true`, additionally discovers:
- Common subdomain brute-force (wordlist of 1000 common names)
- Certificate Transparency logs (crt.sh)
- DNS zone transfer attempt

---

## 8. Target Profiler

**Endpoint:** `POST /api/targets/profiler`  
**Engine:** `TitanTargetProfiler.profile()`

Advanced anti-fraud profile for a target site — determines optimal approach strategy.

### Profiling Output

```json
{
    "domain": "chase.com",
    "profile": {
        "device_fingerprinting": {
            "active": true,
            "provider": "iovation (TransUnion)",
            "aggressiveness": "high",
            "checks": ["canvas", "webgl", "audio", "fonts", "timing"]
        },
        "behavioral_analytics": {
            "active": true,
            "provider": "NICE Actimize",
            "session_replay": "FullStory",
            "keystroke_dynamics": true,
            "mouse_dynamics": true
        },
        "ml_fraud_scoring": {
            "active": true,
            "provider": "internal + Featurespace ARIC",
            "real_time": true
        },
        "velocity_controls": {
            "ip": "1 account/day",
            "device": "3 accounts/30days",
            "email": "1 account/email"
        },
        "optimal_strategy": {
            "trust_score_minimum": 90,
            "device": "samsung_s25_ultra",
            "profile_age_minimum": 60,
            "warm_session_minutes": 5,
            "carrier": "tmobile_us or att_us",
            "vpn": "residential preferred, datacenter flagged"
        }
    }
}
```

---

## 9. 3DS Strategy Advisor

**Endpoint:** `POST /api/intel/3ds-strategy`  
**Engine:** v11-release 3DS intelligence module

Provides card-specific 3DS bypass strategy based on BIN analysis and issuer behavior patterns.

### Request

```json
{
    "bin": "411111",
    "amount": 150.00,
    "currency": "USD",
    "merchant_category": "5411"  // Grocery stores
}
```

### 3DS Versions

| Version | Challenge Method | Notes |
|---------|----------------|-------|
| 3DS 1.0 | Redirect to bank page | Legacy, high friction, declining |
| 3DS 2.0 | Frictionless + challenge | Risk-based, device fingerprint matters |
| 3DS 2.2 | Decoupled auth | OOB methods (push notification) |

### Risk-Based Authentication Signals

3DS 2.x issuers use these signals to decide frictionless vs. challenge:

| Signal | Weight |
|--------|--------|
| Device fingerprint consistency | High |
| IP reputation (residential vs. datacenter) | High |
| Billing address match | Medium |
| Purchase history velocity | Medium |
| Time of transaction | Low |
| Amount vs. typical transaction | Medium |
| Browser/app fingerprint | High |
| Authentication age (how long since last auth) | Medium |

### Response

```json
{
    "bin": "411111",
    "issuer": "Chase",
    "network": "Visa",
    "3ds_version": "2.0",
    "challenge_rate": "low (15%)",
    "frictionless_rate": "85%",
    "strategy": {
        "device": "pixel_9_pro",
        "trust_score_min": 85,
        "ip_type": "residential (same state as billing)",
        "session_warmup": "3-5 minutes browsing",
        "time_of_day": "10am-6pm local time (lower friction)",
        "amount_limit": "$500 first transaction",
        "billing_address": "Must match card billing address",
        "velocity": "Max 1 transaction/device/day"
    },
    "notes": "Chase uses Cardinal Commerce for 3DS. Frictionless rate is high for Device+ integrity."
}
```

---

## 10. API Reference

### Intel Router (`/api/intel`)

| Method | Path | Engine | Description |
|--------|------|--------|-------------|
| `POST` | `/api/intel/copilot` | `AIIntelligenceEngine` | Free-form AI intelligence query |
| `POST` | `/api/intel/recon` | `target_intelligence` | Domain OSINT |
| `POST` | `/api/intel/osint` | `OSINTOrchestrator` | Multi-tool persona OSINT |
| `POST` | `/api/intel/3ds-strategy` | v11-release 3DS module | Card-specific 3DS bypass strategy |
| `POST` | `/api/intel/dark-web` | external module | Dark web search (stub) |

### Cerberus Router (`/api/cerberus`)

| Method | Path | Engine | Description |
|--------|------|--------|-------------|
| `POST` | `/api/cerberus/validate` | `CerberusValidator` | Single card validation + BIN enrichment |
| `POST` | `/api/cerberus/batch` | `CerberusValidator` | Multi-card batch validation |
| `POST` | `/api/cerberus/bin` | BIN database | BIN lookup only |

### Targets Router (`/api/targets`)

| Method | Path | Engine | Description |
|--------|------|--------|-------------|
| `POST` | `/api/targets/analyze` | `WebCheckEngine` | Full 12-factor site analysis |
| `POST` | `/api/targets/waf` | `WAFDetector` | WAF identification |
| `POST` | `/api/targets/dns` | `DNSIntel` | Full DNS record enumeration |
| `POST` | `/api/targets/profiler` | `TitanTargetProfiler` | Anti-fraud profile + strategy |

### Module Availability

These intelligence engines come from the `v11-release` codebase and require PYTHONPATH to include `/root/titan-v11-release/core`. If not available, all endpoints return `{"stub": true, "message": "..."}` gracefully without crashing.

---

*See [09-network-kyc.md](09-network-kyc.md) for VPN, proxy, and KYC pipeline documentation.*
