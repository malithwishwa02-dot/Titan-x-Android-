#!/usr/bin/env python3
"""
Titan V11.3 — Oracle Cloud CVD Device Registration
====================================================
Registers the Oracle Cloud Cuttlefish device (cvd-oracle-1) into the Titan
device manager and sets up an ADB SSH tunnel from OVH → Oracle so the
device can be controlled remotely.

Oracle device specs:
  - IP: 140.245.44.110 (username: ubuntu, key: /root/.ssh/oracle_cvd.pem)
  - Android 15 AOSP, ADB 127.0.0.1:6520 (on Oracle localhost)
  - Tunnel: OVH:16520 → Oracle:6520 (ADB)

Usage:
    # Register device + set up tunnel (run on OVH):
    python register_oracle_device.py --register --tunnel

    # Check status only:
    python register_oracle_device.py --status

    # Remove device registration:
    python register_oracle_device.py --remove
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("titan.oracle-reg")

ORACLE_IP = "140.245.44.110"
ORACLE_USER = "ubuntu"
ORACLE_KEY = "/root/.ssh/oracle_cvd.pem"
ORACLE_ADB_PORT = 6520
TUNNEL_LOCAL_PORT = 16520  # OVH local port that tunnels to Oracle ADB

DEVICES_JSON = "/opt/titan/data/devices/devices.json"
TUNNEL_SERVICE = "/etc/systemd/system/titan-oracle-tunnel.service"

DEVICE_ENTRY = {
    "id": "cvd-oracle-1",
    "name": "Oracle CVD Android 15",
    "type": "cuttlefish",
    "platform": "oracle_cloud",
    "adb_target": f"127.0.0.1:{TUNNEL_LOCAL_PORT}",
    "android_version": "15",
    "sdk_version": "35",
    "resolution": "1080x2340",
    "status": "online",
    "preset": "samsung_s25_ultra",
    "tags": ["cuttlefish", "oracle", "android15"],
}

TUNNEL_SERVICE_CONTENT = f"""[Unit]
Description=Titan Oracle CVD ADB Tunnel
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/ssh \\
    -i {ORACLE_KEY} \\
    -o StrictHostKeyChecking=no \\
    -o ServerAliveInterval=30 \\
    -o ServerAliveCountMax=3 \\
    -o ExitOnForwardFailure=yes \\
    -N \\
    -L 127.0.0.1:{TUNNEL_LOCAL_PORT}:127.0.0.1:{ORACLE_ADB_PORT} \\
    {ORACLE_USER}@{ORACLE_IP}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def check_oracle_reachable() -> bool:
    """Check if Oracle server is reachable via SSH."""
    try:
        r = subprocess.run(
            ["ssh", "-i", ORACLE_KEY,
             "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=10",
             f"{ORACLE_USER}@{ORACLE_IP}",
             "echo ok"],
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0 and "ok" in r.stdout
    except Exception as e:
        logger.error(f"Oracle SSH check failed: {e}")
        return False


def check_cuttlefish_running() -> bool:
    """Check if Cuttlefish is running on Oracle."""
    try:
        r = subprocess.run(
            ["ssh", "-i", ORACLE_KEY,
             "-o", "StrictHostKeyChecking=no",
             f"{ORACLE_USER}@{ORACLE_IP}",
             "adb connect 127.0.0.1:6520 2>/dev/null; "
             "adb -s 127.0.0.1:6520 shell echo ok 2>/dev/null"],
            capture_output=True, text=True, timeout=20,
        )
        return "ok" in r.stdout
    except Exception as e:
        logger.warning(f"Cuttlefish check failed: {e}")
        return False


def setup_tunnel_service():
    """Install and start the SSH tunnel systemd service."""
    if not os.path.isfile(ORACLE_KEY):
        logger.error(f"Oracle SSH key not found: {ORACLE_KEY}")
        return False

    logger.info("Installing tunnel service...")
    with open(TUNNEL_SERVICE, "w") as f:
        f.write(TUNNEL_SERVICE_CONTENT)

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "titan-oracle-tunnel"], check=True)
    subprocess.run(["systemctl", "start", "titan-oracle-tunnel"], check=True)

    # Wait for tunnel to establish
    time.sleep(5)

    # Verify tunnel is working
    try:
        r = subprocess.run(
            ["adb", "connect", f"127.0.0.1:{TUNNEL_LOCAL_PORT}"],
            capture_output=True, text=True, timeout=15,
        )
        if "connected" in r.stdout.lower() or "already connected" in r.stdout.lower():
            logger.info(f"Tunnel active: OVH:{TUNNEL_LOCAL_PORT} → Oracle:{ORACLE_ADB_PORT}")
            return True
        else:
            logger.warning(f"ADB connect output: {r.stdout.strip()}")
    except Exception as e:
        logger.warning(f"ADB connect test failed: {e}")
    return False


def register_device():
    """Add device entry to devices.json."""
    devices_path = Path(DEVICES_JSON)
    devices_path.parent.mkdir(parents=True, exist_ok=True)

    devices = []
    if devices_path.exists():
        try:
            with open(devices_path) as f:
                data = json.load(f)
                devices = data if isinstance(data, list) else data.get("devices", [])
        except json.JSONDecodeError:
            logger.warning("devices.json corrupt, starting fresh")

    # Remove existing entry if present
    devices = [d for d in devices if d.get("id") != DEVICE_ENTRY["id"]]
    devices.append(DEVICE_ENTRY)

    with open(devices_path, "w") as f:
        json.dump(devices, f, indent=2)

    logger.info(f"Registered {DEVICE_ENTRY['id']} in {DEVICES_JSON}")
    return True


def remove_device():
    """Remove device from devices.json."""
    devices_path = Path(DEVICES_JSON)
    if not devices_path.exists():
        logger.info("devices.json not found — nothing to remove")
        return

    with open(devices_path) as f:
        devices = json.load(f)
    if isinstance(devices, list):
        devices = [d for d in devices if d.get("id") != "cvd-oracle-1"]
    with open(devices_path, "w") as f:
        json.dump(devices, f, indent=2)

    subprocess.run(["systemctl", "stop", "titan-oracle-tunnel"], capture_output=True)
    subprocess.run(["systemctl", "disable", "titan-oracle-tunnel"], capture_output=True)
    if os.path.exists(TUNNEL_SERVICE):
        os.unlink(TUNNEL_SERVICE)
    logger.info("cvd-oracle-1 removed")


def status():
    """Print current status of Oracle device and tunnel."""
    print(f"\n{'='*50}")
    print("Oracle Cloud CVD Status")
    print(f"{'='*50}")

    # Check tunnel service
    r = subprocess.run(["systemctl", "is-active", "titan-oracle-tunnel"],
                       capture_output=True, text=True)
    tunnel_active = r.stdout.strip() == "active"
    print(f"Tunnel service: {'✓ active' if tunnel_active else '✗ inactive'}")

    # Check ADB
    try:
        r = subprocess.run(
            ["adb", "-s", f"127.0.0.1:{TUNNEL_LOCAL_PORT}", "shell", "echo", "ok"],
            capture_output=True, text=True, timeout=10,
        )
        adb_ok = "ok" in r.stdout
    except Exception:
        adb_ok = False
    print(f"ADB (:{TUNNEL_LOCAL_PORT}): {'✓ connected' if adb_ok else '✗ not connected'}")

    # Check device registration
    if os.path.exists(DEVICES_JSON):
        with open(DEVICES_JSON) as f:
            devices = json.load(f)
        registered = any(d.get("id") == "cvd-oracle-1" for d in devices)
        print(f"Device registered: {'✓ yes' if registered else '✗ no'}")

    # Check Oracle SSH
    oracle_up = check_oracle_reachable()
    print(f"Oracle SSH: {'✓ reachable' if oracle_up else '✗ unreachable'}")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(description="Register Oracle Cloud CVD device")
    parser.add_argument("--register", action="store_true", help="Register device in Titan")
    parser.add_argument("--tunnel", action="store_true", help="Set up ADB SSH tunnel")
    parser.add_argument("--remove", action="store_true", help="Remove device registration")
    parser.add_argument("--status", action="store_true", help="Show current status")
    args = parser.parse_args()

    if args.status:
        status()
        return

    if args.remove:
        remove_device()
        return

    if not (args.register or args.tunnel):
        parser.print_help()
        return

    if args.tunnel:
        logger.info("Checking Oracle server reachability...")
        if not check_oracle_reachable():
            logger.error(f"Cannot reach Oracle at {ORACLE_IP} — check key and firewall")
            sys.exit(1)

        logger.info("Checking Cuttlefish on Oracle...")
        if not check_cuttlefish_running():
            logger.warning("Cuttlefish not running on Oracle — launch it first:")
            logger.warning(f"  ssh -i {ORACLE_KEY} {ORACLE_USER}@{ORACLE_IP}")
            logger.warning("  cd ~/cf && HOME=$PWD ./bin/launch_cvd --daemon "
                           "--cpus=2 --memory_mb=4096 --gpu_mode=guest_swiftshader "
                           "--start_webrtc=true --report_anonymous_usage_stats=n")
            # Continue anyway — device may start later

        if not setup_tunnel_service():
            logger.error("Tunnel setup failed")
            sys.exit(1)

    if args.register:
        register_device()
        logger.info(f"Done. Device cvd-oracle-1 available at 127.0.0.1:{TUNNEL_LOCAL_PORT}")
        logger.info("Restart titan-api to pick up the new device:")
        logger.info("  systemctl restart titan-api")

    status()


if __name__ == "__main__":
    main()
