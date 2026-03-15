"""
Titan V11.3 — App Data Forger
Generates per-app SharedPreferences XML files and SQLite databases
using the APK Data Map registry. Makes each installed app appear
genuinely used with login state, user data, and app settings.

Also handles Play Store library.db and localappstate.db forging
from purchase history data.

Usage:
    forger = AppDataForger(adb_target="127.0.0.1:5555")
    result = forger.forge_and_inject(
        installed_packages=["com.instagram.android", "com.whatsapp", ...],
        persona={
            "email": "alex.mercer@gmail.com",
            "name": "Alex Mercer",
            "phone": "+12125551234",
            "country": "US",
        },
        play_purchases=[...],
        app_installs=[...],
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

from adb_utils import adb as _adb, adb_shell as _adb_shell, adb_push as _adb_push, ensure_adb_root as _ensure_adb_root

logger = logging.getLogger("titan.app-data-forger")

try:
    from apk_data_map import APK_DATA_MAP, get_app_map
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from apk_data_map import APK_DATA_MAP, get_app_map


# ═══════════════════════════════════════════════════════════════════════
# RESULT
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class AppDataForgeResult:
    shared_prefs_written: int = 0
    databases_written: int = 0
    play_library_ok: bool = False
    play_appstate_ok: bool = False
    apps_processed: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "shared_prefs_written": self.shared_prefs_written,
            "databases_written": self.databases_written,
            "play_library": self.play_library_ok,
            "play_appstate": self.play_appstate_ok,
            "apps_processed": self.apps_processed,
            "errors": self.errors,
        }


# ═══════════════════════════════════════════════════════════════════════
# APP DATA FORGER
# ═══════════════════════════════════════════════════════════════════════

class AppDataForger:
    """Forges per-app SharedPreferences and databases, then injects via ADB."""

    VENDING_DATA = "/data/data/com.android.vending"

    def __init__(self, adb_target: str = "127.0.0.1:5555"):
        self.target = adb_target

    def forge_and_inject(self,
                         installed_packages: List[str],
                         persona: Dict[str, str],
                         play_purchases: Optional[List[Dict]] = None,
                         app_installs: Optional[List[Dict]] = None,
                         ) -> AppDataForgeResult:
        """
        Forge and inject app data for all installed packages.

        Args:
            installed_packages: List of package names to forge data for
            persona: Dict with email, name, phone, country
            play_purchases: Purchase history from AndroidProfileForge
            app_installs: App install records from AndroidProfileForge
        """
        result = AppDataForgeResult()
        _ensure_adb_root(self.target)

        email = persona.get("email", "user@gmail.com")
        name = persona.get("name", "User")
        phone = persona.get("phone", "+10000000000")
        country = persona.get("country", "US")

        parts = name.split(None, 1)
        first_name = parts[0] if parts else "User"
        last_name = parts[1] if len(parts) > 1 else ""

        now_ms = str(int(time.time() * 1000))
        android_id = secrets.token_hex(8)

        # Template values for placeholder resolution
        template_vars = {
            "{persona_email}": email,
            "{persona_name}": name,
            "{persona_phone}": phone,
            "{first_name}": first_name,
            "{last_name}": last_name,
            "{device_id}": secrets.token_hex(8),
            "{android_id}": android_id,
            "{install_ts}": now_ms,
            "{last_open_ts}": now_ms,
            "{random_hex_16}": secrets.token_hex(8),
            "{random_hex_32}": secrets.token_hex(16),
            "{random_int}": str(random.randint(100000000, 999999999)),
            "{uuid4}": str(uuid.uuid4()),
            "{country}": country,
            "{locale}": f"{country.lower()}_{country.upper()}",
        }

        logger.info(f"Forging app data for {len(installed_packages)} packages → {self.target}")

        for pkg in installed_packages:
            app_map = get_app_map(pkg)
            if not app_map:
                continue

            try:
                # Refresh random values per app
                template_vars["{random_hex_16}"] = secrets.token_hex(8)
                template_vars["{random_hex_32}"] = secrets.token_hex(16)
                template_vars["{random_int}"] = str(random.randint(100000000, 999999999))
                template_vars["{uuid4}"] = str(uuid.uuid4())
                template_vars["{device_id}"] = secrets.token_hex(8)

                # Find install timestamp for this app
                if app_installs:
                    for ai in app_installs:
                        if ai.get("package") == pkg:
                            template_vars["{install_ts}"] = str(ai.get("install_time", now_ms))
                            break

                # Forge SharedPreferences
                prefs_count = self._forge_shared_prefs(pkg, app_map, template_vars, result)
                result.shared_prefs_written += prefs_count

                # Forge databases
                db_count = self._forge_databases(pkg, app_map, template_vars, result)
                result.databases_written += db_count

                result.apps_processed += 1

            except Exception as e:
                result.errors.append(f"{pkg}: {e}")
                logger.error(f"Failed to forge data for {pkg}: {e}")

        # Forge Play Store library.db from purchase history
        if play_purchases:
            self._forge_play_library(play_purchases, email, result)
            self._forge_play_appstate(play_purchases, app_installs or [], email, result)

        logger.info(f"App data forging complete: {result.apps_processed} apps, "
                     f"{result.shared_prefs_written} prefs, {result.databases_written} DBs")
        return result

    # ─── SHARED PREFERENCES ───────────────────────────────────────────

    def _forge_shared_prefs(self, pkg: str, app_map: Dict,
                            template_vars: Dict[str, str],
                            result: AppDataForgeResult) -> int:
        """Generate and push SharedPreferences XML files for an app."""
        prefs = app_map.get("shared_prefs", {})
        if not prefs:
            return 0

        data_dir = app_map.get("data_dir", f"/data/data/{pkg}")
        count = 0

        for filename, kv_template in prefs.items():
            try:
                # Resolve template placeholders
                resolved = {}
                for key, tmpl_value in kv_template.items():
                    value = str(tmpl_value)
                    for placeholder, replacement in template_vars.items():
                        value = value.replace(placeholder, replacement)
                    resolved[key] = value

                xml = self._build_prefs_xml(resolved)

                remote_path = f"{data_dir}/shared_prefs/{filename}"
                if self._push_xml(remote_path, xml, pkg):
                    count += 1
                else:
                    result.errors.append(f"{pkg}: failed to push {filename}")

            except Exception as e:
                result.errors.append(f"{pkg}/{filename}: {e}")

        return count

    # ─── DATABASES ─────────────────────────────────────────────────────

    def _forge_databases(self, pkg: str, app_map: Dict,
                         template_vars: Dict[str, str],
                         result: AppDataForgeResult) -> int:
        """Generate and push SQLite databases for an app."""
        databases = app_map.get("databases", {})
        if not databases:
            return 0

        data_dir = app_map.get("data_dir", f"/data/data/{pkg}")
        count = 0

        for db_name, db_spec in databases.items():
            try:
                tables = db_spec.get("tables", {})
                if not tables:
                    continue

                with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                    tmp_path = tmp.name

                conn = sqlite3.connect(tmp_path)
                c = conn.cursor()

                for table_name, table_spec in tables.items():
                    schema = table_spec.get("schema", "")
                    if schema:
                        c.execute(schema)

                    rows = table_spec.get("rows", [])
                    for row in rows:
                        # Resolve template placeholders in row values
                        resolved_row = []
                        for val in row:
                            val_str = str(val)
                            for placeholder, replacement in template_vars.items():
                                val_str = val_str.replace(placeholder, replacement)
                            resolved_row.append(val_str)

                        if len(resolved_row) == 2:
                            c.execute(
                                f"INSERT OR REPLACE INTO {table_name} VALUES (?, ?)",
                                resolved_row,
                            )

                conn.commit()
                conn.close()

                remote_path = f"{data_dir}/databases/{db_name}"
                _adb_shell(self.target, f"mkdir -p {data_dir}/databases")

                if _adb_push(self.target, tmp_path, remote_path):
                    self._fix_ownership(remote_path, pkg)
                    count += 1
                else:
                    result.errors.append(f"{pkg}: failed to push {db_name}")

                os.unlink(tmp_path)

            except Exception as e:
                result.errors.append(f"{pkg}/{db_name}: {e}")

        return count

    # ─── PLAY STORE LIBRARY.DB ─────────────────────────────────────────

    def _forge_play_library(self, purchases: List[Dict], email: str,
                            result: AppDataForgeResult):
        """Forge Play Store library.db from purchase history."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            c.execute("""
                CREATE TABLE IF NOT EXISTS ownership (
                    account TEXT,
                    library_id TEXT,
                    backend INTEGER DEFAULT 3,
                    doc_id TEXT,
                    doc_type INTEGER DEFAULT 1,
                    offer_type INTEGER DEFAULT 1,
                    purchase_time INTEGER DEFAULT 0,
                    availability INTEGER DEFAULT 1,
                    PRIMARY KEY(account, library_id)
                )
            """)

            for i, purchase in enumerate(purchases):
                lib_id = f"lib_{i:06d}"
                c.execute("""
                    INSERT OR REPLACE INTO ownership
                    (account, library_id, backend, doc_id, doc_type, offer_type,
                     purchase_time, availability)
                    VALUES (?, ?, 3, ?, ?, ?, ?, 1)
                """, (
                    purchase.get("account", email),
                    lib_id,
                    purchase.get("doc_id", ""),
                    purchase.get("doc_type", 1),
                    purchase.get("offer_type", 1),
                    purchase.get("purchase_time", 0),
                ))

            conn.commit()
            conn.close()

            remote_path = f"{self.VENDING_DATA}/databases/library.db"
            _adb_shell(self.target, f"mkdir -p {self.VENDING_DATA}/databases")

            if _adb_push(self.target, tmp_path, remote_path):
                self._fix_ownership(remote_path, "com.android.vending")
                result.play_library_ok = True
                logger.info(f"  Play Store library.db: {len(purchases)} entries")
            else:
                result.errors.append("Failed to push library.db")

            os.unlink(tmp_path)

        except Exception as e:
            result.errors.append(f"play_library: {e}")
            logger.error(f"Play Store library.db forging failed: {e}")

    # ─── PLAY STORE LOCALAPPSTATE.DB ───────────────────────────────────

    def _forge_play_appstate(self, purchases: List[Dict],
                             app_installs: List[Dict], email: str,
                             result: AppDataForgeResult):
        """Forge Play Store localappstate.db from install + purchase data."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            c.execute("""
                CREATE TABLE IF NOT EXISTS appstate (
                    package_name TEXT PRIMARY KEY,
                    auto_update INTEGER DEFAULT 1,
                    desired_version INTEGER DEFAULT 0,
                    download_uri TEXT DEFAULT '',
                    delivery_data BLOB DEFAULT NULL,
                    delivery_data_timestamp_ms INTEGER DEFAULT 0,
                    first_download_ms INTEGER DEFAULT 0,
                    account TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    last_notified_version INTEGER DEFAULT 0,
                    last_update_timestamp_ms INTEGER DEFAULT 0,
                    install_reason INTEGER DEFAULT 0
                )
            """)

            # Merge purchases + installs into app states
            seen_pkgs = set()
            now_ms = int(time.time() * 1000)

            for install in app_installs:
                pkg = install.get("package", "")
                if not pkg or pkg in seen_pkgs:
                    continue
                seen_pkgs.add(pkg)

                install_time = install.get("install_time", now_ms - 86400000 * 30)
                c.execute("""
                    INSERT OR REPLACE INTO appstate
                    (package_name, auto_update, first_download_ms, account, title,
                     last_update_timestamp_ms, install_reason)
                    VALUES (?, 1, ?, ?, ?, ?, ?)
                """, (
                    pkg, install_time, email,
                    install.get("name", pkg),
                    install_time + random.randint(86400000, 86400000 * 7),
                    0 if install.get("is_system") else 4,  # 4 = user install
                ))

            for purchase in purchases:
                pkg = purchase.get("doc_id", "").split(":")[0]
                if not pkg or pkg in seen_pkgs:
                    continue
                seen_pkgs.add(pkg)

                c.execute("""
                    INSERT OR REPLACE INTO appstate
                    (package_name, auto_update, first_download_ms, account, title,
                     last_update_timestamp_ms, install_reason)
                    VALUES (?, 1, ?, ?, ?, ?, 4)
                """, (
                    pkg, purchase.get("purchase_time", now_ms - 86400000 * 30),
                    email, purchase.get("title", pkg),
                    purchase.get("purchase_time", now_ms) + random.randint(86400000, 86400000 * 7),
                ))

            conn.commit()
            conn.close()

            remote_path = f"{self.VENDING_DATA}/databases/localappstate.db"
            if _adb_push(self.target, tmp_path, remote_path):
                self._fix_ownership(remote_path, "com.android.vending")
                result.play_appstate_ok = True
                logger.info(f"  Play Store localappstate.db: {len(seen_pkgs)} apps")
            else:
                result.errors.append("Failed to push localappstate.db")

            os.unlink(tmp_path)

        except Exception as e:
            result.errors.append(f"play_appstate: {e}")
            logger.error(f"Play Store localappstate.db forging failed: {e}")

    # ─── HELPERS ──────────────────────────────────────────────────────

    def _build_prefs_xml(self, data: Dict[str, str]) -> str:
        """Build Android SharedPreferences XML from a dict."""
        lines = ['<?xml version=\'1.0\' encoding=\'utf-8\' standalone=\'yes\' ?>']
        lines.append("<map>")
        for key, value in data.items():
            escaped = (
                str(value).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")
            )
            if value.lower() in ("true", "false"):
                lines.append(f'    <boolean name="{key}" value="{value.lower()}" />')
            elif value.isdigit() and len(value) < 18:
                lines.append(f'    <long name="{key}" value="{value}" />')
            else:
                lines.append(f'    <string name="{key}">{escaped}</string>')
        lines.append("</map>")
        return "\n".join(lines)

    def _push_xml(self, remote_path: str, xml_content: str, package: str) -> bool:
        """Push XML content to device via ADB."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as tmp:
                tmp.write(xml_content)
                tmp_path = tmp.name

            prefs_dir = os.path.dirname(remote_path)
            _adb_shell(self.target, f"mkdir -p {prefs_dir}")

            ok = _adb_push(self.target, tmp_path, remote_path)
            if ok:
                self._fix_ownership(remote_path, package)

            os.unlink(tmp_path)
            return ok

        except Exception:
            return False

    def _fix_ownership(self, remote_path: str, package: str):
        """Fix file ownership to match app UID."""
        uid = _adb_shell(self.target,
            f"stat -c %U /data/data/{package} 2>/dev/null || "
            f"ls -ld /data/data/{package} | awk '{{print $3}}'")
        uid = uid.strip()
        if uid:
            _adb_shell(self.target, f"chown {uid}:{uid} {remote_path}")
        _adb_shell(self.target, f"chmod 660 {remote_path}")
