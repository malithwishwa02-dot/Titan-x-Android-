# 10 — Training Pipeline

The Titan V11.3 training pipeline collects agent interaction data, human demonstrations, and scenario trajectories, then exports them for LoRA fine-tuning of the `titan-agent:7b` action model and `titan-screen:7b` vision model. This closes the loop between platform use and model improvement.

---

## Table of Contents

1. [Pipeline Overview](#1-pipeline-overview)
2. [DemoRecorder — Human Demonstrations](#2-demorecorder--human-demonstrations)
3. [TrajectoryLogger — Automated Recording](#3-trajectorylogger--automated-recording)
4. [ScenarioRunner — Batch Generation](#4-scenariorunner--batch-generation)
5. [TrainingDataExporter — JSONL Export](#5-trainingdataexporter--jsonl-export)
6. [LoRA Fine-Tuning Workflow](#6-lora-fine-tuning-workflow)
7. [Model Update Cycle](#7-model-update-cycle)
8. [Training Data Schema](#8-training-data-schema)
9. [API Reference](#9-api-reference)

---

## 1. Pipeline Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                 DATA COLLECTION LAYER                            │
│                                                                  │
│  Human Demo Recording          AI Agent Trajectories             │
│  (DemoRecorder)                (TrajectoryLogger)                │
│  ├── High quality              ├── High volume                   │
│  ├── Expert behavior           ├── Some errors                   │
│  └── 30% of training set       └── 70% of training set           │
│                │                          │                      │
│                └──────────────────────────┘                      │
│                              │                                   │
│                 /opt/titan/data/trajectories/                    │
│                 {task_id}.jsonl + {task_id}_meta.json            │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│              EXPORT LAYER (TrainingDataExporter)                 │
│  ├── Format: ChatML / Alpaca / ShareGPT                          │
│  ├── Filter: by source, model, date, task category              │
│  └── Output: titan-trajectories.jsonl                            │
└──────────────────────────────┬───────────────────────────────────┘
                               │  (download + copy to Vast.ai GPU)
┌──────────────────────────────▼───────────────────────────────────┐
│              FINE-TUNING LAYER (Vast.ai GPU)                     │
│  ├── Base model: hermes3:8b (Ollama)                             │
│  ├── LoRA adapter training on trajectory JSONL                   │
│  ├── Eval: task success rate on held-out scenario set            │
│  └── Output: titan-agent:7b (new LoRA checkpoint)               │
└──────────────────────────────┬───────────────────────────────────┘
                               │  (pull updated model to VPS)
┌──────────────────────────────▼───────────────────────────────────┐
│              DEPLOYMENT (Ollama on VPS/GPU)                      │
│  ├── ollama pull titan-agent:7b                                  │
│  └── _detect_best_model() automatically uses titan-agent:7b     │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. DemoRecorder — Human Demonstrations

**Module:** `core/demo_recorder.py`  
**Router:** `server/routers/training.py`

DemoRecorder captures manually-controlled device interactions with rich annotation metadata. These high-quality expert demonstrations are the most valuable training examples because they include correct recovery behaviors, handling of unexpected UI states, and optimal action selection that autonomous agents rarely discover on their own.

### Session Lifecycle

```
POST /api/training/demo/start/{device_id}
{
    "prompt": "Install Chase mobile app and log in with test credentials",
    "task_category": "banking",
    "app_context": "com.chase.sig.android"
}
→ {"session_id": "demo-abc123", "status": "recording"}
```

During the session, the human operates the device via the Screen Stream tab or directly via ADB/scrcpy.

```
# Record each intentional action:
POST /api/training/demo/action/{device_id}
{
    "action": "tap",
    "x": 540,
    "y": 960,
    "text": "",
    "reason": "Tapping 'Install' button on Play Store",
    "capture_screen": true
}
→ {"step": 3, "screenshot_saved": true}
```

```
POST /api/training/demo/stop/{device_id}
→ {
    "session_id": "demo-abc123",
    "steps_recorded": 14,
    "duration_seconds": 222,
    "trajectory_path": "/opt/titan/data/trajectories/demo-abc123.jsonl"
}
```

### DemoSession Dataclass

```python
@dataclass
class DemoSession:
    session_id: str
    device_id: str
    prompt: str
    task_category: str
    app_context: str
    started_at: float
    steps: List[Dict]      # All recorded step dicts
    is_recording: bool
```

### What Makes a Good Demo

| Quality Factor | Guideline |
|---------------|-----------|
| Step count | 8–40 steps (too few = trivial, too many = wandering) |
| Reason annotation | Every step should have a reason explaining the decision |
| Error handling | Deliberately encounter and recover from one error (popup, loading, wrong screen) |
| Task completion | Always complete the full task — partial demos are filtered out |
| Screenshot capture | Enable for every step (visual context is critical for vision model training) |

### Best Demo Categories

1. **Banking app login** — Covers navigation, form fill, OTP handling
2. **E-commerce checkout** — Covers search, product selection, cart, payment
3. **Account creation** — Covers multi-step forms, email verification
4. **Social media signup** — Covers profile setup, permission dialogs
5. **Wallet activation** — Covers Google Pay setup, card addition flow

---

## 3. TrajectoryLogger — Automated Recording

**Module:** `core/trajectory_logger.py`

Every step of every `DeviceAgent` task is automatically logged by `TrajectoryLogger`. This requires no operator effort and generates high-volume training data as a natural byproduct of platform use.

### Step Record Format

Each step produces one JSONL line appended to `{task_id}.jsonl`:

```json
{
    "task_id": "t-abc123",
    "step": 3,
    "timestamp": 1710384000.0,
    "task_prompt": "Open Chrome and search for headphones on Amazon",
    "step_history": [
        {"step": 1, "action": "open_app", "package": "com.android.chrome"},
        {"step": 2, "action": "tap", "x": 540, "y": 120, "reason": "Tap address bar"}
    ],
    "screen_state": {
        "screenshot_b64": "iVBORw0KGgoAAAANSUhEUgA...",
        "current_app": "com.android.chrome",
        "current_activity": "org.chromium.chrome.browser.ChromeTabbedActivity",
        "ui_elements_count": 8,
        "keyboard_visible": true,
        "scroll_position": 0.0
    },
    "action_taken": {
        "action": "type",
        "text": "amazon.com",
        "reason": "Typing Amazon URL in address bar"
    },
    "model_used": "hermes3:8b",
    "ollama_endpoint": "http://127.0.0.1:11435",
    "confidence": 0.94,
    "step_duration_ms": 2840,
    "inference_time_ms": 1120
}
```

### Task Metadata File

`{task_id}_meta.json`:

```json
{
    "task_id": "t-abc123",
    "source": "agent",
    "device_id": "dev-a3f12b",
    "device_preset": "samsung_s25_ultra",
    "task_prompt": "Open Chrome and search for headphones on Amazon",
    "template": "browse_amazon",
    "params": {"product_query": "headphones"},
    "started_at": 1710384000.0,
    "completed_at": 1710384142.3,
    "duration_seconds": 142.3,
    "total_steps": 18,
    "status": "completed",
    "model_used": "hermes3:8b",
    "verifier_result": {"screen_shows:amazon.com": true, "app_installed:com.android.chrome": true}
}
```

### File Organization

```
/opt/titan/data/trajectories/
├── t-abc123.jsonl          # Step-by-step trajectory
├── t-abc123_meta.json      # Task metadata
├── demo-xyz456.jsonl       # Human demo trajectory
├── demo-xyz456_meta.json   # Demo metadata
├── batch-789_summary.json  # ScenarioRunner batch summary
└── ...
```

### Trajectory Quality Filtering

Before export, `TrainingDataExporter` filters out low-quality trajectories:
- `status != "completed"` → excluded (failed tasks)
- `total_steps < 3` → excluded (trivially short)
- `confidence_avg < 0.6` → excluded (low-confidence throughout)
- Duplicate task+device combinations → deduplicated (keep highest confidence)

---

## 4. ScenarioRunner — Batch Generation

**Module:** `core/scenario_runner.py`  
**Router:** `server/routers/training.py`

`ScenarioRunner` executes task templates across a fleet of devices with varied parameter sets, generating large volumes of training data automatically.

### Batch Execution

```python
runner = ScenarioRunner(device_manager=dm)
batch = await runner.run_batch(
    device_ids    = ["dev-a3f12b", "dev-b4c9d1"],
    templates     = ["warmup_device", "search_google", "browse_amazon"],
    params_sets   = [
        {"query": "best headphones 2026"},
        {"query": "running shoes men size 10"},
        {"query": "coffee maker under 100"},
    ],
    max_steps     = 30,
    retries       = 1,
    result_filter = lambda r: r.status == "completed",
)
# Generates up to 2 devices × 3 templates × 3 param_sets = 18 trajectories
```

### ScenarioResult Dataclass

```python
@dataclass
class ScenarioResult:
    scenario_id: str
    device_id: str
    template: str
    params: Dict
    status: str        # "completed" | "failed" | "timeout"
    steps: int
    duration_seconds: float
    trajectory_path: str
    error: str
```

### Batch Progress Tracking

`GET /api/training/scenarios/status/{batch_id}`

```json
{
    "batch_id": "batch-456",
    "total": 18,
    "completed": 12,
    "failed": 2,
    "running": 2,
    "pending": 2,
    "success_rate": 0.857,
    "results": [...]
}
```

### Parameter Variation Strategy

For maximum training data diversity:

| Template | Vary | Notes |
|----------|------|-------|
| `search_google` | `query` (100+ different queries) | Covers many UI paths |
| `browse_amazon` | `product_query` + `device` | Cross-device variation |
| `warmup_device` | `device` only | Device-specific UI differences |
| `login_facebook` | `email` + `device` | Multi-account login diversity |
| `install_app` | `app_name` | Different Play Store flows |

### Retry Logic

```python
for attempt in range(retries + 1):
    result = await _run_single_scenario(device_id, template, params, max_steps)
    if result.status == "completed":
        break
    if attempt < retries:
        logger.info(f"Retrying scenario {scenario_id} (attempt {attempt+2})")
        await asyncio.sleep(5)  # Brief pause before retry
```

---

## 5. TrainingDataExporter — JSONL Export

**Module:** `core/trajectory_logger.py` (`TrainingDataExporter` class)

Converts raw trajectory files into structured JSONL suitable for Ollama LoRA fine-tuning.

### Export Options

```python
exporter = TrainingDataExporter()
output_path = exporter.export_to_chatml(
    output_file      = "/tmp/titan-trajectories.jsonl",
    source_filter    = "all",          # "all" | "human" | "agent"
    model_filter     = None,           # Filter by model used (e.g., "hermes3:8b")
    days_limit       = 30,             # Only include last N days
    include_vision   = True,           # Include screenshot base64 (multimodal)
    min_steps        = 5,              # Minimum steps per trajectory
    min_confidence   = 0.7,            # Minimum avg confidence
    max_trajectories = 5000,           # Cap total trajectories
)
```

### ChatML Output Format (per trajectory)

Each trajectory becomes one JSON object per step in ChatML format:

```json
{
    "messages": [
        {
            "role": "system",
            "content": "You are an autonomous Android device controller. You see the device screen and must decide the next action to accomplish the task.\n\nAvailable actions: tap(x,y), type(text), swipe(x1,y1,x2,y2), scroll(direction), back(), home(), open_app(package), open_url(url), wait(seconds), done(reason)\n\nRespond with JSON only."
        },
        {
            "role": "user",
            "content": "Task: Open Chrome and search for headphones on Amazon\n\nPrevious actions:\n- Step 1: open_app com.android.chrome\n- Step 2: tap(540, 120) - Tap address bar\n\nCurrent screen:\n<image>\n[base64_screenshot_data]\n\nUI Elements: 8 interactive elements detected. Keyboard visible.\nCurrent app: com.android.chrome\n\nWhat is the next action?"
        },
        {
            "role": "assistant",
            "content": "{\"action\": \"type\", \"text\": \"amazon.com\", \"reason\": \"Typing Amazon URL in address bar\"}"
        }
    ]
}
```

### Export Statistics

After export, the exporter reports:

```
Export Complete
  Total trajectories: 1,247
  Total steps: 18,432
  Human demos: 374 (30%)
  Agent auto: 873 (70%)
  Models: hermes3:8b (82%), qwen2.5:7b (18%)
  Avg steps/trajectory: 14.8
  Avg confidence: 0.87
  Output file: titan-trajectories.jsonl (2.4 GB with screenshots)
  Output file: titan-trajectories-novision.jsonl (180 MB without screenshots)
```

---

## 6. LoRA Fine-Tuning Workflow

### Setup on Vast.ai GPU

```bash
# Connect to Vast.ai GPU instance
ssh -i /root/.ssh/vastai_key -p 28704 ssh2.vast.ai

# Ensure Ollama + GPU working
ollama list
# Should show: hermes3:8b, qwen2.5:7b, ...

# Copy training data from VPS
scp -P 28704 -i /root/.ssh/vastai_key \
    root@72.62.72.48:/tmp/titan-trajectories.jsonl \
    ./titan-trajectories.jsonl
```

### Modelfile for LoRA

Create `Modelfile.titan-agent`:

```
FROM hermes3:8b

# LoRA adapter training data
ADAPTER ./titan-trajectories.jsonl

# System prompt optimization
SYSTEM """You are titan-agent, an autonomous Android device controller.
You analyze device screenshots and UI state to determine the next action.
Always respond with valid JSON action objects."""

# Inference parameters
PARAMETER temperature 0.3
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1
```

### Training Command

```bash
# Create the fine-tuned model
ollama create titan-agent:7b -f Modelfile.titan-agent

# Training runs on GPU (~2-4 hours for 18K steps on RTX 5060)
# Monitor GPU usage
watch -n 2 nvidia-smi
```

### Evaluation

After training, evaluate on a held-out scenario set (10% of scenarios not used in training):

```bash
# Run evaluation batch
POST /api/training/scenarios/run
{
    "device_ids": ["dev-a3f12b"],
    "templates": ["search_google", "browse_amazon", "warmup_device"],
    "use_model": "titan-agent:7b",  # Force use new model
    "eval_mode": true
}

# Compare success rates:
# Before fine-tune: hermes3:8b baseline
# After fine-tune: titan-agent:7b
```

---

## 7. Model Update Cycle

### Pulling Updated Model to VPS

Once training completes and evaluation shows improvement:

```bash
# On Vast.ai GPU: push model to Ollama registry (or use file transfer)
# Option A: Ollama push (if using Ollama Cloud)
ollama push titan-agent:7b

# Option B: File transfer (direct, no registry)
# On GPU: export model
ollama show titan-agent:7b --modelfile > titan-agent-v2.modelfile
cp ~/.ollama/models/blobs/{sha} /tmp/titan-agent-weights.bin

# On VPS: receive and register
scp -P 28704 ... /tmp/titan-agent-weights.bin .
ollama create titan-agent:7b -f titan-agent-v2.modelfile
```

### Auto-Detection

`DeviceAgent._detect_best_model()` polls `/api/tags` on Ollama:

```python
def _detect_best_model(self) -> str:
    PREFERRED_CHAIN = [
        "titan-agent:7b",    # Fine-tuned on platform data (best)
        "hermes3:8b",        # Strong instruction following
        "dolphin-llama3:8b", # Uncensored, good tool use
        "qwen2.5:7b",        # Fast, good for simple tasks
    ]
    for model in PREFERRED_CHAIN:
        if self._model_available(model, self.gpu_url):
            return model
    return "qwen2.5:7b"  # Guaranteed fallback (always available)
```

When `titan-agent:7b` is present, it's automatically used for all new agent tasks without any configuration change.

---

## 8. Training Data Schema

### Step Record Fields

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | str | Unique task identifier |
| `step` | int | Step number (1-based) |
| `timestamp` | float | Unix timestamp |
| `task_prompt` | str | Original task description |
| `step_history` | List[Dict] | Previous steps (action summaries) |
| `screen_state.screenshot_b64` | str | Base64 PNG screenshot |
| `screen_state.current_app` | str | Foreground package |
| `screen_state.current_activity` | str | Current Android Activity |
| `screen_state.ui_elements_count` | int | Parsed interactive elements |
| `screen_state.keyboard_visible` | bool | IME visible |
| `action_taken.action` | str | Action type |
| `action_taken.x/y` | int | Coordinates (for tap/swipe) |
| `action_taken.text` | str | Text input (for type) |
| `action_taken.reason` | str | LLM explanation |
| `model_used` | str | LLM model name |
| `confidence` | float | Action confidence 0.0-1.0 |
| `step_duration_ms` | int | Total step time |
| `inference_time_ms` | int | LLM inference time only |

### Task Metadata Fields

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | str | Unique identifier |
| `source` | str | "agent" or "human" |
| `device_id` | str | Device that ran the task |
| `device_preset` | str | Device model preset used |
| `task_prompt` | str | Task description |
| `template` | str | Template name (if used) |
| `params` | Dict | Template parameters |
| `started_at` | float | Start timestamp |
| `completed_at` | float | End timestamp |
| `duration_seconds` | float | Total task duration |
| `total_steps` | int | Number of steps |
| `status` | str | "completed" / "failed" / "timeout" |
| `model_used` | str | Primary model used |
| `verifier_result` | Dict | TaskVerifier check results |

---

## 9. API Reference

### Training Router (`/api/training`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/training/demo/start/{device_id}` | Start human demo recording |
| `POST` | `/api/training/demo/action/{device_id}` | Record a single action |
| `POST` | `/api/training/demo/stop/{device_id}` | Stop recording, finalize |
| `GET` | `/api/training/trajectories` | List all trajectory files |
| `GET` | `/api/training/trajectories/{task_id}` | Get trajectory file content |
| `DELETE` | `/api/training/trajectories/{task_id}` | Delete trajectory |
| `POST` | `/api/training/export` | Export trajectories as JSONL |
| `GET` | `/api/training/export/status` | Check export job status |
| `POST` | `/api/training/scenarios/run` | Start batch scenario runner |
| `GET` | `/api/training/scenarios/status/{batch_id}` | Check batch status |
| `POST` | `/api/training/scenarios/stop/{batch_id}` | Abort running batch |

### Demo Start Request

```json
{
    "prompt": "Install Chase mobile app and complete onboarding",
    "task_category": "banking",
    "app_context": "com.chase.sig.android"
}
```

### Export Request

```json
{
    "source_filter": "all",
    "days_limit": 30,
    "include_vision": false,
    "min_steps": 5,
    "min_confidence": 0.70,
    "format": "chatml"
}
```

### Scenario Run Request

```json
{
    "device_ids": ["dev-a3f12b", "dev-b4c9d1"],
    "templates": ["warmup_device", "search_google", "browse_amazon"],
    "params_sets": [
        {"query": "best headphones"},
        {"query": "coffee maker"}
    ],
    "max_steps": 30,
    "retries": 1
}
```

---

*See [11-real-world-success-rates.md](11-real-world-success-rates.md) for empirical performance analysis across all system components.*
