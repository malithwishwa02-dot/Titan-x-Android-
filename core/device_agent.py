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
  - hermes3:8b      — screen understanding + action planning (primary)
  - dolphin-llama3:8b — uncensored operator for complex tasks
  - deepseek-r1:7b  — fast decisions for simple actions

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

logger = logging.getLogger("titan.device-agent")

# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

GPU_OLLAMA_URL = os.environ.get("TITAN_GPU_OLLAMA", "http://127.0.0.1:11435")
CPU_OLLAMA_URL = os.environ.get("TITAN_CPU_OLLAMA", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("TITAN_AGENT_MODEL", "hermes3:8b")
MAX_STEPS = int(os.environ.get("TITAN_AGENT_MAX_STEPS", "50"))
STEP_TIMEOUT = int(os.environ.get("TITAN_AGENT_STEP_TIMEOUT", "30"))


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
                  max_tokens: int = 512) -> str:
    """Query Ollama API and return raw text response."""
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }).encode()

    urls_to_try = [ollama_url, CPU_OLLAMA_URL] if ollama_url != CPU_OLLAMA_URL else [ollama_url]

    for url in urls_to_try:
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
            logger.warning(f"Ollama ({url}) failed: {e}")
            continue

    return ""


def _parse_action_json(text: str) -> Optional[Dict]:
    """Extract JSON action from LLM response."""
    # Try to find JSON block
    json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Try full response as JSON
    try:
        return json.loads(text.strip())
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

_AGENT_SYSTEM_PROMPT = """You are an AI agent controlling an Android phone. You can see the screen and must decide the next action to complete the user's task.

AVAILABLE ACTIONS (respond with exactly ONE JSON object):
- {"action": "tap", "x": 540, "y": 1200, "reason": "tap Sign In button"}
- {"action": "type", "text": "hello@gmail.com", "reason": "enter email address"}
- {"action": "swipe", "x1": 540, "y1": 1800, "x2": 540, "y2": 600, "reason": "scroll down"}
- {"action": "scroll_down", "reason": "scroll to see more content"}
- {"action": "scroll_up", "reason": "scroll back up"}
- {"action": "back", "reason": "go back to previous screen"}
- {"action": "home", "reason": "go to home screen"}
- {"action": "enter", "reason": "press enter/submit"}
- {"action": "open_app", "package": "com.android.chrome", "reason": "open Chrome"}
- {"action": "open_url", "url": "https://amazon.com", "reason": "navigate to URL"}
- {"action": "wait", "seconds": 3, "reason": "wait for page to load"}
- {"action": "done", "reason": "task is complete"}
- {"action": "error", "reason": "cannot proceed because..."}

RULES:
1. Respond with ONLY a single JSON object. No explanation outside JSON.
2. The "reason" field must explain WHY you chose this action.
3. Use exact pixel coordinates from the element list when tapping.
4. If a text field needs input, tap it first, then type in the next step.
5. After typing, press enter or tap submit button.
6. Wait after navigation for pages to load.
7. Say "done" when the task is clearly completed.
8. Say "error" if you're stuck or the task is impossible."""

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
    "browse_url": {
        "prompt": "Open Chrome browser and navigate to {url}. Wait for the page to load completely.",
        "params": ["url"],
    },
    "create_account": {
        "prompt": "Go to {url} and create a new account. Use the persona details provided. Fill in all required fields and submit the registration form.",
        "params": ["url"],
    },
    "install_app": {
        "prompt": "Open the Google Play Store and search for '{app_name}'. Install the app and wait for installation to complete.",
        "params": ["app_name"],
    },
    "login_app": {
        "prompt": "Open {app_name} app and log in with email {email} and password {password}.",
        "params": ["app_name", "email", "password"],
    },
    "warmup_device": {
        "prompt": "Open Chrome and browse naturally for 5 minutes. Visit Google, YouTube, and 3 other popular websites. Scroll through content on each site. This is to warm up the device with realistic usage.",
        "params": [],
    },
    "search_google": {
        "prompt": "Open Chrome, go to google.com, and search for '{query}'. Click on the first organic result and scroll through the page.",
        "params": ["query"],
    },
}


# ═══════════════════════════════════════════════════════════════════════
# DEVICE AGENT
# ═══════════════════════════════════════════════════════════════════════

class DeviceAgent:
    """AI-powered autonomous Android device controller."""

    def __init__(self, adb_target: str = "127.0.0.1:5555",
                 model: str = DEFAULT_MODEL,
                 ollama_url: str = GPU_OLLAMA_URL):
        self.target = adb_target
        self.model = model
        self.ollama_url = ollama_url
        self.analyzer = ScreenAnalyzer(adb_target=adb_target)
        self.touch = TouchSimulator(adb_target=adb_target)
        self._tasks: Dict[str, AgentTask] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._stop_flags: Dict[str, threading.Event] = {}

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
        logger.info(f"Task {task_id} finished: {task.status} ({task.steps_taken} steps, "
                     f"{task.completed_at - task.started_at:.1f}s)")

    def _execute_step(self, task: AgentTask, step: int) -> AgentAction:
        """Single see→think→act iteration."""
        action = AgentAction(step=step, timestamp=time.time())

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

        # 2. THINK — ask LLM for next action
        screen_context = screen.to_llm_context()

        # Build action history (last 8 actions)
        history_lines = []
        for prev in task.actions[-8:]:
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
        action.reasoning = parsed.get("reason", "")
        action.params = {k: v for k, v in parsed.items() if k not in ("action", "reason")}

        # 4. ACT — execute the action
        action.success = self._execute_action(action)

        logger.info(f"  Step {step}: {action.action_type}({json.dumps(action.params)[:60]}) "
                     f"→ {'OK' if action.success else 'FAIL'}")
        return action

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
