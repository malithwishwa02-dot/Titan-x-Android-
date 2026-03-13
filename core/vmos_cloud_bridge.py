"""
Titan V11.3 — VMOS Cloud API Bridge
Wraps VMOS Cloud OpenAPI for managing cloud Android instances.
Provides the same interface patterns as device_manager.py so Titan API
can route commands through either Redroid (direct ADB) or VMOS Cloud.

API Docs: https://cloud.vmoscloud.com/vmoscloud/doc/en/server/OpenAPI.html

Usage:
    bridge = VMOSCloudBridge(api_key="...", api_secret="...")
    devices = await bridge.list_instances()
    await bridge.update_device_props(pad_code, {...})
    await bridge.inject_contacts(pad_code, [...])
    result = await bridge.exec_shell(pad_code, "ls /data")
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.vmos-bridge")

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

VMOS_API_BASE = os.environ.get("VMOS_API_BASE", "https://api.vmoscloud.com")
VMOS_API_KEY = os.environ.get("VMOS_API_KEY", "")
VMOS_API_SECRET = os.environ.get("VMOS_API_SECRET", "")
VMOS_API_HOST = os.environ.get("VMOS_API_HOST", "api.vmoscloud.com")
VMOS_SERVICE = "armcloud-paas"

TASK_POLL_INTERVAL = 2.0   # seconds between task status polls
TASK_POLL_TIMEOUT = 60.0   # max seconds to wait for async task


# ═══════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class VMOSInstance:
    pad_code: str = ""
    status: str = ""          # running, stopped, etc.
    device_ip: str = ""
    android_version: str = ""
    image_id: str = ""
    device_level: str = ""    # m2-6, q2-4, etc.
    model: str = ""
    brand: str = ""
    online: bool = False

    def to_dict(self) -> dict:
        return {
            "pad_code": self.pad_code,
            "status": self.status,
            "device_ip": self.device_ip,
            "android_version": self.android_version,
            "image_id": self.image_id,
            "device_level": self.device_level,
            "model": self.model,
            "brand": self.brand,
            "online": self.online,
        }


@dataclass
class VMOSTaskResult:
    task_id: int = 0
    pad_code: str = ""
    status: int = 0           # 1=pending, 2=running, 3=success, 4=failed
    result: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 3

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "pad_code": self.pad_code,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "ok": self.ok,
        }


# ═══════════════════════════════════════════════════════════════════════
# VMOS CLOUD API CLIENT
# ═══════════════════════════════════════════════════════════════════════

class VMOSCloudBridge:
    """Client for VMOS Cloud OpenAPI with async task polling."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        base_url: str = "",
    ):
        self.api_key = api_key or VMOS_API_KEY
        self.api_secret = api_secret or VMOS_API_SECRET
        self.base_url = (base_url or VMOS_API_BASE).rstrip("/")
        self._http = None  # lazy init

    # ─── HTTP ────────────────────────────────────────────────────────

    def _get_http(self):
        if self._http is None:
            try:
                import httpx
                self._http = httpx.AsyncClient(timeout=30.0)
            except ImportError:
                import aiohttp
                self._http = None  # will use aiohttp session
        return self._http

    def _sign_request(self, body_str: str) -> Dict[str, str]:
        """Generate VMOS Cloud HMAC-SHA256 authentication headers.
        Implements the exact signing algorithm from VMOS Cloud docs."""
        from datetime import datetime, timezone as tz
        x_date = datetime.now(tz.utc).strftime("%Y%m%dT%H%M%SZ")
        short_date = x_date[:8]
        content_type = "application/json;charset=UTF-8"
        signed_headers = "content-type;host;x-content-sha256;x-date"
        host = VMOS_API_HOST

        body_bytes = body_str.encode("utf-8")
        x_content_sha256 = hashlib.sha256(body_bytes).hexdigest()

        canonical = (
            f"host:{host}\n"
            f"x-date:{x_date}\n"
            f"content-type:{content_type}\n"
            f"signedHeaders:{signed_headers}\n"
            f"x-content-sha256:{x_content_sha256}"
        )
        hash_canonical = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        credential_scope = f"{short_date}/{VMOS_SERVICE}/request"
        string_to_sign = f"HMAC-SHA256\n{x_date}\n{credential_scope}\n{hash_canonical}"

        k_date = hmac.new(self.api_secret.encode("utf-8"), short_date.encode("utf-8"), hashlib.sha256).digest()
        k_service = hmac.new(k_date, VMOS_SERVICE.encode("utf-8"), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"request", hashlib.sha256).digest()
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        auth = f"HMAC-SHA256 Credential={self.api_key}, SignedHeaders={signed_headers}, Signature={signature}"
        return {
            "content-type": content_type,
            "x-host": host,
            "x-date": x_date,
            "authorization": auth,
        }

    async def _post(self, path: str, body: dict) -> dict:
        """POST to VMOS Cloud API with HMAC-SHA256 auth.
        Uses http.client as primary transport — urllib/httpx get 500s from
        TencentEdgeOne CDN due to header handling differences.
        """
        body_str = json.dumps(body, separators=(",", ":"))
        headers = self._sign_request(body_str)

        # http.client works reliably through TencentEdgeOne CDN
        import http.client as _hc
        try:
            conn = _hc.HTTPSConnection(VMOS_API_HOST, timeout=30)
            conn.request("POST", path, body=body_str.encode("utf-8"), headers=headers)
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8")
            conn.close()
            data = json.loads(raw)
        except Exception as e:
            logger.warning(f"VMOS API http.client failed: {path} -> {e}")
            # Fallback to httpx/urllib
            url = f"{self.base_url}{path}"
            try:
                import httpx
                client = self._get_http()
                if client:
                    resp = await client.post(url, content=body_str.encode("utf-8"), headers=headers)
                    data = resp.json()
                else:
                    raise ImportError("httpx client not available")
            except ImportError:
                import urllib.request
                req = urllib.request.Request(url, data=body_str.encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())

        if data.get("code") != 200:
            logger.warning(f"VMOS API error: {path} -> {data.get('code')} {data.get('msg')}")
        return data

    # ─── TASK POLLING ────────────────────────────────────────────────

    async def _wait_for_task(self, task_id: int, pad_code: str = "") -> VMOSTaskResult:
        """Poll task status until complete or timeout."""
        start = time.time()
        while time.time() - start < TASK_POLL_TIMEOUT:
            data = await self._post("/vcpcloud/api/padApi/padTaskDetail", {
                "taskIds": [task_id]
            })
            tasks = data.get("data", [])
            if tasks:
                t = tasks[0]
                status = t.get("taskStatus", 0)
                if status >= 3:  # 3=success, 4+=failed
                    return VMOSTaskResult(
                        task_id=task_id,
                        pad_code=t.get("padCode", pad_code),
                        status=status,
                        result=t.get("taskResult", ""),
                        error=t.get("errorMsg", "") or t.get("taskContent", ""),
                    )
            await asyncio.sleep(TASK_POLL_INTERVAL)

        return VMOSTaskResult(
            task_id=task_id, pad_code=pad_code,
            status=4, error="Task poll timeout"
        )

    async def _submit_and_wait(self, path: str, body: dict) -> List[VMOSTaskResult]:
        """Submit an API call that returns taskIds, wait for all to complete."""
        data = await self._post(path, body)
        results = []
        for item in data.get("data", []):
            tid = item.get("taskId", 0)
            pc = item.get("padCode", "")
            if tid:
                r = await self._wait_for_task(tid, pc)
                results.append(r)
            else:
                results.append(VMOSTaskResult(
                    pad_code=pc, status=4, error="No taskId returned"
                ))
        return results

    # ─── INSTANCE MANAGEMENT ─────────────────────────────────────────

    async def list_instances(self, page: int = 1, rows: int = 50) -> List[VMOSInstance]:
        """Get list of all VMOS Cloud instances."""
        data = await self._post("/vcpcloud/api/padApi/infos", {
            "page": page, "rows": rows
        })
        instances = []
        for p in data.get("data", {}).get("pageData", []):
            instances.append(VMOSInstance(
                pad_code=p.get("padCode", ""),
                status="running" if p.get("padStatus") == 10 else "stopped",
                device_ip=p.get("deviceIp", ""),
                android_version="",
                image_id=p.get("imageId", ""),
                device_level=p.get("padGrade", p.get("deviceLevel", "")),
                online=bool(p.get("online")),
            ))
        return instances

    async def get_instance_details(self, pad_code: str) -> dict:
        """Get detailed properties of a specific instance."""
        data = await self._post("/vcpcloud/api/padApi/padDetails", {
            "page": 1, "rows": 1, "padCodes": [pad_code]
        })
        pages = data.get("data", {}).get("pageData", [])
        return pages[0] if pages else {}

    async def get_instance_properties(self, pad_code: str) -> dict:
        """Get all system/modem/settings properties for an instance."""
        data = await self._post("/vcpcloud/api/padApi/padProperties", {
            "padCode": pad_code
        })
        return data.get("data", {})

    async def restart_instance(self, pad_code: str) -> VMOSTaskResult:
        """Restart a VMOS Cloud instance."""
        results = await self._submit_and_wait("/vcpcloud/api/padApi/restart", {
            "padCodes": [pad_code]
        })
        return results[0] if results else VMOSTaskResult(status=4, error="No result")

    async def screenshot(self, pad_code: str, fmt: str = "png") -> Optional[str]:
        """Get screenshot URL for an instance."""
        data = await self._post("/vcpcloud/api/padApi/getLongGenerateUrl", {
            "padCodes": [pad_code], "format": fmt
        })
        items = data.get("data", [])
        if items and items[0].get("success"):
            return items[0].get("url")
        return None

    # ─── DEVICE FINGERPRINT / STEALTH ─────────────────────────────────

    async def update_android_props(self, pad_code: str, props: Dict[str, str]) -> VMOSTaskResult:
        """
        Set Android ro.* properties for device fingerprint spoofing.
        Uses padCode (singular) + props (dict) format per VMOS Cloud API.

        Example props:
            {
                "ro.product.brand": "samsung",
                "ro.product.model": "SM-S928U",
                "ro.build.fingerprint": "samsung/...",
                "persist.sys.cloud.imeinum": "351234567890123",
                "persist.sys.cloud.iccidnum": "89014...",
                ...
            }
        """
        data = await self._post(
            "/vcpcloud/api/padApi/updatePadAndroidProp",
            {"padCode": pad_code, "props": props}
        )
        task_id = 0
        raw_data = data.get("data", {})
        if isinstance(raw_data, dict):
            task_id = raw_data.get("taskId", 0)
        if task_id:
            return await self._wait_for_task(task_id, pad_code)
        # If no taskId, check if it was a direct success
        if data.get("code") == 200:
            return VMOSTaskResult(pad_code=pad_code, status=3, result="ok")
        return VMOSTaskResult(status=4, error=data.get("msg", "No result"))

    async def update_device_identity(
        self,
        pad_code: str,
        brand: str = "samsung",
        model: str = "SM-S928U",
        device: str = "e3q",
        fingerprint: str = "",
        android_version: str = "15",
        sdk_version: str = "35",
        security_patch: str = "2026-02-05",
        imei: str = "",
        iccid: str = "",
        imsi: str = "",
        phone_number: str = "",
        android_id: str = "",
        carrier_mcc: str = "310",
        carrier_mnc: str = "260",
    ) -> VMOSTaskResult:
        """High-level device identity update using VMOS Cloud native APIs."""
        props = {
            "ro.product.brand": brand,
            "ro.product.model": model,
            "ro.product.device": device,
            "ro.product.name": device,
            "ro.product.manufacturer": brand,
            "ro.product.board": device,
            "ro.build.product": device,
            "ro.hardware": device,
            "ro.build.version.release": android_version,
            "ro.build.version.sdk": sdk_version,
            "ro.build.version.security_patch": security_patch,
            "ro.build.type": "user",
            "ro.build.tags": "release-keys",
        }
        if fingerprint:
            props["ro.build.fingerprint"] = fingerprint
            props["ro.odm.build.fingerprint"] = fingerprint
            props["ro.product.build.fingerprint"] = fingerprint
            props["ro.system.build.fingerprint"] = fingerprint
            props["ro.vendor.build.fingerprint"] = fingerprint

        if imei:
            props["persist.sys.cloud.imeinum"] = imei
        if iccid:
            props["persist.sys.cloud.iccidnum"] = iccid
        if imsi:
            props["persist.sys.cloud.imsinum"] = imsi
        if phone_number:
            props["persist.sys.cloud.phonenum"] = phone_number
        if android_id:
            props["ro.sys.cloud.android_id"] = android_id
        if carrier_mcc and carrier_mnc:
            props["persist.sys.cloud.mobileinfo"] = f"{carrier_mcc},{carrier_mnc}"

        return await self.update_android_props(pad_code, props)

    async def update_sim(self, pad_code: str, imei: str, iccid: str = "",
                         imsi: str = "", phone: str = "") -> VMOSTaskResult:
        """Update SIM card information."""
        body = {"padCodes": [pad_code], "imei": imei}
        if iccid:
            body["iccid"] = iccid
        if imsi:
            body["imsi"] = imsi
        if phone:
            body["phoneNum"] = phone
        results = await self._submit_and_wait("/vcpcloud/api/padApi/updateSIM", body)
        return results[0] if results else VMOSTaskResult(status=4, error="No result")

    # ─── GPS / LOCATION ──────────────────────────────────────────────

    async def set_gps(self, pad_code: str, lat: float, lon: float,
                      altitude: float = 15.0, speed: float = 0.0) -> VMOSTaskResult:
        """Inject GPS coordinates into the device."""
        props = {
            "persist.sys.cloud.gps.lat": str(lat),
            "persist.sys.cloud.gps.lon": str(lon),
            "persist.sys.cloud.gps.altitude": str(altitude),
            "persist.sys.cloud.gps.speed": str(speed),
            "persist.sys.cloud.gps.bearing": "0",
        }
        return await self.update_android_props(pad_code, props)

    # ─── WIFI SIMULATION ─────────────────────────────────────────────

    async def set_wifi(self, pad_code: str, ssid: str = "NETGEAR72-5G",
                       mac: str = "02:00:00:00:00:01", ip: str = "192.168.1.100",
                       gateway: str = "192.168.1.1") -> VMOSTaskResult:
        """Configure WiFi network simulation."""
        data = await self._post("/vcpcloud/api/padApi/setWifiList", {
            "padCodes": [pad_code],
            "wifiJsonList": [{
                "SSID": ssid,
                "BSSID": mac.replace("02:", "A4:"),
                "MAC": mac,
                "IP": ip,
                "gateway": gateway,
                "DNS1": gateway,
                "DNS2": "8.8.8.8",
                "frequency": 5180,
                "linkSpeed": 866,
                "level": -45,
            }]
        })
        tasks = data.get("data", [])
        if tasks and tasks[0].get("taskId"):
            return await self._wait_for_task(tasks[0]["taskId"], pad_code)
        return VMOSTaskResult(pad_code=pad_code, status=3, result="ok")

    # ─── PROXY ────────────────────────────────────────────────────────

    async def set_proxy(self, pad_code: str, ip: str, port: int,
                        username: str = "", password: str = "",
                        proxy_type: str = "socks5") -> VMOSTaskResult:
        """Set network proxy for the instance."""
        body = {
            "padCodes": [pad_code],
            "ip": ip,
            "port": port,
            "enable": True,
            "sUoT": proxy_type == "socks5",
        }
        if username:
            body["account"] = username
        if password:
            body["password"] = password
        results = await self._submit_and_wait("/vcpcloud/api/padApi/setProxy", body)
        return results[0] if results else VMOSTaskResult(status=4, error="No result")

    # ─── CONTACTS / CALL LOGS / SMS ──────────────────────────────────

    async def inject_contacts(self, pad_code: str, contacts: List[Dict[str, str]]) -> VMOSTaskResult:
        """
        Inject contacts into the device.
        Each contact: {"firstName": "...", "phone": "...", "email": "..."}
        """
        results = await self._submit_and_wait("/vcpcloud/api/padApi/updateContacts", {
            "padCodes": [pad_code],
            "info": contacts,
        })
        return results[0] if results else VMOSTaskResult(status=4, error="No result")

    async def inject_call_logs(self, pad_code: str, calls: List[Dict[str, Any]]) -> VMOSTaskResult:
        """
        Inject call log records.
        Each call: {"number": "+1...", "inputType": 1|2|3, "duration": 30, "timeString": "2026-01-15 14:00:09"}
        inputType: 1=incoming, 2=outgoing, 3=missed
        """
        results = await self._submit_and_wait("/vcpcloud/api/padApi/addPhoneRecord", {
            "padCodes": [pad_code],
            "callRecords": calls,
        })
        return results[0] if results else VMOSTaskResult(status=4, error="No result")

    async def send_sms(self, pad_code: str, sender: str, message: str) -> VMOSTaskResult:
        """Simulate receiving an SMS on the device via content provider insert."""
        ts = int(time.time() * 1000)
        safe_sender = sender.replace("'", "")
        safe_message = message.replace("'", "")
        cmd = (
            f"content insert --uri content://sms "
            f"--bind address:s:'{safe_sender}' "
            f"--bind body:s:'{safe_message}' "
            f"--bind type:i:1 "
            f"--bind date:l:{ts} "
            f"--bind read:i:1"
        )
        return await self.exec_shell(pad_code, cmd)

    # ─── SHELL / ADB COMMANDS ────────────────────────────────────────

    async def exec_shell(self, pad_code: str, command: str) -> VMOSTaskResult:
        """
        Execute arbitrary shell command on the device (async).
        This is the key API for Chrome data injection, wallet creation, etc.
        """
        results = await self._submit_and_wait("/vcpcloud/api/padApi/asyncCmd", {
            "padCodes": [pad_code],
            "scriptContent": command,
        })
        return results[0] if results else VMOSTaskResult(status=4, error="No result")

    async def exec_shell_batch(self, pad_codes: List[str], command: str) -> List[VMOSTaskResult]:
        """Execute shell command on multiple devices simultaneously."""
        return await self._submit_and_wait("/vcpcloud/api/padApi/asyncCmd", {
            "padCodes": pad_codes,
            "scriptContent": command,
        })

    async def get_shell_result(self, task_id: int) -> VMOSTaskResult:
        """Get result of a previously submitted shell command."""
        data = await self._post("/vcpcloud/api/padApi/executeScriptInfo", {
            "taskIds": [task_id]
        })
        items = data.get("data", [])
        if items:
            t = items[0]
            return VMOSTaskResult(
                task_id=t.get("taskId", task_id),
                pad_code=t.get("padCode", ""),
                status=t.get("taskStatus", 0),
                result=t.get("taskResult", ""),
                error=t.get("errorMsg", ""),
            )
        return VMOSTaskResult(task_id=task_id, status=4, error="No data")

    # ─── ADB OVER SSH ────────────────────────────────────────────────

    async def open_adb(self, pad_code: str) -> Optional[Dict[str, str]]:
        """
        Open ADB-over-SSH tunnel to the device.
        Returns SSH connection details + ADB connect command.
        """
        data = await self._post("/vcpcloud/api/padApi/openOnlineAdb", {
            "padCodes": [pad_code]
        })
        raw = data.get("data", {})
        # API may return dict with successList/failedList OR a flat list
        if isinstance(raw, dict):
            success = raw.get("successList", [])
            if success:
                s = success[0]
                return {
                    "pad_code": s.get("padCode", pad_code),
                    "ssh_command": s.get("command", ""),
                    "adb_connect": s.get("adb", ""),
                    "ssh_key": s.get("key", ""),
                    "expire_time": s.get("expireTime", ""),
                    "enabled": s.get("enable", False),
                }
            failed = raw.get("failedList", [])
            if failed:
                logger.warning(f"ADB open failed for {pad_code}: {failed[0].get('errorMsg')}")
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("taskStatus") == 3:
                    return {
                        "pad_code": item.get("padCode", pad_code),
                        "ssh_command": "",
                        "adb_connect": "",
                        "ssh_key": "",
                        "expire_time": "",
                        "enabled": True,
                    }
        return None

    # ─── TOUCH / INPUT ────────────────────────────────────────────────

    async def simulate_touch(self, pad_code: str, actions: List[Dict[str, Any]],
                             width: int = 1080, height: int = 2400) -> VMOSTaskResult:
        """
        Simulate touch events on the device.
        Each action: {"actionType": 0|1|2, "x": int, "y": int, "nextPositionWaitTime": int}
        actionType: 0=down, 1=up, 2=move
        """
        results = await self._submit_and_wait("/vcpcloud/api/padApi/simulateTouch", {
            "padCodes": [pad_code],
            "width": width,
            "height": height,
            "pointCount": 1,
            "positions": actions,
        })
        return results[0] if results else VMOSTaskResult(status=4, error="No result")

    async def tap(self, pad_code: str, x: int, y: int) -> VMOSTaskResult:
        """Simple tap at coordinates."""
        return await self.simulate_touch(pad_code, [
            {"actionType": 0, "x": x, "y": y, "nextPositionWaitTime": 50},
            {"actionType": 1, "x": x, "y": y},
        ])

    async def swipe(self, pad_code: str, x1: int, y1: int, x2: int, y2: int,
                    duration_ms: int = 300) -> VMOSTaskResult:
        """Swipe from (x1,y1) to (x2,y2)."""
        steps = max(5, duration_ms // 30)
        actions = [{"actionType": 0, "x": x1, "y": y1, "nextPositionWaitTime": 10}]
        for i in range(1, steps):
            t = i / steps
            cx = int(x1 + (x2 - x1) * t)
            cy = int(y1 + (y2 - y1) * t)
            actions.append({"actionType": 2, "x": cx, "y": cy, "nextPositionWaitTime": duration_ms // steps})
        actions.append({"actionType": 1, "x": x2, "y": y2})
        return await self.simulate_touch(pad_code, actions)

    async def input_text(self, pad_code: str, text: str) -> VMOSTaskResult:
        """Type text into the currently focused input field."""
        data = await self._post("/vcpcloud/api/padApi/inputText", {
            "padCodes": [pad_code],
            "text": text,
        })
        tasks = data.get("data", [])
        if tasks and tasks[0].get("taskId"):
            return await self._wait_for_task(tasks[0]["taskId"], pad_code)
        return VMOSTaskResult(pad_code=pad_code, status=3)

    # ─── APP MANAGEMENT ──────────────────────────────────────────────

    async def install_app(self, pad_code: str, file_id: str) -> VMOSTaskResult:
        """Install an APK (must be uploaded first via upload_file)."""
        results = await self._submit_and_wait("/vcpcloud/api/padApi/installApp", {
            "padCodes": [pad_code],
            "fileUniqueId": file_id,
        })
        return results[0] if results else VMOSTaskResult(status=4, error="No result")

    async def list_apps(self, pad_code: str) -> List[Dict[str, str]]:
        """List installed apps on the device."""
        data = await self._post("/vcpcloud/api/padApi/listInstalledApp", {
            "padCodes": [pad_code], "appName": ""
        })
        items = data.get("data", [])
        if items:
            return items[0].get("apps", [])
        return []

    # ─── IMAGE / GALLERY ─────────────────────────────────────────────

    async def inject_pictures(self, pad_code: str, count: int = 10) -> VMOSTaskResult:
        """Inject random gallery pictures into the device."""
        props = {"ro.sys.cloud.rand_pics": str(count)}
        return await self.update_android_props(pad_code, props)

    # ─── ROOT TOGGLE ─────────────────────────────────────────────────

    async def switch_root(self, pad_code: str, enable: bool = True,
                          package: str = "") -> VMOSTaskResult:
        """Toggle root access. Optionally limit to specific package."""
        body = {"padCodes": [pad_code], "rootSwitch": enable}
        if package:
            body["packageName"] = package
        results = await self._submit_and_wait("/vcpcloud/api/padApi/switchRoot", body)
        return results[0] if results else VMOSTaskResult(status=4, error="No result")

    # ─── GAID ─────────────────────────────────────────────────────────

    async def reset_gaid(self, pad_code: str) -> VMOSTaskResult:
        """Reset Google Advertising ID."""
        results = await self._submit_and_wait("/vcpcloud/api/padApi/resetGAID", {
            "padCodes": [pad_code],
            "taskSource": "OPEN_PLATFORM",
            "oprBy": "titan",
            "resetGmsType": "GAID",
        })
        return results[0] if results else VMOSTaskResult(status=4, error="No result")

    # ─── HIGH-LEVEL: FULL STEALTH PATCH ──────────────────────────────

    async def full_stealth_patch(
        self,
        pad_code: str,
        preset: Dict[str, str],
        carrier: Dict[str, str],
        location: Dict[str, float],
        wifi: Dict[str, str] = None,
    ) -> Dict[str, Any]:
        """
        Apply complete stealth identity to a VMOS Cloud device.
        Equivalent to anomaly_patcher.full_patch() but using VMOS native APIs.

        Args:
            preset: Device preset dict with brand, model, fingerprint, etc.
            carrier: Carrier dict with mcc, mnc, imei, iccid, etc.
            location: GPS dict with lat, lon, altitude
            wifi: WiFi dict with ssid, mac, ip, gateway
        """
        results = {}

        # 1. Device fingerprint
        logger.info(f"[{pad_code}] Patching device identity...")
        r = await self.update_device_identity(
            pad_code,
            brand=preset.get("brand", "samsung"),
            model=preset.get("model", "SM-S928U"),
            device=preset.get("device", "e3q"),
            fingerprint=preset.get("fingerprint", ""),
            android_version=preset.get("android_version", "15"),
            sdk_version=preset.get("sdk_version", "35"),
            security_patch=preset.get("security_patch", "2026-02-05"),
            imei=carrier.get("imei", ""),
            iccid=carrier.get("iccid", ""),
            imsi=carrier.get("imsi", ""),
            phone_number=carrier.get("phone_number", ""),
            carrier_mcc=carrier.get("mcc", "310"),
            carrier_mnc=carrier.get("mnc", "260"),
        )
        results["identity"] = r.to_dict()

        # 2. GPS
        if location:
            logger.info(f"[{pad_code}] Setting GPS...")
            r = await self.set_gps(
                pad_code,
                lat=location.get("lat", 40.7128),
                lon=location.get("lon", -74.0060),
            )
            results["gps"] = r.to_dict()

        # 3. WiFi
        if wifi:
            logger.info(f"[{pad_code}] Setting WiFi...")
            r = await self.set_wifi(
                pad_code,
                ssid=wifi.get("ssid", "NETGEAR72-5G"),
                mac=wifi.get("mac", "02:00:00:00:00:01"),
                ip=wifi.get("ip", "192.168.1.100"),
                gateway=wifi.get("gateway", "192.168.1.1"),
            )
            results["wifi"] = r.to_dict()

        # 4. Gallery photos
        logger.info(f"[{pad_code}] Injecting gallery photos...")
        r = await self.inject_pictures(pad_code, count=15)
        results["gallery"] = r.to_dict()

        # 5. Battery simulation
        props = {
            "persist.sys.cloud.battery.capacity": "5000",
            "persist.sys.cloud.battery.level": "78",
        }
        r = await self.update_android_props(pad_code, props)
        results["battery"] = r.to_dict()

        logger.info(f"[{pad_code}] Stealth patch complete")
        return results

    # ─── HIGH-LEVEL: FULL PROFILE INJECTION ──────────────────────────

    async def full_profile_inject(
        self,
        pad_code: str,
        contacts: List[Dict[str, str]] = None,
        call_logs: List[Dict[str, Any]] = None,
        sms_messages: List[Dict[str, str]] = None,
        chrome_commands: List[str] = None,
        wallet_commands: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Full profile data injection using VMOS Cloud APIs.
        Uses native APIs for contacts/calls/sms, asyncCmd for Chrome/wallet.
        """
        results = {}

        # 1. Contacts (native API — better than ADB)
        if contacts:
            logger.info(f"[{pad_code}] Injecting {len(contacts)} contacts...")
            r = await self.inject_contacts(pad_code, contacts)
            results["contacts"] = r.to_dict()

        # 2. Call logs (native API)
        if call_logs:
            logger.info(f"[{pad_code}] Injecting {len(call_logs)} call logs...")
            r = await self.inject_call_logs(pad_code, call_logs)
            results["call_logs"] = r.to_dict()

        # 3. SMS (native API)
        if sms_messages:
            logger.info(f"[{pad_code}] Injecting {len(sms_messages)} SMS...")
            for sms in sms_messages:
                await self.send_sms(
                    pad_code,
                    sender=sms.get("sender", "+12125551001"),
                    message=sms.get("message", "Hey"),
                )
            results["sms"] = {"count": len(sms_messages), "ok": True}

        # 4. Chrome data via shell (asyncCmd)
        if chrome_commands:
            logger.info(f"[{pad_code}] Injecting Chrome data via shell...")
            for cmd in chrome_commands:
                r = await self.exec_shell(pad_code, cmd)
                if not r.ok:
                    logger.warning(f"Chrome inject cmd failed: {r.error}")
            results["chrome"] = {"commands": len(chrome_commands), "ok": True}

        # 5. Wallet data via shell (asyncCmd)
        if wallet_commands:
            logger.info(f"[{pad_code}] Injecting wallet data via shell...")
            for cmd in wallet_commands:
                r = await self.exec_shell(pad_code, cmd)
                if not r.ok:
                    logger.warning(f"Wallet inject cmd failed: {r.error}")
            results["wallet"] = {"commands": len(wallet_commands), "ok": True}

        return results
