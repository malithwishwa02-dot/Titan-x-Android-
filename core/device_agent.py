"""
Titan V11.3 — AI Device Agent
Autonomous Android device control powered by GPU LLM models.
See→Think→Act loop: screenshot device → LLM decides action → execute via ADB.

Supports:
  - Free-form user prompts ("create an Amazon account")
  - Pre-built task templates (browse, login, install app)
  - Multi-step workflows with memory
  - Human-like touch/type via TouchSimulator

AI Models (via Vast.ai GPU Ollama tunnel):
  - titan-agent:7b   — trained action planning model (primary)
  - titan-specialist:7b — anomaly patching + wallet specialist
  - minicpm-v:8b     — vision model for screenshot analysis

Usage:
    agent = DeviceAgent(adb_target="127.0.0.1:5555")
    task = agent.start_task("Open Chrome and go to amazon.com")
    # Returns task_id, runs async in background
    status = agent.get_task_status(task_id)
"""

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from screen_analyzer import ScreenAnalyzer, ScreenState
from touch_simulator import TouchSimulator
from trajectory_logger import TrajectoryLogger

logger = logging.getLogger("titan.device-agent")

# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

GPU_OLLAMA_URL = os.environ.get("TITAN_GPU_OLLAMA", "http://127.0.0.1:11435")
CPU_OLLAMA_URL = os.environ.get("TITAN_CPU_OLLAMA", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("TITAN_AGENT_MODEL", "titan-agent:7b")
MAX_STEPS = int(os.environ.get("TITAN_AGENT_MAX_STEPS", "50"))
STEP_TIMEOUT = int(os.environ.get("TITAN_AGENT_STEP_TIMEOUT", "30"))

# Trained model preferences — auto-detected at startup
TRAINED_ACTION_MODEL = os.environ.get("TITAN_TRAINED_ACTION", "titan-agent:7b")
TRAINED_SPECIALIST_MODEL = os.environ.get("TITAN_SPECIALIST_MODEL", "titan-specialist:7b")
TRAINED_VISION_MODEL = os.environ.get("TITAN_TRAINED_VISION", "minicpm-v:8b")
FALLBACK_ACTION_MODELS = ["titan-specialist:7b", "hermes3:8b", "qwen2.5:7b"]
FALLBACK_VISION_MODELS = ["minicpm-v:8b", "llava:7b", "llava:13b"]

_available_models_cache: Optional[List[str]] = None
_models_cache_time: float = 0.0


def _detect_best_model(ollama_url: str = GPU_OLLAMA_URL,
                       model_type: str = "action") -> str:
    """Auto-detect the best available model, preferring trained LoRA models."""
    global _available_models_cache, _models_cache_time
    import urllib.request

    # Cache model list for 60 seconds
    if _available_models_cache is not None and time.time() - _models_cache_time < 60:
        available = _available_models_cache
    else:
        available = []
        for url in [ollama_url, CPU_OLLAMA_URL]:
            try:
                req = urllib.request.Request(f"{url}/api/tags")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    available = [m["name"] for m in data.get("models", [])]
                    if available:
                        break
            except Exception:
                continue
        _available_models_cache = available
        _models_cache_time = time.time()

    if model_type == "vision":
        preferred = [TRAINED_VISION_MODEL] + FALLBACK_VISION_MODELS
    else:
        preferred = [TRAINED_ACTION_MODEL] + FALLBACK_ACTION_MODELS

    for model in preferred:
        if model in available:
            return model
        # Check without tag (e.g. "titan-agent" matches "titan-agent:7b")
        base = model.split(":")[0]
        for avail in available:
            if avail.startswith(base):
                return avail

    return DEFAULT_MODEL


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class AgentAction:
    """Single action taken by the agent."""
    step: int = 0
    action_type: str = ""    # tap, type, swipe, scroll_down, scroll_up, back, home, enter, open_app, open_url, wait, done, error
    params: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    screen_summary: str = ""
    timestamp: float = 0.0
    success: bool = False

    def to_dict(self) -> dict:
        return {
            "step": self.step, "action": self.action_type,
            "params": self.params, "reasoning": self.reasoning[:200],
            "screen": self.screen_summary[:200],
            "success": self.success,
            "time": self.timestamp,
        }


@dataclass
class AgentTask:
    """A running or completed agent task."""
    id: str = ""
    device_id: str = ""
    prompt: str = ""
    status: str = "queued"     # queued, running, completed, failed, stopped
    model: str = ""
    steps_taken: int = 0
    max_steps: int = MAX_STEPS
    actions: List[AgentAction] = field(default_factory=list)
    result: str = ""
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    persona: Dict[str, str] = field(default_factory=dict)  # name, email, phone for form filling

    def to_dict(self) -> dict:
        return {
            "id": self.id, "device_id": self.device_id,
            "prompt": self.prompt, "status": self.status,
            "model": self.model,
            "steps_taken": self.steps_taken, "max_steps": self.max_steps,
            "actions": [a.to_dict() for a in self.actions[-20:]],
            "result": self.result, "error": self.error,
            "started_at": self.started_at, "completed_at": self.completed_at,
            "duration": round(self.completed_at - self.started_at, 1) if self.completed_at else 0,
        }


# ═══════════════════════════════════════════════════════════════════════
# LLM CLIENT
# ═══════════════════════════════════════════════════════════════════════

def _query_ollama(prompt: str, model: str = DEFAULT_MODEL,
                  ollama_url: str = GPU_OLLAMA_URL,
                  temperature: float = 0.3,
                  max_tokens: int = 256) -> str:
    """Query Ollama API and return raw text response."""
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }).encode()

    urls_to_try = [ollama_url, CPU_OLLAMA_URL] if ollama_url != CPU_OLLAMA_URL else [ollama_url]

    for url in urls_to_try:
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    f"{url}/api/generate",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=STEP_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode())
                    return data.get("response", "")
            except Exception as e:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Ollama ({url}) attempt {attempt+1}/3 failed: {e}, retry in {wait}s")
                if attempt < 2:
                    time.sleep(wait)
                continue
        logger.warning(f"Ollama ({url}) exhausted all retries, trying next endpoint")

    return ""


def _parse_action_json(text: str) -> Optional[Dict]:
    """Extract JSON action from LLM response."""
    # Try full response as JSON first (most common with format=json)
    try:
        parsed = json.loads(text.strip())
        if isinstance(parsed, dict) and "action" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    # Try to find JSON block with "action" key
    json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Try fixing unquoted keys: {action: "tap"} -> {"action": "tap"}
    fixed = re.sub(r'([{,])\s*(\w+)\s*:', r'\1 "\2":', text)
    fix_match = re.search(r'\{[^{}]*"action"[^{}]*\}', fixed, re.DOTALL)
    if fix_match:
        try:
            return json.loads(fix_match.group())
        except json.JSONDecodeError:
            pass

    # Try to extract from markdown code block
    code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except json.JSONDecodeError:
            pass

    return None


# ═══════════════════════════════════════════════════════════════════════
# ACTION PROMPT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════

_AGENT_SYSTEM_PROMPT = """You are an AI agent controlling an Android phone. Output ONE JSON action per response.

FORMAT (pick ONE):
{"action":"tap","x":540,"y":1200,"reason":"tap Sign In"}
{"action":"type","text":"hello@gmail.com","reason":"enter email"}
{"action":"scroll_down","reason":"scroll to find element"}
{"action":"scroll_up","reason":"scroll back up"}
{"action":"swipe","x1":540,"y1":1800,"x2":540,"y2":600,"reason":"swipe"}
{"action":"back","reason":"go back"}
{"action":"home","reason":"home screen"}
{"action":"enter","reason":"submit"}
{"action":"open_app","package":"com.android.settings","reason":"open Settings"}
{"action":"open_url","url":"https://amazon.com","reason":"navigate"}
{"action":"wait","seconds":3,"reason":"wait for load"}
{"action":"done","reason":"task complete"}
{"action":"error","reason":"cannot proceed"}

RULES (strictly follow):
1. Output ONLY the JSON object — no text before or after, no markdown, no steps.
2. WRONG: "Let me..." {"action":"tap"}  WRONG: Step 1: {...} Step 2: {...}
3. CORRECT: {"action":"tap","x":360,"y":880,"reason":"tap Display"}
4. Only tap elements VISIBLE in the CURRENT SCREEN list — use exact coordinates shown.
5. If the needed app is NOT open yet: use open_app with its package name. If already open: do NOT use open_app.
6. If a target element is NOT visible in the list: use scroll_down — do NOT tap off-screen coordinates.
7. To enter text: FIRST tap the text field, THEN type in the next step. Never type without tapping first.
8. After typing text, press enter or tap the submit/search button.
9. Wait 2-3s after app launches or page navigations.
10. Say done only when the task goal is clearly achieved.
11. Say error only if truly stuck after multiple attempts."""

_STEP_PROMPT = """TASK: {task}

{persona_context}

STEP {step}/{max_steps}

CURRENT SCREEN:
{screen_context}

PREVIOUS ACTIONS:
{action_history}

What is the next action? Respond with a single JSON object."""


# ═══════════════════════════════════════════════════════════════════════
# TASK TEMPLATES
# ═══════════════════════════════════════════════════════════════════════

TASK_TEMPLATES = {
    # ── INSTALL ───────────────────────────────────────────────────────
    "install_app": {
        "prompt": "Open the Google Play Store and search for '{app_name}'. Install the app and wait for installation to complete. Once installed, go back to Play Store home.",
        "params": ["app_name"],
        "category": "install",
    },
    "install_batch": {
        "prompt": "Open Google Play Store and install the following apps one by one: {app_list}. For each app: search by name, tap Install, wait for installation to finish, then go back to Play Store for the next one. Skip any app that requires payment.",
        "params": ["app_list"],
        "category": "install",
    },
    # ── SIGN-IN ───────────────────────────────────────────────────────
    "google_signin": {
        "prompt": "Open Settings, go to Accounts, and add a Google account. Use email {email} and password {password}. Complete any verification steps. Accept all terms.",
        "params": ["email", "password"],
        "category": "sign_in",
    },
    "chrome_signin": {
        "prompt": "Open Google Chrome. Tap the profile icon or go to Settings > Sign in. Sign in with Google account {email} and password {password}. Enable sync if prompted.",
        "params": ["email", "password"],
        "category": "sign_in",
    },
    "login_app": {
        "prompt": "Open {app_name} app and log in with email {email} and password {password}. Complete any verification or setup steps that appear.",
        "params": ["app_name", "email", "password"],
        "category": "sign_in",
    },
    "paypal_signin": {
        "prompt": "Open PayPal app. Tap 'Log In'. Enter email {email} and password {password}. Complete any security verification. Skip any promotional screens.",
        "params": ["email", "password"],
        "category": "sign_in",
    },
    "venmo_signin": {
        "prompt": "Open Venmo app. Tap 'Sign In'. Enter phone number or email {email} and password {password}. Complete verification if asked. Skip any setup prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
    },
    "cashapp_signin": {
        "prompt": "Open Cash App. Enter phone number or email {email}. Complete the sign-in flow. Verify with code if needed. Skip optional setup steps.",
        "params": ["email"],
        "category": "sign_in",
    },
    "bank_app_signin": {
        "prompt": "Open {app_name} banking app. Tap 'Sign In' or 'Log In'. Enter username {email} and password {password}. Complete any security challenge or biometric prompt. Skip marketing screens.",
        "params": ["app_name", "email", "password"],
        "category": "sign_in",
    },
    "instagram_signin": {
        "prompt": "Open Instagram. Tap 'Log In'. Enter username {email} and password {password}. If asked to save login info, tap 'Save'. Skip any popups or notifications prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
    },
    # ── WALLET ────────────────────────────────────────────────────────
    "wallet_verify": {
        "prompt": "Open Google Wallet (or Google Pay) app. Check if a payment card is visible on the main screen. If a card ending in {card_last4} is shown, the wallet is set up correctly. Take a screenshot showing the card. Then go back to home screen.",
        "params": ["card_last4"],
        "category": "wallet",
    },
    "wallet_add_card_ui": {
        "prompt": "Open Google Wallet (or Google Pay). Tap 'Add to Wallet' or '+' button. Select 'Payment card' or 'Credit or debit card'. When the camera/scanner appears, tap 'Enter details manually'. Fill in the card details when prompted and accept all terms. Complete any bank verification steps that appear.",
        "params": [],
        "category": "wallet",
    },
    "play_store_add_payment": {
        "prompt": "Open Google Play Store. Tap your profile icon (top right). Tap 'Payments & subscriptions'. Tap 'Payment methods'. Tap 'Add payment method' or 'Add credit or debit card'. Follow the prompts to add a card. Accept any terms.",
        "params": [],
        "category": "wallet",
    },
    # ── AGING / WARMUP ────────────────────────────────────────────────
    "warmup_device": {
        "prompt": "Open Chrome and browse naturally for 5 minutes. Visit Google, YouTube, and 3 other popular websites. Scroll through content on each site. This is to warm up the device with realistic usage.",
        "params": [],
        "category": "aging",
    },
    "warmup_youtube": {
        "prompt": "Open YouTube app. Search for '{query}' or browse the home feed. Watch at least 2 videos for 30 seconds each, scrolling the feed between videos. Like one video.",
        "params": ["query"],
        "category": "aging",
    },
    "warmup_maps": {
        "prompt": "Open Google Maps. Search for '{location}'. Explore the area, check a restaurant or business listing, look at reviews. Then get directions from current location to that place.",
        "params": ["location"],
        "category": "aging",
    },
    "warmup_social": {
        "prompt": "Open {app_name}. Scroll through the main feed for 2-3 minutes. View 3-4 posts. Like one post. Go to the Explore/Discover tab and browse briefly.",
        "params": ["app_name"],
        "category": "aging",
    },
    "gmail_compose": {
        "prompt": "Open Gmail. Compose a new email to {to_email} with subject '{subject}' and body '{body}'. Send the email.",
        "params": ["to_email", "subject", "body"],
        "category": "aging",
    },
    "settings_tweak": {
        "prompt": "Open Settings. Change the display brightness to about 60%. Go to Sounds and set the ring volume to medium. Go to Display and check the current wallpaper. Go back to home screen.",
        "params": [],
        "category": "aging",
    },
    # ── BROWSE ────────────────────────────────────────────────────────
    "browse_url": {
        "prompt": "Open the web browser and navigate to {url}. Wait for the page to load completely.",
        "params": ["url"],
        "category": "browse",
    },
    "search_google": {
        "prompt": "Open the web browser, go to google.com, and search for '{query}'. Click on the first organic result and scroll through the page.",
        "params": ["query"],
        "category": "browse",
    },
    "create_account": {
        "prompt": "Go to {url} and create a new account. Use the persona details provided. Fill in all required fields and submit the registration form.",
        "params": ["url"],
        "category": "sign_in",
    },
    # ── SOCIAL SIGN-INS ──────────────────────────────────────────────
    "facebook_signin": {
        "prompt": "Open Facebook app. Tap 'Log In'. Enter email {email} and password {password}. Tap 'Log In' button. If asked to save login, tap 'OK'. Skip any 'Find Friends' or notification prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
    },
    "tiktok_signin": {
        "prompt": "Open TikTok app. Tap 'Profile' tab at bottom. Tap 'Log in'. Choose 'Use phone/email/username'. Enter email {email} and password {password}. Complete any CAPTCHA or verification. Skip onboarding prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
    },
    "whatsapp_setup": {
        "prompt": "Open WhatsApp. Enter phone number {phone} when prompted. Verify with SMS code if possible, otherwise wait. Enter display name {name} when asked. Skip backup restoration. Allow contacts access if prompted.",
        "params": ["phone", "name"],
        "category": "sign_in",
    },
    "telegram_signin": {
        "prompt": "Open Telegram app. Enter phone number {phone}. Wait for SMS verification code. Enter the code if received. Set display name to {name} if prompted. Skip optional profile photo.",
        "params": ["phone", "name"],
        "category": "sign_in",
    },
    "snapchat_signin": {
        "prompt": "Open Snapchat app. Tap 'Log In'. Enter username or email {email} and password {password}. Complete any verification. Skip 'Add Friends' and notification prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
    },
    "twitter_signin": {
        "prompt": "Open X (Twitter) app. Tap 'Sign in'. Enter email or username {email}. Enter password {password} on next screen. Skip any 'Turn on notifications' or suggestions prompts.",
        "params": ["email", "password"],
        "category": "sign_in",
    },
    # ── CRYPTO / COMMERCE ────────────────────────────────────────────
    "crypto_signin": {
        "prompt": "Open {app_name} app. Tap 'Sign In' or 'Log In'. Enter email {email} and password {password}. Complete 2FA or email verification if prompted. Skip any promotional screens or tutorials.",
        "params": ["app_name", "email", "password"],
        "category": "sign_in",
    },
    "amazon_signin": {
        "prompt": "Open Amazon Shopping app. Tap 'Sign In'. Enter email {email} and password {password}. Complete any CAPTCHA or OTP verification. Skip 'Turn on notifications'. Browse home page briefly.",
        "params": ["email", "password"],
        "category": "sign_in",
    },
    # ── PLAY STORE / APP MANAGEMENT ──────────────────────────────────
    "play_purchase": {
        "prompt": "Open Google Play Store. Search for '{app_name}'. If it has an in-app purchase or paid version, tap 'Buy' or 'Install' (paid). Complete the purchase using the saved payment method. Accept any confirmations.",
        "params": ["app_name"],
        "category": "install",
    },
    "app_update": {
        "prompt": "Open Google Play Store. Tap your profile icon (top right). Tap 'Manage apps & device'. Tap 'Updates available'. Update {app_name} if listed, or tap 'Update all'. Wait for updates to finish.",
        "params": ["app_name"],
        "category": "install",
    },
    # ── NOTIFICATION / PERMISSION HANDLING ───────────────────────────
    "handle_permissions": {
        "prompt": "A dialog or permission prompt is visible on screen. If it asks to allow notifications, tap 'Allow'. If it asks for location/camera/contacts permission, tap 'Allow' or 'While using the app'. If it shows a promotional popup, dismiss it by tapping 'No thanks', 'Skip', 'Not now', or the X button. Return to the app's main screen.",
        "params": [],
        "category": "aging",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# DEVICE AGENT
# ═══════════════════════════════════════════════════════════════════════

class DeviceAgent:
    """AI-powered autonomous Android device controller."""

    def __init__(self, adb_target: str = "127.0.0.1:5555",
                 model: str = "",
                 ollama_url: str = GPU_OLLAMA_URL):
        self.target = adb_target
        self.ollama_url = ollama_url
        # Auto-detect best action model if not explicitly set
        self.model = model or _detect_best_model(ollama_url, "action")
        self.vision_model = _detect_best_model(ollama_url, "vision")
        self.analyzer = ScreenAnalyzer(adb_target=adb_target)
        self.touch = TouchSimulator(adb_target=adb_target)
        self._tasks: Dict[str, AgentTask] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._stop_flags: Dict[str, threading.Event] = {}
        self._current_traj: Optional[TrajectoryLogger] = None
        logger.info(f"DeviceAgent init: action={self.model}, vision={self.vision_model}")

    # ─── PUBLIC API ───────────────────────────────────────────────────

    def start_task(self, prompt: str, persona: Dict[str, str] = None,
                   template: str = None, template_params: Dict = None,
                   max_steps: int = MAX_STEPS) -> str:
        """Start an autonomous task on the device. Returns task_id."""
        task_id = f"task-{uuid.uuid4().hex[:8]}"

        # Apply template if specified
        final_prompt = prompt
        if template and template in TASK_TEMPLATES:
            tmpl = TASK_TEMPLATES[template]
            params = template_params or {}
            final_prompt = tmpl["prompt"].format(**params)

        task = AgentTask(
            id=task_id,
            device_id=self.target,
            prompt=final_prompt,
            status="queued",
            model=self.model,
            max_steps=max_steps,
            persona=persona or {},
        )
        self._tasks[task_id] = task

        stop_flag = threading.Event()
        self._stop_flags[task_id] = stop_flag

        thread = threading.Thread(target=self._run_task, args=(task_id,), daemon=True)
        self._threads[task_id] = thread
        thread.start()

        logger.info(f"Task started: {task_id} — {final_prompt[:80]}...")
        return task_id

    def stop_task(self, task_id: str) -> bool:
        """Stop a running task."""
        flag = self._stop_flags.get(task_id)
        if flag:
            flag.set()
            task = self._tasks.get(task_id)
            if task:
                task.status = "stopped"
            return True
        return False

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        return self._tasks.get(task_id)

    def list_tasks(self) -> List[Dict]:
        return [t.to_dict() for t in self._tasks.values()]

    def analyze_screen(self) -> Dict:
        """One-shot screen analysis."""
        state = self.analyzer.capture_and_analyze()
        return state.to_dict()

    # ─── TASK EXECUTION LOOP ─────────────────────────────────────────

    def _run_task(self, task_id: str):
        """Main see→think→act loop. Runs in background thread."""
        task = self._tasks[task_id]
        stop = self._stop_flags[task_id]

        task.status = "running"
        task.started_at = time.time()

        # ── Trajectory logging ──
        traj = TrajectoryLogger(task_id=task_id, device_id=task.device_id)
        traj.set_metadata(
            prompt=task.prompt, model=task.model, persona=task.persona,
            device_type="cuttlefish",
        )
        self._current_traj = traj

        try:
            for step in range(1, task.max_steps + 1):
                if stop.is_set():
                    task.status = "stopped"
                    break

                action = self._execute_step(task, step)
                task.actions.append(action)
                task.steps_taken = step

                if action.action_type == "done":
                    task.status = "completed"
                    task.result = action.reasoning
                    break
                elif action.action_type == "error":
                    task.status = "failed"
                    task.error = action.reasoning
                    break

                # Post-action delay for UI transitions to settle
                import random as _rnd
                time.sleep(_rnd.uniform(1.5, 2.5))

                # Prevent infinite loops — if last 5 actions are identical, stop
                if len(task.actions) >= 5:
                    recent = [a.action_type + str(a.params) for a in task.actions[-5:]]
                    if len(set(recent)) == 1:
                        task.status = "failed"
                        task.error = "Stuck in loop — same action repeated 5 times"
                        break

            else:
                task.status = "completed"
                task.result = f"Max steps ({task.max_steps}) reached"

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.exception(f"Task {task_id} failed")

        task.completed_at = time.time()
        traj.finalize(status=task.status, total_steps=task.steps_taken)
        self._current_traj = None
        logger.info(f"Task {task_id} finished: {task.status} ({task.steps_taken} steps, "
                     f"{task.completed_at - task.started_at:.1f}s)")

    def _execute_step(self, task: AgentTask, step: int) -> AgentAction:
        """Single see→think→act iteration."""
        action = AgentAction(step=step, timestamp=time.time())
        vision_used = False
        vision_desc_text = ""

        # 1. SEE — capture and analyze screen
        screen = self.analyzer.capture_and_analyze(
            use_ui_dump=True,
            use_ocr=(step % 3 == 1),  # OCR every 3rd step for speed
        )
        action.screen_summary = screen.description[:200]

        if screen.error:
            action.action_type = "error"
            action.reasoning = f"Screen capture failed: {screen.error}"
            return action

        # 1b. AUTO-DISMISS — handle crash/ANR dialogs before LLM query
        _crash_patterns = ["isn't responding", "has stopped", "keeps stopping",
                           "close app", "app isn't responding"]
        if screen.all_text:
            _lower_text = screen.all_text.lower()
            for _pat in _crash_patterns:
                if _pat in _lower_text:
                    # Try to dismiss: tap "Close app" or "Wait" or "OK"
                    for el in screen.elements:
                        if el.text and el.text.lower() in ("close app", "close", "wait", "ok"):
                            self.touch.tap(el.center[0], el.center[1])
                            action.action_type = "dismiss_dialog"
                            action.reasoning = f"Auto-dismissed crash dialog: '{_pat}' → tapped '{el.text}'"
                            action.success = True
                            logger.info(f"Step {step}: auto-dismissed crash/ANR dialog")
                            return action
                    # Fallback: press Back to dismiss
                    self.touch.press_back()
                    action.action_type = "dismiss_dialog"
                    action.reasoning = f"Auto-dismissed crash dialog via BACK key: '{_pat}'"
                    action.success = True
                    return action

        # 2. THINK — ask LLM for next action
        screen_context = screen.to_llm_context()

        # Vision fallback: when UI dump returns 0 elements (e.g. canvas-based UI),
        # use a vision model to describe the screen visually.
        if len(screen.elements) == 0 and screen.screenshot_b64:
            vision_desc_text = self._vision_describe_screen(screen.screenshot_b64, task.prompt)
            if vision_desc_text:
                vision_used = True
                screen_context = (
                    f"[Screen: {screen.width}x{screen.height} | App: {screen.current_app}]\n"
                    f"[Vision Analysis - UI dump empty, screenshot analyzed by vision model]:\n"
                    f"{vision_desc_text}"
                )

        # Scroll heuristic: if last action was NOT scroll and task mentions a keyword
        # not visible in current elements, append a hint to steer the model.
        if not vision_used and screen.elements:
            visible_texts = " ".join(e.text.lower() for e in screen.elements if e.text)
            # Extract meaningful words from task prompt (>4 chars, not common verbs)
            _skip = {"open", "find", "the", "and", "tap", "click", "into", "from",
                     "with", "that", "this", "then", "after", "when", "your", "scroll"}
            task_words = [w.lower().strip(".,") for w in task.prompt.split()
                          if len(w) > 4 and w.lower().strip(".,") not in _skip]
            last_action = task.actions[-1].action_type if task.actions else ""
            if task_words and last_action not in ("scroll_down", "scroll_up"):
                if not any(w in visible_texts for w in task_words[:6]):
                    screen_context += "\n[HINT: Target element not visible in current view — consider scroll_down]"

        # Build action history (last 12 actions)
        history_lines = []
        for prev in task.actions[-12:]:
            history_lines.append(
                f"  Step {prev.step}: {prev.action_type}({json.dumps(prev.params)}) → {'OK' if prev.success else 'FAIL'} | {prev.reasoning[:60]}"
            )
        action_history = "\n".join(history_lines) if history_lines else "  (no previous actions)"

        # Build persona context
        persona_ctx = ""
        if task.persona:
            persona_parts = []
            for k, v in task.persona.items():
                if v:
                    persona_parts.append(f"{k}: {v}")
            if persona_parts:
                persona_ctx = "PERSONA DATA (use for form filling):\n  " + "\n  ".join(persona_parts)

        prompt = _AGENT_SYSTEM_PROMPT + "\n\n" + _STEP_PROMPT.format(
            task=task.prompt,
            persona_context=persona_ctx,
            step=step,
            max_steps=task.max_steps,
            screen_context=screen_context,
            action_history=action_history,
        )

        llm_response = _query_ollama(prompt, model=task.model, ollama_url=self.ollama_url)

        if not llm_response:
            action.action_type = "error"
            action.reasoning = "LLM returned empty response"
            return action

        # 3. Parse action
        parsed = _parse_action_json(llm_response)
        if not parsed:
            action.action_type = "error"
            action.reasoning = f"Could not parse LLM response: {llm_response[:200]}"
            return action

        action.action_type = parsed.get("action", "error")
        action.reasoning = parsed.get("reason", "")[:60]
        action.params = {k: v for k, v in parsed.items() if k not in ("action", "reason")}

        # 4. ACT — execute the action
        action.success = self._execute_action(action)

        # 5. LOG — record step for training data
        traj = getattr(self, "_current_traj", None)
        if traj:
            traj.log_step(
                step=step,
                screen_b64=getattr(screen, "screenshot_b64", ""),
                screen_context=screen_context,
                screen_width=screen.width,
                screen_height=screen.height,
                current_app=getattr(screen, "current_app", ""),
                element_count=len(screen.elements),
                vision_used=vision_used,
                vision_description=vision_desc_text,
                llm_prompt=prompt,
                llm_response=llm_response,
                llm_model=task.model,
                action=parsed,
                action_type=action.action_type,
                action_success=action.success,
                action_reasoning=action.reasoning,
            )

        logger.info(f"  Step {step}: {action.action_type}({json.dumps(action.params)[:60]}) "
                     f"→ {'OK' if action.success else 'FAIL'}")
        return action

    def _vision_describe_screen(self, screenshot_b64: str, task_hint: str = "") -> str:
        """Use vision model to describe screen when UIAutomator returns no elements.
        Sends base64 screenshot to minicpm-v or llava via Ollama /api/generate."""
        import urllib.request
        import urllib.error

        vision_models = [self.vision_model] + [m for m in FALLBACK_VISION_MODELS if m != self.vision_model]
        prompt = (
            f"Describe this Android phone screen in detail for an AI agent. "
            f"Current task: {task_hint[:100]}. "
            "List: 1) What app/screen is shown, 2) All visible buttons and their positions, "
            "3) Any text fields or input areas, 4) The best next tap coordinates (x,y) to progress the task. "
            "Be concise and specific about UI element positions."
        )

        urls_to_try = [self.ollama_url, CPU_OLLAMA_URL]
        for url in urls_to_try:
            for model in vision_models:
                try:
                    payload = json.dumps({
                        "model": model,
                        "prompt": prompt,
                        "images": [screenshot_b64],
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": 400},
                    }).encode()
                    req = urllib.request.Request(
                        f"{url}/api/generate",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        data = json.loads(resp.read().decode())
                        desc = data.get("response", "")
                        if desc:
                            logger.debug(f"Vision fallback used ({model}): {desc[:80]}...")
                            return desc
                except Exception as e:
                    logger.debug(f"Vision model {model} at {url} failed: {e}")
                    continue
        return ""

    def _execute_action(self, action: AgentAction) -> bool:
        """Execute a parsed action via TouchSimulator."""
        t = action.action_type
        p = action.params

        try:
            if t == "tap":
                return self.touch.tap(int(p.get("x", 0)), int(p.get("y", 0)))

            elif t == "type":
                return self.touch.type_text(str(p.get("text", "")))

            elif t == "swipe":
                return self.touch.swipe(
                    int(p.get("x1", 0)), int(p.get("y1", 0)),
                    int(p.get("x2", 0)), int(p.get("y2", 0)),
                )

            elif t == "scroll_down":
                return self.touch.scroll_down(int(p.get("amount", 800)))

            elif t == "scroll_up":
                return self.touch.scroll_up(int(p.get("amount", 800)))

            elif t == "back":
                return self.touch.back()

            elif t == "home":
                return self.touch.home()

            elif t == "enter":
                return self.touch.enter()

            elif t == "open_app":
                return self.touch.open_app(str(p.get("package", "")))

            elif t == "open_url":
                return self.touch.open_url(str(p.get("url", "")))

            elif t == "wait":
                self.touch.wait(float(p.get("seconds", 2)))
                return True

            elif t == "done":
                return True

            elif t == "error":
                return False

            else:
                logger.warning(f"Unknown action type: {t}")
                return False

        except Exception as e:
            logger.error(f"Action execution failed: {e}")
            return False
