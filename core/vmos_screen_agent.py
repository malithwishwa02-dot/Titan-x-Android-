"""
Titan V11.3 — VMOS Screen Agent
AI-powered screen reading and human-like task automation for VMOS Cloud devices.

Uses Ollama vision models (LLaVA / MiniCPM-V) to understand device screenshots,
then executes actions through the VMOS Cloud API (touch, type, swipe, shell).

Architecture:
    1. Screenshot capture via VMOS Cloud API
    2. Vision LLM analyzes screen → structured understanding
    3. Task planner decides next action
    4. Action executor performs touch/type/swipe via VMOS API
    5. Loop until task is complete

Usage:
    agent = VMOSScreenAgent(pad_code="ACP2509244LGV1MV")
    result = await agent.execute_task("Open Chrome and search for 'weather NYC'")
"""

import asyncio
import base64
import io
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("titan.vmos-screen-agent")

OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
VISION_MODEL = os.environ.get("TITAN_VISION_MODEL", "minicpm-v:8b")
SCREEN_WIDTH = 1080
SCREEN_HEIGHT = 2400
MAX_STEPS = 30
STEP_DELAY = 1.5  # seconds between actions


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ScreenUnderstanding:
    """What the AI sees on the screen."""
    description: str = ""
    current_app: str = ""
    visible_text: List[str] = field(default_factory=list)
    clickable_elements: List[Dict[str, Any]] = field(default_factory=list)
    input_fields: List[Dict[str, Any]] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)
    screen_type: str = ""  # home, app_list, browser, form, dialog, keyboard, etc.
    raw_analysis: str = ""


@dataclass
class AgentAction:
    """An action the agent wants to perform."""
    action_type: str = ""   # tap, type, swipe, back, home, wait, shell, done, fail
    x: int = 0
    y: int = 0
    x2: int = 0
    y2: int = 0
    text: str = ""
    reason: str = ""
    confidence: float = 0.0


@dataclass
class TaskResult:
    """Result of a completed task."""
    success: bool = False
    steps_taken: int = 0
    final_screen: str = ""
    actions_log: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    duration: float = 0.0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "steps_taken": self.steps_taken,
            "final_screen": self.final_screen[:500],
            "actions": self.actions_log[-10:],
            "error": self.error,
            "duration_s": round(self.duration, 1),
        }


# ═══════════════════════════════════════════════════════════════════════
# OLLAMA VISION CLIENT
# ═══════════════════════════════════════════════════════════════════════

async def _ollama_vision(prompt: str, image_b64: str,
                         model: str = "", temperature: float = 0.3) -> str:
    """Send image + prompt to Ollama vision model and get text response."""
    model = model or VISION_MODEL
    url = f"{OLLAMA_BASE}/api/generate"
    body = {
        "model": model,
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 1024},
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=body)
            data = resp.json()
            return data.get("response", "")
    except ImportError:
        import urllib.request
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            return data.get("response", "")


async def _ollama_text(prompt: str, model: str = "minicpm-v:8b",
                       temperature: float = 0.2) -> str:
    """Text-only Ollama query for planning."""
    url = f"{OLLAMA_BASE}/api/generate"
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 512},
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=body)
            return resp.json().get("response", "")
    except ImportError:
        import urllib.request
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()).get("response", "")


# ═══════════════════════════════════════════════════════════════════════
# VMOS SCREEN AGENT
# ═══════════════════════════════════════════════════════════════════════

class VMOSScreenAgent:
    """AI agent that reads VMOS device screens and performs tasks like a human."""

    def __init__(self, pad_code: str, bridge=None):
        self.pad_code = pad_code
        self._bridge = bridge
        self._action_log: List[Dict[str, Any]] = []
        self._step = 0
        self._last_screen: str = ""

    def _get_bridge(self):
        if self._bridge is None:
            from vmos_cloud_bridge import VMOSCloudBridge
            self._bridge = VMOSCloudBridge()
        return self._bridge

    # ─── SCREEN CAPTURE ────────────────────────────────────────────

    async def capture_screen(self) -> Optional[str]:
        """Capture VMOS device screenshot, return base64 JPEG."""
        bridge = self._get_bridge()
        url = await bridge.screenshot(self.pad_code, fmt="png")
        if not url:
            return None

        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    png_bytes = resp.content
                    # Resize for LLM efficiency
                    try:
                        from PIL import Image
                        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
                        w, h = img.size
                        if w > 768:
                            ratio = 768 / w
                            img = img.resize((768, int(h * ratio)), Image.LANCZOS)
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=60)
                        return base64.b64encode(buf.getvalue()).decode()
                    except ImportError:
                        return base64.b64encode(png_bytes).decode()
        except Exception as e:
            logger.warning(f"Screenshot capture failed: {e}")
        return None

    # ─── SCREEN ANALYSIS ───────────────────────────────────────────

    async def analyze_screen(self, image_b64: str) -> ScreenUnderstanding:
        """Use vision LLM to understand what's on the screen."""
        prompt = """You are analyzing an Android phone screenshot. Describe what you see in a structured format:

1. SCREEN_TYPE: (home_screen | app_drawer | browser | settings | form | dialog | login | notification | keyboard_visible | other)
2. CURRENT_APP: What app is shown (e.g. Chrome, Instagram, Settings)
3. VISIBLE_TEXT: List the main text content you can read on screen
4. CLICKABLE_ELEMENTS: List buttons, links, icons with their approximate position:
   Format: "element_description" at (x, y) where x,y are pixel coordinates on a 1080x2400 screen
5. INPUT_FIELDS: Any text input fields visible, describe what they're for
6. ERRORS: Any error messages or alerts visible
7. STATUS: Brief 1-sentence summary of the screen state

Be precise with coordinates. The screen is 1080 pixels wide and ~2400 pixels tall.
Top status bar is around y=0-80. Navigation bar at bottom y=2300-2400."""

        raw = await _ollama_vision(prompt, image_b64)
        self._last_screen = raw

        # Parse the structured response
        understanding = ScreenUnderstanding(raw_analysis=raw)

        # Extract screen type
        st_match = re.search(r'SCREEN_TYPE:\s*(\w+)', raw, re.IGNORECASE)
        if st_match:
            understanding.screen_type = st_match.group(1).lower()

        # Extract current app
        app_match = re.search(r'CURRENT_APP:\s*(.+?)(?:\n|$)', raw, re.IGNORECASE)
        if app_match:
            understanding.current_app = app_match.group(1).strip()

        # Extract clickable elements with coordinates
        coord_pattern = re.compile(
            r'"([^"]+)"\s*at\s*\(?(\d+)\s*,\s*(\d+)\)?', re.IGNORECASE
        )
        for m in coord_pattern.finditer(raw):
            understanding.clickable_elements.append({
                "text": m.group(1),
                "x": int(m.group(2)),
                "y": int(m.group(3)),
            })

        # Extract description
        status_match = re.search(r'STATUS:\s*(.+?)(?:\n|$)', raw, re.IGNORECASE)
        if status_match:
            understanding.description = status_match.group(1).strip()
        else:
            understanding.description = raw[:200]

        return understanding

    # ─── ACTION PLANNING ──────────────────────────────────────────

    async def plan_action(self, task: str, screen: ScreenUnderstanding,
                          history: List[Dict[str, Any]]) -> AgentAction:
        """Given a task and current screen state, decide the next action."""

        history_text = ""
        if history:
            recent = history[-5:]
            history_text = "\n".join([
                f"  Step {h['step']}: {h['action']} → {h.get('description','')}"
                for h in recent
            ])

        elements_text = ""
        if screen.clickable_elements:
            elements_text = "\n".join([
                f"  - \"{e['text']}\" at ({e['x']}, {e['y']})"
                for e in screen.clickable_elements[:15]
            ])

        prompt = f"""You are an AI controlling an Android phone (1080x2400 screen).

TASK: {task}

CURRENT SCREEN:
{screen.description}
Screen type: {screen.screen_type}
App: {screen.current_app}

CLICKABLE ELEMENTS:
{elements_text or "  (none detected clearly)"}

PREVIOUS ACTIONS:
{history_text or "  (none yet)"}

Decide the SINGLE next action. Respond in EXACTLY this format:
ACTION: tap|type|swipe_up|swipe_down|swipe_left|swipe_right|back|home|wait|done|fail
X: <number 0-1080>
Y: <number 0-2400>
TEXT: <text to type if action=type>
REASON: <brief explanation>
CONFIDENCE: <0.0 to 1.0>

Rules:
- Use "tap" to click buttons/links at specific coordinates
- Use "type" to enter text (the keyboard must be visible)
- Use "swipe_up" to scroll down, "swipe_down" to scroll up
- Use "back" to go back, "home" to go to home screen
- Use "wait" if a page is still loading
- Use "done" when the task is COMPLETE
- Use "fail" if the task seems impossible
- Be precise with tap coordinates - aim for the center of the element
- If the screen hasn't changed after 3 similar actions, try a different approach"""

        raw = await _ollama_vision(prompt, await self.capture_screen() or "")

        # Parse the action
        action = AgentAction()

        action_match = re.search(r'ACTION:\s*(\w+)', raw, re.IGNORECASE)
        if action_match:
            action.action_type = action_match.group(1).lower()

        x_match = re.search(r'\bX:\s*(\d+)', raw, re.IGNORECASE)
        y_match = re.search(r'\bY:\s*(\d+)', raw, re.IGNORECASE)
        if x_match:
            action.x = int(x_match.group(1))
        if y_match:
            action.y = int(y_match.group(1))

        text_match = re.search(r'TEXT:\s*(.+?)(?:\n|$)', raw, re.IGNORECASE)
        if text_match:
            action.text = text_match.group(1).strip()

        reason_match = re.search(r'REASON:\s*(.+?)(?:\n|$)', raw, re.IGNORECASE)
        if reason_match:
            action.reason = reason_match.group(1).strip()

        conf_match = re.search(r'CONFIDENCE:\s*([\d.]+)', raw, re.IGNORECASE)
        if conf_match:
            try:
                action.confidence = float(conf_match.group(1))
            except ValueError:
                action.confidence = 0.5

        return action

    # ─── ACTION EXECUTION ─────────────────────────────────────────

    async def execute_action(self, action: AgentAction) -> bool:
        """Execute a planned action on the VMOS device."""
        bridge = self._get_bridge()
        import random

        if action.action_type == "tap":
            # Human-like jitter
            jx = action.x + random.randint(-5, 5)
            jy = action.y + random.randint(-5, 5)
            jx = max(0, min(jx, SCREEN_WIDTH))
            jy = max(0, min(jy, SCREEN_HEIGHT))
            r = await bridge.tap(self.pad_code, jx, jy)
            return r.ok

        elif action.action_type == "type":
            r = await bridge.input_text(self.pad_code, action.text)
            return r.ok

        elif action.action_type == "swipe_up":
            # Scroll down (finger moves up)
            r = await bridge.swipe(self.pad_code, 540, 1800, 540, 800, 400)
            return r.ok

        elif action.action_type == "swipe_down":
            # Scroll up (finger moves down)
            r = await bridge.swipe(self.pad_code, 540, 800, 540, 1800, 400)
            return r.ok

        elif action.action_type == "swipe_left":
            r = await bridge.swipe(self.pad_code, 900, 1200, 200, 1200, 300)
            return r.ok

        elif action.action_type == "swipe_right":
            r = await bridge.swipe(self.pad_code, 200, 1200, 900, 1200, 300)
            return r.ok

        elif action.action_type == "back":
            r = await bridge.exec_shell(self.pad_code, "input keyevent KEYCODE_BACK")
            return r.ok

        elif action.action_type == "home":
            r = await bridge.exec_shell(self.pad_code, "input keyevent KEYCODE_HOME")
            return r.ok

        elif action.action_type == "wait":
            await asyncio.sleep(2.0)
            return True

        elif action.action_type in ("done", "fail"):
            return True

        elif action.action_type == "shell":
            r = await bridge.exec_shell(self.pad_code, action.text)
            return r.ok

        return False

    # ─── MAIN TASK LOOP ───────────────────────────────────────────

    async def execute_task(self, task: str,
                           max_steps: int = 0,
                           on_step: callable = None) -> TaskResult:
        """Execute a high-level task on the VMOS device.

        Args:
            task: Natural language description of what to do
            max_steps: Maximum number of actions (default: MAX_STEPS)
            on_step: Optional callback(step, action, screen) for progress
        """
        max_steps = max_steps or MAX_STEPS
        result = TaskResult()
        start = time.time()
        self._action_log = []
        self._step = 0

        logger.info(f"[{self.pad_code}] Starting task: {task}")

        for step in range(max_steps):
            self._step = step + 1

            # 1. Capture screen
            image_b64 = await self.capture_screen()
            if not image_b64:
                result.error = "Failed to capture screenshot"
                break

            # 2. Analyze screen
            screen = await self.analyze_screen(image_b64)

            # 3. Plan next action
            action = await self.plan_action(task, screen, self._action_log)

            # Log
            log_entry = {
                "step": self._step,
                "action": action.action_type,
                "x": action.x, "y": action.y,
                "text": action.text[:50] if action.text else "",
                "reason": action.reason[:100],
                "confidence": action.confidence,
                "screen_type": screen.screen_type,
                "description": screen.description[:100],
            }
            self._action_log.append(log_entry)

            logger.info(
                f"[{self.pad_code}] Step {self._step}: {action.action_type} "
                f"({action.x},{action.y}) '{action.text[:30]}' - {action.reason[:50]}"
            )

            # Notify callback
            if on_step:
                try:
                    on_step(self._step, log_entry, screen.description)
                except Exception:
                    pass

            # 4. Check if done
            if action.action_type == "done":
                result.success = True
                result.final_screen = screen.description
                break
            elif action.action_type == "fail":
                result.error = action.reason
                break

            # 5. Execute action
            ok = await self.execute_action(action)
            log_entry["executed"] = ok

            # 6. Wait for screen to update
            await asyncio.sleep(STEP_DELAY)

        result.steps_taken = self._step
        result.actions_log = self._action_log
        result.duration = time.time() - start

        logger.info(
            f"[{self.pad_code}] Task {'completed' if result.success else 'failed'} "
            f"in {result.steps_taken} steps ({result.duration:.1f}s)"
        )

        return result

    # ─── QUICK SCREEN READ ────────────────────────────────────────

    async def read_screen(self) -> Dict[str, Any]:
        """Just read the screen and return what's visible — no actions."""
        image_b64 = await self.capture_screen()
        if not image_b64:
            return {"error": "Failed to capture screenshot"}

        screen = await self.analyze_screen(image_b64)
        return {
            "description": screen.description,
            "screen_type": screen.screen_type,
            "current_app": screen.current_app,
            "elements": screen.clickable_elements[:20],
            "input_fields": screen.input_fields,
            "errors": screen.error_messages,
            "raw": screen.raw_analysis[:1000],
            "screenshot_b64": image_b64,
        }

    # ─── TARGETED ACTIONS (shortcuts) ─────────────────────────────

    async def open_app(self, package: str) -> bool:
        """Open an app by package name."""
        bridge = self._get_bridge()
        r = await bridge.exec_shell(
            self.pad_code,
            f"am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER "
            f"$(pm resolve-activity --brief {package} 2>/dev/null | tail -1) 2>/dev/null || "
            f"monkey -p {package} -c android.intent.category.LAUNCHER 1 2>/dev/null"
        )
        await asyncio.sleep(2)
        return r.ok

    async def type_in_focused(self, text: str) -> bool:
        """Type text into the currently focused field."""
        bridge = self._get_bridge()
        r = await bridge.input_text(self.pad_code, text)
        return r.ok

    async def tap_at(self, x: int, y: int) -> bool:
        """Tap at specific coordinates."""
        bridge = self._get_bridge()
        r = await bridge.tap(self.pad_code, x, y)
        return r.ok

    async def go_home(self) -> bool:
        """Press home button."""
        bridge = self._get_bridge()
        r = await bridge.exec_shell(self.pad_code, "input keyevent KEYCODE_HOME")
        return r.ok

    async def go_back(self) -> bool:
        """Press back button."""
        bridge = self._get_bridge()
        r = await bridge.exec_shell(self.pad_code, "input keyevent KEYCODE_BACK")
        return r.ok
