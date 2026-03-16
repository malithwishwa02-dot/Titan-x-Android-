"""
Titan V11.3 — Mullvad VPN CLI Wrapper
Provides programmatic control over Mullvad VPN for IP rotation
and geographic targeting in operations.

Wraps the mullvad CLI tool with Python interface.

Usage:
    from mullvad_vpn import MullvadVPN
    vpn = MullvadVPN()
    status = vpn.get_status()
    vpn.connect(country="us", city="nyc")
    vpn.disconnect()
"""

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.mullvad-vpn")


@dataclass
class VPNStatus:
    """VPN connection status."""
    connected: bool
    state: str  # connected, connecting, disconnected, error
    country: str
    city: str
    server: str
    ip: str
    protocol: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "connected": self.connected,
            "state": self.state,
            "country": self.country,
            "city": self.city,
            "server": self.server,
            "ip": self.ip,
            "protocol": self.protocol,
        }


class MullvadVPN:
    """Mullvad VPN control wrapper."""
    
    # Available relay locations (subset)
    LOCATIONS = {
        "us": {
            "name": "United States",
            "cities": ["nyc", "lax", "sea", "chi", "mia", "atl", "dal", "phx", "den", "slc"],
        },
        "gb": {
            "name": "United Kingdom", 
            "cities": ["lon", "man"],
        },
        "de": {
            "name": "Germany",
            "cities": ["fra", "ber", "dus"],
        },
        "nl": {
            "name": "Netherlands",
            "cities": ["ams"],
        },
        "se": {
            "name": "Sweden",
            "cities": ["sto", "got", "mma"],
        },
        "ch": {
            "name": "Switzerland",
            "cities": ["zrh"],
        },
        "ca": {
            "name": "Canada",
            "cities": ["tor", "van", "mtl"],
        },
        "au": {
            "name": "Australia",
            "cities": ["syd", "mel", "bne"],
        },
        "jp": {
            "name": "Japan",
            "cities": ["tyo", "osa"],
        },
        "sg": {
            "name": "Singapore",
            "cities": ["sin"],
        },
    }
    
    def __init__(self, cli_path: str = "mullvad"):
        self.cli_path = cli_path
        self._check_installed()
    
    def _check_installed(self) -> bool:
        """Check if Mullvad CLI is installed."""
        try:
            result = subprocess.run(
                [self.cli_path, "version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                logger.info(f"Mullvad CLI found: {result.stdout.strip()}")
                return True
        except FileNotFoundError:
            logger.warning("Mullvad CLI not found - VPN features disabled")
        except Exception as e:
            logger.warning(f"Mullvad CLI check failed: {e}")
        return False
    
    def _run_cmd(self, args: List[str], timeout: int = 30) -> Tuple[bool, str]:
        """Run Mullvad CLI command."""
        try:
            cmd = [self.cli_path] + args
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output.strip()
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except FileNotFoundError:
            return False, "Mullvad CLI not installed"
        except Exception as e:
            return False, str(e)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current VPN connection status."""
        ok, output = self._run_cmd(["status"])
        
        if not ok:
            return VPNStatus(
                connected=False, state="error", country="", city="",
                server="", ip="", protocol=""
            ).to_dict()
        
        # Parse status output
        connected = "Connected" in output
        state = "connected" if connected else "disconnected"
        
        country = ""
        city = ""
        server = ""
        ip = ""
        protocol = ""
        
        for line in output.split("\n"):
            line = line.strip()
            if "Location:" in line:
                # Format: "Location: City, Country"
                parts = line.replace("Location:", "").strip().split(",")
                if len(parts) >= 2:
                    city = parts[0].strip()
                    country = parts[1].strip()
            elif "Relay:" in line:
                server = line.replace("Relay:", "").strip()
            elif "IPv4:" in line:
                ip = line.replace("IPv4:", "").strip()
            elif "Protocol:" in line or "Tunnel protocol:" in line:
                protocol = line.split(":")[-1].strip()
        
        return VPNStatus(
            connected=connected, state=state, country=country, city=city,
            server=server, ip=ip, protocol=protocol
        ).to_dict()
    
    def connect(self, country: str = "", city: str = "") -> Dict[str, Any]:
        """
        Connect to VPN.
        
        Args:
            country: Country code (us, gb, de, etc.)
            city: City code (nyc, lon, fra, etc.)
        """
        # Set relay location if specified
        if country:
            relay_args = ["relay", "set", "location", country]
            if city:
                relay_args.append(city)
            ok, output = self._run_cmd(relay_args)
            if not ok:
                logger.warning(f"Failed to set relay location: {output}")
        
        # Connect
        ok, output = self._run_cmd(["connect"])
        
        if not ok:
            return {"status": "error", "message": output}
        
        # Wait for connection
        for _ in range(10):
            time.sleep(1)
            status = self.get_status()
            if status.get("connected"):
                logger.info(f"VPN connected: {status.get('country')} / {status.get('city')}")
                return {"status": "connected", **status}
        
        return {"status": "timeout", "message": "Connection timed out"}
    
    def disconnect(self) -> Dict[str, Any]:
        """Disconnect from VPN."""
        ok, output = self._run_cmd(["disconnect"])
        
        if not ok:
            return {"status": "error", "message": output}
        
        # Wait for disconnection
        for _ in range(5):
            time.sleep(0.5)
            status = self.get_status()
            if not status.get("connected"):
                logger.info("VPN disconnected")
                return {"status": "disconnected"}
        
        return {"status": "disconnected"}
    
    def reconnect(self) -> Dict[str, Any]:
        """Reconnect (get new IP)."""
        ok, output = self._run_cmd(["reconnect"])
        
        if not ok:
            return {"status": "error", "message": output}
        
        # Wait for reconnection
        for _ in range(10):
            time.sleep(1)
            status = self.get_status()
            if status.get("connected"):
                return {"status": "reconnected", **status}
        
        return {"status": "timeout"}
    
    def list_relays(self, country: str = "") -> Dict[str, Any]:
        """List available relay servers."""
        ok, output = self._run_cmd(["relay", "list"])
        
        if not ok:
            return {"relays": [], "error": output}
        
        # Parse relay list (simplified)
        relays = []
        current_country = ""
        
        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Country lines are not indented
            if not line.startswith("-") and not line.startswith("│"):
                current_country = line
            elif "-" in line and current_country:
                if not country or country.lower() in current_country.lower():
                    relays.append({
                        "country": current_country,
                        "server": line.strip("- │"),
                    })
        
        return {"relays": relays[:50], "total": len(relays)}  # Limit output
    
    def set_protocol(self, protocol: str = "wireguard") -> Dict[str, Any]:
        """Set tunnel protocol (wireguard or openvpn)."""
        ok, output = self._run_cmd(["tunnel", protocol, "set", "quantum-resistant", "on"])
        
        if protocol == "wireguard":
            ok, output = self._run_cmd(["relay", "set", "tunnel-protocol", "wireguard"])
        else:
            ok, output = self._run_cmd(["relay", "set", "tunnel-protocol", "openvpn"])
        
        return {"status": "ok" if ok else "error", "protocol": protocol, "message": output}
    
    def get_account(self) -> Dict[str, Any]:
        """Get account info."""
        ok, output = self._run_cmd(["account", "get"])
        
        if not ok:
            return {"logged_in": False, "error": output}
        
        # Parse account info
        account = {"logged_in": True}
        for line in output.split("\n"):
            if "Account:" in line:
                account["account_number"] = line.split(":")[-1].strip()
            elif "Expires" in line:
                account["expires"] = line.split(":")[-1].strip()
        
        return account
    
    def is_connected(self) -> bool:
        """Quick check if VPN is connected."""
        status = self.get_status()
        return status.get("connected", False)
    
    def get_available_locations(self) -> Dict[str, Any]:
        """Get available locations."""
        return {"locations": self.LOCATIONS}


def get_mullvad_status() -> Dict[str, Any]:
    """Convenience function for quick status check."""
    try:
        vpn = MullvadVPN()
        return vpn.get_status()
    except Exception as e:
        return {"connected": False, "state": "error", "error": str(e)}
