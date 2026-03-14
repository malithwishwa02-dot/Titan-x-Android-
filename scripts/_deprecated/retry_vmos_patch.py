#!/usr/bin/env python3
"""
Titan V11.3 — VMOS Cloud Full Pipeline (Direct API)
====================================================
Connects directly to the VMOS Cloud API, forges a 365-day circadian-weighted
Genesis profile via AndroidProfileForge, applies stealth patches, injects
all behavioral data (contacts, calls, SMS, Chrome cookies/history, autofill,
Google Account, wallet), and runs verification.

Usage:
    python scripts/retry_vmos_patch.py [--pad ACP2509244LGV1MV] [--age-days 365]
    python scripts/retry_vmos_patch.py --cc-number 4111111111111111 --cc-exp 12/28 --cc-name "Alex Mercer"
    python scripts/retry_vmos_patch.py --ai-check

Env vars:
    VMOS_API_KEY      — VMOS Cloud API key
    VMOS_API_SECRET   — VMOS Cloud API secret
"""

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time

# Add project root and core to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from android_profile_forge import AndroidProfileForge  # noqa: E402
from vmos_cloud_bridge import VMOSCloudBridge  # noqa: E402
from vmos_cloud_patcher import VMOSCloudPatcher  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("titan-pipeline")

# Colors
G = "\033[92m"
R = "\033[91m"
Y = "\033[93m"
C = "\033[96m"
B = "\033[1m"
DIM = "\033[2m"
RST = "\033[0m"

# ═══════════════════════════════════════════════════════════════════════
# LA PERSONA GENERATION
# ═══════════════════════════════════════════════════════════════════════

FIRST_NAMES = [
    "James", "Maria", "David", "Jennifer", "Michael", "Jessica",
    "Robert", "Sarah", "Daniel", "Emily", "Carlos", "Ashley",
    "Christopher", "Amanda", "Matthew", "Stephanie", "Anthony", "Nicole",
]
LAST_NAMES = [
    "Garcia", "Martinez", "Lopez", "Hernandez", "Gonzalez", "Rodriguez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
    "White", "Harris", "Martin", "Thompson", "Robinson", "Clark",
]
LA_AREA_CODES = ["213", "310", "323", "424", "818"]


def _generate_persona():
    """Auto-generate a realistic LA-based persona."""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    name = f"{first} {last}"
    # Gmail-style email
    sep = random.choice([".", ""])
    suffix = random.randint(1, 999) if random.random() > 0.4 else ""
    email = f"{first.lower()}{sep}{last.lower()}{suffix}@gmail.com"
    # LA phone number
    area = random.choice(LA_AREA_CODES)
    phone = f"+1{area}{random.randint(200, 999)}{random.randint(1000, 9999)}"
    address = {
        "street": f"{random.randint(100, 9999)} {random.choice(['Sunset Blvd', 'Wilshire Blvd', 'Santa Monica Blvd', 'Hollywood Blvd', 'Venice Blvd', 'Melrose Ave', 'La Brea Ave', 'Figueroa St'])}",
        "city": random.choice(["Los Angeles", "Santa Monica", "Burbank", "Glendale", "Pasadena"]),
        "state": "CA",
        "postal": f"90{random.randint(1, 99):03d}",
        "country": "US",
    }
    return name, email, phone, address


# ═══════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════

async def run(args):
    key = os.environ.get("VMOS_API_KEY", "")
    secret = os.environ.get("VMOS_API_SECRET", "")
    if not key or not secret:
        print(f"{R}ERROR: Set VMOS_API_KEY and VMOS_API_SECRET env vars{RST}")
        sys.exit(1)

    bridge = VMOSCloudBridge(api_key=key, api_secret=secret)
    patcher = VMOSCloudPatcher(bridge, args.pad)

    # ── Generate persona ────────────────────────────────────────
    persona_name, persona_email, persona_phone, persona_address = _generate_persona()

    # Parse card data if provided
    card_data = None
    if args.cc_number:
        exp_parts = (args.cc_exp or "12/28").split("/")
        card_data = {
            "number": args.cc_number,
            "exp_month": int(exp_parts[0]),
            "exp_year": int(exp_parts[1]) if int(exp_parts[1]) > 99 else 2000 + int(exp_parts[1]),
            "cardholder": args.cc_name or persona_name,
        }

    total_steps = 6 if args.ai_check else 5

    print(f"\n{B}{'═' * 65}{RST}")
    print(f"{B}  Titan V11.3 — Full VMOS Cloud Pipeline{RST}")
    print(f"{B}{'═' * 65}{RST}")
    print(f"  Pad:       {C}{args.pad}{RST}")
    print(f"  Carrier:   {C}{args.carrier}{RST}")
    print(f"  Location:  {C}{args.location}{RST}")
    print(f"  Preset:    {C}{args.preset}{RST}")
    print(f"  Persona:   {C}{persona_name}{RST}")
    print(f"  Email:     {C}{persona_email}{RST}")
    print(f"  Phone:     {C}{persona_phone}{RST}")
    print(f"  Age:       {C}{args.age_days} days{RST}")
    print(f"  Archetype: {C}{args.archetype}{RST}")
    if card_data:
        print(f"  Card:      {C}****{args.cc_number[-4:]}{RST}")
    print(f"{B}{'═' * 65}{RST}\n")

    # ── Step 1: Connectivity check ──────────────────────────────
    print(f"{Y}[1/{total_steps}] Checking device connectivity...{RST}")
    try:
        probe = await bridge.exec_shell(args.pad, "getprop ro.product.model")
        if not probe.ok:
            print(f"{R}  ✗ Device unreachable: {probe.result}{RST}")
            sys.exit(1)
        model = (probe.result or "").strip()
        print(f"{G}  ✓ Device online — model: {model}{RST}")
    except Exception as e:
        print(f"{R}  ✗ Connection failed: {e}{RST}")
        sys.exit(1)

    # ── Step 2: Forge Genesis profile ───────────────────────────
    print(f"\n{Y}[2/{total_steps}] Forging {args.age_days}-day Genesis profile ({args.archetype})...{RST}")
    forge = AndroidProfileForge()
    profile = forge.forge(
        persona_name=persona_name,
        persona_email=persona_email,
        persona_phone=persona_phone,
        country="US",
        archetype=args.archetype,
        age_days=args.age_days,
        carrier=args.carrier,
        location=args.location,
        device_model="oneplus_ace3",
        persona_address=persona_address,
        persona_area_code=persona_phone[2:5],  # extract area code from +1XXX
        city_area_codes=LA_AREA_CODES,
    )
    stats = profile.get("stats", {})
    print(f"{G}  ✓ Profile forged: {profile['id']}{RST}")
    print(f"    Contacts: {stats.get('contacts', 0)}  |  Calls: {stats.get('call_logs', 0)}  |  SMS: {stats.get('sms', 0)}")
    print(f"    Cookies:  {stats.get('cookies', 0)}  |  History: {stats.get('history', 0)}  |  WiFi: {stats.get('wifi', 0)}")
    print(f"    Apps:     {stats.get('apps', 0)}  |  Purchases: {stats.get('play_purchases', 0)}")

    # ── Step 3: Full stealth patch ──────────────────────────────
    print(f"\n{Y}[3/{total_steps}] Applying stealth patches (7 phases)...{RST}")
    try:
        report = await patcher.full_patch(
            carrier=args.carrier, location=args.location, preset=args.preset,
        )
    except Exception as e:
        print(f"{R}  ✗ Patch failed: {e}{RST}")
        sys.exit(1)

    for phase in report.phases:
        icon = f"{G}✓{RST}" if phase.success else f"{R}✗{RST}"
        print(f"  {icon} {phase.name}: {phase.detail} {DIM}({phase.commands_run} cmds){RST}")

    print(f"\n  Patch Score: {B}{report.score}%{RST} ({report.passed}/{report.total} phases)")

    # ── Step 4: Full behavioral injection ───────────────────────
    print(f"\n{Y}[4/{total_steps}] Injecting full behavioral profile...{RST}")
    try:
        inject_result = await patcher.full_inject(profile, card_data)
    except Exception as e:
        print(f"{R}  ✗ Injection failed: {e}{RST}")
        inject_result = {}

    for channel, value in inject_result.items():
        if isinstance(value, dict):
            detail = ", ".join(f"{k}={v}" for k, v in value.items())
        else:
            detail = str(value)
        print(f"  {G}✓{RST} {channel}: {detail}")

    # ── Step 5: Verification scan ───────────────────────────────
    print(f"\n{Y}[5/{total_steps}] Running verification scan...{RST}")
    try:
        verify = await patcher.verify()
    except Exception as e:
        print(f"{R}  ✗ Verify failed: {e}{RST}")
        sys.exit(1)

    passed_checks = []
    failed_checks = []
    for check in verify.checks:
        actual = check.get("actual", "")[:60]
        if check["pass"]:
            passed_checks.append(check)
            print(f"  {G}✓{RST} {check['name']}: {actual}")
        else:
            failed_checks.append(check)
            print(f"  {R}✗{RST} {check['name']}: {actual} {DIM}(expected: {check.get('expected', '')}){RST}")

    print(f"\n  Verify Score: {B}{verify.score}%{RST} ({verify.passed}/{verify.total} checks)")

    # ── Step 6 (optional): AI agent smoke test ──────────────────
    ai_result = None
    if args.ai_check:
        print(f"\n{Y}[6/{total_steps}] AI agent smoke test...{RST}")
        try:
            from vmos_agent_adapter import VMOSAgentAdapter
            from vmos_screen_agent import VMOSScreenAgent

            adapter = VMOSAgentAdapter(bridge, args.pad)
            agent = VMOSScreenAgent(adapter)

            # Open Settings app and take screenshot
            await bridge.exec_shell(args.pad, "am start -a android.settings.SETTINGS")
            await asyncio.sleep(2)
            screenshot_url = await bridge.screenshot(args.pad)
            if screenshot_url:
                print(f"  {G}✓{RST} Screenshot captured: {screenshot_url[:80]}...")
                ai_result = {"status": "ok", "screenshot": screenshot_url}
            else:
                print(f"  {R}✗{RST} Screenshot failed")
                ai_result = {"status": "failed"}
        except Exception as e:
            print(f"  {R}✗{RST} AI agent error: {e}")
            ai_result = {"status": "error", "message": str(e)}

    # ── Summary ─────────────────────────────────────────────────
    print(f"\n{B}{'═' * 65}{RST}")
    overall = "PASS" if report.score >= 80 and verify.score >= 70 else "FAIL"
    color = G if overall == "PASS" else R
    print(f"  {B}Overall: {color}{overall}{RST}")
    print(f"  Patch:    {report.score}%  |  Verify: {verify.score}%")
    print(f"  Persona:  {persona_name} <{persona_email}>")
    print(f"  Profile:  {profile['id']} ({args.age_days}d / {args.archetype})")
    inject_total = sum(v if isinstance(v, int) else sum(v.values()) if isinstance(v, dict) else 0 for v in inject_result.values())
    print(f"  Injected: {inject_total} records across {len(inject_result)} channels")
    if failed_checks:
        print(f"  {R}Failed:  {', '.join(c['name'] for c in failed_checks)}{RST}")
    print(f"{B}{'═' * 65}{RST}\n")

    # ── Save results ────────────────────────────────────────────
    results = {
        "pad_code": args.pad,
        "carrier": args.carrier,
        "location": args.location,
        "preset": args.preset,
        "persona": {
            "name": persona_name,
            "email": persona_email,
            "phone": persona_phone,
            "address": persona_address,
        },
        "profile_id": profile["id"],
        "age_days": args.age_days,
        "archetype": args.archetype,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "patch": report.to_dict(),
        "verify": verify.to_dict(),
        "injection": inject_result,
        "profile_stats": stats,
        "overall": overall,
    }
    if ai_result:
        results["ai_check"] = ai_result
    out_path = os.path.join(os.path.dirname(__file__), f"patch_results_{args.pad}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Results saved to {out_path}")

    return overall == "PASS"


def main():
    parser = argparse.ArgumentParser(
        description="Titan V11.3 — Full VMOS Cloud Pipeline (patch + forge + inject + verify)",
    )
    parser.add_argument("--pad", default="ACP2509244LGV1MV", help="VMOS pad code")
    parser.add_argument("--carrier", default="att_us", help="Carrier key (att_us, tmobile_us, etc.)")
    parser.add_argument("--location", default="la", help="Location key (la, nyc, etc.)")
    parser.add_argument("--preset", default="oneplus_ace3", help="Device preset key")
    parser.add_argument("--age-days", type=int, default=365, help="Profile age in days (default: 365)")
    parser.add_argument("--archetype", default="professional",
                        choices=["professional", "student", "night_shift", "retiree", "gamer"],
                        help="Circadian archetype (default: professional)")
    parser.add_argument("--cc-number", default="", help="Credit card number for wallet injection")
    parser.add_argument("--cc-exp", default="12/28", help="Card expiration MM/YY (default: 12/28)")
    parser.add_argument("--cc-name", default="", help="Cardholder name (default: persona name)")
    parser.add_argument("--ai-check", action="store_true", help="Run AI agent smoke test after injection")
    args = parser.parse_args()

    success = asyncio.run(run(args))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
