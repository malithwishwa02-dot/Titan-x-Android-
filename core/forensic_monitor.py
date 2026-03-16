"""
Titan V11.3 — Forensic Monitor
System-level forensic scanning to detect emulator/VM artifacts,
rooting indicators, and stealth patch effectiveness.

Runs non-invasive checks on the host system and connected Android devices
to identify detection vectors that could expose the virtualized environment.

Usage:
    from forensic_monitor import ForensicMonitor
    monitor = ForensicMonitor()
    result = monitor.scan_system_state()
    print(result["risk_score"], result["findings"])
"""

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.forensic-monitor")


@dataclass
class Finding:
    """Single forensic finding."""
    category: str  # process, file, network, device, memory
    severity: str  # critical, high, medium, low, info
    name: str
    description: str
    evidence: str = ""
    remediation: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "name": self.name,
            "description": self.description,
            "evidence": self.evidence,
            "remediation": self.remediation,
        }


@dataclass
class ScanResult:
    """Complete forensic scan result."""
    risk_score: int  # 0-100, higher = more risk
    risk_level: str  # critical, high, medium, low
    total_findings: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    findings: List[Finding] = field(default_factory=list)
    scan_time_ms: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "total_findings": self.total_findings,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "findings": [f.to_dict() for f in self.findings],
            "scan_time_ms": self.scan_time_ms,
        }


class ForensicMonitor:
    """System forensic scanner for detection vector analysis."""
    
    # Suspicious process patterns
    SUSPICIOUS_PROCESSES = [
        ("frida", "critical", "Frida instrumentation framework detected"),
        ("magisk", "high", "Magisk root framework detected"),
        ("supersu", "high", "SuperSU root framework detected"),
        ("xposed", "high", "Xposed framework detected"),
        ("substrate", "high", "Cydia Substrate detected"),
        ("tcpdump", "medium", "Network capture tool running"),
        ("wireshark", "medium", "Network analysis tool running"),
        ("burp", "medium", "Proxy/interception tool running"),
        ("mitmproxy", "medium", "MITM proxy detected"),
        ("charles", "medium", "Charles proxy detected"),
        ("objection", "high", "Objection toolkit detected"),
        ("gdb", "medium", "Debugger attached"),
        ("lldb", "medium", "LLDB debugger detected"),
        ("strace", "medium", "System call tracer detected"),
        ("ltrace", "medium", "Library call tracer detected"),
    ]
    
    # Suspicious file paths
    SUSPICIOUS_FILES = [
        ("/data/local/tmp/frida", "critical", "Frida server binary"),
        ("/system/xbin/su", "high", "SU binary in system"),
        ("/system/bin/su", "high", "SU binary in system"),
        ("/sbin/su", "high", "SU binary in sbin"),
        ("/data/adb/magisk", "high", "Magisk data directory"),
        ("/data/data/com.topjohnwu.magisk", "high", "Magisk app data"),
        ("/system/app/Superuser.apk", "high", "SuperUser APK"),
        ("/system/etc/init.d", "medium", "Init.d scripts (root indicator)"),
        ("/data/local/tmp/re.frida.server", "critical", "Frida server"),
    ]
    
    # Network indicators
    SUSPICIOUS_PORTS = [
        (27042, "critical", "Frida default port"),
        (27043, "critical", "Frida gadget port"),
        (8080, "low", "Common proxy port"),
        (8888, "low", "Charles proxy port"),
        (9090, "low", "Burp proxy port"),
    ]
    
    def __init__(self, adb_target: Optional[str] = None):
        self.adb_target = adb_target
        self.findings: List[Finding] = []
    
    def _run_cmd(self, cmd: List[str], timeout: int = 10) -> Tuple[bool, str]:
        """Run shell command safely."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return True, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as e:
            return False, str(e)
    
    def _adb_shell(self, cmd: str, timeout: int = 10) -> Tuple[bool, str]:
        """Run ADB shell command."""
        if not self.adb_target:
            return False, "no_target"
        adb_cmd = ["adb", "-s", self.adb_target, "shell", cmd]
        return self._run_cmd(adb_cmd, timeout)
    
    def _add_finding(self, category: str, severity: str, name: str,
                     description: str, evidence: str = "", remediation: str = ""):
        """Add a finding to the list."""
        self.findings.append(Finding(
            category=category,
            severity=severity,
            name=name,
            description=description,
            evidence=evidence,
            remediation=remediation,
        ))
    
    def scan_host_processes(self) -> int:
        """Scan host for suspicious processes."""
        count = 0
        ok, output = self._run_cmd(["ps", "aux"])
        if not ok:
            return 0
        
        output_lower = output.lower()
        for pattern, severity, desc in self.SUSPICIOUS_PROCESSES:
            if pattern in output_lower:
                self._add_finding(
                    "process", severity, f"suspicious_process_{pattern}",
                    desc, f"Pattern '{pattern}' found in process list",
                    f"Kill process containing '{pattern}'"
                )
                count += 1
        
        return count
    
    def scan_host_files(self) -> int:
        """Scan host for suspicious files."""
        count = 0
        for path, severity, desc in self.SUSPICIOUS_FILES:
            if os.path.exists(path):
                self._add_finding(
                    "file", severity, f"suspicious_file_{Path(path).name}",
                    desc, f"File exists: {path}",
                    f"Remove or hide: {path}"
                )
                count += 1
        return count
    
    def scan_host_network(self) -> int:
        """Scan host network for suspicious listeners."""
        count = 0
        ok, output = self._run_cmd(["ss", "-tlnp"])
        if not ok:
            ok, output = self._run_cmd(["netstat", "-tlnp"])
        if not ok:
            return 0
        
        for port, severity, desc in self.SUSPICIOUS_PORTS:
            if f":{port}" in output:
                self._add_finding(
                    "network", severity, f"suspicious_port_{port}",
                    desc, f"Port {port} is listening",
                    f"Close listener on port {port}"
                )
                count += 1
        
        return count
    
    def scan_device_root(self) -> int:
        """Scan Android device for root indicators."""
        if not self.adb_target:
            return 0
        
        count = 0
        
        # Check for su binary
        for path in ["/system/xbin/su", "/system/bin/su", "/sbin/su", "/su/bin/su"]:
            ok, output = self._adb_shell(f"ls {path} 2>/dev/null")
            if ok and path in output:
                self._add_finding(
                    "device", "high", "root_su_binary",
                    f"SU binary found at {path}", path,
                    "Mount-bind to /dev/null"
                )
                count += 1
        
        # Check for Magisk
        ok, output = self._adb_shell("ls /data/adb/magisk 2>/dev/null")
        if ok and "magisk" in output.lower():
            self._add_finding(
                "device", "high", "root_magisk",
                "Magisk installation detected", output.strip(),
                "Uninstall Magisk or use MagiskHide"
            )
            count += 1
        
        # Check ro.debuggable
        ok, output = self._adb_shell("getprop ro.debuggable")
        if ok and output.strip() == "1":
            self._add_finding(
                "device", "medium", "debuggable_build",
                "Device is debuggable (userdebug build)", "ro.debuggable=1",
                "Use resetprop to set ro.debuggable=0"
            )
            count += 1
        
        # Check build type
        ok, output = self._adb_shell("getprop ro.build.type")
        if ok and "userdebug" in output.lower():
            self._add_finding(
                "device", "medium", "userdebug_build",
                "Userdebug build detected", output.strip(),
                "Use resetprop to set ro.build.type=user"
            )
            count += 1
        
        # Check test-keys
        ok, output = self._adb_shell("getprop ro.build.tags")
        if ok and "test-keys" in output.lower():
            self._add_finding(
                "device", "medium", "test_keys",
                "Test-keys build detected", output.strip(),
                "Use resetprop to set ro.build.tags=release-keys"
            )
            count += 1
        
        return count
    
    def scan_device_emulator(self) -> int:
        """Scan for emulator/VM indicators on device."""
        if not self.adb_target:
            return 0
        
        count = 0
        
        # Check for emulator indicators in build props
        emulator_indicators = [
            ("ro.product.device", ["generic", "vsoc", "emulator", "sdk"]),
            ("ro.product.model", ["sdk", "emulator", "android sdk"]),
            ("ro.hardware", ["goldfish", "ranchu", "vsoc"]),
            ("ro.kernel.qemu", ["1"]),
        ]
        
        for prop, patterns in emulator_indicators:
            ok, output = self._adb_shell(f"getprop {prop}")
            if ok:
                output_lower = output.lower().strip()
                for pattern in patterns:
                    if pattern in output_lower:
                        self._add_finding(
                            "device", "high", f"emulator_{prop.replace('.', '_')}",
                            f"Emulator indicator in {prop}", f"{prop}={output.strip()}",
                            f"Use resetprop to override {prop}"
                        )
                        count += 1
                        break
        
        # Check for qemu files
        qemu_files = [
            "/dev/socket/qemud",
            "/dev/qemu_pipe",
            "/system/lib/libc_malloc_debug_qemu.so",
        ]
        for path in qemu_files:
            ok, output = self._adb_shell(f"ls {path} 2>/dev/null")
            if ok and path in output:
                self._add_finding(
                    "device", "high", f"qemu_file_{Path(path).name}",
                    f"QEMU file detected: {path}", path,
                    "Cannot remediate - hardware emulation artifact"
                )
                count += 1
        
        return count
    
    def scan_device_frida(self) -> int:
        """Scan device for Frida indicators."""
        if not self.adb_target:
            return 0
        
        count = 0
        
        # Check for Frida server
        frida_paths = [
            "/data/local/tmp/frida-server",
            "/data/local/tmp/re.frida.server",
            "/data/local/tmp/frida",
        ]
        for path in frida_paths:
            ok, output = self._adb_shell(f"ls {path} 2>/dev/null")
            if ok and "frida" in output.lower():
                self._add_finding(
                    "device", "critical", "frida_server",
                    f"Frida server binary at {path}", path,
                    f"Remove: rm {path}"
                )
                count += 1
        
        # Check for Frida listening port
        ok, output = self._adb_shell("netstat -tlnp 2>/dev/null | grep 27042")
        if ok and "27042" in output:
            self._add_finding(
                "device", "critical", "frida_port",
                "Frida default port 27042 listening", output.strip(),
                "Kill Frida server process"
            )
            count += 1
        
        return count
    
    def scan_device_integrity(self) -> int:
        """Scan device integrity indicators."""
        if not self.adb_target:
            return 0
        
        count = 0
        
        # Check verified boot state
        ok, output = self._adb_shell("getprop ro.boot.verifiedbootstate")
        if ok and output.strip() not in ["green", ""]:
            self._add_finding(
                "device", "medium", "verified_boot_not_green",
                f"Verified boot state: {output.strip()}", output.strip(),
                "Use resetprop to set ro.boot.verifiedbootstate=green"
            )
            count += 1
        
        # Check bootloader lock state
        ok, output = self._adb_shell("getprop ro.boot.flash.locked")
        if ok and output.strip() != "1":
            self._add_finding(
                "device", "medium", "bootloader_unlocked",
                "Bootloader appears unlocked", f"ro.boot.flash.locked={output.strip()}",
                "Use resetprop to set ro.boot.flash.locked=1"
            )
            count += 1
        
        return count
    
    def scan_system_state(self) -> Dict[str, Any]:
        """
        Run full system forensic scan.
        
        Returns comprehensive scan result with risk score and findings.
        """
        import time
        start_time = time.time()
        
        self.findings = []  # Reset findings
        
        # Run all scans
        self.scan_host_processes()
        self.scan_host_files()
        self.scan_host_network()
        self.scan_device_root()
        self.scan_device_emulator()
        self.scan_device_frida()
        self.scan_device_integrity()
        
        # Calculate risk score
        critical_count = sum(1 for f in self.findings if f.severity == "critical")
        high_count = sum(1 for f in self.findings if f.severity == "high")
        medium_count = sum(1 for f in self.findings if f.severity == "medium")
        low_count = sum(1 for f in self.findings if f.severity == "low")
        
        # Weighted risk score
        risk_score = min(100, (
            critical_count * 25 +
            high_count * 15 +
            medium_count * 5 +
            low_count * 1
        ))
        
        # Risk level
        if risk_score >= 75:
            risk_level = "critical"
        elif risk_score >= 50:
            risk_level = "high"
        elif risk_score >= 25:
            risk_level = "medium"
        else:
            risk_level = "low"
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        result = ScanResult(
            risk_score=risk_score,
            risk_level=risk_level,
            total_findings=len(self.findings),
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            findings=self.findings,
            scan_time_ms=elapsed_ms,
        )
        
        logger.info(f"Forensic scan complete: {result.risk_level} risk ({result.risk_score}/100), {result.total_findings} findings in {elapsed_ms}ms")
        
        return result.to_dict()
    
    def quick_scan(self) -> Dict[str, Any]:
        """Quick scan - host only, no device checks."""
        import time
        start_time = time.time()
        
        self.findings = []
        self.scan_host_processes()
        self.scan_host_network()
        
        critical = sum(1 for f in self.findings if f.severity == "critical")
        high = sum(1 for f in self.findings if f.severity == "high")
        
        return {
            "risk_score": min(100, critical * 25 + high * 15),
            "findings_count": len(self.findings),
            "critical_count": critical,
            "high_count": high,
            "scan_time_ms": int((time.time() - start_time) * 1000),
        }
