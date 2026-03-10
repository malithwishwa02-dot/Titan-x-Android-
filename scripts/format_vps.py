#!/usr/bin/env python3
"""
Titan V11.3 — Hostinger VPS Format Script
Recreates the target VPS (72.62.72.48) via Hostinger API with fresh Ubuntu 24.04.
Attaches SSH key and waits for VPS to be ready.

Usage:
    python3 format_vps.py [--confirm]
"""

import argparse
import json
import sys
import time
import requests

API_BASE = "https://developers.hostinger.com/api/vps/v1"
API_TOKEN = "8krvdnkOZGasRYIkHzuLBXYMTOB7kgXQOx0Ark01829491a9"
VPS_ID = "1400969"  # KVM 8: 72.62.72.48 — 8 CPU, 32GB RAM, 400GB disk
SSH_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILYyQ53CiIeSgcBPPyQ6SzLQbuDHbaIyo2BRPwdUf1fd titan@v11"

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json",
}


def api_get(path: str) -> dict:
    r = requests.get(f"{API_BASE}{path}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def api_post(path: str, data: dict = None) -> dict:
    r = requests.post(f"{API_BASE}{path}", headers=HEADERS, json=data or {}, timeout=60)
    r.raise_for_status()
    return r.json()


def get_vps_status() -> dict:
    return api_get(f"/virtual-machines/{VPS_ID}")


def ensure_ssh_key() -> int:
    """Create SSH key on account if not exists, return key ID."""
    print("[1/4] Checking SSH keys...")
    keys = api_get("/public-keys")
    for key in keys:
        if "titan@v11" in key.get("name", "") or SSH_KEY[:40] in key.get("key", ""):
            print(f"  SSH key already exists: ID {key['id']}")
            return key["id"]

    print("  Creating SSH key...")
    result = api_post("/public-keys", {"name": "titan-v11", "key": SSH_KEY})
    key_id = result.get("id")
    print(f"  SSH key created: ID {key_id}")
    return key_id


def attach_ssh_key(key_id: int):
    """Attach SSH key to VPS."""
    print(f"[2/4] Attaching SSH key {key_id} to VPS {VPS_ID}...")
    try:
        api_post(f"/public-keys/attach/{VPS_ID}", {"ids": [key_id]})
        print("  Key attached")
    except Exception as e:
        print(f"  Attach failed (may already be attached): {e}")


def recreate_vps():
    """Recreate VPS with fresh Ubuntu 24.04."""
    print(f"[3/4] Recreating VPS {VPS_ID} with Ubuntu 24.04...")
    api_post(f"/virtual-machines/{VPS_ID}/recreate", {
        "template_id": 1,  # Ubuntu 24.04
    })
    print("  Recreate initiated — VPS is reformatting...")


def wait_for_ready(timeout: int = 600):
    """Wait for VPS to be active and SSH-accessible."""
    print(f"[4/4] Waiting for VPS to be ready (timeout: {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            info = get_vps_status()
            state = info.get("state", "")
            ip = info.get("ip", "")
            print(f"  State: {state} | IP: {ip} | Elapsed: {int(time.time()-start)}s")

            if state == "running" and ip:
                # Try SSH connectivity
                import subprocess
                r = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
                     f"root@{ip}", "echo ready"],
                    capture_output=True, text=True, timeout=10,
                )
                if "ready" in r.stdout:
                    print(f"\n  ✓ VPS ready at {ip}")
                    return ip
        except Exception as e:
            print(f"  Waiting... ({e})")

        time.sleep(15)

    print("  ✗ Timeout waiting for VPS")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Format Hostinger VPS for Titan V11.3")
    parser.add_argument("--confirm", action="store_true", help="Actually format (without this, dry run only)")
    parser.add_argument("--skip-format", action="store_true", help="Skip recreate, just check status")
    args = parser.parse_args()

    print("═══════════════════════════════════════════════════════════")
    print("  TITAN V11.3 — VPS Format Script")
    print(f"  Target: VPS {VPS_ID} (KVM 8)")
    print("═══════════════════════════════════════════════════════════\n")

    # Current status
    info = get_vps_status()
    print(f"Current state: {info.get('state')} | IP: {info.get('ip')} | OS: {info.get('template', {}).get('name', '?')}\n")

    if args.skip_format:
        wait_for_ready()
        return

    if not args.confirm:
        print("DRY RUN — pass --confirm to actually format the VPS")
        print("WARNING: This will DESTROY all data on the VPS!")
        return

    key_id = ensure_ssh_key()
    attach_ssh_key(key_id)
    recreate_vps()
    ip = wait_for_ready()

    print(f"\n═══════════════════════════════════════════════════════════")
    print(f"  VPS formatted and ready: {ip}")
    print(f"  Next: scp titan-v11.3-device/ root@{ip}:/opt/")
    print(f"        ssh root@{ip} 'bash /opt/titan-v11.3-device/scripts/deploy_titan_v11.3.sh'")
    print(f"═══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
