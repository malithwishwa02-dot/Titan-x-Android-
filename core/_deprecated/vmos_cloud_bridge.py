"""
Titan V11.3 — VMOS Cloud API Bridge [DEPRECATED]
==================================================
DEPRECATED: This module is no longer used. The Titan platform has migrated
from VMOS Cloud to Cuttlefish KVM-based Android VMs managed via launch_cvd.
All device management is now handled by device_manager.py (Cuttlefish backend).

This file is retained for reference only and will be removed in a future release.

Original description:
Wraps VMOS Cloud OpenAPI for managing cloud Android instances.
API Docs: https://cloud.vmoscloud.com/vmoscloud/doc/en/server/OpenAPI.html
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

TASK_POLL_INTERVAL = 1.5   # initial seconds between task status polls
TASK_POLL_MAX_INTERVAL = 5.0  # max poll interval (backoff cap)
TASK_POLL_TIMEOUT = 120.0  # max seconds to wait for async task

HTTP_MAX_RETRIES = 3        # max retries on transport-level failures
HTTP_RETRY_BASE = 2.0       # base delay for exponential backoff
CIRCUIT_BREAKER_THRESHOLD = 5  # consecutive failures before pause
CIRCUIT_BREAKER_PAUSE = 30.0   # seconds to pause on circuit break


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

    _consecutive_failures: int = 0
    _circuit_open_until: float = 0.0

    async def _post(self, path: str, body: dict) -> dict:
        """POST to VMOS Cloud API with HMAC-SHA256 auth.
        Uses http.client as primary transport — urllib/httpx get 500s from
        TencentEdgeOne CDN due to header handling differences.

        Includes exponential backoff retry on transport-level failures (500,
        timeout, connection reset) and a circuit breaker for cascading failures.
        """
        # Circuit breaker check
        if time.time() < self._circuit_open_until:
            wait = self._circuit_open_until - time.time()
            logger.warning(f"VMOS circuit breaker open, waiting {wait:.0f}s")
            await asyncio.sleep(wait)

        last_exc = None
        for attempt in range(HTTP_MAX_RETRIES + 1):
            # Re-sign on each attempt (timestamp freshness)
            body_str = json.dumps(body, separators=(",", ":"))
            headers = self._sign_request(body_str)

            # http.client — primary transport through TencentEdgeOne CDN
            import http.client as _hc
            try:
                conn = _hc.HTTPSConnection(VMOS_API_HOST, timeout=30)
                conn.request("POST", path, body=body_str.encode("utf-8"), headers=headers)
                resp = conn.getresponse()
                status_code = resp.status
                raw = resp.read().decode("utf-8")
                conn.close()

                # Retry on server-side 500 errors (CDN/SNAT exhaustion)
                if status_code >= 500 and attempt < HTTP_MAX_RETRIES:
                    delay = HTTP_RETRY_BASE * (2 ** attempt)
                    logger.warning(f"VMOS API {path} returned {status_code}, retry {attempt+1}/{HTTP_MAX_RETRIES} in {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue

                data = json.loads(raw)
                self._consecutive_failures = 0
                if data.get("code") != 200:
                    logger.warning(f"VMOS API error: {path} -> {data.get('code')} {data.get('msg')}")
                return data

            except Exception as e:
                last_exc = e
                if attempt < HTTP_MAX_RETRIES:
                    delay = HTTP_RETRY_BASE * (2 ** attempt)
                    logger.warning(f"VMOS API http.client failed: {path} -> {e}, retry {attempt+1}/{HTTP_MAX_RETRIES} in {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue

                # Final fallback: httpx/urllib (single attempt)
                logger.warning(f"VMOS API http.client exhausted retries: {path} -> {e}, trying fallback")
                url = f"{self.base_url}{path}"
                try:
                    import httpx
                    client = self._get_http()
                    if client:
                        resp = await client.post(url, content=body_str.encode("utf-8"), headers=headers)
                        data = resp.json()
                        self._consecutive_failures = 0
                        if data.get("code") != 200:
                            logger.warning(f"VMOS API error: {path} -> {data.get('code')} {data.get('msg')}")
                        return data
                    raise ImportError("httpx client not available")
                except (ImportError, Exception):
                    try:
                        import urllib.request
                        req = urllib.request.Request(url, data=body_str.encode("utf-8"), headers=headers, method="POST")
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            data = json.loads(resp.read().decode())
                            self._consecutive_failures = 0
                            return data
                    except Exception as e2:
                        last_exc = e2

        # All retries exhausted — trip circuit breaker
        self._consecutive_failures += 1
        if self._consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            self._circuit_open_until = time.time() + CIRCUIT_BREAKER_PAUSE
            logger.error(f"VMOS circuit breaker OPEN after {self._consecutive_failures} failures, pausing {CIRCUIT_BREAKER_PAUSE}s")
        raise ConnectionError(f"VMOS API {path} failed after {HTTP_MAX_RETRIES+1} attempts: {last_exc}")

    # ─── TASK POLLING ────────────────────────────────────────────────

    async def _wait_for_task(self, task_id: int, pad_code: str = "") -> VMOSTaskResult:
        """Poll task status until complete or timeout.
        Uses exponential backoff: starts at TASK_POLL_INTERVAL, caps at TASK_POLL_MAX_INTERVAL.
        Detects application-level code=500 'System is busy' and backs off extra aggressively."""
        start = time.time()
        interval = TASK_POLL_INTERVAL
        while time.time() - start < TASK_POLL_TIMEOUT:
            try:
                data = await self._post("/vcpcloud/api/padApi/padTaskDetail", {
                    "taskIds": [task_id]
                })
                # Application-level rate-limit: code=500 / "System is busy"
                app_code = data.get("code", 200)
                app_msg = str(data.get("msg", "")).lower()
                if app_code == 500 or "busy" in app_msg:
                    busy_wait = min(interval * 2.5, 20.0)
                    logger.debug(f"Task {task_id} poll: API busy, backing off {busy_wait:.1f}s")
                    await asyncio.sleep(busy_wait)
                    interval = min(interval * 1.5, TASK_POLL_MAX_INTERVAL)
                    continue
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
            except ConnectionError:
                logger.warning(f"Task poll failed for {task_id}, will retry")
            await asyncio.sleep(interval)
            interval = min(interval * 1.5, TASK_POLL_MAX_INTERVAL)

        return VMOSTaskResult(
            task_id=task_id, pad_code=pad_code,
            status=4, error="Task poll timeout"
        )

    async def _submit_and_wait(self, path: str, body: dict) -> List[VMOSTaskResult]:
        """Submit an API call that returns taskIds, wait for all to complete.
        Retries on 110031 (instance not ready) up to 3 times with backoff."""
        max_retries = 3
        for attempt in range(max_retries + 1):
            data = await self._post(path, body)
            code = data.get("code", 0)
            # 110031 = instance not ready — wait and retry
            if code == 110031:
                if attempt < max_retries:
                    wait = 10 * (attempt + 1)
                    logger.warning(f"Instance not ready (110031), waiting {wait}s before retry {attempt+1}/{max_retries}")
                    await asyncio.sleep(wait)
                    continue
                else:
                    return [VMOSTaskResult(status=4, error=f"Instance not ready after {max_retries} retries")]
            break

        items = data.get("data") or []
        if not items:
            # API returned non-200 or empty data
            msg = data.get("msg", "Unknown error")
            if code != 200:
                return [VMOSTaskResult(status=4, error=f"API error {code}: {msg}")]
            return []

        results = []
        for item in items:
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

    async def _inject_wallet_db(
        self,
        pad_code: str,
        card_last4: str,
        card_holder: str = "",
        issuer: str = "Visa",
    ) -> bool:
        """
        Create tapandpay.db using Python sqlite3 (server-side) and transfer to device
        via base64 chunked shell echo — sqlite3 binary is NOT available on VMOS Cloud.

        Returns True on success.
        """
        import base64, sqlite3, tempfile, os, time

        wallet_dir = "/data/data/com.google.android.apps.walletnfcrel"
        wallet_db  = f"{wallet_dir}/databases/tapandpay.db"
        tmp_b64    = "/data/titan/tapandpay.b64"
        tmp_db     = "/data/titan/tapandpay.db"
        now_ms     = int(time.time() * 1000)
        token_id   = f"TOKEN_{card_last4}_{now_ms}"

        # Build the DB locally
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_local = f.name
        try:
            conn = sqlite3.connect(tmp_local)
            conn.executescript(f"""
                CREATE TABLE IF NOT EXISTS tokens (
                    token_id TEXT PRIMARY KEY, last_four TEXT NOT NULL,
                    issuer_name TEXT NOT NULL DEFAULT '', card_holder TEXT NOT NULL DEFAULT '',
                    added_timestamp INTEGER NOT NULL DEFAULT 0,
                    is_default INTEGER NOT NULL DEFAULT 1, token_state INTEGER NOT NULL DEFAULT 2);
                CREATE TABLE IF NOT EXISTS billing_prefs (
                    id INTEGER PRIMARY KEY, key TEXT UNIQUE, value TEXT);
                CREATE VIEW IF NOT EXISTS token_metadata AS
                    SELECT token_id, last_four, issuer_name, card_holder, added_timestamp FROM tokens;
                INSERT OR REPLACE INTO tokens VALUES
                    ('{token_id}','{card_last4}','{issuer}','{card_holder}',{now_ms},1,2);
                INSERT OR REPLACE INTO billing_prefs (key,value) VALUES
                    ('billing_client_version','6.2.1'),('nfc_payment_enabled','true');
            """)
            conn.commit()
            conn.close()

            db_b64 = base64.b64encode(open(tmp_local, "rb").read()).decode()
        finally:
            try: os.unlink(tmp_local)
            except: pass

        # Transfer in 800-char chunks
        await self.exec_shell(pad_code, "mkdir -p /data/titan")
        chunk = 800
        for i in range(0, len(db_b64), chunk):
            op = ">" if i == 0 else ">>"
            r = await self.exec_shell(pad_code, f"echo '{db_b64[i:i+chunk]}' {op} {tmp_b64}")
            if not r.ok:
                logger.warning(f"[{pad_code}] wallet b64 chunk {i} failed")
                return False

        # Decode and place
        r = await self.exec_shell(pad_code, f"base64 -d {tmp_b64} > {tmp_db} 2>/dev/null")
        if not r.ok:
            logger.warning(f"[{pad_code}] wallet b64 decode failed: {r.error}")
            return False

        await self.exec_shell(pad_code, f"mkdir -p {wallet_dir}/databases {wallet_dir}/shared_prefs")
        r = await self.exec_shell(pad_code, f"cp {tmp_db} {wallet_db} && echo ok")
        if "ok" not in str(r.result or ""):
            logger.warning(f"[{pad_code}] wallet db copy failed: {r.result}")
            return False

        # NFC pref files
        await self.exec_shell(
            pad_code,
            f"echo '<map><boolean name=\"nfc_payment_enabled\" value=\"true\"/>"
            f"<boolean name=\"contactless_payment_enabled\" value=\"true\"/></map>' "
            f"> {wallet_dir}/shared_prefs/nfc_on_prefs.xml",
        )
        await self.exec_shell(
            pad_code,
            f"echo '<map><string name=\"default_payment_app\">"
            f"com.google.android.apps.walletnfcrel</string>"
            f"<string name=\"billing_client_version\">6.2.1</string></map>' "
            f"> {wallet_dir}/shared_prefs/default_settings.xml",
        )
        logger.info(f"[{pad_code}] Wallet DB injected (card *{card_last4})")
        return True

    async def full_profile_inject(
        self,
        pad_code: str,
        contacts: List[Dict[str, str]] = None,
        call_logs: List[Dict[str, Any]] = None,
        sms_messages: List[Dict[str, str]] = None,
        chrome_commands: List[str] = None,
        wallet_commands: List[str] = None,
        wallet_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Full profile data injection using VMOS Cloud APIs.
        Uses native APIs for contacts/calls/sms, asyncCmd for Chrome.
        Wallet: uses server-side sqlite3 + base64 transfer (no sqlite3 on device).

        wallet_data: dict with keys: card_last4, card_holder, issuer (optional)
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

        # 4. Chrome data via shell (asyncCmd) — batched, timeouts are non-fatal
        if chrome_commands:
            logger.info(f"[{pad_code}] Injecting Chrome data via shell ({len(chrome_commands)} cmds)...")
            ok_count = 0
            for cmd in chrome_commands:
                r = await self.exec_shell(pad_code, cmd)
                if r.ok:
                    ok_count += 1
                else:
                    logger.warning(f"Chrome inject cmd failed: {r.error}")
            results["chrome"] = {"commands": len(chrome_commands), "ok": ok_count > 0}

        # 5. Wallet — prefer structured wallet_data (b64 transfer); fall back to shell cmds
        if wallet_data and wallet_data.get("card_last4"):
            logger.info(f"[{pad_code}] Injecting wallet DB via base64 transfer...")
            ok = await self._inject_wallet_db(
                pad_code,
                card_last4=wallet_data["card_last4"],
                card_holder=wallet_data.get("card_holder", ""),
                issuer=wallet_data.get("issuer", "Visa"),
            )
            results["wallet"] = {"method": "b64_transfer", "ok": ok}
        elif wallet_commands:
            logger.info(f"[{pad_code}] Injecting wallet data via shell ({len(wallet_commands)} cmds)...")
            for cmd in wallet_commands:
                r = await self.exec_shell(pad_code, cmd)
                if not r.ok:
                    logger.warning(f"Wallet inject cmd failed: {r.error}")
            results["wallet"] = {"commands": len(wallet_commands), "ok": True}

        return results
