#!/usr/bin/env python3
"""
Titan V11.3 — OVH KS-4 Server Manager
Manage the OVH dedicated server via the OVH API (ca endpoint).

API Console: https://ca.api.ovh.com/console/?section=%2Fdedicated%2Fserver&branch=v1

Usage:
    python3 ovh_manager.py info          # Server details
    python3 ovh_manager.py stats         # CPU/RAM/traffic stats
    python3 ovh_manager.py reboot        # Hard reboot
    python3 ovh_manager.py tasks         # List active tasks
    python3 ovh_manager.py ips           # List IP addresses
    python3 ovh_manager.py reverse       # Show reverse DNS
    python3 ovh_manager.py templates     # Available OS templates
    python3 ovh_manager.py health        # Quick connectivity check
    python3 ovh_manager.py grant         # Request new consumer key with permissions
"""

import json
import sys
import time
import hashlib
import urllib.request
import urllib.error

# ═══════════════════════════════════════════════════════════════════
# OVH API CREDENTIALS (ca endpoint)
# ═══════════════════════════════════════════════════════════════════
ENDPOINT = "https://ca.api.ovh.com/1.0"
APP_KEY = "b3888cb5c64a4077"
APP_SECRET = "2fd1064dc9ef12dd78b522566a84e309"
CONSUMER_KEY = "28ea74914185fe7973c59bd343d45923"

OVH_IP = "51.68.33.34"

# Time delta between local clock and OVH server (auto-calibrated)
_time_delta = None


def _get_time_delta():
    """Calculate clock skew between local machine and OVH API server."""
    global _time_delta
    if _time_delta is not None:
        return _time_delta
    try:
        req = urllib.request.Request(f"{ENDPOINT}/auth/time")
        with urllib.request.urlopen(req, timeout=10) as resp:
            server_time = int(resp.read().decode().strip())
            _time_delta = server_time - int(time.time())
    except Exception:
        _time_delta = 0
    return _time_delta


def _sign(method, url, body, timestamp):
    """Compute OVH API signature: $1$SHA1(AS+CK+METHOD+URL+BODY+TS)."""
    raw = "+".join([APP_SECRET, CONSUMER_KEY, method.upper(), url, body, str(timestamp)])
    sig = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"$1${sig}"


def api_call(method, path, body=None):
    """Make an authenticated OVH API call. Returns parsed JSON."""
    url = f"{ENDPOINT}{path}"
    body_str = json.dumps(body) if body else ""
    timestamp = int(time.time()) + _get_time_delta()

    headers = {
        "X-Ovh-Application": APP_KEY,
        "X-Ovh-Timestamp": str(timestamp),
        "X-Ovh-Signature": _sign(method, url, body_str, timestamp),
        "X-Ovh-Consumer": CONSUMER_KEY,
        "Content-Type": "application/json",
    }

    data = body_str.encode("utf-8") if body_str else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else ""
        if e.code == 403 and "NOT_GRANTED_CALL" in err_body:
            print(f"\n❌ Consumer key not authorized for this API route.", file=sys.stderr)
            print(f"   Run: python3 {sys.argv[0]} grant", file=sys.stderr)
            print(f"   Then visit the URL to authorize, and update CONSUMER_KEY.\n", file=sys.stderr)
        else:
            print(f"HTTP {e.code}: {err_body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════════════

def cmd_servers():
    """List all dedicated servers on the account."""
    servers = api_call("GET", "/dedicated/server")
    print("Dedicated Servers:")
    for s in servers:
        print(f"  - {s}")
    return servers


def cmd_info():
    """Get detailed info about the server."""
    servers = api_call("GET", "/dedicated/server")
    if not servers:
        print("No servers found on this account.")
        return
    for name in servers:
        info = api_call("GET", f"/dedicated/server/{name}")
        print(f"\n{'═' * 60}")
        print(f"  Server Name:    {info.get('name', name)}")
        print(f"  IP:             {info.get('ip', 'N/A')}")
        print(f"  State:          {info.get('state', 'N/A')}")
        print(f"  OS:             {info.get('os', 'N/A')}")
        print(f"  Datacenter:     {info.get('datacenter', 'N/A')}")
        print(f"  CPU:            {info.get('commercialRange', 'N/A')}")
        print(f"  Rack:           {info.get('rack', 'N/A')}")
        print(f"  Boot Mode:      {info.get('bootId', 'N/A')}")
        print(f"  Monitoring:     {info.get('monitoring', 'N/A')}")
        print(f"  Rescue Mail:    {info.get('rescueMail', 'N/A')}")
        print(f"{'═' * 60}")

        # Service info (billing, renewal)
        try:
            svc = api_call("GET", f"/dedicated/server/{name}/serviceInfos")
            print(f"  Billing:")
            print(f"    Creation:     {svc.get('creation', 'N/A')}")
            print(f"    Expiration:   {svc.get('expiration', 'N/A')}")
            print(f"    Renew Period: {svc.get('renewalType', 'N/A')}")
            print(f"    Status:       {svc.get('status', 'N/A')}")
        except Exception:
            pass


def cmd_stats():
    """Get server statistics (traffic)."""
    servers = api_call("GET", "/dedicated/server")
    for name in servers:
        print(f"\nStats for {name}:")
        for stat_type in ["traffic:download", "traffic:upload", "cpu:used"]:
            try:
                stats = api_call("GET", f"/dedicated/server/{name}/statistics?period=daily&type={stat_type}")
                if isinstance(stats, dict) and "values" in stats:
                    vals = stats["values"]
                    if vals:
                        latest = vals[-1].get("value", 0)
                        unit = stats.get("unit", "")
                        print(f"  {stat_type}: {latest} {unit} (latest)")
                else:
                    print(f"  {stat_type}: {stats}")
            except Exception as e:
                print(f"  {stat_type}: unavailable ({e})")


def cmd_reboot():
    """Hard reboot the server."""
    servers = api_call("GET", "/dedicated/server")
    if not servers:
        print("No servers found.")
        return
    name = servers[0]
    print(f"Rebooting {name}...")
    result = api_call("POST", f"/dedicated/server/{name}/reboot")
    print(f"  Task: {json.dumps(result, indent=2)}")
    print("  Server is rebooting. Wait 3-5 minutes before reconnecting.")


def cmd_tasks():
    """List active tasks on the server."""
    servers = api_call("GET", "/dedicated/server")
    for name in servers:
        task_ids = api_call("GET", f"/dedicated/server/{name}/task")
        if not task_ids:
            print(f"  {name}: No active tasks")
        else:
            print(f"  {name}: {len(task_ids)} task(s)")
            for tid in task_ids[-5:]:  # Show last 5
                task = api_call("GET", f"/dedicated/server/{name}/task/{tid}")
                print(f"    [{tid}] {task.get('function', '?')} — {task.get('status', '?')} ({task.get('doneDate', 'pending')})")


def cmd_ips():
    """List IP addresses."""
    ips = api_call("GET", "/ip")
    print("IP Addresses:")
    for ip in ips:
        print(f"  - {ip}")


def cmd_reverse():
    """Show reverse DNS for server IP."""
    ip_block = f"{OVH_IP}/32"
    try:
        reverse = api_call("GET", f"/ip/{ip_block}/reverse")
        print(f"Reverse DNS for {OVH_IP}:")
        for r in reverse:
            detail = api_call("GET", f"/ip/{ip_block}/reverse/{r}")
            print(f"  {r} → {detail.get('reverse', 'N/A')}")
    except Exception:
        print(f"  Could not query reverse DNS for {ip_block}")
        print(f"  Try: /ip endpoint to find your exact IP block")


def cmd_templates():
    """List available OS install templates."""
    servers = api_call("GET", "/dedicated/server")
    if not servers:
        return
    name = servers[0]
    try:
        caps = api_call("GET", f"/dedicated/server/{name}/install/compatibleTemplates")
        print("Available OS Templates:")
        for family, templates in caps.items():
            if templates:
                print(f"\n  {family}:")
                for t in templates:
                    print(f"    - {t}")
    except Exception:
        print("  Could not fetch templates (may require specific permissions)")


def cmd_grant():
    """Request new consumer key with full dedicated server permissions."""
    access_rules = [
        {"method": "GET", "path": "/dedicated/server/*"},
        {"method": "POST", "path": "/dedicated/server/*"},
        {"method": "PUT", "path": "/dedicated/server/*"},
        {"method": "DELETE", "path": "/dedicated/server/*"},
        {"method": "GET", "path": "/ip/*"},
        {"method": "PUT", "path": "/ip/*"},
        {"method": "GET", "path": "/dedicated/server"},
        {"method": "GET", "path": "/ip"},
        {"method": "GET", "path": "/auth/time"},
    ]
    body = json.dumps({
        "accessRules": access_rules,
        "redirection": "https://51.68.33.34/",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{ENDPOINT}/auth/credential",
        data=body,
        headers={
            "X-Ovh-Application": APP_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'═' * 60}")
    print(f"  OVH API — Consumer Key Authorization")
    print(f"{'═' * 60}")
    print(f"")
    print(f"  1. Open this URL in your browser:")
    print(f"")
    print(f"     {result['validationUrl']}")
    print(f"")
    print(f"  2. Log in with your OVH account and click 'Authorize'")
    print(f"")
    print(f"  3. After authorizing, update CONSUMER_KEY in this script:")
    print(f"")
    print(f"     New Consumer Key: {result['consumerKey']}")
    print(f"")
    print(f"  4. Replace the old value in scripts/ovh_manager.py line ~32")
    print(f"{'═' * 60}")
    print(f"")
    print(f"  Then run: python3 ovh_manager.py health")


def cmd_health():
    """Quick connectivity + API health check."""
    import subprocess

    print(f"OVH API Health Check")
    print(f"{'─' * 40}")

    # API auth test
    try:
        servers = api_call("GET", "/dedicated/server")
        print(f"  API Auth:       ✅ OK ({len(servers)} server(s))")
    except Exception as e:
        print(f"  API Auth:       ❌ Failed ({e})")
        return

    # Server state
    for name in servers:
        info = api_call("GET", f"/dedicated/server/{name}")
        state = info.get("state", "unknown")
        icon = "✅" if state == "ok" else "⚠️"
        print(f"  Server State:   {icon} {state}")
        print(f"  Server IP:      {info.get('ip', 'N/A')}")
        print(f"  OS:             {info.get('os', 'N/A')}")

    # Ping test
    try:
        result = subprocess.run(
            ["ping", "-c", "3", "-W", "2", OVH_IP],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            # Extract avg latency
            for line in result.stdout.splitlines():
                if "avg" in line:
                    avg = line.split("/")[4]
                    print(f"  Ping:           ✅ {avg}ms avg")
                    break
        else:
            print(f"  Ping:           ❌ No response")
    except Exception:
        print(f"  Ping:           ⚠️  Could not ping")


# ═══════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

COMMANDS = {
    "grant": cmd_grant,
    "servers": cmd_servers,
    "info": cmd_info,
    "stats": cmd_stats,
    "reboot": cmd_reboot,
    "tasks": cmd_tasks,
    "ips": cmd_ips,
    "reverse": cmd_reverse,
    "templates": cmd_templates,
    "health": cmd_health,
}

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python3 {sys.argv[0]} <command>")
        print(f"\nCommands:")
        for name, func in COMMANDS.items():
            print(f"  {name:12s}  {func.__doc__}")
        sys.exit(0)

    cmd = sys.argv[1]
    COMMANDS[cmd]()


if __name__ == "__main__":
    main()
