"""
Titan V11.3 — APK Data Structure Map
Deep analysis registry mapping Android packages to their internal data files,
SharedPreferences, SQLite databases, and auth structures.

Used by AppDataForger and ProfileInjector to generate and inject realistic
per-app data that makes the device appear genuinely used.

Each entry defines:
  - shared_prefs: dict of XML filename → key/value templates
  - databases: dict of DB filename → table schemas + sample generators
  - account_type: how the app authenticates (google, oauth, email, none)
  - data_dir: app's private data path pattern
  - login_required: whether the app needs auth to look "used"
  - has_payment: whether the app stores payment methods
  - trust_weight: 0-10, how much this app contributes to device trust score
"""

from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════
# SHARED PREFS VALUE GENERATORS
# These are template strings. Placeholders:
#   {persona_email}, {persona_name}, {persona_phone},
#   {first_name}, {last_name}, {device_id}, {android_id},
#   {install_ts}, {last_open_ts}, {random_hex_16}, {random_hex_32},
#   {random_int}, {uuid4}, {country}, {locale}
# ═══════════════════════════════════════════════════════════════════════


APK_DATA_MAP: Dict[str, Dict[str, Any]] = {

    # ─── GOOGLE CORE ───────────────────────────────────────────────────

    "com.google.android.gms": {
        "name": "Google Play Services",
        "account_type": "google",
        "login_required": True,
        "has_payment": False,
        "trust_weight": 10,
        "data_dir": "/data/data/com.google.android.gms",
        "shared_prefs": {
            "CheckinService.xml": {
                "lastCheckin": "{last_open_ts}",
                "deviceId": "{random_int}",
                "digest": "{random_hex_32}",
                "versionInfo": "14.0",
                "lastCheckinElapsedRealtime": "{random_int}",
            },
            "GservicesSettings.xml": {
                "android_id": "{android_id}",
                "checkin_device_id": "{random_int}",
                "gms:version": "24.26.32",
            },
            "com.google.android.gms.measurement.prefs.xml": {
                "has_been_opened": "true",
                "deferred_analytics_collection": "false",
                "first_open_time": "{install_ts}",
                "app_instance_id": "{random_hex_32}",
            },
        },
        "databases": {
            "gservices.db": {
                "tables": {
                    "main": {
                        "schema": "CREATE TABLE IF NOT EXISTS main (name TEXT PRIMARY KEY, value TEXT)",
                        "rows": [
                            ("android_id", "{android_id}"),
                            ("gms_version", "24.26.32"),
                            ("checkin_device_id", "{random_int}"),
                        ],
                    },
                },
            },
        },
    },

    "com.google.android.gsf": {
        "name": "Google Services Framework",
        "account_type": "google",
        "login_required": True,
        "has_payment": False,
        "trust_weight": 9,
        "data_dir": "/data/data/com.google.android.gsf",
        "shared_prefs": {
            "googlesettings.xml": {
                "android_id": "{android_id}",
                "checkin_device_id": "{random_int}",
                "digest": "{random_hex_32}",
            },
        },
        "databases": {},
    },

    "com.android.vending": {
        "name": "Google Play Store",
        "account_type": "google",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 10,
        "data_dir": "/data/data/com.android.vending",
        "shared_prefs": {
            "finsky.xml": {
                "tos_accepted": "true",
                "setup_wizard_complete": "true",
                "account": "{persona_email}",
                "first_account_name": "{persona_email}",
                "content_filters": "0",
                "auto_update_enabled": "true",
                "download_manager_max_bytes_over_mobile": "0",
                "notify_updates": "true",
                "last_notified_time": "{last_open_ts}",
            },
            # NOTE: COIN.xml is written by wallet_provisioner with full
            # payment method fields — do NOT overwrite here.
        },
        "databases": {
            "library.db": {
                "tables": {
                    "ownership": {
                        "schema": (
                            "CREATE TABLE IF NOT EXISTS ownership ("
                            "account TEXT, library_id TEXT, backend INTEGER, "
                            "doc_id TEXT, doc_type INTEGER, offer_type INTEGER, "
                            "purchase_time INTEGER, availability INTEGER, "
                            "PRIMARY KEY(account, library_id))"
                        ),
                        # Rows are generated dynamically from purchase history
                        "rows": [],
                    },
                },
            },
            "localappstate.db": {
                "tables": {
                    "appstate": {
                        "schema": (
                            "CREATE TABLE IF NOT EXISTS appstate ("
                            "package_name TEXT PRIMARY KEY, auto_update INTEGER, "
                            "desired_version INTEGER, download_uri TEXT, "
                            "delivery_data BLOB, delivery_data_timestamp_ms INTEGER, "
                            "first_download_ms INTEGER, account TEXT, "
                            "title TEXT, last_notified_version INTEGER, "
                            "last_update_timestamp_ms INTEGER, "
                            "install_reason INTEGER DEFAULT 0)"
                        ),
                        "rows": [],
                    },
                },
            },
        },
    },

    # ─── GOOGLE PAY / WALLET ──────────────────────────────────────────

    "com.google.android.apps.walletnfcrel": {
        "name": "Google Pay / Wallet",
        "account_type": "google",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 10,
        "data_dir": "/data/data/com.google.android.apps.walletnfcrel",
        "shared_prefs": {
            "default_settings.xml": {
                "wallet_setup_complete": "true",
                "nfc_enabled": "true",
                "default_payment_instrument_id": "{uuid4}",
                "tap_and_pay_setup_complete": "true",
                "contactless_setup_complete": "true",
                "user_account": "{persona_email}",
                "user_display_name": "{persona_name}",
                "last_sync_time": "{last_open_ts}",
                "transit_enabled": "false",
                "loyalty_enabled": "true",
            },
            "com.google.android.apps.walletnfcrel_preferences.xml": {
                "has_accepted_tos": "true",
                "has_seen_onboarding": "true",
                "last_used_timestamp": "{last_open_ts}",
                "notification_enabled": "true",
            },
        },
        "databases": {
            "tapandpay.db": {
                "tables": {
                    "tokens": {
                        "schema": (
                            "CREATE TABLE IF NOT EXISTS tokens ("
                            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                            "dpan TEXT NOT NULL, "
                            "fpan_last4 TEXT NOT NULL, "
                            "card_network INTEGER NOT NULL, "
                            "card_description TEXT, "
                            "issuer_name TEXT, "
                            "expiry_month INTEGER, "
                            "expiry_year INTEGER, "
                            "card_color INTEGER DEFAULT -1, "
                            "is_default INTEGER DEFAULT 0, "
                            "status INTEGER DEFAULT 1, "
                            "token_service_provider INTEGER DEFAULT 1, "
                            "created_timestamp INTEGER, "
                            "last_used_timestamp INTEGER)"
                        ),
                        "rows": [],  # Generated by wallet_provisioner
                    },
                },
            },
        },
    },

    # ─── CHROME ────────────────────────────────────────────────────────

    "com.android.chrome": {
        "name": "Google Chrome",
        "account_type": "google",
        "login_required": False,
        "has_payment": True,
        "trust_weight": 9,
        "data_dir": "/data/data/com.android.chrome",
        "shared_prefs": {
            "com.android.chrome_preferences.xml": {
                "first_run_flow": "true",
                "crash_dump_upload": "never",
                "metrics_reporting_enabled": "false",
                "search_engine_default": "Google",
                "safe_browsing_enabled": "true",
                "data_reduction_proxy_enabled": "false",
                "autofill_enabled": "true",
                "password_manager_enabled": "true",
                "sync_everything": "true",
                "signed_in_account_name": "{persona_email}",
            },
        },
        "databases": {},
        # Chrome profile data is in app_chrome/Default/ — handled by profile_injector
        "extra_files": {
            "app_chrome/Default/Preferences": "json",  # Large JSON config
        },
    },

    # ─── SOCIAL MEDIA ──────────────────────────────────────────────────

    "com.instagram.android": {
        "name": "Instagram",
        "account_type": "oauth",
        "login_required": True,
        "has_payment": False,
        "trust_weight": 6,
        "data_dir": "/data/data/com.instagram.android",
        "shared_prefs": {
            "com.instagram.android_preferences.xml": {
                "is_logged_in": "true",
                "current_user_id": "{random_int}",
                "current_user_name": "{first_name}.{last_name}",
                "current_user_full_name": "{persona_name}",
                "current_user_profile_pic_url": "",
                "has_seen_onboarding": "true",
                "push_notifications_enabled": "true",
                "last_fresh_session_time": "{last_open_ts}",
                "device_id": "{uuid4}",
                "phone_id": "{uuid4}",
                "family_device_id": "{uuid4}",
                "analytics_device_id": "{uuid4}",
            },
        },
        "databases": {},
    },

    "com.whatsapp": {
        "name": "WhatsApp",
        "account_type": "phone",
        "login_required": True,
        "has_payment": False,
        "trust_weight": 7,
        "data_dir": "/data/data/com.whatsapp",
        "shared_prefs": {
            "com.whatsapp_preferences.xml": {
                "registration_complete": "true",
                "my_current_status": "Hey there! I am using WhatsApp",
                "push_name": "{first_name}",
                "my_phone_number": "{persona_phone}",
                "verified_name": "{persona_name}",
                "last_backup_time": "{last_open_ts}",
                "last_connect_time": "{last_open_ts}",
            },
            "keystore.xml": {
                "client_static_keypair_pwd_enc": "{random_hex_32}",
            },
        },
        "databases": {},
    },

    "com.twitter.android": {
        "name": "X (Twitter)",
        "account_type": "oauth",
        "login_required": True,
        "has_payment": False,
        "trust_weight": 5,
        "data_dir": "/data/data/com.twitter.android",
        "shared_prefs": {
            "com.twitter.android_preferences.xml": {
                "is_logged_in": "true",
                "current_user_id": "{random_int}",
                "current_user_screen_name": "{first_name}{last_name}",
                "notifications_enabled": "true",
                "dark_mode": "auto",
            },
        },
        "databases": {},
    },

    "com.facebook.katana": {
        "name": "Facebook",
        "account_type": "oauth",
        "login_required": True,
        "has_payment": False,
        "trust_weight": 6,
        "data_dir": "/data/data/com.facebook.katana",
        "shared_prefs": {
            "com.facebook.katana_preferences.xml": {
                "is_logged_in": "true",
                "user_id": "{random_int}",
                "user_name": "{persona_name}",
                "user_email": "{persona_email}",
                "notifications_enabled": "true",
                "messenger_installed": "false",
            },
        },
        "databases": {},
    },

    "com.snapchat.android": {
        "name": "Snapchat",
        "account_type": "oauth",
        "login_required": True,
        "has_payment": False,
        "trust_weight": 4,
        "data_dir": "/data/data/com.snapchat.android",
        "shared_prefs": {
            "com.snapchat.android_preferences.xml": {
                "username": "{first_name}_{last_name}_{random_int}",
                "user_id": "{uuid4}",
                "is_logged_in": "true",
                "device_id": "{uuid4}",
            },
        },
        "databases": {},
    },

    "org.telegram.messenger": {
        "name": "Telegram",
        "account_type": "phone",
        "login_required": True,
        "has_payment": False,
        "trust_weight": 5,
        "data_dir": "/data/data/org.telegram.messenger",
        "shared_prefs": {
            "userconfing.xml": {  # Telegram's actual typo
                "user_id": "{random_int}",
                "phone": "{persona_phone}",
                "first_name": "{first_name}",
                "last_name": "{last_name}",
                "registered": "true",
                "contactsSavedCount": "0",
            },
        },
        "databases": {},
    },

    # ─── BANKING / FINTECH ─────────────────────────────────────────────

    "com.chase.sig.android": {
        "name": "Chase Mobile",
        "account_type": "email",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 8,
        "data_dir": "/data/data/com.chase.sig.android",
        "shared_prefs": {
            "chase_prefs.xml": {
                "device_registered": "true",
                "device_trust_token": "{random_hex_32}",
                "biometric_enrolled": "true",
                "push_notifications": "true",
                "quick_balance_enabled": "true",
                "last_login_time": "{last_open_ts}",
                "remember_me": "true",
                "username": "{persona_email}",
            },
        },
        "databases": {},
    },

    "com.venmo": {
        "name": "Venmo",
        "account_type": "email",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 7,
        "data_dir": "/data/data/com.venmo",
        "shared_prefs": {
            "venmo_prefs.xml": {
                "is_logged_in": "true",
                "user_id": "{random_int}",
                "display_name": "{persona_name}",
                "email": "{persona_email}",
                "phone_verified": "true",
                "face_id_enabled": "true",
                "push_enabled": "true",
                "device_id": "{uuid4}",
            },
        },
        "databases": {},
    },

    "com.squareup.cash": {
        "name": "Cash App",
        "account_type": "phone",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 7,
        "data_dir": "/data/data/com.squareup.cash",
        "shared_prefs": {
            "cash_prefs.xml": {
                "is_logged_in": "true",
                "customer_id": "{uuid4}",
                "cashtag": "${first_name}{last_name}",
                "phone_verified": "true",
                "card_linked": "true",
                "biometric_enabled": "true",
                "device_token": "{random_hex_32}",
            },
        },
        "databases": {},
    },

    "com.paypal.android.p2pmobile": {
        "name": "PayPal",
        "account_type": "email",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 8,
        "data_dir": "/data/data/com.paypal.android.p2pmobile",
        "shared_prefs": {
            "paypal_prefs.xml": {
                "is_logged_in": "true",
                "email": "{persona_email}",
                "display_name": "{persona_name}",
                "device_id": "{uuid4}",
                "biometric_enabled": "true",
                "one_touch_enabled": "true",
                "push_enabled": "true",
                "last_active": "{last_open_ts}",
            },
        },
        "databases": {},
    },

    "com.onedebit.chime": {
        "name": "Chime",
        "account_type": "email",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 6,
        "data_dir": "/data/data/com.onedebit.chime",
        "shared_prefs": {
            "chime_prefs.xml": {
                "is_logged_in": "true",
                "user_email": "{persona_email}",
                "device_registered": "true",
                "biometric_enabled": "true",
                "push_enabled": "true",
            },
        },
        "databases": {},
    },

    # UK Banking

    "com.monzo.android": {
        "name": "Monzo",
        "account_type": "email",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 8,
        "data_dir": "/data/data/com.monzo.android",
        "shared_prefs": {
            "monzo_prefs.xml": {
                "is_logged_in": "true",
                "device_trusted": "true",
                "pin_set": "true",
                "biometric_enabled": "true",
                "account_holder": "{persona_name}",
                "push_enabled": "true",
            },
        },
        "databases": {},
    },

    "com.revolut.revolut": {
        "name": "Revolut",
        "account_type": "phone",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 8,
        "data_dir": "/data/data/com.revolut.revolut",
        "shared_prefs": {
            "revolut_prefs.xml": {
                "is_logged_in": "true",
                "user_id": "{uuid4}",
                "phone_verified": "true",
                "passcode_set": "true",
                "biometric_enabled": "true",
                "push_enabled": "true",
                "device_id": "{uuid4}",
            },
        },
        "databases": {},
    },

    # ─── BNPL ──────────────────────────────────────────────────────────

    "com.klarna.android": {
        "name": "Klarna",
        "account_type": "email",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 6,
        "data_dir": "/data/data/com.klarna.android",
        "shared_prefs": {
            "klarna_prefs.xml": {
                "is_logged_in": "true",
                "user_email": "{persona_email}",
                "device_fingerprint": "{random_hex_32}",
                "push_enabled": "true",
                "card_added": "true",
            },
        },
        "databases": {},
    },

    "com.afterpay.caportal": {
        "name": "Afterpay",
        "account_type": "email",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 5,
        "data_dir": "/data/data/com.afterpay.caportal",
        "shared_prefs": {
            "afterpay_prefs.xml": {
                "is_logged_in": "true",
                "email": "{persona_email}",
                "card_linked": "true",
                "device_id": "{uuid4}",
            },
        },
        "databases": {},
    },

    # ─── DELIVERY / SHOPPING ───────────────────────────────────────────

    "com.amazon.mShop.android.shopping": {
        "name": "Amazon Shopping",
        "account_type": "email",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 8,
        "data_dir": "/data/data/com.amazon.mShop.android.shopping",
        "shared_prefs": {
            "amazon_prefs.xml": {
                "is_logged_in": "true",
                "customer_id": "{random_hex_16}",
                "email": "{persona_email}",
                "display_name": "{first_name}",
                "marketplace": "{country}",
                "one_click_enabled": "true",
                "push_enabled": "true",
                "device_id": "{uuid4}",
            },
        },
        "databases": {},
    },

    "com.dd.doordash": {
        "name": "DoorDash",
        "account_type": "email",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 5,
        "data_dir": "/data/data/com.dd.doordash",
        "shared_prefs": {
            "doordash_prefs.xml": {
                "is_logged_in": "true",
                "email": "{persona_email}",
                "display_name": "{persona_name}",
                "card_on_file": "true",
                "push_enabled": "true",
                "device_id": "{uuid4}",
            },
        },
        "databases": {},
    },

    "com.ubercab": {
        "name": "Uber",
        "account_type": "phone",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 6,
        "data_dir": "/data/data/com.ubercab",
        "shared_prefs": {
            "uber_prefs.xml": {
                "is_logged_in": "true",
                "user_id": "{uuid4}",
                "phone": "{persona_phone}",
                "display_name": "{first_name}",
                "payment_method_added": "true",
                "push_enabled": "true",
            },
        },
        "databases": {},
    },

    # ─── BROWSERS ──────────────────────────────────────────────────────

    "org.mozilla.firefox": {
        "name": "Firefox",
        "account_type": "none",
        "login_required": False,
        "has_payment": False,
        "trust_weight": 3,
        "data_dir": "/data/data/org.mozilla.firefox",
        "shared_prefs": {
            "org.mozilla.firefox_preferences.xml": {
                "app.installation.timestamp": "{install_ts}",
                "first_run": "false",
                "privacy.donottrackheader.enabled": "false",
            },
        },
        "databases": {},
    },

    "com.brave.browser": {
        "name": "Brave Browser",
        "account_type": "none",
        "login_required": False,
        "has_payment": False,
        "trust_weight": 2,
        "data_dir": "/data/data/com.brave.browser",
        "shared_prefs": {
            "com.brave.browser_preferences.xml": {
                "first_run_flow": "true",
                "brave_shields_default": "true",
            },
        },
        "databases": {},
    },

    # ─── MUSIC / STREAMING ─────────────────────────────────────────────

    "com.spotify.music": {
        "name": "Spotify",
        "account_type": "email",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 5,
        "data_dir": "/data/data/com.spotify.music",
        "shared_prefs": {
            "com.spotify.music_preferences.xml": {
                "is_logged_in": "true",
                "username": "{persona_email}",
                "display_name": "{first_name}",
                "product": "premium",
                "offline_mode": "false",
                "streaming_quality": "high",
                "device_id": "{random_hex_32}",
            },
        },
        "databases": {},
    },

    "com.google.android.youtube": {
        "name": "YouTube",
        "account_type": "google",
        "login_required": False,
        "has_payment": False,
        "trust_weight": 7,
        "data_dir": "/data/data/com.google.android.youtube",
        "shared_prefs": {
            "youtube.xml": {
                "account_name": "{persona_email}",
                "signed_in": "true",
                "autoplay_enabled": "true",
                "dark_theme": "auto",
                "restricted_mode": "false",
                "quality_wifi": "auto",
            },
        },
        "databases": {},
    },

    # ─── GOOGLE APPS ───────────────────────────────────────────────────

    "com.google.android.gm": {
        "name": "Gmail",
        "account_type": "google",
        "login_required": True,
        "has_payment": False,
        "trust_weight": 8,
        "data_dir": "/data/data/com.google.android.gm",
        "shared_prefs": {
            "Gmail.xml": {
                "account_name": "{persona_email}",
                "show_sender_images": "true",
                "default_reply_all": "false",
                "auto_advance": "newer",
                "conversation_view": "true",
                "notifications_enabled": "true",
                "swipe_action_left": "archive",
                "swipe_action_right": "delete",
            },
        },
        "databases": {},
    },

    "com.google.android.apps.maps": {
        "name": "Google Maps",
        "account_type": "google",
        "login_required": False,
        "has_payment": False,
        "trust_weight": 6,
        "data_dir": "/data/data/com.google.android.apps.maps",
        "shared_prefs": {
            "com.google.android.apps.maps_preferences.xml": {
                "signed_in_account": "{persona_email}",
                "navigation_voice": "true",
                "wifi_only_mode": "false",
                "distance_unit": "mi",
                "location_history": "true",
            },
        },
        "databases": {},
    },

    "com.google.android.apps.photos": {
        "name": "Google Photos",
        "account_type": "google",
        "login_required": True,
        "has_payment": False,
        "trust_weight": 6,
        "data_dir": "/data/data/com.google.android.apps.photos",
        "shared_prefs": {
            "com.google.android.apps.photos_preferences.xml": {
                "account_name": "{persona_email}",
                "backup_enabled": "true",
                "backup_wifi_only": "true",
                "backup_quality": "high",
                "face_grouping": "true",
            },
        },
        "databases": {},
    },

    # ─── CRYPTO ────────────────────────────────────────────────────────

    "com.coinbase.android": {
        "name": "Coinbase",
        "account_type": "email",
        "login_required": True,
        "has_payment": True,
        "trust_weight": 5,
        "data_dir": "/data/data/com.coinbase.android",
        "shared_prefs": {
            "coinbase_prefs.xml": {
                "is_logged_in": "true",
                "email": "{persona_email}",
                "biometric_enabled": "true",
                "push_enabled": "true",
                "device_id": "{uuid4}",
                "2fa_enabled": "true",
            },
        },
        "databases": {},
    },
}


# ═══════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def get_app_map(package: str) -> Optional[Dict[str, Any]]:
    """Get data map for a specific package."""
    return APK_DATA_MAP.get(package)


def get_apps_by_trust_weight(min_weight: int = 5) -> List[str]:
    """Get packages sorted by trust weight (highest first)."""
    return sorted(
        [pkg for pkg, data in APK_DATA_MAP.items() if data["trust_weight"] >= min_weight],
        key=lambda p: APK_DATA_MAP[p]["trust_weight"],
        reverse=True,
    )


def get_payment_apps() -> List[str]:
    """Get all packages that support payment methods."""
    return [pkg for pkg, data in APK_DATA_MAP.items() if data.get("has_payment")]


def get_google_apps() -> List[str]:
    """Get all packages that use Google account auth."""
    return [pkg for pkg, data in APK_DATA_MAP.items() if data.get("account_type") == "google"]


def get_login_required_apps() -> List[str]:
    """Get all packages that need auth to look 'used'."""
    return [pkg for pkg, data in APK_DATA_MAP.items() if data.get("login_required")]


def get_total_trust_weight() -> int:
    """Get maximum possible trust weight (sum of all apps)."""
    return sum(data["trust_weight"] for data in APK_DATA_MAP.values())
