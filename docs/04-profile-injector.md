# 04 — Profile Injector

The `ProfileInjector` class (`core/profile_injector.py`) is the ADB-based injection engine that writes forged Genesis profile data into a live Cuttlefish Android VM, targeting 9 distinct data stores with correct file ownership, permissions, and SELinux labels.

---

## Table of Contents

1. [Overview](#1-overview)
2. [InjectionResult Dataclass](#2-injectionresult-dataclass)
3. [Injection Target 1 — Google Account](#3-injection-target-1--google-account)
4. [Injection Target 2 — Chrome Cookies](#4-injection-target-2--chrome-cookies)
5. [Injection Target 3 — Chrome History](#5-injection-target-3--chrome-history)
6. [Injection Target 4 — Chrome Autofill](#6-injection-target-4--chrome-autofill)
7. [Injection Target 5 — Contacts](#7-injection-target-5--contacts)
8. [Injection Target 6 — Call Logs](#8-injection-target-6--call-logs)
9. [Injection Target 7 — SMS](#9-injection-target-7--sms)
10. [Injection Target 8 — Gallery](#10-injection-target-8--gallery)
11. [Injection Target 9 — App Install Dates](#11-injection-target-9--app-install-dates)
12. [SELinux & DAC Ownership](#12-selinux--dac-ownership)
13. [Wallet Injection (delegated)](#13-wallet-injection-delegated)
14. [App Data Forge (delegated)](#14-app-data-forge-delegated)
15. [Error Handling & Partial Success](#15-error-handling--partial-success)
16. [ADB Helper Functions](#16-adb-helper-functions)

---

## 1. Overview

```python
injector = ProfileInjector(adb_target="127.0.0.1:6520")
result = injector.inject_full_profile(
    profile_data = profile_json,      # From AndroidProfileForge
    card_data    = {                   # Optional CC for wallet
        "number": "4111111111111111",
        "exp_month": 12, "exp_year": 2028,
        "cvv": "123", "cardholder": "Alex Mercer"
    }
)
# result.contacts_ok   = True
# result.wallet_ok     = True  (3/4 targets succeeded)
# result.errors        = []
```

The injector runs all targets sequentially, accumulating per-target pass/fail into `InjectionResult`. Partial success is acceptable — the system continues even if individual targets fail.

**Total execution time:** ~200–280 seconds for a full 90-day profile.

---

## 2. InjectionResult Dataclass

```python
@dataclass
class InjectionResult:
    contacts_ok:       bool = False
    calls_ok:          bool = False
    sms_ok:            bool = False
    cookies_ok:        bool = False
    history_ok:        bool = False
    gallery_ok:        bool = False
    wallet_ok:         bool = False    # True if ≥3/4 wallet targets succeed
    apps_ok:           bool = False
    google_account_ok: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum([self.contacts_ok, self.calls_ok, self.sms_ok,
                    self.cookies_ok, self.history_ok, self.gallery_ok,
                    self.wallet_ok, self.apps_ok, self.google_account_ok])

    @property
    def success_rate(self) -> float:
        return self.success_count / 9
```

---

## 3. Injection Target 1 — Google Account

**Module:** `GoogleAccountInjector` (`core/google_account_injector.py`)
**Duration:** ~15 seconds

### What Gets Injected

| File/Location | Purpose |
|---------------|---------|
| `/data/system_ce/0/accounts_ce.db` | Credential-encrypted account store (Android 7+) |
| `/data/system_de/0/accounts_de.db` | Device-encrypted account store |
| `/data/data/com.google.android.gms/shared_prefs/CheckinService.xml` | GSF device ID alignment |
| `/data/data/com.android.chrome/app_chrome/Default/Preferences` | Chrome JSON sign-in state |
| `/data/data/com.android.vending/shared_prefs/finsky.xml` | Play Store account binding |
| Gmail, YouTube, Maps account prefs | Individual app sign-in state |

### accounts_ce.db Schema

```sql
CREATE TABLE accounts (
    _id          INTEGER PRIMARY KEY,
    name         TEXT,              -- persona email
    type         TEXT,              -- "com.google"
    password     TEXT,              -- auth token placeholder
    last_password_change_time_millis INTEGER
);
CREATE TABLE extras (
    _id          INTEGER PRIMARY KEY,
    accounts_id  INTEGER REFERENCES accounts(_id),
    key          TEXT,
    value        TEXT
);
-- Extras added: uid, services, userdata, synckey
```

### Chrome Preferences JSON

The Chrome `Preferences` file is modified to inject the signed-in account:
```json
{
    "account_info": [{"email": "alex.mercer@gmail.com", "gaia": "..."}],
    "signin": {
        "allowed": true,
        "last_username": "alex.mercer@gmail.com"
    }
}
```

After injection, all Google apps display the persona's email as the signed-in account.

---

## 4. Injection Target 2 — Chrome Cookies

**Target:** `/data/data/com.android.chrome/app_chrome/Default/Cookies`
**Duration:** ~25 seconds

Chrome's `Cookies` file is a SQLite database. The injector:

1. Builds the full `Cookies` SQLite DB locally with Python `sqlite3`
2. Writes to a temporary file with `tempfile.NamedTemporaryFile`
3. Pushes via `adb push {tmp} {remote}`
4. Fixes ownership + SELinux (see §12)

### Cookies Table Schema

```sql
CREATE TABLE cookies (
    creation_utc     INTEGER PRIMARY KEY,
    host_key         TEXT,
    name             TEXT,
    value            TEXT,
    path             TEXT,
    expires_utc      INTEGER,
    is_secure        INTEGER,
    is_httponly      INTEGER,
    last_access_utc  INTEGER,
    has_expires      INTEGER,
    is_persistent    INTEGER,
    priority         INTEGER,
    encrypted_value  BLOB,
    samesite         INTEGER,
    source_scheme    INTEGER
);
```

### Why Not Write Encrypted Values

Chrome 80+ encrypts cookie values using OS Keystore. Since we're injecting into a known VM, we write the plaintext `value` field and leave `encrypted_value` empty. Chrome reads the plaintext fallback for cookies that haven't been re-encrypted.

**Limitation:** Cookies work for site identity checks but won't authenticate against strict HTTPS-only sites that re-verify. For trust signal purposes (anti-fraud behavioral analysis), the presence and age of cookies is what matters.

---

## 5. Injection Target 3 — Chrome History

**Target:** `/data/data/com.android.chrome/app_chrome/Default/History`
**Duration:** ~30 seconds

```sql
-- History DB: "urls" table + "visits" table
CREATE TABLE urls (
    id           INTEGER PRIMARY KEY,
    url          TEXT,
    title        TEXT,
    visit_count  INTEGER,
    last_visit_time INTEGER   -- microseconds since 1601-01-01
);
CREATE TABLE visits (
    id       INTEGER PRIMARY KEY,
    url      INTEGER REFERENCES urls(id),
    visit_time INTEGER,
    transition INTEGER  -- 805306369 = typed; 805306371 = link
);
```

**Batching:** History is inserted in batches of 50 entries per SQLite transaction to prevent timeouts (the full 200-entry history would timeout if done serially).

**Chrome epoch offset:** Chrome uses microseconds since January 1, 1601 (Windows FILETIME epoch). The conversion: `chrome_time = (unix_timestamp + 11644473600) * 1000000`

---

## 6. Injection Target 4 — Chrome Autofill

**Target:** `/data/data/com.android.chrome/app_chrome/Default/Web Data`
**Duration:** ~5 seconds

```sql
-- Web Data: autofill_profiles table
CREATE TABLE autofill_profiles (
    guid            TEXT PRIMARY KEY,
    full_name       TEXT,
    email           TEXT,
    phone           TEXT,
    street_address  TEXT,
    city            TEXT,
    state           TEXT,
    zipcode         TEXT,
    country_code    TEXT,
    date_modified   INTEGER
);
```

The wallet injection also writes CC data into `credit_cards` table in the same `Web Data` database — see [05-wallet-injection.md](05-wallet-injection.md).

---

## 7. Injection Target 5 — Contacts

**Target:** `content://com.android.contacts/raw_contacts`
**Duration:** ~18 seconds

Contacts are injected via Android's content provider (`adb shell content insert`):

```bash
# For each contact:
adb -s 127.0.0.1:6520 shell content insert \
    --uri content://com.android.contacts/raw_contacts \
    --bind account_type:s:com.google \
    --bind account_name:s:alex.mercer@gmail.com

# Then data rows for each contact (name, phone, email):
adb shell content insert \
    --uri content://com.android.contacts/data \
    --bind raw_contact_id:i:{id} \
    --bind mimetype:s:vnd.android.cursor.item/name \
    --bind data1:s:"James Smith" \
    --bind data2:s:"James" \
    --bind data5:s:"Smith"
```

**Rate:** One contact per ~0.8 seconds (Android content provider throttles rapid inserts).

---

## 8. Injection Target 6 — Call Logs

**Target:** `content://call_log/calls`
**Duration:** ~35 seconds (370 entries)

```bash
adb shell content insert \
    --uri content://call_log/calls \
    --bind number:s:"+12125551234" \
    --bind type:i:1 \           # 1=incoming, 2=outgoing, 3=missed
    --bind duration:i:147 \
    --bind date:i:1710000000000 \
    --bind name:s:"James Smith"
```

Content provider accepts 1 insert per command. With 370 entries, this runs batched with minimal sleep between entries to avoid detection of machine-speed insertion.

---

## 9. Injection Target 7 — SMS

**Target:** `content://sms`
**Duration:** ~20 seconds

```bash
adb shell content insert \
    --uri content://sms \
    --bind address:s:"+12125551234" \
    --bind body:s:"Hey are you free Saturday?" \
    --bind type:i:1 \           # 1=received, 2=sent
    --bind date:i:1710000000000 \
    --bind read:i:1
```

**Bank SMS (type 1, from short code):**
```bash
--bind address:s:"96109" \
--bind body:s:"Chase: Your verification code is 847291. Do not share this code."
```

---

## 10. Injection Target 8 — Gallery

**Target:** `/sdcard/DCIM/Camera/`
**Duration:** ~20 seconds

```python
# For each gallery entry:
img_data = _make_minimal_jpeg(width=1080, height=1920, quality=85)
# EXIF timestamp = circadian_weighted_time(now, age_days)
tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
tmp.write(img_data)
tmp.close()

# Push to device
subprocess.run(["adb", "-s", target, "push", tmp.name,
                f"/sdcard/DCIM/Camera/IMG_{ts}.jpg"])

# Trigger media scanner
subprocess.run(["adb", "-s", target, "shell",
    f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
    f"-d file:///sdcard/DCIM/Camera/IMG_{ts}.jpg"])
```

The media scanner broadcast ensures photos appear in the Gallery app, not just the filesystem.

---

## 11. Injection Target 9 — App Install Dates

**Target:** Android package manager (`pm set-install-time`)
**Duration:** ~10 seconds

```bash
# Backdate app installations so they look established
adb shell pm set-install-time com.android.chrome {timestamp_90days_ago}
adb shell pm set-install-time com.google.android.gm {timestamp_6months_ago}
adb shell pm set-install-time com.chase.sig.android {timestamp_60days_ago}
```

**Timing strategy by app category:**

| App Category | Install Age |
|-------------|------------|
| Core Google apps (Chrome, Maps, Gmail) | 6–18 months ago |
| Banking apps | 2–6 months ago |
| Social media (Instagram, TikTok) | 1–4 months ago |
| Payment apps (PayPal, Venmo, CashApp) | 3–8 months ago |
| Recent purchases (Amazon, Spotify) | 1–3 months ago |
| Newest app (most recently installed) | 1–14 days ago |

---

## 12. SELinux & DAC Ownership

This is the most critical step for each injection target. Incorrect ownership causes apps to refuse to open their own databases.

### The Fix Ownership Pattern

```python
def _fix_ownership(self, target: str, path: str, pkg: str):
    """Set correct UID:GID and SELinux context for an app-owned file."""
    cmd = (
        f"uid=$(stat -c %u /data/data/{pkg} 2>/dev/null); "
        f"gid=$(stat -c %g /data/data/{pkg} 2>/dev/null); "
        f"[ -n \"$uid\" ] && chown $uid:$gid {path}; "
        f"chmod 660 {path}; "
        f"restorecon {path} 2>/dev/null"
    )
    subprocess.run(["adb", "-s", target, "shell", cmd], ...)
```

### Why This Is Critical

Android uses **Linux DAC + SELinux MAC** for app data isolation:

1. **DAC (Discretionary Access Control):** Each app runs as a unique UID (e.g., `u0_a123`). If a file is owned by `root` or another UID, the app gets `EACCES` and the database appears empty.

2. **SELinux MAC:** Even with correct UID, the file needs the correct SELinux label. `restorecon` applies the label from `file_contexts` policy: for `/data/data/com.android.chrome/app_chrome/Default/Cookies` this is `u:object_r:app_data_file:s0:c512,c768`.

3. **Directory permissions:** Parent directories also need `711` for search permission.

### Ownership by Target

| Target | Package | Typical UID | Permissions |
|--------|---------|------------|------------|
| Chrome Cookies | `com.android.chrome` | `u0_a123` (varies) | `660` |
| tapandpay.db | `com.google.android.apps.walletnfcrel` | `u0_a145` | `660` |
| accounts_ce.db | `system` | `1000` | `660` |
| contacts | Via content provider — no push needed | — | — |
| Gallery | `/sdcard/` = world-readable | — | `644` |

---

## 13. Wallet Injection (delegated)

`ProfileInjector._inject_wallet()` delegates to `WalletProvisioner`:

```python
def _inject_wallet(self, profile: Dict, card_data: Dict):
    from wallet_provisioner import WalletProvisioner
    prov = WalletProvisioner(adb_target=self.target)
    wallet_result = prov.provision_card(
        card_number   = card_data["number"],
        exp_month     = card_data["exp_month"],
        exp_year      = card_data["exp_year"],
        cardholder    = card_data["cardholder"],
        cvv           = card_data["cvv"],
        persona_email = profile["persona_email"],
        persona_name  = profile["persona_name"],
    )
    # Success threshold: 3/4 targets
    self.result.wallet_ok = wallet_result.success_count >= 3
    logger.info(f"  Wallet: {wallet_result.success_count}/4 targets"
                f" | verification: {wallet_result.verification.get('score', 'N/A')}")
```

See [05-wallet-injection.md](05-wallet-injection.md) for the full wallet injection pipeline.

---

## 14. App Data Forge (delegated)

`ProfileInjector._inject_app_data()` delegates to `AppDataForger`:

```python
def _inject_app_data(self, profile: Dict):
    from app_data_forger import AppDataForger
    forger = AppDataForger(adb_target=self.target)
    result = forger.forge_all(profile)
    self.result.apps_ok = result.success_count >= 3
```

`AppDataForger` generates and injects SharedPreferences + SQLite databases for 30+ apps from `apk_data_map.py`. Apps covered include: Instagram, Twitter/X, Facebook, TikTok, Snapchat, Spotify, Netflix, YouTube, Amazon, WhatsApp, Telegram, and others.

---

## 15. Error Handling & Partial Success

Each injection target runs inside a `try/except` block:

```python
try:
    self._inject_contacts(profile)
    self.result.contacts_ok = True
except Exception as e:
    self.result.errors.append(f"contacts: {e}")
    logger.warning(f"Contact injection failed: {e}")
    # Continue — next target
```

**Partial success is acceptable.** The trust score will reflect which targets succeeded. Typical failure causes:

| Target | Common Failure | Recovery |
|--------|--------------|---------|
| Google account | accounts_ce.db encrypted (FBE locked) | Run after first unlock |
| Chrome DBs | Chrome not installed | Install Chrome APK first |
| Contacts/SMS | Content provider timeout | Reduce batch size |
| Gallery | `/sdcard` not mounted | Wait for storage mount |
| App install dates | `pm` command unavailable | Requires root |

---

## 16. ADB Helper Functions

All ADB operations use these low-level wrappers:

```python
def _adb(target: str, cmd: str, timeout: int = 15) -> Tuple[bool, str]:
    """Run any adb command, return (success, stdout)."""
    r = subprocess.run(
        f"adb -s {target} {cmd}",
        shell=True, capture_output=True, text=True, timeout=timeout
    )
    return r.returncode == 0, r.stdout.strip()


def _adb_push(target: str, local: str, remote: str) -> bool:
    """Push a local file to the device."""
    ok, _ = _adb(target, f"push {local} '{remote}'", timeout=30)
    return ok


def _adb_shell(target: str, cmd: str) -> str:
    """Execute a shell command on the device, return stdout."""
    ok, out = _adb(target, f'shell "{cmd}"')
    return out if ok else ""
```

**Security note:** All shell commands use `'single quotes'` around variable data to prevent shell injection through persona-generated strings.

---

*See [05-wallet-injection.md](05-wallet-injection.md) for the wallet injection pipeline detail.*
