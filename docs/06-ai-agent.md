# 06 — AI Device Agent

The `DeviceAgent` class (`core/device_agent.py`) is an autonomous Android device controller powered by GPU-hosted LLM models. It operates on a **See → Think → Act** loop: capture a screenshot, send it to an LLM for visual analysis, execute the chosen action via ADB, and repeat until the task is complete.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [See: ScreenAnalyzer](#2-see-screenanalyzer)
3. [Think: LLM Decision Engine](#3-think-llm-decision-engine)
4. [Act: TouchSimulator](#4-act-touchsimulator)
5. [Model Hierarchy](#5-model-hierarchy)
6. [SensorSimulator — OADEV Noise Model](#6-sensorsimulator--oadev-noise-model)
7. [Task Templates](#7-task-templates)
8. [TrajectoryLogger — Training Data Collection](#8-trajectorylogger--training-data-collection)
9. [DemoRecorder — Human Demonstrations](#9-demorecorder--human-demonstrations)
10. [TaskVerifier — Post-Task Verification](#10-taskverifier--post-task-verification)
11. [Configuration Reference](#11-configuration-reference)
12. [API Endpoints](#12-api-endpoints)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      DeviceAgent Loop                           │
│                                                                  │
│  ┌──────────┐    screenshot    ┌──────────────┐                  │
│  │          │ ──────────────→  │ ScreenAnalyzer│                  │
│  │ Android  │                  │ (base64 PNG)  │                  │
│  │   VM     │ ←─────────────── └──────┬───────┘                  │
│  │ ADB:6520 │   adb input tap         │ ScreenState              │
│  └──────────┘   adb input text        ▼                          │
│                              ┌──────────────┐                   │
│                              │  LLM Model   │                   │
│                              │  (Ollama)    │                   │
│                              │  GPU :11435  │                   │
│                              │  CPU :11434  │                   │
│                              └──────┬───────┘                   │
│                                     │ ActionDecision             │
│                                     ▼                            │
│                              ┌──────────────┐                   │
│                              │TouchSimulator│                   │
│                              │ Fitts's Law  │                   │
│                              │ Micro-tremor │                   │
│                              └──────────────┘                   │
│                                                                  │
│  Each step logged by TrajectoryLogger (screenshot + action)      │
└─────────────────────────────────────────────────────────────────┘
```

**Key parameters:**
```python
GPU_OLLAMA_URL   = "http://127.0.0.1:11435"  # Vast.ai GPU tunnel
CPU_OLLAMA_URL   = "http://127.0.0.1:11434"  # Local CPU fallback
DEFAULT_MODEL    = "hermes3:8b"
MAX_STEPS        = 50                         # Per task
STEP_TIMEOUT     = 30                         # Seconds per step
```

---

## 2. See: ScreenAnalyzer

`ScreenAnalyzer` (`core/screen_analyzer.py`) captures and parses the device screen state.

### Screenshot Capture

```python
# Via ADB screencap
subprocess.run(["adb", "-s", target, "exec-out", "screencap", "-p"],
               capture_output=True)
# Returns PNG bytes → base64-encoded for LLM multimodal input
```

### ScreenState Dataclass

```python
@dataclass
class ScreenState:
    screenshot_b64: str          # Base64 PNG
    ui_elements: List[Dict]      # Parsed UI elements from uiautomator dump
    current_app: str             # Foreground package name
    current_activity: str        # Current Activity class
    keyboard_visible: bool       # IME visible?
    scroll_position: float       # Vertical scroll 0.0-1.0
    screen_width: int
    screen_height: int
    timestamp: float
```

### UI Element Parsing

`ScreenAnalyzer` also runs `uiautomator dump` to extract interactive elements:

```bash
adb shell uiautomator dump /dev/tty
```

Output XML is parsed to extract: element bounds, text, content-description, class, clickable, scrollable, focused. This gives the LLM structured information about what's on screen in addition to the visual screenshot.

---

## 3. Think: LLM Decision Engine

The LLM receives a multimodal prompt containing:
1. The current task description
2. Previous steps taken (memory context)
3. The screenshot (base64 PNG)
4. Parsed UI elements (structured XML summary)
5. Available action schema

### System Prompt (abbreviated)

```
You are an autonomous Android device controller. You see the device screen
and must decide the next action to accomplish the task.

Available actions:
- tap(x, y): Tap a screen coordinate
- type(text): Type text using keyboard
- swipe(x1, y1, x2, y2): Swipe gesture
- scroll(direction): scroll_up or scroll_down
- back(): Press back button
- home(): Press home button
- open_app(package): Launch an app
- open_url(url): Open URL in Chrome
- wait(seconds): Wait for loading
- done(reason): Task completed

Respond with JSON: {"action": "tap", "x": 540, "y": 1200, "reason": "..."}
```

### ActionDecision Dataclass

```python
@dataclass
class ActionDecision:
    action: str           # "tap" | "type" | "swipe" | "scroll" | "back" |
                          # "home" | "open_app" | "open_url" | "wait" | "done"
    x: int = 0            # For tap/swipe start
    y: int = 0
    x2: int = 0           # For swipe end
    y2: int = 0
    text: str = ""        # For type action
    package: str = ""     # For open_app
    url: str = ""         # For open_url
    direction: str = ""   # "up" | "down" for scroll
    seconds: float = 1.0  # For wait
    reason: str = ""      # LLM explanation
    confidence: float = 1.0  # 0.0-1.0
```

**Confidence threshold:** Actions with `confidence < 0.7` trigger a retry with a more explicit prompt before execution.

---

## 4. Act: TouchSimulator

`TouchSimulator` (`core/touch_simulator.py`) translates LLM-decided coordinates into human-like ADB input.

### Fitts's Law Trajectory

Real human finger movements follow **Fitts's Law** — the movement time is proportional to the log of distance/target_width. The simulator models this:

```python
def tap(self, x: int, y: int, duration_ms: int = 80):
    """Human-like tap with Fitts's Law trajectory and micro-tremor."""
    # Add Gaussian jitter (±5px) simulating finger imprecision
    jitter_x = int(random.gauss(0, 2.0))
    jitter_y = int(random.gauss(0, 2.0))
    actual_x = max(0, min(self.screen_width, x + jitter_x))
    actual_y = max(0, min(self.screen_height, y + jitter_y))
    
    # Add pre-tap hover pause (50-150ms) — real fingers have approach time
    time.sleep(random.uniform(0.05, 0.15))
    
    # Execute via ADB input
    subprocess.run([
        "adb", "-s", self.target, "shell",
        f"input tap {actual_x} {actual_y}"
    ])
    
    # Post-tap pause (random 200-600ms before next action)
    time.sleep(random.uniform(0.2, 0.6))
```

### Typing Pattern

Character-by-character typing with inter-key delay variation:

```python
def type_text(self, text: str):
    """Type text with realistic keystroke timing."""
    for char in text:
        # Inter-key delay: 80-200ms (varies, faster for common bigrams)
        delay = random.uniform(0.08, 0.20)
        time.sleep(delay)
        
        # Use ADB input text for printable chars
        escaped = char.replace("'", "\\'").replace(" ", "%s")
        subprocess.run([
            "adb", "-s", self.target, "shell",
            f"input text '{escaped}'"
        ])
    
    # Post-typing pause
    time.sleep(random.uniform(0.3, 0.8))
```

### Swipe Gesture

```python
def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
    """Natural scroll swipe — curved path with velocity curve."""
    # ADB swipe with duration (simulates real finger speed)
    subprocess.run([
        "adb", "-s", self.target, "shell",
        f"input swipe {x1} {y1} {x2} {y2} {duration_ms}"
    ])
```

---

## 5. Model Hierarchy

The agent auto-detects the best available model at startup via `_detect_best_model()`:

### Action Models (decision + text)

| Priority | Model | Notes |
|----------|-------|-------|
| 1 | `titan-agent:7b` | Fine-tuned LoRA on Titan trajectory data |
| 2 | `hermes3:8b` | Hermes-3 instruction following, strong tool use |
| 3 | `dolphin-llama3:8b` | Uncensored operator for complex/sensitive tasks |
| 4 | `qwen2.5:7b` | Fast general purpose, good for simple navigation |

### Vision Models (screenshot analysis)

| Priority | Model | Notes |
|----------|-------|-------|
| 1 | `titan-screen:7b` | Fine-tuned vision model for Android UI |
| 2 | `minicpm-v:8b` | Excellent mobile UI understanding |
| 3 | `llava:7b` | General vision-language |
| 4 | `llava:13b` | Higher quality, slower |

### Endpoint Priority

```
GPU (Vast.ai via tunnel :11435)  → 41 tok/s warm, 11 tok/s cold
CPU (Local Docker :11434)        → ~4 tok/s (fallback)
```

`_detect_best_model()` queries `/api/tags` on GPU first, falls back to CPU. Result is cached for 60 seconds to avoid repeated API calls.

---

## 6. SensorSimulator — OADEV Noise Model

`SensorSimulator` (`core/sensor_simulator.py`) generates and injects realistic IMU sensor data. This prevents fraud systems from detecting perfectly-static sensor readings (impossible on real devices held by humans).

### OADEV (Allan Deviation) Noise Parameters

Real MEMS sensors have three noise sources modeled by Allan deviation analysis:

```python
@dataclass
class SensorNoiseProfile:
    bias_instability: float   # Long-term drift (mg for accel, °/s for gyro)
    random_walk: float        # White noise integration (mg/√Hz)
    quantization: float       # ADC quantization noise floor
```

### Device-Specific Profiles

| Device Brand | Chip | Accel Bias | Gyro Bias | Notes |
|-------------|------|-----------|---------|-------|
| Samsung | Bosch BMI323 | 0.18 mg | 0.008 °/s | Low noise premium chip |
| Google Pixel | InvenSense ICM-42688 | 0.16 mg | 0.007 °/s | Lowest noise |
| OnePlus/Xiaomi | Bosch BMI270 | 0.20 mg | 0.010 °/s | Mid-tier MEMS |
| Generic | TDK MPU-6500 | 0.24 mg | 0.012 °/s | Budget MEMS |

### Gesture Coupling

When `TouchSimulator` executes a tap or swipe, `SensorSimulator.couple_with_gesture()` injects a correlated IMU burst:

```python
def couple_with_gesture(self, gesture_type: str, magnitude: float = 0.3):
    """Inject sensor burst correlated with a user gesture."""
    if gesture_type == "tap":
        # Short ~200ms burst: accelerometer spike (hand micro-jerk)
        self.inject_sensor_burst("accelerometer", duration_ms=200,
                                  peak_magnitude=magnitude)
    elif gesture_type == "swipe":
        # Longer ~400ms burst: gyroscope rotation + accel
        self.inject_sensor_burst("gyroscope", duration_ms=400,
                                  peak_magnitude=magnitude * 0.6)
        self.inject_sensor_burst("accelerometer", duration_ms=400,
                                  peak_magnitude=magnitude)
```

### Background Noise Injection

`start_background_noise()` launches a background thread that continuously injects low-amplitude noise:

```python
# Every 50-200ms:
accel_noise = [
    random.gauss(0, profile.random_walk) for _ in range(3)  # x, y, z
]
# Write to /dev/input/event{N} or via ADB sendevent
```

---

## 7. Task Templates

`DeviceAgent.TASK_TEMPLATES` contains pre-defined task scaffolds with parameter slots:

| Template | Parameters | Description |
|----------|-----------|-------------|
| `warmup_device` | — | Scroll home screen, open/close apps, mimic natural usage |
| `search_google` | `query` | Open Chrome → google.com → search → browse result |
| `browse_site` | `url` | Navigate to URL, scroll, click 2-3 links |
| `install_app` | `app_name` | Open Play Store → search → install |
| `open_app` | `package` | Launch app, navigate main screen |
| `login_facebook` | `email`, `password` | Full Facebook login flow |
| `browse_amazon` | `product_query` | Amazon search + product page + add to cart |
| `check_gmail` | — | Open Gmail, read top email |
| `take_photo` | — | Open Camera, take photo, return |
| `youtube_video` | `query` | Search YouTube, play first result for 30s |

### Custom Task (Free-form)

```python
agent = DeviceAgent(adb_target="127.0.0.1:6520")
task_id = agent.start_task("Create an account on Venmo using the email alex@gmail.com")
# Returns task_id, runs async in background thread
status = agent.get_task_status(task_id)
```

### Task Status

```python
{
    "task_id": "abc123",
    "status": "completed",        # pending | running | completed | failed
    "steps_taken": 18,
    "elapsed_seconds": 142.3,
    "last_action": {"action": "done", "reason": "Account created successfully"},
    "error": None,
    "trajectory_path": "/opt/titan/data/trajectories/abc123.jsonl"
}
```

---

## 8. TrajectoryLogger — Training Data Collection

`TrajectoryLogger` (`core/trajectory_logger.py`) records every step of every agent task as training data for future LoRA fine-tuning.

### Trajectory Record Format (JSONL)

Each step produces one JSONL line:

```json
{
    "task_id": "abc123",
    "step": 3,
    "timestamp": 1710384000.0,
    "task_prompt": "Create an account on Venmo",
    "screen_state": {
        "screenshot_b64": "iVBORw0KGgoAAAANSUhEUgA...",
        "current_app": "com.venmo",
        "ui_elements_count": 12,
        "keyboard_visible": false
    },
    "action": {
        "action": "tap",
        "x": 540,
        "y": 1200,
        "reason": "Tapping 'Create Account' button"
    },
    "model_used": "hermes3:8b",
    "confidence": 0.92,
    "step_duration_ms": 2340
}
```

### Trajectory Files

- **Location:** `/opt/titan/data/trajectories/{task_id}.jsonl`
- **One file per task**
- **Metadata file:** `{task_id}_meta.json` with task summary

### TrainingDataExporter

`TrainingDataExporter.export_to_chatml()` converts trajectory files into the ChatML format required for Ollama LoRA fine-tuning:

```json
{
    "messages": [
        {"role": "system", "content": "You are an Android device controller..."},
        {"role": "user", "content": "<image>\nTask: Create Venmo account\nPrevious actions: [tap(open_app), ...]"},
        {"role": "assistant", "content": "{\"action\": \"tap\", \"x\": 540, \"y\": 1200}"}
    ]
}
```

---

## 9. DemoRecorder — Human Demonstrations

`DemoRecorder` (`core/demo_recorder.py`) records manually-controlled device interactions as high-quality training demonstrations.

### Recording Workflow

```
POST /api/training/demo/start/{device_id}
{"prompt": "Install Chase app and log in", "task_category": "banking"}
→ Returns: {"session_id": "demo-xyz"}

# Human takes over control via scrcpy or console UI
# Each action is recorded:

POST /api/training/demo/action/{device_id}
{
    "action": "tap", "x": 540, "y": 960,
    "text": "", "reason": "Tapping Sign In button",
    "capture_screen": true
}

POST /api/training/demo/stop/{device_id}
→ Returns trajectory file path
```

### Why Human Demos Matter

The agent's `titan-agent:7b` LoRA is fine-tuned on a mixture of:
- **70% agent-generated trajectories** (automatic, high volume, some errors)
- **30% human demonstrations** (manual, lower volume, expert quality)

Human demos provide recovery behavior examples (handling unexpected popups, CAPTCHA, etc.) that the agent alone can't generate.

---

## 10. TaskVerifier — Post-Task Verification

`TaskVerifier` (`core/task_verifier.py`) verifies device state after an agent task completes.

```python
verifier = TaskVerifier(adb_target="127.0.0.1:6520")
result = await verifier.full_verify(expected_checks=[
    "screen_shows:Welcome",
    "app_installed:com.venmo",
    "file_exists:/data/data/com.venmo/shared_prefs/venmo_prefs.xml",
])
```

### Check Types

| Check Type | Example | Method |
|-----------|---------|--------|
| `screen_shows:{text}` | `screen_shows:Welcome` | `uiautomator dump` grep |
| `app_installed:{pkg}` | `app_installed:com.venmo` | `pm list packages` |
| `file_exists:{path}` | `file_exists:/data/.../prefs.xml` | `ls` check |
| `prop_equals:{k}:{v}` | `prop_equals:gsm.sim.state:READY` | `getprop` |
| `settings_equals:{ns}:{k}:{v}` | `settings_equals:secure:nfc_on:1` | `settings get` |

### VerifyResult Dataclass

```python
@dataclass
class VerifyResult:
    check: str      # "screen_shows:Welcome"
    passed: bool
    detail: str     # What was found
    method: str     # "shell" | "prop" | "settings"
```

---

## 11. Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `TITAN_GPU_OLLAMA` | `http://127.0.0.1:11435` | GPU Ollama endpoint (Vast.ai tunnel) |
| `TITAN_CPU_OLLAMA` | `http://127.0.0.1:11434` | CPU Ollama endpoint (local Docker) |
| `TITAN_AGENT_MODEL` | `hermes3:8b` | Default action model override |
| `TITAN_AGENT_MAX_STEPS` | `50` | Max steps before task declared failed |
| `TITAN_AGENT_STEP_TIMEOUT` | `30` | Seconds per step before timeout |
| `TITAN_TRAINED_ACTION` | `titan-agent:7b` | Fine-tuned action model name |
| `TITAN_TRAINED_VISION` | `titan-screen:7b` | Fine-tuned vision model name |

---

## 12. API Endpoints

### AI Router (`/api/ai`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/ai/status` | GPU/CPU Ollama status + available models |
| `POST` | `/api/ai/{device_id}/task` | Start autonomous agent task |
| `GET` | `/api/ai/{device_id}/task/{task_id}` | Get task status + trajectory |
| `POST` | `/api/ai/{device_id}/tap` | Manual tap via TouchSimulator |
| `POST` | `/api/ai/{device_id}/type` | Manual text input |
| `POST` | `/api/ai/{device_id}/screenshot` | Capture + return screenshot |
| `POST` | `/api/ai/{device_id}/faceswap` | GPU face-swap (source_b64 + target_b64) |
| `GET` | `/api/ai/{device_id}/vision` | Screen analysis via vision model |

### Training Router (`/api/training`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/training/demo/start/{device_id}` | Start demo recording session |
| `POST` | `/api/training/demo/action/{device_id}` | Record a manual action |
| `POST` | `/api/training/demo/stop/{device_id}` | Stop recording, save trajectory |
| `GET` | `/api/training/trajectories` | List all trajectory files |
| `POST` | `/api/training/export` | Export trajectories as ChatML JSONL |
| `POST` | `/api/training/scenarios/run` | Run batch scenario across fleet |
| `GET` | `/api/training/scenarios/status/{batch_id}` | Check batch status |

### Task Request Body

```json
{
    "task": "Open Chrome and go to amazon.com, search for headphones, add the first result to cart",
    "max_steps": 30
}
```

### Task Response

```json
{
    "task_id": "t-abc123",
    "status": "running",
    "device_id": "dev-a3f12b",
    "poll_url": "/api/ai/dev-a3f12b/task/t-abc123"
}
```

---

*See [07-titan-console.md](07-titan-console.md) for the full web console UI reference.*
