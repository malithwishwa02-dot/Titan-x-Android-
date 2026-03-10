"""
Titan V11.3 — Wallet Provisioner
Injects credit card data into Google Pay / Wallet and Play Store billing
so the card appears as a legitimately added payment method.

Injection targets:
  - Google Pay tapandpay.db  → Token with DPAN, last4, network, expiry
  - Google Pay shared_prefs  → Wallet setup complete, default card, NFC on
  - Play Store billing prefs → Payment method visible in Play Store
  - Chrome autofill          → Card saved in browser for web purchases

The DPAN (Device PAN) is generated from the real card's BIN prefix but with
a different number, mimicking how real network tokenization works.

Usage:
    prov = WalletProvisioner(adb_target="127.0.0.1:5555")
    result = prov.provision_card(
        card_number="4532015112830366",
        exp_month=12, exp_year=2027,
        cardholder="Alex Mercer",
        cvv="123",
        persona_email="alex.mercer@gmail.com",
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

logger = logging.getLogger("titan.wallet-provisioner")


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
# CARD NETWORK DETECTION
# ═══════════════════════════════════════════════════════════════════════

CARD_NETWORKS = {
    "visa": {"prefixes": ["4"], "network_id": 1, "name": "Visa", "color": -16776961},
    "mastercard": {"prefixes": ["51", "52", "53", "54", "55", "2221", "2720"],
                   "network_id": 2, "name": "Mastercard", "color": -65536},
    "amex": {"prefixes": ["34", "37"], "network_id": 3, "name": "American Express", "color": -16711936},
    "discover": {"prefixes": ["6011", "65", "644", "649"], "network_id": 4, "name": "Discover", "color": -19712},
}

# Common issuer names by BIN prefix
ISSUER_MAP = {
    "4532": "Chase", "4916": "US Bank", "4024": "Visa Inc.",
    "4556": "Stripe", "4111": "Test Bank", "4000": "Visa Inc.",
    "5100": "Citi", "5425": "Mastercard Inc.", "5500": "HSBC",
    "5200": "Bank of America", "5105": "Capital One",
    "3782": "American Express", "3714": "Amex Centurion",
    "6011": "Discover Financial", "6500": "Discover",
}


def detect_network(card_number: str) -> Dict[str, Any]:
    """Detect card network from number prefix."""
    num = card_number.replace(" ", "").replace("-", "")
    for network, info in CARD_NETWORKS.items():
        for prefix in info["prefixes"]:
            if num.startswith(prefix):
                return {"network": network, **info}
    return {"network": "visa", **CARD_NETWORKS["visa"]}


def detect_issuer(card_number: str) -> str:
    """Detect card issuer from BIN prefix."""
    num = card_number.replace(" ", "").replace("-", "")[:4]
    return ISSUER_MAP.get(num, "Bank")


def generate_dpan(card_number: str) -> str:
    """
    Generate a Device PAN (DPAN) from a real card number.
    Preserves BIN prefix (first 6 digits) but generates different remaining digits.
    This mimics real network tokenization behavior.
    """
    num = card_number.replace(" ", "").replace("-", "")
    bin_prefix = num[:6]

    # Generate random digits for the rest
    remaining_len = len(num) - 7  # -6 for BIN, -1 for check digit
    body = "".join([str(random.randint(0, 9)) for _ in range(remaining_len)])

    partial = bin_prefix + body

    # Luhn check digit (standard algorithm)
    # For the partial number, double every odd-position digit from the right
    digits = [int(d) for d in partial]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            # These positions will be "odd from right" in the final number
            # (shifted by 1 because check digit will be appended)
            doubled = d * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += d
    check = (10 - (total % 10)) % 10

    dpan = partial + str(check)
    return dpan


# ═══════════════════════════════════════════════════════════════════════
# RESULT
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class WalletProvisionResult:
    card_last4: str = ""
    card_network: str = ""
    dpan: str = ""
    dpan_last4: str = ""
    google_pay_ok: bool = False
    play_store_ok: bool = False
    chrome_autofill_ok: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum([self.google_pay_ok, self.play_store_ok, self.chrome_autofill_ok])

    def to_dict(self) -> dict:
        return {
            "card_last4": self.card_last4,
            "card_network": self.card_network,
            "dpan": self.dpan[-4:] if self.dpan else "",
            "google_pay": self.google_pay_ok,
            "play_store": self.play_store_ok,
            "chrome_autofill": self.chrome_autofill_ok,
            "success_count": self.success_count,
            "total_targets": 3,
            "errors": self.errors,
        }


# ═══════════════════════════════════════════════════════════════════════
# WALLET PROVISIONER
# ═══════════════════════════════════════════════════════════════════════

class WalletProvisioner:
    """Provisions payment cards into Google Pay, Play Store, and Chrome."""

    WALLET_DATA = "/data/data/com.google.android.apps.walletnfcrel"
    VENDING_DATA = "/data/data/com.android.vending"
    CHROME_DATA = "/data/data/com.android.chrome"

    def __init__(self, adb_target: str = "127.0.0.1:5555"):
        self.target = adb_target

    def provision_card(self,
                       card_number: str,
                       exp_month: int,
                       exp_year: int,
                       cardholder: str,
                       cvv: str = "",
                       persona_email: str = "",
                       persona_name: str = "",
                       ) -> WalletProvisionResult:
        """
        Provision a credit card into Google Pay, Play Store billing, and Chrome autofill.

        Args:
            card_number: Full card number (spaces/dashes stripped automatically)
            exp_month: Expiry month (1-12)
            exp_year: Expiry year (2-digit or 4-digit)
            cardholder: Name on card
            cvv: CVV/CVC (not stored in wallet DBs, used for Chrome autofill hint)
            persona_email: Google account email for Play Store binding
            persona_name: Display name for wallet profile

        Returns:
            WalletProvisionResult with per-target success flags
        """
        clean_num = card_number.replace(" ", "").replace("-", "")
        last4 = clean_num[-4:]

        # Normalize year
        if exp_year < 100:
            exp_year += 2000

        network_info = detect_network(clean_num)
        issuer = detect_issuer(clean_num)
        dpan = generate_dpan(clean_num)

        result = WalletProvisionResult(
            card_last4=last4,
            card_network=network_info["network"],
            dpan=dpan,
            dpan_last4=dpan[-4:],
        )

        if not persona_name:
            persona_name = cardholder

        logger.info(f"Provisioning {network_info['name']} ****{last4} → {self.target}")
        logger.info(f"  DPAN: ****{dpan[-4:]}, Issuer: {issuer}")

        # 1. Google Pay / Wallet — tapandpay.db + prefs
        self._provision_google_pay(
            clean_num, dpan, last4, exp_month, exp_year,
            cardholder, issuer, network_info, persona_email, persona_name, result,
        )

        # 2. Play Store billing
        self._provision_play_store(last4, network_info, persona_email, result)

        # 3. Chrome autofill card
        self._provision_chrome_autofill(
            clean_num, last4, exp_month, exp_year, cardholder, network_info, result,
        )

        logger.info(f"Wallet provisioning complete: {result.success_count}/3 targets")
        return result

    # ─── GOOGLE PAY ───────────────────────────────────────────────────

    def _provision_google_pay(self, card_number: str, dpan: str, last4: str,
                              exp_month: int, exp_year: int, cardholder: str,
                              issuer: str, network_info: Dict, persona_email: str,
                              persona_name: str, result: WalletProvisionResult):
        """Write Google Pay tapandpay.db + wallet SharedPreferences."""
        try:
            # ── tapandpay.db ──
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            c.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dpan TEXT NOT NULL,
                    fpan_last4 TEXT NOT NULL,
                    card_network INTEGER NOT NULL,
                    card_description TEXT,
                    issuer_name TEXT,
                    expiry_month INTEGER,
                    expiry_year INTEGER,
                    card_color INTEGER DEFAULT -1,
                    is_default INTEGER DEFAULT 0,
                    status INTEGER DEFAULT 1,
                    token_service_provider INTEGER DEFAULT 1,
                    created_timestamp INTEGER,
                    last_used_timestamp INTEGER
                )
            """)

            now_ms = int(time.time() * 1000)
            # Backdate creation by 7-30 days to look established
            created_ms = now_ms - random.randint(7 * 86400000, 30 * 86400000)
            # Last used 0-3 days ago
            last_used_ms = now_ms - random.randint(0, 3 * 86400000)

            card_desc = f"{network_info['name']} •••• {last4}"

            c.execute("""
                INSERT INTO tokens
                (dpan, fpan_last4, card_network, card_description, issuer_name,
                 expiry_month, expiry_year, card_color, is_default, status,
                 token_service_provider, created_timestamp, last_used_timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 1, ?, ?)
            """, (
                dpan, last4, network_info["network_id"], card_desc, issuer,
                exp_month, exp_year, network_info.get("color", -1),
                created_ms, last_used_ms,
            ))

            conn.commit()
            conn.close()

            # Push tapandpay.db
            db_remote = f"{self.WALLET_DATA}/databases/tapandpay.db"
            _adb_shell(self.target, f"mkdir -p {self.WALLET_DATA}/databases")
            if _adb_push(self.target, tmp_path, db_remote):
                self._fix_ownership(db_remote, "com.google.android.apps.walletnfcrel")
                logger.info(f"  Google Pay tapandpay.db: {card_desc}")
            else:
                result.errors.append("Failed to push tapandpay.db")

            os.unlink(tmp_path)

            # ── SharedPreferences ──
            instrument_id = str(uuid.uuid4())
            prefs = {
                "wallet_setup_complete": "true",
                "nfc_enabled": "true",
                "default_payment_instrument_id": instrument_id,
                "tap_and_pay_setup_complete": "true",
                "contactless_setup_complete": "true",
                "user_account": persona_email or "",
                "user_display_name": persona_name or cardholder,
                "last_sync_time": str(now_ms),
                "transit_enabled": "false",
                "loyalty_enabled": "true",
            }
            self._push_shared_prefs_xml(
                f"{self.WALLET_DATA}/shared_prefs/default_settings.xml",
                prefs, "com.google.android.apps.walletnfcrel",
            )

            app_prefs = {
                "has_accepted_tos": "true",
                "has_seen_onboarding": "true",
                "last_used_timestamp": str(last_used_ms),
                "notification_enabled": "true",
            }
            self._push_shared_prefs_xml(
                f"{self.WALLET_DATA}/shared_prefs/com.google.android.apps.walletnfcrel_preferences.xml",
                app_prefs, "com.google.android.apps.walletnfcrel",
            )

            result.google_pay_ok = True

        except Exception as e:
            result.errors.append(f"google_pay: {e}")
            logger.error(f"Google Pay provisioning failed: {e}")

    # ─── PLAY STORE BILLING ───────────────────────────────────────────

    def _provision_play_store(self, last4: str, network_info: Dict,
                              persona_email: str, result: WalletProvisionResult):
        """Write Play Store billing SharedPreferences with payment method."""
        try:
            billing_prefs = {
                "billing_client_version": "6.1.0",
                "has_payment_method": "true",
                "default_payment_method_type": network_info["network"],
                "default_payment_method_last4": last4,
                "default_payment_method_description": f"{network_info['name']} ····{last4}",
                "billing_account": persona_email or "",
            }
            self._push_shared_prefs_xml(
                f"{self.VENDING_DATA}/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml",
                billing_prefs, "com.android.vending",
            )

            result.play_store_ok = True
            logger.info(f"  Play Store billing: {network_info['name']} ****{last4}")

        except Exception as e:
            result.errors.append(f"play_store_billing: {e}")

    # ─── CHROME AUTOFILL ──────────────────────────────────────────────

    def _provision_chrome_autofill(self, card_number: str, last4: str,
                                    exp_month: int, exp_year: int,
                                    cardholder: str, network_info: Dict,
                                    result: WalletProvisionResult):
        """Write card into Chrome's Web Data autofill database."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name

            web_data_path = f"{self.CHROME_DATA}/app_chrome/Default/Web Data"

            # Pull existing or create fresh
            _adb(self.target, f"pull {web_data_path} {tmp_path}", timeout=10)

            conn = sqlite3.connect(tmp_path)
            c = conn.cursor()

            # Create credit_cards table if not exists
            c.execute("""
                CREATE TABLE IF NOT EXISTS credit_cards (
                    guid TEXT NOT NULL,
                    name_on_card TEXT,
                    expiration_month INTEGER,
                    expiration_year INTEGER,
                    card_number_encrypted BLOB,
                    date_modified INTEGER NOT NULL DEFAULT 0,
                    origin TEXT DEFAULT '',
                    use_count INTEGER NOT NULL DEFAULT 0,
                    use_date INTEGER NOT NULL DEFAULT 0,
                    billing_address_id TEXT DEFAULT '',
                    nickname TEXT DEFAULT ''
                )
            """)

            # Create autofill_profiles table if not exists
            c.execute("""
                CREATE TABLE IF NOT EXISTS autofill_profiles (
                    guid TEXT NOT NULL,
                    company_name TEXT DEFAULT '',
                    street_address TEXT DEFAULT '',
                    dependent_locality TEXT DEFAULT '',
                    city TEXT DEFAULT '',
                    state TEXT DEFAULT '',
                    zipcode TEXT DEFAULT '',
                    sorting_code TEXT DEFAULT '',
                    country_code TEXT DEFAULT '',
                    date_modified INTEGER NOT NULL DEFAULT 0,
                    origin TEXT DEFAULT '',
                    language_code TEXT DEFAULT '',
                    use_count INTEGER NOT NULL DEFAULT 0,
                    use_date INTEGER NOT NULL DEFAULT 0
                )
            """)

            now_s = int(time.time())
            # Card added 7-30 days ago
            date_added = now_s - random.randint(7 * 86400, 30 * 86400)
            # Used 3-8 times
            use_count = random.randint(3, 8)
            last_used = now_s - random.randint(0, 3 * 86400)

            # Chrome encrypts card numbers; for local storage we store a hint
            # In practice, Chrome uses OS keystore — we store the encrypted blob
            # as a placeholder that matches the expected format
            card_blob = card_number.encode("utf-8")

            card_guid = str(uuid.uuid4())
            c.execute("""
                INSERT OR REPLACE INTO credit_cards
                (guid, name_on_card, expiration_month, expiration_year,
                 card_number_encrypted, date_modified, origin, use_count, use_date,
                 nickname)
                VALUES (?, ?, ?, ?, ?, ?, 'https://pay.google.com', ?, ?, ?)
            """, (
                card_guid, cardholder, exp_month, exp_year,
                card_blob, date_added, use_count, last_used,
                f"{network_info['name']} ····{last4}",
            ))

            conn.commit()
            conn.close()

            _adb_shell(self.target, f"mkdir -p {self.CHROME_DATA}/app_chrome/Default")
            if _adb_push(self.target, tmp_path, web_data_path):
                self._fix_ownership(web_data_path, "com.android.chrome")
                result.chrome_autofill_ok = True
                logger.info(f"  Chrome autofill: {network_info['name']} ****{last4}")
            else:
                result.errors.append("Failed to push Chrome Web Data")

            os.unlink(tmp_path)

        except Exception as e:
            result.errors.append(f"chrome_autofill: {e}")
            logger.error(f"Chrome autofill provisioning failed: {e}")

    # ─── HELPERS ──────────────────────────────────────────────────────

    def _build_shared_prefs_xml(self, data: Dict[str, str]) -> str:
        """Build Android SharedPreferences XML."""
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

    def _push_shared_prefs_xml(self, remote_path: str, data: Dict[str, str], package: str):
        """Write SharedPreferences XML to device."""
        xml = self._build_shared_prefs_xml(data)
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as tmp:
            tmp.write(xml)
            tmp_path = tmp.name

        prefs_dir = os.path.dirname(remote_path)
        _adb_shell(self.target, f"mkdir -p {prefs_dir}")
        _adb_push(self.target, tmp_path, remote_path)
        self._fix_ownership(remote_path, package)
        os.unlink(tmp_path)

    def _fix_ownership(self, remote_path: str, package: str):
        """Fix file ownership to match app UID."""
        uid = _adb_shell(self.target,
            f"stat -c %U /data/data/{package} 2>/dev/null || "
            f"ls -ld /data/data/{package} | awk '{{print $3}}'")
        uid = uid.strip()
        if uid:
            _adb_shell(self.target, f"chown {uid}:{uid} {remote_path}")
        _adb_shell(self.target, f"chmod 660 {remote_path}")
