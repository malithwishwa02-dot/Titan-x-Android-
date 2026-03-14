"""
Titan V11.3 — VMOS Cloud Agent Adapter [DEPRECATED]
=====================================================
DEPRECATED: This module is no longer used. The Titan platform has migrated
from VMOS Cloud to Cuttlefish KVM-based Android VMs. All device interaction
is now handled via standard ADB using device_agent.py, touch_simulator.py,
and screen_analyzer.py.

This file is retained for reference only and will be removed in a future release.

Original description:
Provides ScreenAnalyzer and TouchSimulator-compatible interfaces
that route through VMOS Cloud APIs using direct synchronous HTTP.
"""

import hashlib
import hmac
import io
import json
import logging
import os
import random
import re
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.vmos-agent")

VMOS_HOST = os.environ.get("VMOS_API_HOST", "api.vmoscloud.com")
VMOS_SERVICE = "armcloud-paas"


def _vmos_post(path: str, body: dict, api_key: str, api_secret: str) -> dict:
    """Synchronous POST to VMOS Cloud API with HMAC-SHA256 signing."""
    from datetime import datetime, timezone
    url = f"https://{VMOS_HOST}{path}"
    body_str = json.dumps(body, separators=(",", ":"))
    body_bytes = body_str.encode("utf-8")

    x_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    ct = "application/json;charset=UTF-8"
    sh = "content-type;host;x-content-sha256;x-date"
    x_sha = hashlib.sha256(body_bytes).hexdigest()

    canonical = f"host:{VMOS_HOST}\nx-date:{x_date}\ncontent-type:{ct}\nsignedHeaders:{sh}\nx-content-sha256:{x_sha}"
    hc = hashlib.sha256(canonical.encode()).hexdigest()
    cs = f"{short_date}/{VMOS_SERVICE}/request"
    sts = f"HMAC-SHA256\n{x_date}\n{cs}\n{hc}"
    kd = hmac.new(api_secret.encode(), short_date.encode(), hashlib.sha256).digest()
    ks = hmac.new(kd, VMOS_SERVICE.encode(), hashlib.sha256).digest()
    kr = hmac.new(ks, b"request", hashlib.sha256).digest()
    sig = hmac.new(kr, sts.encode(), hashlib.sha256).hexdigest()

    headers = {
        "content-type": ct,
        "x-host": VMOS_HOST,
        "x-date": x_date,
        "authorization": f"HMAC-SHA256 Credential={api_key}, SignedHeaders={sh}, Signature={sig}",
    }

    try:
        import http.client as _hc
        conn = _hc.HTTPSConnection(VMOS_HOST, timeout=30)
        conn.request("POST", path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        return json.loads(raw)
    except Exception as e:
        # Fallback to urllib
        try:
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except Exception as e2:
            logger.warning(f"VMOS API call failed: {path}: {e2}")
            return {"code": -1, "msg": str(e2)}


def _vmos_shell_sync(pad_code: str, cmd: str, ak: str, sk: str, wait: int = 15) -> str:
    """Execute shell command on VMOS device synchronously, wait for result."""
    r = _vmos_post("/vcpcloud/api/padApi/asyncCmd", {"padCodes": [pad_code], "scriptContent": cmd}, ak, sk)
    tid = (r.get("data") or [{}])[0].get("taskId") if r.get("data") else None
    if not tid:
        return ""
    time.sleep(wait)
    r2 = _vmos_post("/vcpcloud/api/padApi/padTaskDetail", {"taskIds": [tid]}, ak, sk)
    if r2.get("data"):
        t = r2["data"][0]
        if t.get("taskStatus", 0) >= 3:
            return (t.get("taskResult") or t.get("errorMsg") or "OK")[:2000]
    return ""


# ═══════════════════════════════════════════════════════════════════════
# SCREEN ADAPTER
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class VMOSScreenState:
    screenshot_bytes: bytes = b""
    screenshot_b64: str = ""      # base64 JPEG — populated after capture for vision fallback
    width: int = 1080
    height: int = 2400
    elements: List[Dict] = field(default_factory=list)
    text_blocks: List[str] = field(default_factory=list)
    all_text: str = ""            # ScreenState-compatible flat text join
    current_app: str = ""         # ScreenState-compatible foreground package
    current_activity: str = ""    # ScreenState-compatible foreground activity
    description: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height,
                "elements": len(self.elements), "text_blocks": self.text_blocks[:10],
                "description": self.description[:300], "error": self.error}

    def to_llm_context(self) -> str:
        lines = [f"Screen: {self.width}x{self.height}"]
        if self.description:
            lines.append(f"Description: {self.description}")
        if self.text_blocks:
            lines.append("Visible text:")
            for t in self.text_blocks[:20]:
                lines.append(f"  - {t}")
        if self.elements:
            lines.append(f"UI elements ({len(self.elements)}):")
            for e in self.elements[:30]:
                lines.append(f"  [{e.get('bounds','')}] {e.get('class','')}: {e.get('text','')}")
        return "\n".join(lines)


class VMOSScreenAdapter:
    """Synchronous VMOS Cloud screenshot + UI analysis adapter."""

    def __init__(self, bridge=None, pad_code: str = "",
                 api_key: str = "", api_secret: str = ""):
        self.pad_code = pad_code
        self.ak = api_key or os.environ.get("VMOS_API_KEY", "")
        self.sk = api_secret or os.environ.get("VMOS_API_SECRET", "")
        # Also accept bridge for backwards compat — extract creds from it
        if bridge and not self.ak:
            self.ak = getattr(bridge, "api_key", "")
            self.sk = getattr(bridge, "api_secret", "")

    def capture_and_analyze(self, use_ui_dump: bool = True,
                            use_ocr: bool = False) -> VMOSScreenState:
        state = VMOSScreenState()
        try:
            # 1. Screenshot
            r = _vmos_post("/vcpcloud/api/padApi/getLongGenerateUrl",
                          {"padCodes": [self.pad_code], "format": "png"}, self.ak, self.sk)
            url = None
            if r.get("data"):
                for d in r["data"]:
                    if d.get("success") or d.get("url"):
                        url = d.get("url")
                        break

            if url:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    state.screenshot_bytes = resp.read()
                import base64 as _b64
                state.screenshot_b64 = _b64.b64encode(state.screenshot_bytes).decode()
                try:
                    from PIL import Image
                    img = Image.open(io.BytesIO(state.screenshot_bytes))
                    state.width, state.height = img.size
                except Exception:
                    pass
            else:
                state.error = "No screenshot URL returned"
                return state

            # 2. UI dump
            if use_ui_dump:
                xml = _vmos_shell_sync(self.pad_code,
                    "uiautomator dump /data/local/tmp/u.xml 2>/dev/null; cat /data/local/tmp/u.xml; rm -f /data/local/tmp/u.xml",
                    self.ak, self.sk, wait=12)
                if xml and "<node" in xml:
                    state.elements = self._parse_ui_xml(xml)
                    state.text_blocks = [e["text"] for e in state.elements if e.get("text")]

            state.all_text = " ".join(state.text_blocks)
            if state.text_blocks:
                state.description = f"Screen shows: {', '.join(state.text_blocks[:5])}"
            else:
                state.description = f"Screen captured ({state.width}x{state.height})"
            # Skip dumpsys activity — too slow (5s) for per-step capture; caller can set directly
            pass

        except Exception as e:
            state.error = str(e)
            logger.warning(f"VMOS screen capture failed: {e}")
        return state

    def _parse_ui_xml(self, xml_str: str) -> List[Dict]:
        elements = []
        for m in re.finditer(r'<node\s+([^>]+?)/?>', xml_str, re.DOTALL):
            elem = {}
            for attr in re.finditer(r'(\w[\w-]*)="([^"]*)"', m.group(1)):
                elem[attr.group(1)] = attr.group(2)
            if elem.get("text") or elem.get("content-desc"):
                bounds = elem.get("bounds", "")
                bm = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                if bm:
                    elem["center_x"] = (int(bm[1]) + int(bm[3])) // 2
                    elem["center_y"] = (int(bm[2]) + int(bm[4])) // 2
                elements.append(elem)
        return elements


# ═══════════════════════════════════════════════════════════════════════
# TOUCH ADAPTER
# ═══════════════════════════════════════════════════════════════════════

class VMOSTouchAdapter:
    """Synchronous VMOS Cloud touch/input adapter."""

    def __init__(self, bridge=None, pad_code: str = "",
                 api_key: str = "", api_secret: str = "",
                 width: int = 1260, height: int = 2800):
        self.pad_code = pad_code
        self.ak = api_key or os.environ.get("VMOS_API_KEY", "")
        self.sk = api_secret or os.environ.get("VMOS_API_SECRET", "")
        if bridge and not self.ak:
            self.ak = getattr(bridge, "api_key", "")
            self.sk = getattr(bridge, "api_secret", "")
        self.width = width
        self.height = height
        self._last_touch = 0

    def _rate_limit(self):
        elapsed = time.time() - self._last_touch
        if elapsed < 2.2:
            time.sleep(2.2 - elapsed)
        self._last_touch = time.time()

    def _shell(self, cmd: str, wait: int = 8) -> bool:
        res = _vmos_shell_sync(self.pad_code, cmd, self.ak, self.sk, wait)
        return bool(res)

    def tap(self, x: int, y: int) -> bool:
        self._rate_limit()
        jx = x + random.randint(-5, 5)
        jy = y + random.randint(-5, 5)
        return self._shell(f"input tap {jx} {jy}", 12)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        self._rate_limit()
        jx1 = x1 + random.randint(-3, 3)
        jy1 = y1 + random.randint(-3, 3)
        jx2 = x2 + random.randint(-3, 3)
        jy2 = y2 + random.randint(-3, 3)
        dur = duration + random.randint(-30, 50)
        return self._shell(f"input swipe {jx1} {jy1} {jx2} {jy2} {dur}", 12)

    def scroll_down(self, amount: int = 800) -> bool:
        cx = self.width // 2
        return self.swipe(cx, self.height // 2 + amount // 2, cx, self.height // 2 - amount // 2, 400)

    def scroll_up(self, amount: int = 800) -> bool:
        cx = self.width // 2
        return self.swipe(cx, self.height // 2 - amount // 2, cx, self.height // 2 + amount // 2, 400)

    def type_text(self, text: str) -> bool:
        escaped = text.replace("'", "'\\''")
        return self._shell(f"input text '{escaped}'", 12)

    def back(self) -> bool:
        return self._shell("input keyevent KEYCODE_BACK", 12)

    def home(self) -> bool:
        return self._shell("input keyevent KEYCODE_HOME", 12)

    def enter(self) -> bool:
        return self._shell("input keyevent KEYCODE_ENTER", 12)

    def open_app(self, package: str) -> bool:
        return self._shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1", 12)

    def open_url(self, url: str) -> bool:
        if not url.startswith("http"):
            url = f"https://{url}"
        return self._shell(f"am start -a android.intent.action.VIEW -d '{url}'", 5)

    def wait(self, seconds: float = 2.0):
        time.sleep(seconds)
