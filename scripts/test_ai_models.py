#!/usr/bin/env python3
"""
Titan V11.3 — AI Model Real-World Testing & Gap Analysis
=========================================================
Tests titan-agent:7b, titan-specialist:7b, and minicpm-v:8b
against real-world scenarios to measure accuracy and identify gaps.

Runs against OVH server (51.68.33.34) via SSH.
"""

import json
import subprocess
import time
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── Configuration ──────────────────────────────────────────────────────
OVH_HOST = "51.68.33.34"
SSH_KEY = "/root/.ssh/id_ed25519"
OLLAMA_URL = "http://127.0.0.1:11435"  # on OVH, via tunnel to Vast.ai
API_URL = "http://127.0.0.1:8080"
DEVICE_ID = "cvd-ovh-1"
ADB_TARGET = "127.0.0.1:6520"

# ── Results ────────────────────────────────────────────────────────────
@dataclass
class TestResult:
    name: str
    category: str  # inference, vision, agent, specialist
    model: str
    status: str = "pending"  # pass, partial, fail, error
    duration: float = 0.0
    details: str = ""
    gaps: List[str] = field(default_factory=list)
    raw_response: str = ""

RESULTS: List[TestResult] = []

def ssh_cmd(cmd: str, timeout: int = 60) -> tuple:
    """Run command on OVH via SSH."""
    full = f'ssh -i {SSH_KEY} -o StrictHostKeyChecking=no -o ConnectTimeout=10 root@{OVH_HOST} {repr(cmd)}'
    try:
        r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"

def ollama_generate(prompt: str, model: str, images: List[str] = None, timeout: int = 45) -> tuple:
    """Query Ollama on OVH and return (response_text, duration_seconds)."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 512},
    }
    if images:
        payload["images"] = images
    
    t0 = time.time()
    
    payload_json = json.dumps(payload)
    # Always use scp to transfer payload — avoids all SSH shell escaping issues
    import tempfile as _tmpmod
    with _tmpmod.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(payload_json)
        local_tmp = f.name
    try:
        subprocess.run(
            f'scp -i {SSH_KEY} -o StrictHostKeyChecking=no -q {local_tmp} root@{OVH_HOST}:/tmp/ollama_payload.json',
            shell=True, capture_output=True, timeout=30
        )
    finally:
        import os as _os
        _os.unlink(local_tmp)
    cmd = f"curl -s --connect-timeout 10 --max-time {timeout} {OLLAMA_URL}/api/generate -d @/tmp/ollama_payload.json"
    
    rc, out = ssh_cmd(cmd, timeout=timeout + 30)
    dur = time.time() - t0
    
    if rc != 0 or not out:
        return "", dur
    try:
        data = json.loads(out)
        return data.get("response", ""), dur
    except json.JSONDecodeError:
        return out[:500], dur


def parse_action_json(text: str) -> Optional[Dict]:
    """Try to extract a JSON action from model output."""
    # Try JSON block
    m = re.search(r'\{[^{}]*"action"[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    # Try full text
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # Try markdown block
    m2 = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m2:
        try:
            return json.loads(m2.group(1))
        except json.JSONDecodeError:
            pass
    return None


# ═══════════════════════════════════════════════════════════════════════
# PHASE 1: INFERENCE QUALITY TESTS (no device interaction needed)
# ═══════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are an AI agent controlling an Android phone. You can see the screen and must decide the next action to complete the user's task.

AVAILABLE ACTIONS (respond with exactly ONE JSON object):
- {"action": "tap", "x": 540, "y": 1200, "reason": "tap Sign In button"}
- {"action": "type", "text": "hello@gmail.com", "reason": "enter email address"}
- {"action": "swipe", "x1": 540, "y1": 1800, "x2": 540, "y2": 600, "reason": "scroll down"}
- {"action": "scroll_down", "reason": "scroll to see more content"}
- {"action": "back", "reason": "go back to previous screen"}
- {"action": "home", "reason": "go to home screen"}
- {"action": "enter", "reason": "press enter/submit"}
- {"action": "open_app", "package": "com.android.chrome", "reason": "open Chrome"}
- {"action": "open_url", "url": "https://amazon.com", "reason": "navigate to URL"}
- {"action": "wait", "seconds": 3, "reason": "wait for page to load"}
- {"action": "done", "reason": "task is complete"}

RULES:
1. Respond with ONLY a single JSON object. No explanation outside JSON.
2. Use exact pixel coordinates from the element list when tapping.
3. Say "done" when the task is clearly completed."""


INFERENCE_TESTS = [
    # Test 1: Simple home screen — should open Settings
    {
        "name": "T1: Open Settings from home screen",
        "screen": """[Screen: 720x1280 | App: com.android.launcher3]
[Activity: .Launcher]
[Clickable elements]:
  1. [button] "Phone" at (90,1220)
  2. [button] "Messages" at (270,1220)
  3. [button] "Chrome" at (450,1220)
  4. [button] "Camera" at (630,1220)
  5. [button] "All Apps" at (360,1180)
  6. [text] "12:30" at (360,30)
  7. [text] "Search" at (360,80)""",
        "task": "Open the Settings app",
        "step": 1,
        "expect_action": "open_app",
        "expect_contains": "settings",
    },
    # Test 2: Chrome address bar — should type URL
    {
        "name": "T2: Navigate to URL in browser",
        "screen": """[Screen: 720x1280 | App: com.kiwibrowser.browser]
[Activity: org.chromium.chrome.browser.ChromeTabbedActivity]
[Text on screen]: Search or type URL
[Clickable elements]:
  1. [text_field] "Search or type URL" at (360,80)
  2. [button] "Tabs" at (630,80)
  3. [button] "Menu" at (690,80)
  4. [text] "New Tab" at (360,200)
  5. [button] "Google" at (180,400)
  6. [button] "YouTube" at (360,400)
  7. [button] "Facebook" at (540,400)""",
        "task": "Navigate to amazon.com in the browser",
        "step": 1,
        "expect_action": "tap",
        "expect_coord_near": (360, 80),  # address bar
    },
    # Test 3: After tapping address bar — should type the URL
    {
        "name": "T3: Type URL after tapping address bar",
        "screen": """[Screen: 720x1280 | App: com.kiwibrowser.browser]
[Text on screen]: |  (cursor blinking in address bar)
[Clickable elements]:
  1. [text_field] "" at (360,80)
  2. [text] "amazon.com" at (200,200)
  3. [text] "amazon prime" at (200,260)
  4. [button] "Voice search" at (650,80)""",
        "task": "Navigate to amazon.com in the browser",
        "step": 2,
        "prev_actions": "Step 1: tap({x:360,y:80}) → OK | tapped address bar",
        "expect_action": "type",
        "expect_contains": "amazon",
    },
    # Test 4: Play Store search — should tap search bar
    {
        "name": "T4: Search in Play Store",
        "screen": """[Screen: 720x1280 | App: com.android.vending]
[Activity: .AssetBrowserActivity]
[Text on screen]: Search for apps & games
[Clickable elements]:
  1. [text_field] "Search for apps & games" at (360,60)
  2. [button] "Profile" at (670,60)
  3. [text] "For you" at (90,130)
  4. [text] "Top charts" at (270,130)
  5. [text] "Categories" at (450,130)
  6. [image] "Featured app" at (360,400)
  7. [button] "Install" at (600,700)""",
        "task": "Open Google Play Store and search for 'WhatsApp'. Install the app.",
        "step": 1,
        "expect_action": "tap",
        "expect_coord_near": (360, 60),  # search bar
    },
    # Test 5: Settings display — should find and tap Display option
    {
        "name": "T5: Navigate Settings > Display",
        "screen": """[Screen: 720x1280 | App: com.android.settings]
[Activity: .Settings]
[Clickable elements]:
  1. [button] "Network & internet" at (360,180)
  2. [button] "Connected devices" at (360,280)
  3. [button] "Apps" at (360,380)
  4. [button] "Notifications" at (360,480)
  5. [button] "Battery" at (360,580)
  6. [button] "Storage" at (360,680)
  7. [button] "Sound & vibration" at (360,780)
  8. [button] "Display" at (360,880)
  9. [button] "Wallpaper & style" at (360,980)
  10. [text] "Search settings" at (360,60)""",
        "task": "Open Settings. Change the display brightness to about 60%.",
        "step": 2,
        "prev_actions": "Step 1: open_app({package:com.android.settings}) → OK | opened Settings",
        "expect_action": "tap",
        "expect_coord_near": (360, 880),  # Display
    },
    # Test 6: Permission dialog — should tap Allow
    {
        "name": "T6: Handle permission dialog",
        "screen": """[Screen: 720x1280 | App: com.android.permissioncontroller]
[Text on screen]: Allow YouTube to send you notifications?
[Clickable elements]:
  1. [button] "Allow" at (520,720)
  2. [button] "Don't allow" at (200,720)""",
        "task": "A dialog or permission prompt is visible. Allow notifications if asked.",
        "step": 1,
        "expect_action": "tap",
        "expect_coord_near": (520, 720),  # Allow button
    },
    # Test 7: Task completion detection — should say done
    {
        "name": "T7: Detect task completion",
        "screen": """[Screen: 720x1280 | App: com.android.settings]
[Activity: .SubSettings]
[Text on screen]: About phone | Android version 15 | Build number AP4A.250205.004 | Baseband version | Kernel version 5.15
[Clickable elements]:
  1. [button] "Back" at (40,60)
  2. [text] "About phone" at (360,60)
  3. [text] "Android version" at (200,200)
  4. [text] "15" at (200,240)
  5. [text] "Build number" at (200,340)
  6. [text] "AP4A.250205.004" at (200,380)""",
        "task": "Open Settings > About Phone and tell me the Android version",
        "step": 3,
        "prev_actions": "Step 1: open_app({package:com.android.settings}) → OK\nStep 2: scroll_down → OK | scrolled to About phone and tapped it",
        "expect_action": "done",
        "expect_contains": "15",
    },
    # Test 8: Form filling with persona
    {
        "name": "T8: Form filling with persona data",
        "screen": """[Screen: 720x1280 | App: com.kiwibrowser.browser]
[Text on screen]: Create Account | First Name | Last Name | Email | Password | Sign Up
[Clickable elements]:
  1. [text_field] "First Name" at (360,300)
  2. [text_field] "Last Name" at (360,400)
  3. [text_field] "Email" at (360,500)
  4. [text_field] "Password" at (360,600)
  5. [button] "Sign Up" at (360,750)
  6. [text] "Already have an account? Log in" at (360,820)""",
        "task": "Create a new account on this website. Fill in the form with the persona details.",
        "step": 1,
        "persona": "name: John Smith, email: john.smith42@gmail.com, phone: +1-555-0142",
        "expect_action": "tap",
        "expect_coord_near": (360, 300),  # First Name field
    },
    # Test 9: Scroll needed — content below fold
    {
        "name": "T9: Scroll to find content below fold",
        "screen": """[Screen: 720x1280 | App: com.android.settings]
[Activity: .Settings]
[Clickable elements]:
  1. [button] "Network & internet" at (360,180)
  2. [button] "Connected devices" at (360,280)
  3. [button] "Apps" at (360,380)
  4. [button] "Notifications" at (360,480)
  5. [button] "Battery" at (360,580)
  6. [button] "Storage" at (360,680)
  7. [button] "Sound & vibration" at (360,780)
  8. [button] "Display" at (360,880)
  9. [button] "Wallpaper & style" at (360,980)""",
        "task": "Open Settings and go to About Phone",
        "step": 2,
        "prev_actions": "Step 1: open_app({package:com.android.settings}) → OK",
        "expect_action": "scroll_down",
    },
    # Test 10: Ambiguous screen — error recovery
    {
        "name": "T10: Handle empty/loading screen",
        "screen": """[Screen: 720x1280 | App: com.kiwibrowser.browser]
[Clickable elements]:""",
        "task": "Navigate to google.com",
        "step": 3,
        "prev_actions": "Step 1: open_app({package:com.kiwibrowser.browser}) → OK\nStep 2: tap({x:360,y:80}) → FAIL | no element found",
        "expect_action": "wait",
    },
]


def run_inference_tests():
    """Run all inference quality tests against titan-agent:7b."""
    print("\n" + "="*70)
    print("PHASE 1: INFERENCE QUALITY TESTS (titan-agent:7b)")
    print("="*70)
    
    for i, test in enumerate(INFERENCE_TESTS):
        name = test["name"]
        print(f"\n{'─'*60}")
        print(f"  {name}")
        print(f"{'─'*60}")
        
        result = TestResult(name=name, category="inference", model="titan-agent:7b")
        
        # Build prompt exactly like DeviceAgent does
        prev = test.get("prev_actions", "(no previous actions)")
        persona_ctx = ""
        if test.get("persona"):
            persona_ctx = f"PERSONA DATA (use for form filling):\n  {test['persona']}"
        
        prompt = SYSTEM_PROMPT + "\n\n" + f"""TASK: {test['task']}

{persona_ctx}

STEP {test.get('step', 1)}/30

CURRENT SCREEN:
{test['screen']}

PREVIOUS ACTIONS:
  {prev}

What is the next action? Respond with a single JSON object."""
        
        resp, dur = ollama_generate(prompt, "titan-agent:7b")
        result.duration = dur
        result.raw_response = resp[:500]
        
        if not resp:
            result.status = "error"
            result.details = "Empty response from model"
            result.gaps.append("EMPTY_RESPONSE")
            RESULTS.append(result)
            print(f"  ❌ ERROR: Empty response ({dur:.1f}s)")
            continue
        
        # Parse JSON
        parsed = parse_action_json(resp)
        if not parsed:
            result.status = "fail"
            result.details = f"JSON parse failed. Raw: {resp[:200]}"
            result.gaps.append("JSON_PARSE_FAILURE")
            RESULTS.append(result)
            print(f"  ❌ FAIL: JSON parse failed ({dur:.1f}s)")
            print(f"     Raw: {resp[:150]}")
            continue
        
        action = parsed.get("action", "")
        reason = parsed.get("reason", "")
        
        # Check action type
        if test.get("expect_action") and action != test["expect_action"]:
            result.status = "fail"
            result.details = f"Expected action '{test['expect_action']}', got '{action}'. Reason: {reason}"
            result.gaps.append(f"WRONG_ACTION: expected={test['expect_action']}, got={action}")
            RESULTS.append(result)
            print(f"  ❌ FAIL: Wrong action '{action}' (expected '{test['expect_action']}') ({dur:.1f}s)")
            print(f"     Reason: {reason[:100]}")
            continue
        
        # Check coordinates if applicable
        coord_ok = True
        if test.get("expect_coord_near") and action == "tap":
            ex, ey = test["expect_coord_near"]
            ax, ay = int(parsed.get("x", 0)), int(parsed.get("y", 0))
            dist = ((ax - ex)**2 + (ay - ey)**2) ** 0.5
            if dist > 150:  # allow 150px tolerance
                coord_ok = False
                result.gaps.append(f"COORD_MISS: expected=({ex},{ey}), got=({ax},{ay}), dist={dist:.0f}px")
        
        # Check expected content
        content_ok = True
        if test.get("expect_contains"):
            search_in = json.dumps(parsed).lower()
            if test["expect_contains"].lower() not in search_in:
                content_ok = False
                result.gaps.append(f"MISSING_CONTENT: '{test['expect_contains']}' not in response")
        
        if coord_ok and content_ok:
            result.status = "pass"
            result.details = f"action={action}, reason={reason[:80]}"
            print(f"  ✅ PASS: {action} — {reason[:80]} ({dur:.1f}s)")
        else:
            result.status = "partial"
            result.details = f"action={action} correct, but: {'; '.join(result.gaps)}"
            print(f"  ⚠️ PARTIAL: {action} — {'; '.join(result.gaps)} ({dur:.1f}s)")
        
        RESULTS.append(result)
        time.sleep(1)  # Don't hammer Ollama


# ═══════════════════════════════════════════════════════════════════════
# PHASE 2: LIVE AGENT TESTS (offline tasks on CVD)
# ═══════════════════════════════════════════════════════════════════════

def run_agent_task(task_prompt: str, template: str = "", template_params: dict = None, max_steps: int = 15, timeout: int = 180) -> dict:
    """Start an agent task via API and wait for completion."""
    body = {"max_steps": max_steps}
    if template:
        body["template"] = template
        body["template_params"] = template_params or {}
    if task_prompt:
        body["prompt"] = task_prompt
    
    body_json = json.dumps(body)
    # Write body via scp to avoid shell escaping issues
    import tempfile as _tmpmod
    with _tmpmod.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(body_json)
        local_tmp = f.name
    try:
        subprocess.run(
            f'scp -i {SSH_KEY} -o StrictHostKeyChecking=no -q {local_tmp} root@{OVH_HOST}:/tmp/agent_task.json',
            shell=True, capture_output=True, timeout=15
        )
    finally:
        import os as _os
        _os.unlink(local_tmp)
    
    # Start task
    cmd = f"curl -s -X POST {API_URL}/api/agent/task/{DEVICE_ID} -H 'Content-Type: application/json' -d @/tmp/agent_task.json"
    rc, out = ssh_cmd(cmd, timeout=30)
    if rc != 0 or not out:
        return {"status": "error", "error": f"Failed to start task (rc={rc}): {out[:200]}"}
    
    try:
        start_data = json.loads(out)
    except Exception as e:
        return {"status": "error", "error": f"Invalid start response: {out[:200]} ({e})"}
    
    task_id = start_data.get("task_id", "")
    if not task_id:
        return {"status": "error", "error": f"No task_id in: {json.dumps(start_data)[:200]}"}
    
    print(f"     Task started: {task_id}")
    
    # Poll for completion
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(8)
        cmd2 = f"curl -s {API_URL}/api/agent/task/{DEVICE_ID}/{task_id}"
        rc2, out2 = ssh_cmd(cmd2, timeout=15)
        if rc2 != 0 or not out2:
            continue
        try:
            status_data = json.loads(out2)
        except:
            continue
        
        st = status_data.get("status", "")
        steps = status_data.get("steps_taken", 0)
        if st in ("completed", "failed", "stopped"):
            return status_data
        
        print(f"     ... step {steps}/{max_steps}, status={st}")
    
    # Timeout — stop the task
    ssh_cmd(f"curl -s -X POST {API_URL}/api/agent/stop/{DEVICE_ID}/{task_id}")
    return {"status": "timeout", "error": "Task timed out", "task_id": task_id}


AGENT_TESTS = [
    {
        "name": "A1: Open Settings and read About Phone",
        "prompt": "Open Settings, scroll down to 'About phone' and tap it. Read the Android version number. Then say done.",
        "max_steps": 12,
        "expect_status": "completed",
        "category": "navigation",
    },
    {
        "name": "A2: Change display brightness",
        "template": "settings_tweak",
        "max_steps": 15,
        "expect_status": "completed",
        "category": "navigation",
    },
    {
        "name": "A3: Open YouTube app",
        "prompt": "Open the YouTube app. Wait for it to load. Once you see the YouTube home screen, say done.",
        "max_steps": 8,
        "expect_status": "completed",
        "category": "app_launch",
    },
]


def run_agent_tests():
    """Run live agent tasks on the CVD."""
    print("\n" + "="*70)
    print("PHASE 2: LIVE AGENT TESTS (CVD offline tasks)")
    print("="*70)
    
    # First, go to home screen
    ssh_cmd(f"adb -s {ADB_TARGET} shell input keyevent KEYCODE_HOME")
    time.sleep(2)
    
    for test in AGENT_TESTS:
        name = test["name"]
        print(f"\n{'─'*60}")
        print(f"  {name}")
        print(f"{'─'*60}")
        
        result = TestResult(name=name, category="agent", model="titan-agent:7b")
        
        # Return to home before each test
        ssh_cmd(f"adb -s {ADB_TARGET} shell input keyevent KEYCODE_HOME")
        time.sleep(2)
        
        t0 = time.time()
        task_data = run_agent_task(
            task_prompt=test.get("prompt", ""),
            template=test.get("template", ""),
            template_params=test.get("template_params", {}),
            max_steps=test.get("max_steps", 15),
        )
        result.duration = time.time() - t0
        
        status = task_data.get("status", "error")
        steps = task_data.get("steps_taken", 0)
        error = task_data.get("error", "")
        actions = task_data.get("actions", [])
        
        result.raw_response = json.dumps(task_data, indent=2)[:1000]
        
        if status == test.get("expect_status", "completed"):
            result.status = "pass"
            result.details = f"Completed in {steps} steps"
            print(f"  ✅ PASS: {status} in {steps} steps ({result.duration:.1f}s)")
        elif status == "completed":
            result.status = "partial"
            result.details = f"Completed but expected {test.get('expect_status')}"
            print(f"  ⚠️ PARTIAL: {status} in {steps} steps ({result.duration:.1f}s)")
        else:
            result.status = "fail"
            result.details = f"Status={status}, error={error[:100]}, steps={steps}"
            result.gaps.append(f"TASK_FAILED: {status}")
            if error:
                result.gaps.append(f"ERROR: {error[:100]}")
            print(f"  ❌ FAIL: {status} after {steps} steps — {error[:100]} ({result.duration:.1f}s)")
        
        # Analyze action patterns
        if actions:
            action_types = [a.get("action", "") for a in actions]
            # Check for loops
            if len(action_types) >= 5:
                last5 = action_types[-5:]
                if len(set(last5)) == 1:
                    result.gaps.append(f"STUCK_LOOP: repeated '{last5[0]}' 5 times")
            # Check for errors
            errors = [a for a in actions if a.get("action") == "error"]
            if errors:
                result.gaps.append(f"ACTION_ERRORS: {len(errors)} error actions")
            
            print(f"     Actions: {' → '.join(action_types[:15])}")
        
        if result.gaps:
            print(f"     Gaps: {', '.join(result.gaps)}")
        
        RESULTS.append(result)


# ═══════════════════════════════════════════════════════════════════════
# PHASE 3: VISION + SPECIALIST TESTS
# ═══════════════════════════════════════════════════════════════════════

def get_screenshot_b64() -> str:
    """Capture a screenshot from CVD, resize, and return base64.
    The screenshot is captured and resized on OVH to keep data transfer small."""
    cmd = (
        f"adb -s {ADB_TARGET} exec-out screencap -p > /tmp/cvd_screen.png && "
        f"python3 -c \"from PIL import Image; import io,base64,sys; "
        f"img=Image.open('/tmp/cvd_screen.png').convert('RGB'); "
        f"w,h=img.size; r=min(768/w,1); img=img.resize((int(w*r),int(h*r))); "
        f"buf=io.BytesIO(); img.save(buf,'JPEG',quality=50); "
        f"print(base64.b64encode(buf.getvalue()).decode())\""
    )
    rc, out = ssh_cmd(cmd, timeout=20)
    if rc == 0 and out and len(out) > 100:
        return out.strip()
    return ""


VISION_TESTS = [
    {
        "name": "V1: Describe home screen",
        "setup_cmd": f"adb -s {ADB_TARGET} shell input keyevent KEYCODE_HOME",
        "setup_wait": 3,
        "prompt": "Describe this Android phone screen in detail. List: 1) What app/screen is shown, 2) All visible buttons and their approximate positions, 3) Any text visible, 4) The overall layout.",
        "expect_contains": ["home", "launcher"],
        "model": "minicpm-v:8b",
    },
    {
        "name": "V2: Describe Settings screen",
        "setup_cmd": f"adb -s {ADB_TARGET} shell am start -a android.intent.action.SETTINGS",
        "setup_wait": 4,
        "prompt": "Describe this Android phone screen. What app is shown? List all menu items visible with their approximate positions. What actions can a user take here?",
        "expect_contains": ["settings"],
        "model": "minicpm-v:8b",
    },
]

SPECIALIST_TESTS = [
    {
        "name": "S1: Anomaly assessment — missing GMS",
        "prompt": """You are a mobile device security specialist. Analyze this device anomaly report and provide patching recommendations.

DEVICE: Samsung S25 Ultra (SM-S938U), Android 14, Redroid container
ANOMALIES DETECTED:
- ro.product.first_api_level = 21 (should be 34 for S25U)
- Missing /sys/class/thermal/ entries
- No SIM card detected (telephony.sim.state = ABSENT)  
- Battery level stuck at 100% (not changing)
- Bluetooth MAC = 00:00:00:00:00:00

Rate severity 1-10 for each anomaly and suggest specific patches (setprop commands, file modifications, or behavioral changes).""",
        "model": "titan-specialist:7b",
        "expect_contains": ["first_api_level", "thermal", "patch"],
    },
    {
        "name": "S2: Wallet provisioning guidance",
        "prompt": """You are a wallet provisioning specialist. A device has Google Pay installed but shows 0 payment cards.

DEVICE STATE:
- Google Pay (com.google.android.apps.walletnfcrel) installed, version 26.10
- Google Play Services (com.google.android.gms) v26.10.34
- No Google account signed in
- tapandpay.db exists but has 0 rows in tokens table
- Chrome autofill has 0 credit cards

What are the required steps to provision a Visa card ending in 4242 into this device? Include database tables to modify and file paths.""",
        "model": "titan-specialist:7b",
        "expect_contains": ["tapandpay", "token"],
    },
    {
        "name": "S3: Profile injection quality check",
        "prompt": """You are a device aging specialist. Evaluate this injected profile for realism gaps:

PROFILE: TITAN-ABC123
- Cookies: 45 injected (Chrome)
- History: 200 URLs (all from last 3 days)  
- Contacts: 12 contacts (all added same timestamp)
- SMS: 30 messages (all from last week)
- Call logs: 50 entries
- Gallery photos: 5 (all exactly 1920x1080, no EXIF GPS)
- Autofill: 1 profile (name, email, phone)
- Chrome localStorage: 8 entries

What forensic indicators would flag this as synthetic? Rate overall realism 1-100.""",
        "model": "titan-specialist:7b",
        "expect_contains": ["timestamp", "forensic"],
    },
]


def run_vision_test_remote(setup_cmd: str, setup_wait: int, prompt: str, model: str, timeout: int = 90) -> tuple:
    """Run a vision test entirely on OVH to avoid large data transfer.
    Returns (response_text, duration)."""
    # Setup screen
    if setup_cmd:
        ssh_cmd(setup_cmd)
        time.sleep(setup_wait)
    
    # Build and run entire pipeline on OVH
    escaped_prompt = prompt.replace('"', '\\"').replace("'", "'\\''")
    remote_script = f'''
import json, base64, io, time, urllib.request
from PIL import Image
import subprocess

# 1. Capture screenshot
r = subprocess.run("adb -s {ADB_TARGET} exec-out screencap -p", shell=True, capture_output=True, timeout=10)
if not r.stdout or len(r.stdout) < 1000:
    print(json.dumps({{"error": "screenshot failed"}}))
    exit()

# 2. Resize and encode
img = Image.open(io.BytesIO(r.stdout)).convert("RGB")
w,h = img.size
ratio = min(768/w, 1.0)
img = img.resize((int(w*ratio), int(h*ratio)))
buf = io.BytesIO()
img.save(buf, "JPEG", quality=50)
b64_img = base64.b64encode(buf.getvalue()).decode()

# 3. Query vision model
payload = json.dumps({{
    "model": "{model}",
    "prompt": "{escaped_prompt}",
    "images": [b64_img],
    "stream": False,
    "options": {{"temperature": 0.2, "num_predict": 400}},
}}).encode()

t0 = time.time()
try:
    req = urllib.request.Request("{OLLAMA_URL}/api/generate", data=payload, headers={{"Content-Type": "application/json"}})
    with urllib.request.urlopen(req, timeout={timeout}) as resp:
        data = json.loads(resp.read().decode())
        response = data.get("response", "")
        dur = time.time() - t0
        print(json.dumps({{"response": response[:800], "duration": dur, "img_size": len(b64_img)}}))
except Exception as e:
    print(json.dumps({{"error": str(e), "duration": time.time() - t0}}))
'''
    
    # Write script to OVH and run it
    import tempfile as _tf
    with _tf.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(remote_script)
        local_script = f.name
    try:
        subprocess.run(
            f'scp -i {SSH_KEY} -o StrictHostKeyChecking=no {local_script} root@{OVH_HOST}:/tmp/vision_test.py',
            shell=True, capture_output=True, timeout=15
        )
    finally:
        import os
        os.unlink(local_script)
    
    t0 = time.time()
    rc, out = ssh_cmd(f"/opt/titan-v11.3-device/venv/bin/python3 /tmp/vision_test.py", timeout=timeout + 30)
    dur = time.time() - t0
    
    if rc != 0 or not out:
        return "", dur
    try:
        data = json.loads(out)
        if "error" in data:
            return "", dur
        return data.get("response", ""), data.get("duration", dur)
    except:
        return out[:500], dur


def run_vision_tests():
    """Run vision model tests with real screenshots."""
    print("\n" + "="*70)
    print("PHASE 3A: VISION MODEL TESTS (minicpm-v:8b)")
    print("="*70)
    
    for test in VISION_TESTS:
        name = test["name"]
        print(f"\n{'─'*60}")
        print(f"  {name}")
        print(f"{'─'*60}")
        
        result = TestResult(name=name, category="vision", model=test["model"])
        
        resp, dur = run_vision_test_remote(
            setup_cmd=test.get("setup_cmd", ""),
            setup_wait=test.get("setup_wait", 3),
            prompt=test["prompt"],
            model=test["model"],
        )
        result.duration = dur
        result.raw_response = resp[:500]
        
        if not resp:
            result.status = "error"
            result.details = "Empty response or screenshot failed"
            result.gaps.append("EMPTY_VISION_RESPONSE")
            RESULTS.append(result)
            print(f"  ❌ ERROR: No response ({dur:.1f}s)")
            continue
        
        # Check expected content
        resp_lower = resp.lower()
        found = []
        missing = []
        for expected in test.get("expect_contains", []):
            if expected.lower() in resp_lower:
                found.append(expected)
            else:
                missing.append(expected)
        
        if not missing:
            result.status = "pass"
            result.details = f"Found all expected terms: {found}"
            print(f"  ✅ PASS: Found {found} ({dur:.1f}s)")
        elif found:
            result.status = "partial"
            result.details = f"Found {found}, missing {missing}"
            result.gaps.append(f"MISSING_TERMS: {missing}")
            print(f"  ⚠️ PARTIAL: Found {found}, missing {missing} ({dur:.1f}s)")
        else:
            result.status = "fail"
            result.details = f"Missing all expected: {missing}"
            result.gaps.append(f"VISION_BLIND: none of {missing} found")
            print(f"  ❌ FAIL: None of {test['expect_contains']} found ({dur:.1f}s)")
        
        print(f"     Response: {resp[:200]}...")
        RESULTS.append(result)
        time.sleep(1)


def run_specialist_tests():
    """Run specialist model tests."""
    print("\n" + "="*70)
    print("PHASE 3B: SPECIALIST MODEL TESTS (titan-specialist:7b)")
    print("="*70)
    
    for test in SPECIALIST_TESTS:
        name = test["name"]
        print(f"\n{'─'*60}")
        print(f"  {name}")
        print(f"{'─'*60}")
        
        result = TestResult(name=name, category="specialist", model=test["model"])
        
        resp, dur = ollama_generate(test["prompt"], test["model"], timeout=60)
        result.duration = dur
        result.raw_response = resp[:800]
        
        if not resp:
            result.status = "error"
            result.details = "Empty response"
            result.gaps.append("EMPTY_RESPONSE")
            RESULTS.append(result)
            print(f"  ❌ ERROR: Empty response ({dur:.1f}s)")
            continue
        
        # Check expected content
        resp_lower = resp.lower()
        found = []
        missing = []
        for expected in test.get("expect_contains", []):
            if expected.lower() in resp_lower:
                found.append(expected)
            else:
                missing.append(expected)
        
        if not missing:
            result.status = "pass"
            result.details = f"Comprehensive response covering: {found}"
            print(f"  ✅ PASS: Covers {found} ({dur:.1f}s)")
        elif found:
            result.status = "partial"
            result.details = f"Covers {found}, missing {missing}"
            result.gaps.append(f"INCOMPLETE: missing {missing}")
            print(f"  ⚠️ PARTIAL: Covers {found}, missing {missing} ({dur:.1f}s)")
        else:
            result.status = "fail"
            result.gaps.append(f"NO_DOMAIN_KNOWLEDGE: {missing}")
            print(f"  ❌ FAIL: No relevant domain knowledge ({dur:.1f}s)")
        
        # Check response quality
        if len(resp) < 100:
            result.gaps.append("RESPONSE_TOO_SHORT")
        
        print(f"     Response preview: {resp[:250]}...")
        RESULTS.append(result)
        time.sleep(1)


# ═══════════════════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════════════════

def generate_report():
    """Generate markdown gap analysis report."""
    print("\n" + "="*70)
    print("GENERATING GAP ANALYSIS REPORT")
    print("="*70)
    
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r.status == "pass")
    partial = sum(1 for r in RESULTS if r.status == "partial")
    failed = sum(1 for r in RESULTS if r.status in ("fail", "error"))
    
    all_gaps = []
    for r in RESULTS:
        all_gaps.extend(r.gaps)
    
    # Count gap categories
    gap_counts = {}
    for g in all_gaps:
        cat = g.split(":")[0] if ":" in g else g
        gap_counts[cat] = gap_counts.get(cat, 0) + 1
    
    report = f"""# AI Model Testing — Gap Analysis Report
**Date**: {time.strftime('%Y-%m-%d %H:%M UTC')}  
**Server**: OVH KS-4 (51.68.33.34)  
**Device**: Cuttlefish Android 15 (cvd-ovh-1)  
**Models**: titan-agent:7b, titan-specialist:7b, minicpm-v:8b

## Summary

| Metric | Value |
|--------|-------|
| Total tests | {total} |
| Passed | {passed} ({passed*100//max(total,1)}%) |
| Partial | {partial} ({partial*100//max(total,1)}%) |
| Failed/Error | {failed} ({failed*100//max(total,1)}%) |
| Total gaps found | {len(all_gaps)} |

## Results by Category

"""
    # Group by category
    categories = {}
    for r in RESULTS:
        categories.setdefault(r.category, []).append(r)
    
    for cat, results in categories.items():
        cat_pass = sum(1 for r in results if r.status == "pass")
        cat_total = len(results)
        report += f"### {cat.upper()} ({cat_pass}/{cat_total} passed)\n\n"
        report += "| Test | Model | Status | Duration | Details |\n"
        report += "|------|-------|--------|----------|---------|\n"
        for r in results:
            status_emoji = {"pass": "✅", "partial": "⚠️", "fail": "❌", "error": "🔴"}.get(r.status, "❓")
            report += f"| {r.name} | {r.model} | {status_emoji} {r.status} | {r.duration:.1f}s | {r.details[:80]} |\n"
        report += "\n"
    
    # Gap analysis
    report += "## Gap Analysis\n\n"
    if gap_counts:
        report += "### Gap Categories (ranked by frequency)\n\n"
        report += "| Gap Type | Count | Severity | Description |\n"
        report += "|----------|-------|----------|-------------|\n"
        severity_map = {
            "JSON_PARSE_FAILURE": ("CRITICAL", "Model outputs non-JSON text, breaking the action loop"),
            "WRONG_ACTION": ("HIGH", "Model selects incorrect action type for the screen context"),
            "COORD_MISS": ("HIGH", "Tap coordinates miss the target element by >150px"),
            "STUCK_LOOP": ("HIGH", "Agent repeats same action, unable to progress"),
            "EMPTY_RESPONSE": ("HIGH", "Model returns empty/null response"),
            "TASK_FAILED": ("MEDIUM", "Agent task did not complete successfully"),
            "MISSING_CONTENT": ("MEDIUM", "Response lacks expected domain-specific content"),
            "VISION_BLIND": ("MEDIUM", "Vision model fails to identify screen elements"),
            "MISSING_TERMS": ("LOW", "Response partially covers expected content"),
            "INCOMPLETE": ("LOW", "Specialist response missing some domain areas"),
            "RESPONSE_TOO_SHORT": ("LOW", "Model response suspiciously brief"),
            "SCREENSHOT_FAILED": ("INFRA", "Screenshot capture failed (ADB issue)"),
            "ACTION_ERRORS": ("MEDIUM", "Agent produced error actions during task"),
            "NO_DOMAIN_KNOWLEDGE": ("HIGH", "Specialist model lacks required domain knowledge"),
            "EMPTY_VISION_RESPONSE": ("HIGH", "Vision model returns nothing for screenshot"),
        }
        for gap, count in sorted(gap_counts.items(), key=lambda x: -x[1]):
            sev, desc = severity_map.get(gap, ("MEDIUM", gap))
            report += f"| {gap} | {count} | {sev} | {desc} |\n"
        report += "\n"
    else:
        report += "No gaps detected! All tests passed.\n\n"
    
    # Detailed gap instances
    report += "### Detailed Gap Instances\n\n"
    for r in RESULTS:
        if r.gaps:
            report += f"**{r.name}** ({r.model}):\n"
            for g in r.gaps:
                report += f"- {g}\n"
            report += f"- Raw response: `{r.raw_response[:150]}...`\n\n"
    
    # Recommendations
    report += """## Recommendations

### For titan-agent:7b (Action Model)
1. **JSON compliance**: If parse failures occur, add JSON-only system prompt reinforcement or use constrained decoding
2. **Coordinate accuracy**: Retrain with more diverse screen layouts; ensure training data includes correct coordinates
3. **Loop detection**: Improve action diversity in training data; add "try different approach" examples
4. **Task completion**: Add more "done" detection examples in training data

### For minicpm-v:8b (Vision Model)
1. **Screen element identification**: Fine-tune on Android screenshot → element description pairs
2. **Position estimation**: Improve coordinate prediction from visual layout
3. **App recognition**: Expand training data with more Android app screenshots

### For titan-specialist:7b (Specialist Model)
1. **Domain depth**: Ensure training data covers all anomaly types and wallet provisioning steps
2. **Actionable output**: Train model to produce specific commands/paths, not just descriptions
3. **Forensic analysis**: Add more synthetic profile detection examples

### Infrastructure
1. **CVD Networking**: Cuttlefish Android 15 networking is broken — fix with proper bridge + NAT setup or restart CVD with --net flags
2. **Hostinger VPS**: Connection timed out during testing — verify VPS is running
"""
    
    return report


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Titan V11.3 — AI Model Real-World Testing                 ║")
    print("║  Models: titan-agent:7b, titan-specialist:7b, minicpm-v:8b ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    
    # Verify connectivity
    print("\nVerifying OVH connectivity...")
    rc, out = ssh_cmd("echo OK")
    if rc != 0:
        print(f"FATAL: Cannot connect to OVH: {out}")
        sys.exit(1)
    print(f"  OVH: Connected")
    
    # Verify Ollama
    rc2, out2 = ssh_cmd(f"curl -s {OLLAMA_URL}/api/tags | python3 -c 'import sys,json; print(len(json.loads(sys.stdin.read())[\"models\"]),\"models\")'")
    print(f"  Ollama: {out2}")
    
    # Verify ADB
    rc3, out3 = ssh_cmd(f"adb -s {ADB_TARGET} shell getprop ro.build.version.sdk")
    print(f"  ADB: SDK {out3}")
    
    # Run all phases
    run_inference_tests()
    run_agent_tests()
    run_vision_tests()
    run_specialist_tests()
    
    # Generate report
    report = generate_report()
    
    # Save report
    report_path = "/root/titan-v11.3-device/reports/ai_model_gap_analysis.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\n📄 Report saved to: {report_path}")
    
    # Print summary
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r.status == "pass")
    print(f"\n{'='*60}")
    print(f"FINAL SCORE: {passed}/{total} tests passed ({passed*100//max(total,1)}%)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
