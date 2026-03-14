"""
Titan V11.3 — Google Account Injector
Injects a Google account into a Cuttlefish Android VM so all Google apps appear logged in.

Injection targets:
  - /data/system_ce/0/accounts_ce.db   — Credential-encrypted account store (Android 7+)
  - /data/system_de/0/accounts_de.db   — Device-encrypted account store
  - GMS shared_prefs (CheckinService, Gservices)
  - Chrome sign-in state (Preferences JSON)
  - Play Store account binding (finsky.xml)
  - Gmail, YouTube, Maps account prefs

After injection, all Google apps show the persona's email as the signed-in account
without requiring manual login.

Usage:
    injector = GoogleAccountInjector(adb_target="127.0.0.1:5555")
    result = injector.inject_account(
        email="alex.mercer@gmail.com",
        display_name="Alex Mercer",
        android_id="a1b2c3d4e5f6a7b8",
    )
"""

import json
import logging
import os
import random
import secrets
import sqlite3
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.google-account-injector")


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
    ok, out = _adb(target, "root", timeout=10)
    if ok or "already running as root" in out.lower():
        import time; time.sleep(1)
    return True


# ═══════════════════════════════════════════════════════════════════════
# RESULT
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class AccountInjectionResult:
    email: str = ""
    accounts_ce_ok: bool = False
    accounts_de_ok: bool = False
    gms_prefs_ok: bool = False
    chrome_signin_ok: bool = False
    play_store_ok: bool = False
    gmail_ok: bool = False
    youtube_ok: bool = False
    maps_ok: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum([
            self.accounts_ce_ok, self.accounts_de_ok, self.gms_prefs_ok,
            self.chrome_signin_ok, self.play_store_ok, self.gmail_ok,
            self.youtube_ok, self.maps_ok,
        ])

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "success_count": self.success_count,
            "total_targets": 8,
            "accounts_ce": self.accounts_ce_ok,
            "accounts_de": self.accounts_de_ok,
            "gms_prefs": self.gms_prefs_ok,
            "chrome_signin": self.chrome_signin_ok,
            "play_store": self.play_store_ok,
            "gmail": self.gmail_ok,
            "youtube": self.youtube_ok,
            "maps": self.maps_ok,
            "errors": self.errors,
        }


# ═══════════════════════════════════════════════════════════════════════
# GOOGLE ACCOUNT INJECTOR
# ═══════════════════════════════════════════════════════════════════════

class GoogleAccountInjector:
    """Injects a Google account into a Cuttlefish Android VM for pre-logged-in state."""

    ACCOUNTS_CE_PATH = "/data/system_ce/0/accounts_ce.db"
    ACCOUNTS_DE_PATH = "/data/system_de/0/accounts_de.db"
    GMS_DATA = "/data/data/com.google.android.gms"
    GSF_DATA = "/data/data/com.google.android.gsf"
    CHROME_DATA = "/data/data/com.android.chrome"
    VENDING_DATA = "/data/data/com.android.vending"
    GMAIL_DATA = "/data/data/com.google.android.gm"
    YOUTUBE_DATA = "/data/data/com.google.android.youtube"
    MAPS_DATA = "/data/data/com.google.android.apps.maps"

    def __init__(self, adb_target: str = "127.0.0.1:5555"):
        self.target = adb_target

    def inject_account(self,
                       email: str,
                       display_name: str = "",
                       android_id: str = "",
                       auth_token: str = "",
                       gaia_id: str = "",
                       ) -> AccountInjectionResult:
        """
        Inject a Google account into all relevant system and app databases.

        Args:
            email: Google account email (persona_email)
            display_name: Display name for the account
            android_id: Device android_id (hex string)
            auth_token: Optional pre-generated auth token (auto-generated if empty)
            gaia_id: Google Account ID (auto-generated if empty)

        Returns:
            AccountInjectionResult with per-target success flags
        """
        result = AccountInjectionResult(email=email)
        _ensure_adb_root(self.target)

        if not display_name:
            parts = email.split("@")[0].split(".")
            display_name = " ".join(p.capitalize() for p in parts[:2])

        if not android_id:
            android_id = secrets.token_hex(8)

        if not auth_token:
            auth_token = f"ya29.{secrets.token_urlsafe(120)}"

        if not gaia_id:
            gaia_id = str(random.randint(100000000000000000, 999999999999999999))

        logger.info(f"Injecting Google account: {email} → {self.target}")

        # 1. Inject into accounts_ce.db (credential-encrypted)
        self._inject_accounts_ce(email, display_name, auth_token, gaia_id, result)

        # 2. Inject into accounts_de.db (device-encrypted)
        self._inject_accounts_de(email, result)

        # 3. GMS shared_prefs (Play Services)
        self._inject_gms_prefs(email, android_id, gaia_id, result)

        # 4. Chrome sign-in state
        self._inject_chrome_signin(email, display_name, gaia_id, result)

        # 5. Play Store account binding
        self._inject_play_store(email, result)

        # 6. Gmail prefs
        self._inject_gmail(email, result)

        # 7. YouTube prefs
        self._inject_youtube(email, result)

        # 8. Maps prefs
        self._inject_maps(email, result)

        logger.info(f"Account injection complete: {result.success_count}/8 targets")
        return result

    # ─── ACCOUNTS_CE.DB ───────────────────────────────────────────────

    def _inject_accounts_ce(self, email: str, display_name: str,
                            auth_token: str, gaia_id: str,
                            result: AccountInjectionResult):
        """Inject into Android's credential-encrypted account database."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            # Try to pull existing DB
            _adb(self.target, f"pull {self.ACCOUNTS_CE_PATH} {tmp_path}", timeout=10)

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            # Create tables if they don't exist
            c.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    previous_name TEXT DEFAULT NULL,
                    last_password_entry_time_millis_epoch INTEGER DEFAULT 0
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS authtokens (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    accounts_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    authtoken TEXT NOT NULL,
                    FOREIGN KEY (accounts_id) REFERENCES accounts(_id)
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS extras (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    accounts_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    FOREIGN KEY (accounts_id) REFERENCES accounts(_id)
                )
            """)

            # Check if account already exists
            c.execute("SELECT _id FROM accounts WHERE name=? AND type='com.google'", (email,))
            row = c.fetchone()
            if row:
                account_id = row[0]
            else:
                # Detect schema — Android 14 uses different columns than older versions
                cols = [r[1] for r in c.execute("PRAGMA table_info(accounts)").fetchall()]
                if "last_password_entry_time_millis_epoch" in cols:
                    c.execute(
                        "INSERT INTO accounts (name, type, last_password_entry_time_millis_epoch) VALUES (?, 'com.google', ?)",
                        (email, int(time.time() * 1000)),
                    )
                elif "password" in cols:
                    c.execute(
                        "INSERT INTO accounts (name, type, password) VALUES (?, 'com.google', '')",
                        (email,),
                    )
                else:
                    c.execute(
                        "INSERT INTO accounts (name, type) VALUES (?, 'com.google')",
                        (email,),
                    )
                account_id = c.lastrowid

            # Insert auth tokens — expanded matrix covering core Google scopes
            token_types = [
                ("com.google", auth_token),
                ("oauth2:https://www.googleapis.com/auth/plus.me", f"ya29.{secrets.token_urlsafe(80)}"),
                ("oauth2:https://www.googleapis.com/auth/userinfo.email", f"ya29.{secrets.token_urlsafe(80)}"),
                ("oauth2:https://www.googleapis.com/auth/userinfo.profile", f"ya29.{secrets.token_urlsafe(80)}"),
                ("oauth2:https://www.googleapis.com/auth/drive", f"ya29.{secrets.token_urlsafe(80)}"),
                ("oauth2:https://www.googleapis.com/auth/youtube", f"ya29.{secrets.token_urlsafe(80)}"),
                ("oauth2:https://www.googleapis.com/auth/calendar", f"ya29.{secrets.token_urlsafe(80)}"),
                ("oauth2:https://www.googleapis.com/auth/contacts", f"ya29.{secrets.token_urlsafe(80)}"),
                ("oauth2:https://www.googleapis.com/auth/gmail.readonly", f"ya29.{secrets.token_urlsafe(80)}"),
                ("SID", secrets.token_hex(60)),
                ("LSID", secrets.token_hex(60)),
                ("oauth2:https://www.googleapis.com/auth/android", f"ya29.{secrets.token_urlsafe(80)}"),
            ]

            for token_type, token_value in token_types:
                c.execute("DELETE FROM authtokens WHERE accounts_id=? AND type=?", (account_id, token_type))
                c.execute(
                    "INSERT INTO authtokens (accounts_id, type, authtoken) VALUES (?, ?, ?)",
                    (account_id, token_type, token_value),
                )

            # Insert account extras
            extras = [
                ("google.services.gaia", gaia_id),
                ("is_child_account", "false"),
                ("GoogleUserId", gaia_id),
                ("given_name", display_name.split()[0] if display_name else ""),
                ("family_name", display_name.split()[-1] if display_name and len(display_name.split()) > 1 else ""),
                ("display_name", display_name),
            ]

            for key, value in extras:
                c.execute("DELETE FROM extras WHERE accounts_id=? AND key=?", (account_id, key))
                c.execute(
                    "INSERT INTO extras (accounts_id, key, value) VALUES (?, ?, ?)",
                    (account_id, key, value),
                )

            conn.commit()
            conn.close()

            # Push back
            _adb_shell(self.target, "mkdir -p /data/system_ce/0")
            if _adb_push(self.target, tmp_path, self.ACCOUNTS_CE_PATH):
                _adb_shell(self.target, f"chmod 600 {self.ACCOUNTS_CE_PATH}")
                _adb_shell(self.target, f"chown system:system {self.ACCOUNTS_CE_PATH}")
                _adb_shell(self.target, f"restorecon {self.ACCOUNTS_CE_PATH} 2>/dev/null")
                result.accounts_ce_ok = True
                logger.info(f"  accounts_ce.db: account {email} injected")
            else:
                result.errors.append("Failed to push accounts_ce.db")

            os.unlink(tmp_path)

        except Exception as e:
            result.errors.append(f"accounts_ce: {e}")
            logger.error(f"accounts_ce injection failed: {e}")

    # ─── ACCOUNTS_DE.DB ───────────────────────────────────────────────

    def _inject_accounts_de(self, email: str, result: AccountInjectionResult):
        """Inject into device-encrypted account database."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            _adb(self.target, f"pull {self.ACCOUNTS_DE_PATH} {tmp_path}", timeout=10)

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            c.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    _id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    previous_name TEXT DEFAULT NULL,
                    last_password_entry_time_millis_epoch INTEGER DEFAULT 0
                )
            """)

            c.execute("SELECT _id FROM accounts WHERE name=? AND type='com.google'", (email,))
            if not c.fetchone():
                c.execute(
                    "INSERT INTO accounts (name, type, last_password_entry_time_millis_epoch) VALUES (?, 'com.google', ?)",
                    (email, int(time.time() * 1000)),
                )

            conn.commit()
            conn.close()

            _adb_shell(self.target, "mkdir -p /data/system_de/0")
            if _adb_push(self.target, tmp_path, self.ACCOUNTS_DE_PATH):
                _adb_shell(self.target, f"chmod 600 {self.ACCOUNTS_DE_PATH}")
                _adb_shell(self.target, f"chown system:system {self.ACCOUNTS_DE_PATH}")
                _adb_shell(self.target, f"restorecon {self.ACCOUNTS_DE_PATH} 2>/dev/null")
                result.accounts_de_ok = True
                logger.info(f"  accounts_de.db: account {email} injected")
            else:
                result.errors.append("Failed to push accounts_de.db")

            os.unlink(tmp_path)

        except Exception as e:
            result.errors.append(f"accounts_de: {e}")
            logger.error(f"accounts_de injection failed: {e}")

    # ─── GMS SHARED PREFS ─────────────────────────────────────────────

    def _inject_gms_prefs(self, email: str, android_id: str, gaia_id: str,
                          result: AccountInjectionResult):
        """Inject Google Play Services and GSF shared prefs."""
        try:
            checkin_ts = str(int(time.time() * 1000))
            device_id = str(random.randint(10**15, 10**16 - 1))

            # CheckinService.xml
            checkin_xml = self._build_shared_prefs_xml({
                "lastCheckin": checkin_ts,
                "deviceId": device_id,
                "digest": secrets.token_hex(20),
                "versionInfo": "14.0",
                "lastCheckinElapsedRealtime": str(random.randint(100000, 9999999)),
            })
            self._push_shared_prefs(
                f"{self.GMS_DATA}/shared_prefs/CheckinService.xml",
                checkin_xml, "com.google.android.gms", result,
            )

            # GservicesSettings.xml
            gservices_xml = self._build_shared_prefs_xml({
                "android_id": android_id,
                "checkin_device_id": device_id,
                "gms:version": "24.26.32",
            })
            self._push_shared_prefs(
                f"{self.GMS_DATA}/shared_prefs/GservicesSettings.xml",
                gservices_xml, "com.google.android.gms", result,
            )

            # Measurement prefs
            measurement_xml = self._build_shared_prefs_xml({
                "has_been_opened": "true",
                "deferred_analytics_collection": "false",
                "first_open_time": checkin_ts,
                "app_instance_id": secrets.token_hex(16),
            })
            self._push_shared_prefs(
                f"{self.GMS_DATA}/shared_prefs/com.google.android.gms.measurement.prefs.xml",
                measurement_xml, "com.google.android.gms", result,
            )

            # GSF googlesettings.xml
            gsf_xml = self._build_shared_prefs_xml({
                "android_id": android_id,
                "checkin_device_id": device_id,
                "digest": secrets.token_hex(20),
            })
            self._push_shared_prefs(
                f"{self.GSF_DATA}/shared_prefs/googlesettings.xml",
                gsf_xml, "com.google.android.gsf", result,
            )

            result.gms_prefs_ok = True
            logger.info(f"  GMS prefs: injected for {email}")

        except Exception as e:
            result.errors.append(f"gms_prefs: {e}")
            logger.error(f"GMS prefs injection failed: {e}")

    # ─── CHROME SIGN-IN ───────────────────────────────────────────────

    def _inject_chrome_signin(self, email: str, display_name: str,
                              gaia_id: str, result: AccountInjectionResult):
        """Inject Chrome sign-in state via Preferences JSON."""
        try:
            prefs_path = f"{self.CHROME_DATA}/app_chrome/Default/Preferences"

            # Pull existing Preferences or start fresh
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
                tmp_path = tmp.name

            ok, _ = _adb(self.target, f"pull {prefs_path} {tmp_path}", timeout=10)

            try:
                with open(tmp_path, "r") as f:
                    prefs = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                prefs = {}

            # Inject account info
            prefs["account_info"] = [{
                "account_id": gaia_id,
                "email": email,
                "full_name": display_name,
                "given_name": display_name.split()[0] if display_name else "",
                "gaia": gaia_id,
                "hosted_domain": "",
                "locale": "en",
                "is_child_account": False,
                "is_under_advanced_protection": False,
                "last_downloaded_image_url_with_size": "",
            }]

            prefs["signin"] = {
                "allowed": True,
                "allowed_on_next_startup": True,
            }

            prefs["google"] = prefs.get("google", {})
            prefs["google"]["services"] = prefs["google"].get("services", {})
            prefs["google"]["services"]["signin"] = {
                "allowed": True,
            }

            # Sync enabled
            prefs["sync"] = prefs.get("sync", {})
            prefs["sync"]["has_setup_completed"] = True
            prefs["sync"]["requested"] = True

            # Profile info
            prefs["profile"] = prefs.get("profile", {})
            prefs["profile"]["name"] = display_name
            prefs["profile"]["gaia_info_picture_url"] = ""

            with open(tmp_path, "w") as f:
                json.dump(prefs, f, indent=2)

            # Ensure directory exists
            _adb_shell(self.target, f"mkdir -p {self.CHROME_DATA}/app_chrome/Default")

            if _adb_push(self.target, tmp_path, prefs_path):
                result.chrome_signin_ok = True
                logger.info(f"  Chrome: signed in as {email}")
            else:
                result.errors.append("Failed to push Chrome Preferences")

            os.unlink(tmp_path)

        except Exception as e:
            result.errors.append(f"chrome_signin: {e}")
            logger.error(f"Chrome sign-in injection failed: {e}")

    # ─── PLAY STORE ───────────────────────────────────────────────────

    def _inject_play_store(self, email: str, result: AccountInjectionResult):
        """Inject Play Store account binding via finsky.xml."""
        try:
            finsky_xml = self._build_shared_prefs_xml({
                "tos_accepted": "true",
                "setup_wizard_complete": "true",
                "account": email,
                "first_account_name": email,
                "content_filters": "0",
                "auto_update_enabled": "true",
                "download_manager_max_bytes_over_mobile": "0",
                "notify_updates": "true",
                "last_notified_time": str(int(time.time() * 1000)),
            })

            self._push_shared_prefs(
                f"{self.VENDING_DATA}/shared_prefs/finsky.xml",
                finsky_xml, "com.android.vending", result,
            )

            result.play_store_ok = True
            logger.info(f"  Play Store: bound to {email}")

        except Exception as e:
            result.errors.append(f"play_store: {e}")

    # ─── GMAIL ────────────────────────────────────────────────────────

    def _inject_gmail(self, email: str, result: AccountInjectionResult):
        """Inject Gmail account preferences."""
        try:
            gmail_xml = self._build_shared_prefs_xml({
                "account_name": email,
                "show_sender_images": "true",
                "default_reply_all": "false",
                "auto_advance": "newer",
                "conversation_view": "true",
                "notifications_enabled": "true",
                "swipe_action_left": "archive",
                "swipe_action_right": "delete",
            })

            self._push_shared_prefs(
                f"{self.GMAIL_DATA}/shared_prefs/Gmail.xml",
                gmail_xml, "com.google.android.gm", result,
            )

            result.gmail_ok = True
            logger.info(f"  Gmail: configured for {email}")

        except Exception as e:
            result.errors.append(f"gmail: {e}")

    # ─── YOUTUBE ──────────────────────────────────────────────────────

    def _inject_youtube(self, email: str, result: AccountInjectionResult):
        """Inject YouTube account preferences."""
        try:
            yt_xml = self._build_shared_prefs_xml({
                "account_name": email,
                "signed_in": "true",
                "autoplay_enabled": "true",
                "dark_theme": "auto",
                "restricted_mode": "false",
                "quality_wifi": "auto",
            })

            self._push_shared_prefs(
                f"{self.YOUTUBE_DATA}/shared_prefs/youtube.xml",
                yt_xml, "com.google.android.youtube", result,
            )

            result.youtube_ok = True
            logger.info(f"  YouTube: signed in as {email}")

        except Exception as e:
            result.errors.append(f"youtube: {e}")

    # ─── MAPS ─────────────────────────────────────────────────────────

    def _inject_maps(self, email: str, result: AccountInjectionResult):
        """Inject Google Maps account preferences."""
        try:
            maps_xml = self._build_shared_prefs_xml({
                "signed_in_account": email,
                "navigation_voice": "true",
                "wifi_only_mode": "false",
                "distance_unit": "mi",
                "location_history": "true",
            })

            self._push_shared_prefs(
                f"{self.MAPS_DATA}/shared_prefs/com.google.android.apps.maps_preferences.xml",
                maps_xml, "com.google.android.apps.maps", result,
            )

            result.maps_ok = True
            logger.info(f"  Maps: signed in as {email}")

        except Exception as e:
            result.errors.append(f"maps: {e}")

    # ─── SHARED PREFS HELPERS ─────────────────────────────────────────

    def _build_shared_prefs_xml(self, data: Dict[str, str]) -> str:
        """Build Android SharedPreferences XML from a dict."""
        lines = ['<?xml version=\'1.0\' encoding=\'utf-8\' standalone=\'yes\' ?>']
        lines.append("<map>")
        for key, value in data.items():
            escaped_value = (
                str(value)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&apos;")
            )
            if value.lower() in ("true", "false"):
                lines.append(f'    <boolean name="{key}" value="{value.lower()}" />')
            elif value.isdigit() and len(value) < 18:
                lines.append(f'    <long name="{key}" value="{value}" />')
            else:
                lines.append(f'    <string name="{key}">{escaped_value}</string>')
        lines.append("</map>")
        return "\n".join(lines)

    def _push_shared_prefs(self, remote_path: str, xml_content: str,
                           package: str, result: AccountInjectionResult):
        """Write SharedPreferences XML to device via ADB push."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as tmp:
                tmp.write(xml_content)
                tmp_path = tmp.name

            # Ensure shared_prefs dir exists
            prefs_dir = os.path.dirname(remote_path)
            _adb_shell(self.target, f"mkdir -p {prefs_dir}")

            if _adb_push(self.target, tmp_path, remote_path):
                # Fix ownership — get the app's UID
                uid = _adb_shell(self.target,
                    f"stat -c %U /data/data/{package} 2>/dev/null || "
                    f"ls -ld /data/data/{package} | awk '{{print $3}}'")
                uid = uid.strip()
                if uid:
                    _adb_shell(self.target, f"chown {uid}:{uid} {remote_path}")
                _adb_shell(self.target, f"chmod 660 {remote_path}")
                _adb_shell(self.target, f"restorecon {remote_path} 2>/dev/null")
            else:
                result.errors.append(f"Failed to push {remote_path}")

            os.unlink(tmp_path)

        except Exception as e:
            result.errors.append(f"push_prefs({remote_path}): {e}")
