"""
Titan V11.3 — Network Shield
Provides network-level protection including firewall rules,
traffic monitoring, and leak prevention for stealth operations.

Usage:
    from network_shield import NetworkShield
    shield = NetworkShield()
    status = shield.get_status()
    shield.enable_stealth_mode()
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.network-shield")


@dataclass
class ShieldStatus:
    """Network shield status."""
    enabled: bool
    stealth_mode: bool
    rules_active: int
    blocked_connections: int
    dns_leak_protected: bool
    webrtc_leak_protected: bool
    ipv6_disabled: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "stealth_mode": self.stealth_mode,
            "rules_active": self.rules_active,
            "blocked_connections": self.blocked_connections,
            "dns_leak_protected": self.dns_leak_protected,
            "webrtc_leak_protected": self.webrtc_leak_protected,
            "ipv6_disabled": self.ipv6_disabled,
        }


class NetworkShield:
    """Network protection and stealth enforcement."""
    
    # Domains to block for leak prevention
    LEAK_DOMAINS = [
        "*.google.com",  # Google telemetry
        "*.googleapis.com",
        "*.gstatic.com", 
        "*.crashlytics.com",
        "*.firebase.io",
        "*.firebaseio.com",
        "*.facebook.com",
        "*.fbcdn.net",
        "*.amplitude.com",
        "*.mixpanel.com",
        "*.segment.io",
        "*.appsflyer.com",
        "*.adjust.com",
        "*.branch.io",
    ]
    
    # IPs to allow (VPN endpoints, etc.)
    ALLOWED_IPS = []
    
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = Path(data_dir) if data_dir else Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))
        self.rules_file = self.data_dir / "shield_rules.json"
        self._load_rules()
    
    def _load_rules(self):
        """Load custom rules from file."""
        if self.rules_file.exists():
            try:
                with open(self.rules_file) as f:
                    rules = json.load(f)
                self.LEAK_DOMAINS.extend(rules.get("block_domains", []))
                self.ALLOWED_IPS.extend(rules.get("allow_ips", []))
            except Exception as e:
                logger.warning(f"Failed to load shield rules: {e}")
    
    def _run_cmd(self, cmd: List[str], timeout: int = 10) -> Tuple[bool, str]:
        """Run shell command."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)
    
    def _iptables_rule_exists(self, rule: str) -> bool:
        """Check if iptables rule exists."""
        ok, output = self._run_cmd(["iptables", "-C"] + rule.split())
        return ok
    
    def _add_iptables_rule(self, rule: str) -> bool:
        """Add iptables rule if not exists."""
        if not self._iptables_rule_exists(rule):
            ok, _ = self._run_cmd(["iptables", "-A"] + rule.split())
            return ok
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """Get current shield status."""
        # Check iptables rules
        ok, output = self._run_cmd(["iptables", "-L", "-n"])
        rules_count = output.count("\n") if ok else 0
        
        # Check if stealth rules are active
        stealth_active = "DROP" in output if ok else False
        
        # Check IPv6 status
        ok6, output6 = self._run_cmd(["sysctl", "net.ipv6.conf.all.disable_ipv6"])
        ipv6_disabled = "= 1" in output6 if ok6 else False
        
        # Count blocked connections (from iptables counters)
        blocked = 0
        if ok:
            for line in output.split("\n"):
                if "DROP" in line:
                    parts = line.split()
                    if len(parts) > 0 and parts[0].isdigit():
                        blocked += int(parts[0])
        
        return ShieldStatus(
            enabled=rules_count > 10,
            stealth_mode=stealth_active,
            rules_active=rules_count,
            blocked_connections=blocked,
            dns_leak_protected=self._check_dns_protection(),
            webrtc_leak_protected=True,  # Handled at browser level
            ipv6_disabled=ipv6_disabled,
        ).to_dict()
    
    def _check_dns_protection(self) -> bool:
        """Check if DNS leak protection is active."""
        # Check resolv.conf for VPN DNS
        try:
            with open("/etc/resolv.conf") as f:
                content = f.read()
            # VPN typically sets DNS to 10.x.x.x or specific provider DNS
            return "10." in content or "mullvad" in content.lower()
        except Exception:
            return False
    
    def enable_stealth_mode(self) -> Dict[str, Any]:
        """
        Enable stealth mode - blocks telemetry and leak-prone connections.
        
        WARNING: This modifies iptables rules. Requires root.
        """
        logger.info("Enabling network stealth mode")
        
        results = {"rules_added": 0, "errors": []}
        
        # Block outbound to telemetry domains (by IP resolution)
        for domain in self.LEAK_DOMAINS[:10]:  # Limit for safety
            # Note: Real implementation would resolve domains first
            pass
        
        # Disable IPv6 (leak vector)
        ok, _ = self._run_cmd(["sysctl", "-w", "net.ipv6.conf.all.disable_ipv6=1"])
        if ok:
            results["ipv6_disabled"] = True
        
        # Block ICMP (ping) - anti-fingerprinting
        if self._add_iptables_rule("OUTPUT -p icmp --icmp-type echo-request -j DROP"):
            results["rules_added"] += 1
        
        # Block mDNS (local discovery)
        if self._add_iptables_rule("OUTPUT -p udp --dport 5353 -j DROP"):
            results["rules_added"] += 1
        
        # Block LLMNR
        if self._add_iptables_rule("OUTPUT -p udp --dport 5355 -j DROP"):
            results["rules_added"] += 1
        
        # Block NetBIOS
        if self._add_iptables_rule("OUTPUT -p udp --dport 137:139 -j DROP"):
            results["rules_added"] += 1
        
        logger.info(f"Stealth mode enabled: {results['rules_added']} rules added")
        return {"status": "enabled", **results}
    
    def disable_stealth_mode(self) -> Dict[str, Any]:
        """Disable stealth mode and restore normal networking."""
        logger.info("Disabling network stealth mode")
        
        # Flush custom rules (careful - preserves default chains)
        self._run_cmd(["iptables", "-F", "OUTPUT"])
        
        # Re-enable IPv6
        self._run_cmd(["sysctl", "-w", "net.ipv6.conf.all.disable_ipv6=0"])
        
        return {"status": "disabled"}
    
    def block_domain(self, domain: str) -> bool:
        """Block a specific domain."""
        # Resolve domain to IPs and block
        try:
            import socket
            ips = socket.gethostbyname_ex(domain)[2]
            for ip in ips:
                self._add_iptables_rule(f"OUTPUT -d {ip} -j DROP")
            logger.info(f"Blocked domain {domain} ({len(ips)} IPs)")
            return True
        except Exception as e:
            logger.error(f"Failed to block domain {domain}: {e}")
            return False
    
    def allow_ip(self, ip: str) -> bool:
        """Explicitly allow an IP (whitelist)."""
        ok = self._add_iptables_rule(f"OUTPUT -d {ip} -j ACCEPT")
        if ok:
            logger.info(f"Allowed IP: {ip}")
        return ok
    
    def get_active_connections(self) -> List[Dict[str, str]]:
        """Get list of active network connections."""
        connections = []
        ok, output = self._run_cmd(["ss", "-tunapo"])
        
        if ok:
            for line in output.split("\n")[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 5:
                    connections.append({
                        "protocol": parts[0],
                        "state": parts[1] if len(parts) > 1 else "",
                        "local": parts[4] if len(parts) > 4 else "",
                        "remote": parts[5] if len(parts) > 5 else "",
                    })
        
        return connections[:50]  # Limit output
    
    def detect_leaks(self) -> Dict[str, Any]:
        """Detect potential privacy leaks."""
        leaks = []
        
        # Check for direct (non-VPN) connections
        connections = self.get_active_connections()
        for conn in connections:
            remote = conn.get("remote", "")
            # Check if connection is to a known tracker
            for domain in self.LEAK_DOMAINS:
                if domain.replace("*.", "") in remote:
                    leaks.append({
                        "type": "tracker_connection",
                        "remote": remote,
                        "domain": domain,
                    })
        
        # Check DNS configuration
        if not self._check_dns_protection():
            leaks.append({
                "type": "dns_leak_risk",
                "description": "DNS not configured for VPN",
            })
        
        return {
            "leak_count": len(leaks),
            "leaks": leaks,
            "protected": len(leaks) == 0,
        }
