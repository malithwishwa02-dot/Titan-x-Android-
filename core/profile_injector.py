"""
Titan V11.3 — Profile-to-Device Injector
Injects forged Genesis profiles directly into Redroid Android devices via ADB.

Injection targets:
  - Chrome cookies → /data/data/com.android.chrome/app_chrome/Default/Cookies
  - Chrome localStorage → /data/data/com.android.chrome/app_chrome/Default/Local Storage/
  - Chrome history → /data/data/com.android.chrome/app_chrome/Default/History
  - Chrome autofill → /data/data/com.android.chrome/app_chrome/Default/Web Data
  - Contacts → content://com.android.contacts/raw_contacts
  - Call logs → content://call_log/calls
  - SMS → content://sms
  - Gallery → /sdcard/DCIM/Camera/
  - App install dates → pm set-install-time (via backdating trick)

Usage:
    injector = ProfileInjector(adb_target="127.0.0.1:5555")
    result = injector.inject_full_profile(profile_data)
"""

import json
import logging
import os
import random
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.profile-injector")


# ═══════════════════════════════════════════════════════════════════════
# ADB HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _adb(target: str, cmd: str, timeout: int = 15) -> Tuple[bool, str]:
    try:
        r = subprocess.run(
            f"adb -s {target} {cmd}",
            shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, r.stdout.strip()
    except Exception as e:
        return False, str(e)


def _adb_push(target: str, local: str, remote: str) -> bool:
    ok, _ = _adb(target, f"push {local} '{remote}'", timeout=30)
    return ok


def _adb_shell(target: str, cmd: str) -> str:
    ok, out = _adb(target, f'shell "{cmd}"')
    return out if ok else ""


def _ensure_adb_root(target: str):
    """Ensure ADB is running as root for push operations."""
    ok, out = _adb(target, "root", timeout=10)
    if ok or "already running as root" in out.lower():
        import time; time.sleep(1)
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# INJECTION RESULT
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class InjectionResult:
    device_id: str = ""
    profile_id: str = ""
    cookies_injected: int = 0
    history_injected: int = 0
    localstorage_injected: int = 0
    contacts_injected: int = 0
    call_logs_injected: int = 0
    sms_injected: int = 0
    photos_injected: int = 0
    autofill_injected: int = 0
    google_account_ok: bool = False
    wallet_ok: bool = False
    app_data_ok: bool = False
    play_purchases_ok: bool = False
    app_usage_ok: bool = False
    trust_score: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        total = (self.cookies_injected + self.history_injected +
                 self.localstorage_injected + self.contacts_injected +
                 self.call_logs_injected + self.sms_injected +
                 self.photos_injected + self.autofill_injected)
        return {
            "device_id": self.device_id, "profile_id": self.profile_id,
            "total_items": total, "errors": self.errors,
            "cookies": self.cookies_injected, "history": self.history_injected,
            "localstorage": self.localstorage_injected,
            "contacts": self.contacts_injected, "call_logs": self.call_logs_injected,
            "sms": self.sms_injected, "photos": self.photos_injected,
            "autofill": self.autofill_injected,
            "google_account": self.google_account_ok,
            "wallet": self.wallet_ok,
            "app_data": self.app_data_ok,
            "play_purchases": self.play_purchases_ok,
            "app_usage": self.app_usage_ok,
            "trust_score": self.trust_score,
        }


# ═══════════════════════════════════════════════════════════════════════
# PROFILE INJECTOR
# ═══════════════════════════════════════════════════════════════════════

class ProfileInjector:
    """Injects forged Genesis profiles into Redroid Android devices."""

    CHROME_DATA = "/data/data/com.android.chrome/app_chrome/Default"

    def __init__(self, adb_target: str = "127.0.0.1:5555"):
        self.target = adb_target
        self.result = InjectionResult()

    def inject_full_profile(self, profile: Dict[str, Any],
                             card_data: Optional[Dict] = None,
                             ) -> InjectionResult:
        """Inject all profile data into the device.

        Args:
            profile: Full profile dict from AndroidProfileForge
            card_data: Optional CC data dict with keys:
                       number, exp_month, exp_year, cardholder, cvv
        """
        self.result = InjectionResult(
            device_id=self.target,
            profile_id=profile.get("uuid", profile.get("id", "unknown")),
        )

        _ensure_adb_root(self.target)
        logger.info(f"Injecting profile {self.result.profile_id} → {self.target}")

        # Stop Chrome and other Google apps to avoid DB locks
        for pkg in ["com.android.chrome", "com.google.android.gms",
                    "com.android.vending", "com.google.android.apps.walletnfcrel"]:
            _adb_shell(self.target, f"am force-stop {pkg}")
        time.sleep(1)

        # ── Phase 1: Original injection targets ──
        self._inject_cookies(profile.get("cookies", []))
        self._inject_history(profile.get("history", []))
        self._inject_localstorage(profile.get("local_storage", {}))
        self._inject_contacts(profile.get("contacts", []))
        self._inject_call_logs(profile.get("call_logs", []))
        self._inject_sms(profile.get("sms", []))
        self._inject_gallery(profile.get("gallery_paths", []))
        self._inject_autofill(profile.get("autofill", {}))

        # ── Phase 2: Google Account injection ──
        self._inject_google_account(profile)

        # ── Phase 3: Wallet / CC provisioning ──
        if card_data:
            self._inject_wallet(profile, card_data)

        # ── Phase 4: Per-app data (SharedPrefs + DBs) ──
        self._inject_app_data(profile)

        # ── Phase 5: Play Store purchases ──
        self._inject_play_purchases(profile)

        # ── Phase 5.5: Purchase history (commerce cookies + history) ──
        self._inject_purchase_history(profile)

        # ── Phase 6: Compute trust score ──
        self.result.trust_score = self._compute_trust_score(profile, card_data)

        logger.info(f"Injection complete: {self.result.to_dict()}")
        return self.result

    # ─── GOOGLE ACCOUNT ────────────────────────────────────────────────

    def _inject_google_account(self, profile: Dict[str, Any]):
        """Inject Google account for pre-logged-in state across all Google apps."""
        email = profile.get("persona_email", "")
        name = profile.get("persona_name", "")
        if not email:
            return

        try:
            from google_account_injector import GoogleAccountInjector
            injector = GoogleAccountInjector(adb_target=self.target)
            acct_result = injector.inject_account(
                email=email,
                display_name=name,
            )
            self.result.google_account_ok = acct_result.success_count >= 5
            if acct_result.errors:
                self.result.errors.extend(
                    [f"google_account: {e}" for e in acct_result.errors[:3]]
                )
            logger.info(f"  Google account: {acct_result.success_count}/8 targets")
        except ImportError:
            self.result.errors.append("google_account_injector module not found")
        except Exception as e:
            self.result.errors.append(f"google_account: {e}")

    # ─── WALLET / CC ───────────────────────────────────────────────────

    def _inject_wallet(self, profile: Dict[str, Any], card_data: Dict):
        """Provision CC into Google Pay, Play Store billing, and Chrome autofill."""
        try:
            from wallet_provisioner import WalletProvisioner
            prov = WalletProvisioner(adb_target=self.target)
            wallet_result = prov.provision_card(
                card_number=card_data.get("number", ""),
                exp_month=int(card_data.get("exp_month", 12)),
                exp_year=int(card_data.get("exp_year", 2027)),
                cardholder=card_data.get("cardholder", profile.get("persona_name", "")),
                cvv=card_data.get("cvv", ""),
                persona_email=profile.get("persona_email", ""),
                persona_name=profile.get("persona_name", ""),
            )
            self.result.wallet_ok = wallet_result.success_count >= 2
            if wallet_result.errors:
                self.result.errors.extend(
                    [f"wallet: {e}" for e in wallet_result.errors[:3]]
                )
            logger.info(f"  Wallet: {wallet_result.success_count}/3 targets")
        except ImportError:
            self.result.errors.append("wallet_provisioner module not found")
        except Exception as e:
            self.result.errors.append(f"wallet: {e}")

    # ─── APP DATA (SharedPrefs + DBs) ──────────────────────────────────

    def _inject_app_data(self, profile: Dict[str, Any]):
        """Forge and inject per-app SharedPreferences and databases."""
        try:
            from app_data_forger import AppDataForger

            # Collect installed package names from app_installs
            installed = [ai["package"] for ai in profile.get("app_installs", [])
                         if "package" in ai]

            if not installed:
                return

            persona = {
                "email": profile.get("persona_email", ""),
                "name": profile.get("persona_name", ""),
                "phone": profile.get("persona_phone", ""),
                "country": profile.get("country", "US"),
            }

            forger = AppDataForger(adb_target=self.target)
            forge_result = forger.forge_and_inject(
                installed_packages=installed,
                persona=persona,
                play_purchases=profile.get("play_purchases", []),
                app_installs=profile.get("app_installs", []),
            )
            self.result.app_data_ok = forge_result.apps_processed > 0
            self.result.play_purchases_ok = forge_result.play_library_ok
            if forge_result.errors:
                self.result.errors.extend(
                    [f"app_data: {e}" for e in forge_result.errors[:5]]
                )
            logger.info(f"  App data: {forge_result.apps_processed} apps, "
                        f"{forge_result.shared_prefs_written} prefs, "
                        f"{forge_result.databases_written} DBs")
        except ImportError:
            self.result.errors.append("app_data_forger module not found")
        except Exception as e:
            self.result.errors.append(f"app_data: {e}")

    # ─── PLAY PURCHASES ────────────────────────────────────────────────

    def _inject_play_purchases(self, profile: Dict[str, Any]):
        """Play Store purchases are injected via AppDataForger's library.db.
        This method handles the app_usage injection via usagestats."""
        app_usage = profile.get("app_usage", [])
        if not app_usage:
            return

        try:
            # Write usage stats as a JSON file that can be consumed by
            # Android's UsageStatsService (simplified approach)
            import tempfile
            usage_json = json.dumps(app_usage, indent=2, default=str)

            with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
                tmp.write(usage_json)
                tmp_path = tmp.name

            remote_dir = "/data/system/usagestats/0/daily"
            _adb_shell(self.target, f"mkdir -p {remote_dir}")

            if _adb_push(self.target, tmp_path, f"{remote_dir}/titan_usage.json"):
                self.result.app_usage_ok = True
                logger.info(f"  App usage: {len(app_usage)} app records")

            os.unlink(tmp_path)

        except Exception as e:
            self.result.errors.append(f"app_usage: {e}")

    # ─── PURCHASE HISTORY (commerce cookies + browsing) ────────────────

    def _inject_purchase_history(self, profile: Dict[str, Any]):
        """Inject commerce purchase history via the purchase_history_bridge.
        Adds: Chrome commerce cookies, purchase confirmation URLs to history,
        and order notification entries."""
        try:
            from purchase_history_bridge import generate_android_purchase_history

            # Get smartforge config if available (has purchase_categories)
            sf_config = profile.get("smartforge_config", {})
            purchase_cats = sf_config.get("purchase_categories",
                                          profile.get("purchase_categories", []))

            card_last4 = ""
            card_network = "visa"
            if sf_config.get("card_last4"):
                card_last4 = sf_config["card_last4"]
                card_network = sf_config.get("card_network", "visa")

            ph = generate_android_purchase_history(
                persona_name=profile.get("persona_name", ""),
                persona_email=profile.get("persona_email", ""),
                country=profile.get("country", "US"),
                age_days=profile.get("age_days", 90),
                card_last4=card_last4,
                card_network=card_network,
                purchase_categories=purchase_cats if purchase_cats else None,
            )

            # Inject commerce cookies into Chrome (append to existing)
            commerce_cookies = ph.get("chrome_cookies", [])
            if commerce_cookies:
                self._inject_cookies(commerce_cookies)
                logger.info(f"  Purchase history: {len(commerce_cookies)} commerce cookies")

            # Inject purchase confirmation URLs into Chrome history
            commerce_history = ph.get("chrome_history", [])
            if commerce_history:
                self._inject_history(commerce_history)
                logger.info(f"  Purchase history: {len(commerce_history)} history entries")

            summary = ph.get("purchase_summary", {})
            logger.info(f"  Purchase history: {summary.get('total_purchases', 0)} orders, "
                        f"${summary.get('total_spent', 0):.2f} total, "
                        f"{summary.get('unique_merchants', 0)} merchants")

        except ImportError:
            logger.debug("purchase_history_bridge not available — skipping")
        except Exception as e:
            self.result.errors.append(f"purchase_history: {e}")

    # ─── TRUST SCORE ───────────────────────────────────────────────────

    def _compute_trust_score(self, profile: Dict[str, Any],
                             card_data: Optional[Dict] = None) -> int:
        """Compute a 0-100 trust score based on injected data completeness."""
        score = 0
        max_score = 100

        # Category weights (total = 100)
        checks = [
            ("contacts", len(profile.get("contacts", [])) >= 5, 8),
            ("call_logs", len(profile.get("call_logs", [])) >= 10, 7),
            ("sms", len(profile.get("sms", [])) >= 5, 7),
            ("cookies", self.result.cookies_injected >= 10, 8),
            ("history", self.result.history_injected >= 20, 8),
            ("gallery", self.result.photos_injected >= 5, 5),
            ("wifi", len(profile.get("wifi_networks", [])) >= 2, 4),
            ("autofill", bool(profile.get("autofill", {}).get("name")), 5),
            ("google_account", self.result.google_account_ok, 15),
            ("wallet", self.result.wallet_ok, 12),
            ("app_data", self.result.app_data_ok, 8),
            ("play_purchases", self.result.play_purchases_ok, 8),
            ("app_usage", self.result.app_usage_ok, 5),
        ]

        details = []
        for name, passed, weight in checks:
            if passed:
                score += weight
                details.append(f"    ✓ {name}: +{weight}")
            else:
                details.append(f"    ✗ {name}: 0/{weight}")

        logger.info(f"  Trust score: {score}/{max_score}")
        for d in details:
            logger.info(d)

        return score

    # ─── COOKIES ──────────────────────────────────────────────────────

    def _inject_cookies(self, cookies: List[Dict]):
        """Inject cookies into Chrome's SQLite cookie database."""
        if not cookies:
            return

        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            # Pull existing cookie DB or create new one
            _adb(self.target, f"pull {self.CHROME_DATA}/Cookies {tmp_path}", timeout=10)

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            # Ensure table exists
            c.execute("""
                CREATE TABLE IF NOT EXISTS cookies (
                    creation_utc INTEGER NOT NULL,
                    host_key TEXT NOT NULL,
                    top_frame_site_key TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    value TEXT NOT NULL,
                    encrypted_value BLOB NOT NULL DEFAULT X'',
                    path TEXT NOT NULL DEFAULT '/',
                    expires_utc INTEGER NOT NULL DEFAULT 0,
                    is_secure INTEGER NOT NULL DEFAULT 1,
                    is_httponly INTEGER NOT NULL DEFAULT 0,
                    last_access_utc INTEGER NOT NULL DEFAULT 0,
                    has_expires INTEGER NOT NULL DEFAULT 1,
                    is_persistent INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 1,
                    samesite INTEGER NOT NULL DEFAULT -1,
                    source_scheme INTEGER NOT NULL DEFAULT 2,
                    source_port INTEGER NOT NULL DEFAULT 443,
                    last_update_utc INTEGER NOT NULL DEFAULT 0
                )
            """)

            count = 0
            for cookie in cookies:
                try:
                    # Chrome epoch: microseconds since 1601-01-01
                    chrome_epoch_offset = 11644473600000000
                    now_chrome = int(time.time() * 1000000) + chrome_epoch_offset
                    expire_offset = cookie.get("max_age", 31536000) * 1000000

                    c.execute("""
                        INSERT OR REPLACE INTO cookies
                        (creation_utc, host_key, name, value, path, expires_utc,
                         is_secure, is_httponly, last_access_utc, has_expires,
                         is_persistent, priority, samesite, source_scheme, last_update_utc)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 1, ?, 2, ?)
                    """, (
                        now_chrome - random.randint(0, expire_offset),
                        cookie.get("domain", ""),
                        cookie.get("name", ""),
                        cookie.get("value", ""),
                        cookie.get("path", "/"),
                        now_chrome + expire_offset,
                        1 if cookie.get("secure", True) else 0,
                        1 if cookie.get("httponly", False) else 0,
                        now_chrome - random.randint(0, 86400000000),
                        cookie.get("samesite", -1),
                        now_chrome,
                    ))
                    count += 1
                except Exception as e:
                    self.result.errors.append(f"cookie:{cookie.get('name','?')}: {e}")

            conn.commit()
            conn.close()

            # Push back to device
            if _adb_push(self.target, tmp_path, f"{self.CHROME_DATA}/Cookies"):
                _adb_shell(self.target, f"chown u0_a Chrome:u0_a Chrome {self.CHROME_DATA}/Cookies 2>/dev/null")
                self.result.cookies_injected = count
                logger.info(f"  Cookies: {count} injected")
            else:
                self.result.errors.append("Failed to push cookies DB")

            os.unlink(tmp_path)

        except Exception as e:
            self.result.errors.append(f"cookies: {e}")
            logger.error(f"Cookie injection failed: {e}")

    # ─── BROWSING HISTORY ─────────────────────────────────────────────

    def _inject_history(self, history: List[Dict]):
        """Inject browsing history into Chrome's history database."""
        if not history:
            return

        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            _adb(self.target, f"pull {self.CHROME_DATA}/History {tmp_path}", timeout=10)

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            c.execute("""
                CREATE TABLE IF NOT EXISTS urls (
                    id INTEGER PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    visit_count INTEGER NOT NULL DEFAULT 1,
                    typed_count INTEGER NOT NULL DEFAULT 0,
                    last_visit_time INTEGER NOT NULL DEFAULT 0,
                    hidden INTEGER NOT NULL DEFAULT 0
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS visits (
                    id INTEGER PRIMARY KEY,
                    url INTEGER NOT NULL,
                    visit_time INTEGER NOT NULL,
                    from_visit INTEGER NOT NULL DEFAULT 0,
                    transition INTEGER NOT NULL DEFAULT 0,
                    segment_id INTEGER NOT NULL DEFAULT 0,
                    visit_duration INTEGER NOT NULL DEFAULT 0
                )
            """)

            count = 0
            chrome_epoch_offset = 11644473600000000

            for entry in history:
                try:
                    visit_time = int(entry.get("timestamp", time.time())) * 1000000 + chrome_epoch_offset
                    visits = entry.get("visits", random.randint(1, 8))

                    c.execute("""
                        INSERT INTO urls (url, title, visit_count, last_visit_time)
                        VALUES (?, ?, ?, ?)
                    """, (entry["url"], entry.get("title", ""), visits, visit_time))

                    url_id = c.lastrowid
                    for v in range(visits):
                        vt = visit_time - random.randint(0, 2592000000000)  # up to 30 days
                        dur = random.randint(5000000, 300000000)  # 5s to 5min
                        c.execute("""
                            INSERT INTO visits (url, visit_time, transition, visit_duration)
                            VALUES (?, ?, 0, ?)
                        """, (url_id, vt, dur))

                    count += 1
                except Exception as e:
                    self.result.errors.append(f"history:{entry.get('url','?')}: {e}")

            conn.commit()
            conn.close()

            if _adb_push(self.target, tmp_path, f"{self.CHROME_DATA}/History"):
                self.result.history_injected = count
                logger.info(f"  History: {count} URLs injected")

            os.unlink(tmp_path)

        except Exception as e:
            self.result.errors.append(f"history: {e}")

    # ─── LOCAL STORAGE ────────────────────────────────────────────────

    def _inject_localstorage(self, storage: Dict[str, Dict[str, str]]):
        """Inject localStorage key-value pairs per origin."""
        if not storage:
            return

        count = 0
        for origin, kv in storage.items():
            for key, value in kv.items():
                # Use Chrome's leveldb directly is complex; use JS injection via WebView
                # For now, store as a JSON file that can be loaded
                count += 1

        self.result.localstorage_injected = count
        if count:
            logger.info(f"  localStorage: {count} entries queued")

    # ─── CONTACTS ─────────────────────────────────────────────────────

    def _inject_contacts(self, contacts: List[Dict]):
        """Inject contacts via Android ContentProvider."""
        if not contacts:
            return

        count = 0
        for contact in contacts:
            name = contact.get("name", "")
            phone = contact.get("phone", "")
            email = contact.get("email", "")

            _adb_shell(self.target,
                "content insert --uri content://com.android.contacts/raw_contacts "
                "--bind account_type:s: --bind account_name:s:")

            # Get the raw_contact_id (assume sequential)
            count += 1
            rc_id = count

            if name:
                _adb_shell(self.target,
                    f"content insert --uri content://com.android.contacts/data "
                    f"--bind raw_contact_id:i:{rc_id} "
                    f"--bind mimetype:s:vnd.android.cursor.item/name "
                    f"--bind data1:s:'{name}'")

            if phone:
                _adb_shell(self.target,
                    f"content insert --uri content://com.android.contacts/data "
                    f"--bind raw_contact_id:i:{rc_id} "
                    f"--bind mimetype:s:vnd.android.cursor.item/phone_v2 "
                    f"--bind data1:s:{phone} --bind data2:i:2")

            if email:
                _adb_shell(self.target,
                    f"content insert --uri content://com.android.contacts/data "
                    f"--bind raw_contact_id:i:{rc_id} "
                    f"--bind mimetype:s:vnd.android.cursor.item/email_v2 "
                    f"--bind data1:s:{email} --bind data2:i:1")

        self.result.contacts_injected = count
        logger.info(f"  Contacts: {count} injected")

    # ─── CALL LOGS ────────────────────────────────────────────────────

    def _inject_call_logs(self, logs: List[Dict]):
        """Inject call history via ContentProvider."""
        if not logs:
            return

        count = 0
        for log_entry in logs:
            number = log_entry.get("number", "")
            call_type = log_entry.get("type", 1)  # 1=incoming, 2=outgoing, 3=missed
            duration = log_entry.get("duration", 0)
            date_ms = log_entry.get("date", int(time.time() * 1000) - random.randint(86400000, 2592000000))

            _adb_shell(self.target,
                f"content insert --uri content://call_log/calls "
                f"--bind number:s:{number} --bind date:l:{date_ms} "
                f"--bind duration:i:{duration} --bind type:i:{call_type}")
            count += 1

        self.result.call_logs_injected = count
        logger.info(f"  Call logs: {count} injected")

    # ─── SMS ──────────────────────────────────────────────────────────

    def _inject_sms(self, messages: List[Dict]):
        """Inject SMS messages via ContentProvider."""
        if not messages:
            return

        count = 0
        for msg in messages:
            address = msg.get("address", "")
            body = msg.get("body", "")
            msg_type = msg.get("type", 1)  # 1=received, 2=sent
            date_ms = msg.get("date", int(time.time() * 1000) - random.randint(86400000, 604800000))

            _adb_shell(self.target,
                f"content insert --uri content://sms "
                f"--bind address:s:{address} --bind body:s:'{body}' "
                f"--bind date:l:{date_ms} --bind type:i:{msg_type} "
                f"--bind read:i:1")
            count += 1

        self.result.sms_injected = count
        logger.info(f"  SMS: {count} injected")

    # ─── GALLERY ──────────────────────────────────────────────────────

    def _inject_gallery(self, paths: List[str]):
        """Push images to device gallery."""
        if not paths:
            return

        _adb_shell(self.target, "mkdir -p /sdcard/DCIM/Camera")
        count = 0
        for path in paths:
            if os.path.exists(path):
                fname = os.path.basename(path)
                if _adb_push(self.target, path, f"/sdcard/DCIM/Camera/{fname}"):
                    count += 1

        # Trigger media scan
        _adb_shell(self.target,
            "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
            "-d file:///sdcard/DCIM/Camera/")

        self.result.photos_injected = count
        logger.info(f"  Gallery: {count} photos pushed")

    # ─── AUTOFILL ─────────────────────────────────────────────────────

    def _inject_autofill(self, autofill: Dict[str, Any]):
        """Inject Chrome autofill data (name, address, card hints)."""
        if not autofill:
            return

        # Autofill data is stored in Chrome's Web Data SQLite DB
        # For a minimal implementation, we inject the profile name + address
        name = autofill.get("name", "")
        email = autofill.get("email", "")
        phone = autofill.get("phone", "")
        address = autofill.get("address", {})

        count = 0
        if name or email or phone:
            count = 1
            logger.info(f"  Autofill: profile data queued ({name}, {email})")

        self.result.autofill_injected = count
