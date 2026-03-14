#!/usr/bin/env python3
"""
Titan V11.3 — VMOS Cloud E2E Pipeline Test
Registers a VMOS device, forges a profile, injects, ages, and scores.

Usage:
    python scripts/test_vmos_pipeline.py [--base http://127.0.0.1:8080] [--pad ACP2509244LGV1MV]
"""

import argparse
import json
import sys
import time
import requests

def main():
    parser = argparse.ArgumentParser(description="VMOS Cloud E2E pipeline test")
    parser.add_argument("--base", default="http://127.0.0.1:8080", help="Titan API base URL")
    parser.add_argument("--pad", default="ACP2509244LGV1MV", help="VMOS pad_code to register")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    pad_code = args.pad
    passed = 0
    failed = 0

    def api(method, path, body=None):
        url = f"{base}/api{path}"
        r = requests.request(method, url, json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  ✓ {name} {detail}")
            passed += 1
        else:
            print(f"  ✗ {name} {detail}")
            failed += 1

    # ── Step 1: Register VMOS device ─────────────────────────────
    print("\n[1/6] Register VMOS device...")
    try:
        r = api("POST", "/vmos/register", {"pad_code": pad_code, "model": "samsung_s25_ultra", "country": "US"})
        device_id = r.get("device_id", "")
        check("Device registered", bool(device_id), f"→ {device_id}")
    except requests.HTTPError as e:
        # Device may already exist — try to find it
        devices = api("GET", "/devices")
        device_id = ""
        for d in devices.get("devices", []):
            if d.get("vmos_pad_code") == pad_code or d.get("device_type") == "vmos_cloud":
                device_id = d["id"]
                break
        check("Device exists (already registered)", bool(device_id), f"→ {device_id}")

    if not device_id:
        print("FATAL: No VMOS device available")
        sys.exit(1)

    # ── Step 2: Verify device in list ────────────────────────────
    print("\n[2/6] Verify device in fleet...")
    devices = api("GET", "/devices")
    dev = next((d for d in devices.get("devices", []) if d["id"] == device_id), None)
    check("Device in list", dev is not None)
    check("Device type is vmos_cloud", dev and dev.get("device_type") == "vmos_cloud")
    check("Has pad_code", dev and bool(dev.get("vmos_pad_code")))

    # ── Step 3: Forge profile ────────────────────────────────────
    print("\n[3/6] Forge profile...")
    profile = api("POST", "/genesis/create", {
        "name": "Alex Morrison", "email": "alex.morrison@proton.me",
        "phone": "+12125551234", "country": "US", "archetype": "professional",
        "age_days": 120, "carrier": "tmobile_us", "location": "nyc",
        "device_model": "samsung_s25_ultra",
    })
    profile_id = profile.get("profile_id", "")
    check("Profile forged", bool(profile_id), f"→ {profile_id}")
    stats = profile.get("stats", {})
    check("Has contacts", stats.get("contacts", 0) >= 5, f"({stats.get('contacts', 0)})")
    check("Has cookies", stats.get("cookies", 0) >= 10, f"({stats.get('cookies', 0)})")

    # ── Step 4: Inject into VMOS device ──────────────────────────
    print("\n[4/6] Inject profile into VMOS device...")
    inject_r = api("POST", f"/genesis/inject/{device_id}", {"profile_id": profile_id})
    job_id = inject_r.get("job_id", "")
    check("Inject started", inject_r.get("status") == "inject_started", f"job={job_id}")

    # Poll for completion
    if job_id:
        for _ in range(60):
            time.sleep(2)
            status = api("GET", f"/genesis/inject-status/{job_id}")
            if status.get("status") != "running":
                break
        check("Inject completed", status.get("status") == "completed",
              f"({status.get('status', 'unknown')})")
    else:
        check("Inject completed", False, "(no job_id)")

    # ── Step 5: Age device ───────────────────────────────────────
    print("\n[5/6] Age device...")
    age_r = api("POST", f"/genesis/age-device/{device_id}", {
        "device_id": device_id, "preset": "samsung_s25_ultra",
        "carrier": "tmobile_us", "location": "nyc", "age_days": 90,
    })
    check("Aging complete", age_r.get("status") == "complete",
          f"phases={age_r.get('phases', '?')}")

    # ── Step 6: Trust score ──────────────────────────────────────
    print("\n[6/6] Trust score...")
    score = api("GET", f"/genesis/trust-score/{device_id}")
    ts = score.get("trust_score", 0)
    grade = score.get("grade", "?")
    check("Trust score computed", ts > 0, f"→ {ts}/100 ({grade})")
    check("Grade ≥ C", grade in ("A+", "A", "B", "C"), f"(got {grade})")

    # ── Summary ──────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"  PASSED: {passed}  |  FAILED: {failed}")
    print(f"{'='*50}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
