#!/usr/bin/env python3
"""
Titan V11.3 — Bootstrap Training Data Generator
=================================================
Generates synthetic trajectory data from ALL TASK_TEMPLATES to bootstrap
the training pipeline before live device trajectories are available.

Each synthetic trajectory simulates a realistic See→Think→Act sequence
with plausible screen contexts, LLM prompts/responses, and action chains.

Usage:
    python bootstrap_training_data.py --output /opt/titan/data/trajectories
    python bootstrap_training_data.py --output /opt/titan/data/trajectories --count 5
"""

import argparse
import json
import logging
import os
import random
import sys
import time
import uuid
from pathlib import Path

CORE_DIR = Path(__file__).parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("titan.bootstrap")

# ═══════════════════════════════════════════════════════════════════════
# SYNTHETIC SCREEN CONTEXTS
# ═══════════════════════════════════════════════════════════════════════

SCREEN_CONTEXTS = {
    "home_screen": [
        "[Screen: 1080x2400 | App: com.android.launcher3]\n"
        "Elements:\n"
        "  [0] App icon 'Chrome' at (162, 1950) clickable\n"
        "  [1] App icon 'Play Store' at (378, 1950) clickable\n"
        "  [2] App icon 'Settings' at (594, 1950) clickable\n"
        "  [3] App icon 'Phone' at (810, 1950) clickable\n"
        "  [4] Google search bar at (540, 200) clickable\n"
        "  [5] Clock widget '2:45 PM' at (540, 400)\n"
        "  [6] App icon 'Instagram' at (162, 1750) clickable\n"
        "  [7] App icon 'WhatsApp' at (378, 1750) clickable",
    ],
    "play_store_search": [
        "[Screen: 1080x2400 | App: com.android.vending]\n"
        "Elements:\n"
        "  [0] Search bar 'Search for apps & games' at (540, 120) clickable\n"
        "  [1] App result '{app_name}' with icon at (540, 350) clickable\n"
        "  [2] Rating '4.5★' at (400, 420)\n"
        "  [3] Install button 'Install' at (900, 380) clickable\n"
        "  [4] Category 'Top Charts' at (200, 220) clickable\n"
        "  [5] Category 'For You' at (400, 220) clickable",
    ],
    "play_store_installing": [
        "[Screen: 1080x2400 | App: com.android.vending]\n"
        "Elements:\n"
        "  [0] App name '{app_name}' at (540, 200)\n"
        "  [1] Progress bar '45%' at (540, 400)\n"
        "  [2] Cancel button at (900, 400) clickable\n"
        "  [3] Description text at (540, 600)",
    ],
    "play_store_installed": [
        "[Screen: 1080x2400 | App: com.android.vending]\n"
        "Elements:\n"
        "  [0] App name '{app_name}' at (540, 200)\n"
        "  [1] Button 'Open' at (800, 400) clickable\n"
        "  [2] Button 'Uninstall' at (400, 400) clickable\n"
        "  [3] Rating section at (540, 600)",
    ],
    "google_signin_form": [
        "[Screen: 1080x2400 | App: com.google.android.gms]\n"
        "Elements:\n"
        "  [0] Text 'Sign in' at (540, 300)\n"
        "  [1] Text 'to continue to Google' at (540, 380)\n"
        "  [2] Input field 'Email or phone' at (540, 600) editable\n"
        "  [3] Link 'Forgot email?' at (200, 750) clickable\n"
        "  [4] Link 'Create account' at (200, 850) clickable\n"
        "  [5] Button 'Next' at (900, 1000) clickable",
    ],
    "google_password_form": [
        "[Screen: 1080x2400 | App: com.google.android.gms]\n"
        "Elements:\n"
        "  [0] Text 'Welcome' at (540, 250)\n"
        "  [1] Text '{email}' at (540, 350)\n"
        "  [2] Input field 'Enter your password' at (540, 550) editable password\n"
        "  [3] Checkbox 'Show password' at (200, 700) clickable\n"
        "  [4] Link 'Forgot password?' at (200, 800) clickable\n"
        "  [5] Button 'Next' at (900, 950) clickable",
    ],
    "chrome_browser": [
        "[Screen: 1080x2400 | App: com.android.chrome]\n"
        "Elements:\n"
        "  [0] URL bar '{url}' at (540, 80) clickable\n"
        "  [1] Tab count '3' at (950, 80) clickable\n"
        "  [2] Menu '⋮' at (1020, 80) clickable\n"
        "  [3] Page content at (540, 1200)\n"
        "  [4] Link 'Sign in' at (900, 160) clickable",
    ],
    "settings_main": [
        "[Screen: 1080x2400 | App: com.android.settings]\n"
        "Elements:\n"
        "  [0] Title 'Settings' at (200, 100)\n"
        "  [1] Search bar at (540, 180) clickable\n"
        "  [2] Item 'Network & internet' at (540, 320) clickable\n"
        "  [3] Item 'Connected devices' at (540, 440) clickable\n"
        "  [4] Item 'Apps' at (540, 560) clickable\n"
        "  [5] Item 'Notifications' at (540, 680) clickable\n"
        "  [6] Item 'Display' at (540, 800) clickable\n"
        "  [7] Item 'Sound & vibration' at (540, 920) clickable\n"
        "  [8] Item 'Accounts' at (540, 1320) clickable",
    ],
    "wallet_add_card": [
        "[Screen: 1080x2400 | App: com.google.android.apps.walletnfcrel]\n"
        "Elements:\n"
        "  [0] Title 'Add a card' at (540, 200)\n"
        "  [1] Input 'Card number' at (540, 400) editable\n"
        "  [2] Input 'Expiration date' at (300, 550) editable\n"
        "  [3] Input 'CVC' at (700, 550) editable\n"
        "  [4] Input 'Cardholder name' at (540, 700) editable\n"
        "  [5] Button 'Save' at (540, 900) clickable",
    ],
    "youtube_home": [
        "[Screen: 1080x2400 | App: com.google.android.youtube]\n"
        "Elements:\n"
        "  [0] Search icon at (850, 80) clickable\n"
        "  [1] Video thumbnail 'Top 10 Tech' at (540, 400) clickable\n"
        "  [2] Video thumbnail 'Cooking Made Easy' at (540, 800) clickable\n"
        "  [3] Video thumbnail 'Travel Vlog NYC' at (540, 1200) clickable\n"
        "  [4] Tab 'Home' at (150, 2350) clickable selected\n"
        "  [5] Tab 'Shorts' at (350, 2350) clickable\n"
        "  [6] Tab 'Subscriptions' at (750, 2350) clickable",
    ],
    "maps_main": [
        "[Screen: 1080x2400 | App: com.google.android.apps.maps]\n"
        "Elements:\n"
        "  [0] Search bar 'Search here' at (540, 120) clickable\n"
        "  [1] Map view at (540, 1200)\n"
        "  [2] Current location button at (980, 1800) clickable\n"
        "  [3] Tab 'Explore' at (150, 2350) clickable\n"
        "  [4] Tab 'Go' at (350, 2350) clickable\n"
        "  [5] Tab 'Saved' at (550, 2350) clickable",
    ],
    "instagram_login": [
        "[Screen: 1080x2400 | App: com.instagram.android]\n"
        "Elements:\n"
        "  [0] Logo 'Instagram' at (540, 300)\n"
        "  [1] Input 'Phone number, username, or email' at (540, 550) editable\n"
        "  [2] Input 'Password' at (540, 700) editable password\n"
        "  [3] Button 'Log in' at (540, 900) clickable\n"
        "  [4] Link 'Forgot password?' at (540, 1000) clickable\n"
        "  [5] Button 'Create new account' at (540, 1200) clickable",
    ],
    "permission_dialog": [
        "[Screen: 1080x2400 | App: com.android.permissioncontroller]\n"
        "Elements:\n"
        "  [0] Text 'Allow {app_name} to access your location?' at (540, 800)\n"
        "  [1] Button 'While using the app' at (540, 1050) clickable\n"
        "  [2] Button 'Only this time' at (540, 1200) clickable\n"
        "  [3] Button 'Don\\'t allow' at (540, 1350) clickable",
    ],
    "notification_prompt": [
        "[Screen: 1080x2400 | App: com.android.permissioncontroller]\n"
        "Elements:\n"
        "  [0] Text 'Allow {app_name} to send you notifications?' at (540, 800)\n"
        "  [1] Button 'Allow' at (700, 1050) clickable\n"
        "  [2] Button 'Don\\'t allow' at (350, 1050) clickable",
    ],
    "gmail_compose": [
        "[Screen: 1080x2400 | App: com.google.android.gm]\n"
        "Elements:\n"
        "  [0] Input 'To' at (540, 150) editable\n"
        "  [1] Input 'Subject' at (540, 250) editable\n"
        "  [2] Input 'Compose email' at (540, 500) editable\n"
        "  [3] Button 'Send' (paper plane icon) at (980, 80) clickable\n"
        "  [4] Button 'Attach' at (900, 80) clickable\n"
        "  [5] Back arrow at (60, 80) clickable",
    ],
    "social_feed": [
        "[Screen: 1080x2400 | App: {package}]\n"
        "Elements:\n"
        "  [0] Post by @user123 with image at (540, 400)\n"
        "  [1] Like button ♡ at (100, 700) clickable\n"
        "  [2] Comment button at (200, 700) clickable\n"
        "  [3] Share button at (300, 700) clickable\n"
        "  [4] Post by @foodie456 with image at (540, 1200)\n"
        "  [5] Tab 'Home' at (150, 2350) clickable selected\n"
        "  [6] Tab 'Search' at (350, 2350) clickable\n"
        "  [7] Tab 'Profile' at (950, 2350) clickable",
    ],
}

# ═══════════════════════════════════════════════════════════════════════
# ACTION SEQUENCES PER TEMPLATE CATEGORY
# ═══════════════════════════════════════════════════════════════════════

ACTION_SEQUENCES = {
    "install_app": [
        {"action": "open_app", "package": "com.android.vending", "reason": "Open Play Store"},
        {"action": "tap", "x": 540, "y": 120, "reason": "Tap search bar"},
        {"action": "type", "text": "{app_name}", "reason": "Type app name"},
        {"action": "enter", "reason": "Submit search"},
        {"action": "wait", "seconds": 2, "reason": "Wait for search results"},
        {"action": "tap", "x": 540, "y": 350, "reason": "Tap first search result"},
        {"action": "tap", "x": 900, "y": 380, "reason": "Tap Install button"},
        {"action": "wait", "seconds": 10, "reason": "Wait for installation"},
        {"action": "done", "reason": "App installed successfully"},
    ],
    "google_signin": [
        {"action": "open_app", "package": "com.android.settings", "reason": "Open Settings"},
        {"action": "scroll_down", "reason": "Scroll to Accounts section"},
        {"action": "tap", "x": 540, "y": 1320, "reason": "Tap Accounts"},
        {"action": "tap", "x": 540, "y": 400, "reason": "Tap Add account"},
        {"action": "tap", "x": 540, "y": 300, "reason": "Tap Google"},
        {"action": "type", "text": "{email}", "reason": "Enter email address"},
        {"action": "tap", "x": 900, "y": 1000, "reason": "Tap Next"},
        {"action": "wait", "seconds": 2, "reason": "Wait for password screen"},
        {"action": "type", "text": "{password}", "reason": "Enter password"},
        {"action": "tap", "x": 900, "y": 950, "reason": "Tap Next"},
        {"action": "wait", "seconds": 3, "reason": "Wait for account setup"},
        {"action": "done", "reason": "Google account signed in"},
    ],
    "chrome_signin": [
        {"action": "open_app", "package": "com.android.chrome", "reason": "Open Chrome"},
        {"action": "tap", "x": 1020, "y": 80, "reason": "Tap menu"},
        {"action": "tap", "x": 800, "y": 300, "reason": "Tap Settings"},
        {"action": "tap", "x": 540, "y": 200, "reason": "Tap Sign in to Chrome"},
        {"action": "tap", "x": 540, "y": 800, "reason": "Tap Continue as {email}"},
        {"action": "done", "reason": "Chrome signed in"},
    ],
    "wallet_add_card": [
        {"action": "open_app", "package": "com.google.android.apps.walletnfcrel", "reason": "Open Google Wallet"},
        {"action": "tap", "x": 540, "y": 1800, "reason": "Tap Add to Wallet"},
        {"action": "tap", "x": 540, "y": 400, "reason": "Tap Payment card"},
        {"action": "tap", "x": 540, "y": 600, "reason": "Tap New credit or debit card"},
        {"action": "type", "text": "{card_number}", "reason": "Enter card number"},
        {"action": "tap", "x": 300, "y": 550, "reason": "Tap expiration field"},
        {"action": "type", "text": "{card_exp}", "reason": "Enter expiration date"},
        {"action": "tap", "x": 700, "y": 550, "reason": "Tap CVC field"},
        {"action": "type", "text": "{card_cvv}", "reason": "Enter CVC"},
        {"action": "tap", "x": 540, "y": 900, "reason": "Tap Save"},
        {"action": "done", "reason": "Card added to Google Wallet"},
    ],
    "warmup_browse": [
        {"action": "open_app", "package": "com.android.chrome", "reason": "Open Chrome"},
        {"action": "tap", "x": 540, "y": 80, "reason": "Tap URL bar"},
        {"action": "type", "text": "google.com", "reason": "Navigate to Google"},
        {"action": "enter", "reason": "Go to URL"},
        {"action": "wait", "seconds": 2, "reason": "Wait for page load"},
        {"action": "tap", "x": 540, "y": 600, "reason": "Tap search box"},
        {"action": "type", "text": "{query}", "reason": "Type search query"},
        {"action": "enter", "reason": "Submit search"},
        {"action": "wait", "seconds": 2, "reason": "Wait for results"},
        {"action": "tap", "x": 540, "y": 500, "reason": "Click first result"},
        {"action": "scroll_down", "reason": "Scroll through page"},
        {"action": "done", "reason": "Browsing complete"},
    ],
    "warmup_youtube": [
        {"action": "open_app", "package": "com.google.android.youtube", "reason": "Open YouTube"},
        {"action": "tap", "x": 850, "y": 80, "reason": "Tap search icon"},
        {"action": "type", "text": "{query}", "reason": "Type search query"},
        {"action": "enter", "reason": "Submit search"},
        {"action": "wait", "seconds": 2, "reason": "Wait for results"},
        {"action": "tap", "x": 540, "y": 400, "reason": "Tap first video"},
        {"action": "wait", "seconds": 15, "reason": "Watch video for 15 seconds"},
        {"action": "scroll_down", "reason": "Scroll to comments"},
        {"action": "done", "reason": "YouTube session complete"},
    ],
    "warmup_maps": [
        {"action": "open_app", "package": "com.google.android.apps.maps", "reason": "Open Google Maps"},
        {"action": "tap", "x": 540, "y": 120, "reason": "Tap search bar"},
        {"action": "type", "text": "{location}", "reason": "Search for location"},
        {"action": "enter", "reason": "Submit search"},
        {"action": "wait", "seconds": 3, "reason": "Wait for map to load"},
        {"action": "tap", "x": 540, "y": 600, "reason": "Tap result pin"},
        {"action": "scroll_down", "reason": "Scroll location details"},
        {"action": "done", "reason": "Maps exploration complete"},
    ],
    "social_signin": [
        {"action": "open_app", "package": "{package}", "reason": "Open {app_name}"},
        {"action": "tap", "x": 540, "y": 900, "reason": "Tap Log In"},
        {"action": "tap", "x": 540, "y": 550, "reason": "Tap email field"},
        {"action": "type", "text": "{email}", "reason": "Enter email"},
        {"action": "tap", "x": 540, "y": 700, "reason": "Tap password field"},
        {"action": "type", "text": "{password}", "reason": "Enter password"},
        {"action": "tap", "x": 540, "y": 900, "reason": "Tap Log In button"},
        {"action": "wait", "seconds": 3, "reason": "Wait for login"},
        {"action": "done", "reason": "Signed in to {app_name}"},
    ],
    "warmup_social": [
        {"action": "open_app", "package": "{package}", "reason": "Open {app_name}"},
        {"action": "wait", "seconds": 2, "reason": "Wait for feed to load"},
        {"action": "scroll_down", "reason": "Scroll through feed"},
        {"action": "scroll_down", "reason": "Continue scrolling"},
        {"action": "tap", "x": 100, "y": 700, "reason": "Like a post"},
        {"action": "scroll_down", "reason": "Scroll more"},
        {"action": "scroll_down", "reason": "Browse more content"},
        {"action": "done", "reason": "Social browsing complete"},
    ],
    "gmail_compose": [
        {"action": "open_app", "package": "com.google.android.gm", "reason": "Open Gmail"},
        {"action": "tap", "x": 980, "y": 2200, "reason": "Tap Compose FAB"},
        {"action": "tap", "x": 540, "y": 150, "reason": "Tap To field"},
        {"action": "type", "text": "{to_email}", "reason": "Enter recipient"},
        {"action": "tap", "x": 540, "y": 250, "reason": "Tap Subject field"},
        {"action": "type", "text": "{subject}", "reason": "Enter subject"},
        {"action": "tap", "x": 540, "y": 500, "reason": "Tap body"},
        {"action": "type", "text": "{body}", "reason": "Type email body"},
        {"action": "tap", "x": 980, "y": 80, "reason": "Tap Send"},
        {"action": "done", "reason": "Email sent"},
    ],
    "settings_tweak": [
        {"action": "open_app", "package": "com.android.settings", "reason": "Open Settings"},
        {"action": "tap", "x": 540, "y": 800, "reason": "Tap Display"},
        {"action": "tap", "x": 540, "y": 400, "reason": "Tap Brightness level"},
        {"action": "swipe", "x1": 300, "y1": 500, "x2": 700, "y2": 500, "reason": "Adjust brightness"},
        {"action": "back", "reason": "Go back"},
        {"action": "tap", "x": 540, "y": 920, "reason": "Tap Sound & vibration"},
        {"action": "done", "reason": "Settings adjusted"},
    ],
    "handle_permissions": [
        {"action": "tap", "x": 540, "y": 1050, "reason": "Tap 'While using the app' to allow permission"},
        {"action": "done", "reason": "Permission granted"},
    ],
    "app_update": [
        {"action": "open_app", "package": "com.android.vending", "reason": "Open Play Store"},
        {"action": "tap", "x": 980, "y": 80, "reason": "Tap profile icon"},
        {"action": "tap", "x": 540, "y": 400, "reason": "Tap Manage apps & device"},
        {"action": "tap", "x": 540, "y": 600, "reason": "Tap Updates available"},
        {"action": "tap", "x": 900, "y": 300, "reason": "Tap Update all"},
        {"action": "wait", "seconds": 10, "reason": "Wait for updates"},
        {"action": "done", "reason": "Apps updated"},
    ],
}

# Map templates to action sequence keys
TEMPLATE_TO_SEQUENCE = {
    "install_app": "install_app",
    "install_batch": "install_app",
    "google_signin": "google_signin",
    "chrome_signin": "chrome_signin",
    "login_app": "social_signin",
    "paypal_signin": "social_signin",
    "venmo_signin": "social_signin",
    "cashapp_signin": "social_signin",
    "bank_app_signin": "social_signin",
    "instagram_signin": "social_signin",
    "wallet_add_card": "wallet_add_card",
    "wallet_samsung_pay": "wallet_add_card",
    "warmup_device": "warmup_browse",
    "warmup_youtube": "warmup_youtube",
    "warmup_maps": "warmup_maps",
    "warmup_social": "warmup_social",
    "gmail_compose": "gmail_compose",
    "settings_tweak": "settings_tweak",
    "browse_url": "warmup_browse",
    "search_google": "warmup_browse",
    "create_account": "social_signin",
    "facebook_signin": "social_signin",
    "tiktok_signin": "social_signin",
    "whatsapp_setup": "social_signin",
    "telegram_signin": "social_signin",
    "snapchat_signin": "social_signin",
    "twitter_signin": "social_signin",
    "crypto_signin": "social_signin",
    "amazon_signin": "social_signin",
    "play_purchase": "install_app",
    "app_update": "app_update",
    "handle_permissions": "handle_permissions",
}

# Sample persona data
PERSONAS = [
    {"name": "John Miller", "email": "john.miller2847@gmail.com", "phone": "+12125551234", "password": "S3cur3P@ss!"},
    {"name": "Sarah Johnson", "email": "sarah.j.2901@gmail.com", "phone": "+13105559876", "password": "MyP@ssw0rd!"},
    {"name": "Mike Chen", "email": "mike.chen.dev@gmail.com", "phone": "+14155553421", "password": "Ch3nM!ke92"},
    {"name": "Emily Davis", "email": "em.davis.88@gmail.com", "phone": "+17185557890", "password": "Em!lyD@v1s"},
    {"name": "Robert Wilson", "email": "r.wilson.pro@gmail.com", "phone": "+12025556543", "password": "W!ls0nR0b"},
]

DEVICE_IDS = ["dev-us1", "vmos-oneplus-ace3", "vmos-samsung-s24"]
DEVICE_TYPES = {"dev-us1": "redroid", "vmos-oneplus-ace3": "vmos_cloud", "vmos-samsung-s24": "vmos_cloud"}

APP_PACKAGES = {
    "Instagram": "com.instagram.android",
    "Facebook": "com.facebook.katana",
    "TikTok": "com.zhiliaoapp.musically",
    "WhatsApp": "com.whatsapp",
    "Telegram": "org.telegram.messenger",
    "Snapchat": "com.snapchat.android",
    "X (Twitter)": "com.twitter.android",
    "PayPal": "com.paypal.android.p2pmobile",
    "Venmo": "com.venmo",
    "Cash App": "com.squareup.cash",
    "Chase": "com.chase.sig.android",
    "Coinbase": "com.coinbase.android",
    "Amazon": "com.amazon.mShop.android.shopping",
}


def generate_trajectory(template_name: str, template_def: dict, persona: dict,
                        device_id: str, output_dir: Path) -> str:
    """Generate a single synthetic trajectory for a task template."""
    task_id = f"synth-{template_name}-{uuid.uuid4().hex[:8]}"
    traj_dir = output_dir / task_id
    traj_dir.mkdir(parents=True, exist_ok=True)

    # Resolve template params
    params = {}
    for p in template_def.get("params", []):
        if p == "email":
            params[p] = persona["email"]
        elif p == "password":
            params[p] = persona["password"]
        elif p == "phone":
            params[p] = persona["phone"]
        elif p == "name":
            params[p] = persona["name"]
        elif p == "app_name":
            params[p] = random.choice(list(APP_PACKAGES.keys()))
        elif p == "query":
            params[p] = random.choice(["best restaurants near me", "weather today", "how to cook pasta", "NBA scores", "tech news 2026"])
        elif p == "url":
            params[p] = random.choice(["https://amazon.com", "https://target.com", "https://walmart.com"])
        elif p == "location":
            params[p] = random.choice(["Times Square NYC", "Golden Gate Bridge", "Starbucks near me"])
        elif p == "to_email":
            params[p] = "friend@example.com"
        elif p == "subject":
            params[p] = "Hello there"
        elif p == "body":
            params[p] = "Just wanted to say hi!"
        elif p in ("card_number", "card_exp", "card_cvv", "card_name"):
            params["card_number"] = "4111111111111111"
            params["card_exp"] = "12/28"
            params["card_cvv"] = "123"
            params["card_name"] = persona["name"]

    try:
        prompt_text = template_def["prompt"].format(**params)
    except KeyError:
        prompt_text = template_def["prompt"]

    category = template_def.get("category", "general")
    device_type = DEVICE_TYPES.get(device_id, "redroid")

    # Get action sequence
    seq_key = TEMPLATE_TO_SEQUENCE.get(template_name, "warmup_browse")
    actions = ACTION_SEQUENCES.get(seq_key, ACTION_SEQUENCES["warmup_browse"])

    # Write step files
    started_at = time.time() - random.uniform(30, 120)
    steps = []
    for i, action_template in enumerate(actions):
        step_num = i + 1
        step_time = started_at + step_num * random.uniform(1.5, 4.0)

        # Resolve action params
        fmt_vars = dict(params)
        fmt_vars["package"] = APP_PACKAGES.get(params.get("app_name", ""), "com.android.chrome")
        fmt_vars.setdefault("url", "google.com")
        action = {}
        for k, v in action_template.items():
            if isinstance(v, str):
                try:
                    action[k] = v.format(**fmt_vars)
                except (KeyError, IndexError):
                    action[k] = v
            else:
                action[k] = v

        is_last = action.get("action") == "done"
        success = True if is_last else random.random() > 0.05

        # Build synthetic screen context
        screen_ctx = random.choice(SCREEN_CONTEXTS.get("home_screen"))
        try:
            screen_ctx = screen_ctx.format(**fmt_vars)
        except (KeyError, IndexError):
            pass

        # Build LLM prompt
        llm_prompt = f"TASK: {prompt_text}\n\nSTEP {step_num}/{len(actions)}\n\nCURRENT SCREEN:\n{screen_ctx}\n\nWhat is the next action?"
        llm_response = json.dumps(action)

        step_record = {
            "step": step_num,
            "timestamp": step_time,
            "screen_context": screen_ctx,
            "screen_width": 1080,
            "screen_height": 2400,
            "current_app": action.get("package", "com.android.launcher3"),
            "element_count": random.randint(3, 12),
            "has_screenshot": False,
            "vision_used": device_type == "vmos_cloud",
            "vision_description": screen_ctx[:300] if device_type == "vmos_cloud" else "",
            "llm_prompt": llm_prompt,
            "llm_response": llm_response,
            "llm_model": "hermes3:8b",
            "action": action,
            "action_type": action.get("action", ""),
            "action_success": success,
            "action_reasoning": action.get("reason", ""),
            "screen_changed": True,
            "error": "",
        }

        step_file = traj_dir / f"step_{step_num:03d}.json"
        step_file.write_text(json.dumps(step_record, indent=2))
        steps.append(step_record)

    # Write metadata
    completed_at = started_at + len(actions) * 3.0
    metadata = {
        "task_id": task_id,
        "device_id": device_id,
        "device_type": device_type,
        "prompt": prompt_text,
        "model": "hermes3:8b",
        "persona": {k: v for k, v in persona.items() if k != "password"},
        "template": template_name,
        "app_context": APP_PACKAGES.get(params.get("app_name", ""), ""),
        "task_category": category,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": "completed",
        "total_steps": len(steps),
        "successful_steps": sum(1 for s in steps if s["action_success"]),
        "duration": completed_at - started_at,
    }
    (traj_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    return task_id


def main():
    parser = argparse.ArgumentParser(description="Bootstrap synthetic training data")
    parser.add_argument("--output", default="/opt/titan/data/trajectories",
                        help="Output trajectory directory")
    parser.add_argument("--count", type=int, default=3,
                        help="Number of trajectories per template per device")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    from device_agent import TASK_TEMPLATES

    total = 0
    for tmpl_name, tmpl_def in TASK_TEMPLATES.items():
        for device_id in DEVICE_IDS:
            for i in range(args.count):
                persona = random.choice(PERSONAS)
                tid = generate_trajectory(tmpl_name, tmpl_def, persona, device_id, output_dir)
                total += 1
                if total % 20 == 0:
                    logger.info(f"Generated {total} trajectories...")

    logger.info(f"Bootstrap complete: {total} synthetic trajectories in {output_dir}")
    logger.info(f"Templates: {len(TASK_TEMPLATES)}, Devices: {len(DEVICE_IDS)}, Count: {args.count}")

    # Export training data
    from trajectory_logger import TrainingDataExporter
    exporter = TrainingDataExporter(trajectory_dir=str(output_dir))

    action_count = exporter.export_action_training()
    vision_count = exporter.export_vision_training()
    stats = exporter.stats()

    logger.info(f"Action training examples: {action_count}")
    logger.info(f"Vision training examples: {vision_count}")
    logger.info(f"Stats: {json.dumps(stats, indent=2)}")


if __name__ == "__main__":
    main()
