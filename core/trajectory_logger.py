"""
Titan V11.3 — Trajectory Logger
================================
Records every See→Think→Act step from DeviceAgent
as structured training data for LoRA fine-tuning.

Storage layout:
    /opt/titan/data/trajectories/{task_id}/
        metadata.json          — task prompt, device, model, persona, timestamps
        step_{NNN}.json        — screen context, LLM prompt/response, action, result
        step_{NNN}_screen.jpg  — screenshot before action (resized ≤768px wide)

Training export formats:
    - action_training.jsonl    — instruction→output pairs for action model
    - vision_training.jsonl    — image+prompt→description pairs for vision model

Usage:
    logger = TrajectoryLogger(task_id="task-abc123", device_id="dev-us1")
    logger.set_metadata(prompt="Install Chase app", model="hermes3:8b", persona={...})
    logger.log_step(step=1, screen_b64="...", screen_context="...",
                    llm_prompt="...", llm_response="...",
                    action={"action": "tap", "x": 540, "y": 1200},
                    success=True)
    logger.finalize(status="completed", total_steps=15)
"""

import base64
import io
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.trajectory")

TRAJECTORY_DIR = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "trajectories"


@dataclass
class StepRecord:
    """Single step in a trajectory."""
    step: int = 0
    timestamp: float = 0.0
    # Screen state
    screen_context: str = ""
    screen_width: int = 0
    screen_height: int = 0
    current_app: str = ""
    element_count: int = 0
    has_screenshot: bool = False
    # Vision fallback
    vision_used: bool = False
    vision_description: str = ""
    # LLM interaction
    llm_prompt: str = ""
    llm_response: str = ""
    llm_model: str = ""
    # Parsed action
    action: Dict[str, Any] = field(default_factory=dict)
    action_type: str = ""
    action_success: bool = False
    action_reasoning: str = ""
    # Metadata
    screen_changed: bool = True
    error: str = ""


@dataclass
class TrajectoryMetadata:
    """Metadata for a complete trajectory."""
    task_id: str = ""
    device_id: str = ""
    device_type: str = ""          # cuttlefish
    prompt: str = ""
    model: str = ""
    persona: Dict[str, str] = field(default_factory=dict)
    template: str = ""
    app_context: str = ""          # primary app being used
    task_category: str = ""        # sign_in | install | wallet | aging | browse
    started_at: float = 0.0
    completed_at: float = 0.0
    status: str = ""               # completed | failed | stopped
    total_steps: int = 0
    successful_steps: int = 0
    duration: float = 0.0


class TrajectoryLogger:
    """Records agent trajectories for training data collection."""

    def __init__(self, task_id: str, device_id: str, enabled: bool = True):
        self.task_id = task_id
        self.device_id = device_id
        self.enabled = enabled
        self._metadata = TrajectoryMetadata(task_id=task_id, device_id=device_id)
        self._steps: List[StepRecord] = []
        self._dir: Optional[Path] = None
        self._prev_screen_hash: str = ""

        if self.enabled:
            self._dir = TRAJECTORY_DIR / task_id
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(f"Cannot create trajectory dir {self._dir}: {e}")
                self.enabled = False

    # ─── METADATA ────────────────────────────────────────────────────

    def set_metadata(self, prompt: str = "", model: str = "",
                     persona: Dict[str, str] = None, template: str = "",
                     device_type: str = "", task_category: str = "",
                     app_context: str = ""):
        m = self._metadata
        m.prompt = prompt
        m.model = model
        m.persona = persona or {}
        m.template = template
        m.device_type = device_type
        m.started_at = time.time()
        m.task_category = task_category or self._infer_category(prompt)
        m.app_context = app_context or self._infer_app(prompt)

    # ─── STEP LOGGING ────────────────────────────────────────────────

    def log_step(self, step: int, screen_b64: str = "",
                 screen_context: str = "", screen_width: int = 0,
                 screen_height: int = 0, current_app: str = "",
                 element_count: int = 0,
                 vision_used: bool = False, vision_description: str = "",
                 llm_prompt: str = "", llm_response: str = "",
                 llm_model: str = "",
                 action: Dict[str, Any] = None,
                 action_type: str = "", action_success: bool = False,
                 action_reasoning: str = "", error: str = ""):
        """Log a single See→Think→Act step."""
        if not self.enabled:
            return

        # Detect screen change via hash
        screen_hash = ""
        screen_changed = True
        if screen_b64:
            import hashlib
            screen_hash = hashlib.md5(screen_b64[:1000].encode()).hexdigest()[:12]
            screen_changed = screen_hash != self._prev_screen_hash
            self._prev_screen_hash = screen_hash

        record = StepRecord(
            step=step,
            timestamp=time.time(),
            screen_context=screen_context[:3000],
            screen_width=screen_width,
            screen_height=screen_height,
            current_app=current_app,
            element_count=element_count,
            has_screenshot=bool(screen_b64),
            vision_used=vision_used,
            vision_description=vision_description[:1000],
            llm_prompt=llm_prompt[:4000],
            llm_response=llm_response[:2000],
            llm_model=llm_model,
            action=action or {},
            action_type=action_type,
            action_success=action_success,
            action_reasoning=action_reasoning[:500],
            screen_changed=screen_changed,
            error=error[:500],
        )
        self._steps.append(record)

        # Write step JSON
        try:
            step_file = self._dir / f"step_{step:03d}.json"
            with open(step_file, "w") as f:
                json.dump(asdict(record), f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to write step {step}: {e}")

        # Save screenshot as JPEG
        if screen_b64:
            self._save_screenshot(step, screen_b64)

    def _save_screenshot(self, step: int, b64_data: str):
        """Save base64 screenshot as resized JPEG file."""
        try:
            raw = base64.b64decode(b64_data)
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                w, h = img.size
                if w > 768:
                    ratio = 768 / w
                    img = img.resize((768, int(h * ratio)), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70)
                jpg_bytes = buf.getvalue()
            except ImportError:
                jpg_bytes = raw  # save raw if no PIL

            out = self._dir / f"step_{step:03d}_screen.jpg"
            with open(out, "wb") as f:
                f.write(jpg_bytes)
        except Exception as e:
            logger.debug(f"Failed to save screenshot step {step}: {e}")

    # ─── FINALIZE ────────────────────────────────────────────────────

    def finalize(self, status: str = "completed", total_steps: int = 0):
        """Write final metadata after task completion."""
        if not self.enabled:
            return

        m = self._metadata
        m.status = status
        m.completed_at = time.time()
        m.total_steps = total_steps or len(self._steps)
        m.successful_steps = sum(1 for s in self._steps if s.action_success)
        m.duration = m.completed_at - m.started_at

        try:
            meta_file = self._dir / "metadata.json"
            with open(meta_file, "w") as f:
                json.dump(asdict(m), f, indent=2)
            logger.info(f"Trajectory saved: {self.task_id} ({m.total_steps} steps, "
                        f"{m.status}, {m.duration:.1f}s)")
        except Exception as e:
            logger.warning(f"Failed to write metadata: {e}")

    # ─── CATEGORY INFERENCE ──────────────────────────────────────────

    @staticmethod
    def _infer_category(prompt: str) -> str:
        p = prompt.lower()
        if any(w in p for w in ("sign in", "log in", "login", "sign-in")):
            return "sign_in"
        if any(w in p for w in ("install", "download", "play store")):
            return "install"
        if any(w in p for w in ("wallet", "payment", "card", "pay setup")):
            return "wallet"
        if any(w in p for w in ("browse", "search", "youtube", "scroll")):
            return "browse"
        if any(w in p for w in ("warm", "age", "natural")):
            return "aging"
        return "general"

    @staticmethod
    def _infer_app(prompt: str) -> str:
        p = prompt.lower()
        app_keywords = {
            "play store": "com.android.vending",
            "chrome": "com.android.chrome",
            "instagram": "com.instagram.android",
            "whatsapp": "com.whatsapp",
            "paypal": "com.paypal.android.p2pmobile",
            "venmo": "com.venmo",
            "cash app": "com.squareup.cash",
            "chase": "com.chase.sig.android",
            "bank of america": "com.bankofamerica.cashpromobile",
            "wells fargo": "com.wf.wellsfargomobile",
            "youtube": "com.google.android.youtube",
            "gmail": "com.google.android.gm",
            "google wallet": "com.google.android.apps.walletnfcrel",
            "google pay": "com.google.android.apps.walletnfcrel",
            "samsung pay": "com.samsung.android.spay",
        }
        for keyword, pkg in app_keywords.items():
            if keyword in p:
                return pkg
        return ""


# ═══════════════════════════════════════════════════════════════════════
# TRAINING DATA EXPORT
# ═══════════════════════════════════════════════════════════════════════

class TrainingDataExporter:
    """Export collected trajectories into fine-tuning datasets."""

    def __init__(self, trajectory_dir: str = ""):
        self.base = Path(trajectory_dir) if trajectory_dir else TRAJECTORY_DIR

    def list_trajectories(self, status: str = "completed",
                          category: str = "") -> List[Dict]:
        """List all trajectory metadata, optionally filtered."""
        results = []
        if not self.base.exists():
            return results
        for d in sorted(self.base.iterdir()):
            meta_file = d / "metadata.json"
            if not meta_file.exists():
                continue
            try:
                meta = json.loads(meta_file.read_text())
                if status and meta.get("status") != status:
                    continue
                if category and meta.get("task_category") != category:
                    continue
                meta["path"] = str(d)
                results.append(meta)
            except Exception:
                continue
        return results

    def export_action_training(self, output_path: str = "",
                               min_success_rate: float = 0.5) -> int:
        """Export action model training data as JSONL.

        Format: {"instruction": "<system+screen+history>", "output": "<action JSON>"}
        """
        output = Path(output_path) if output_path else self.base / "action_training.jsonl"
        count = 0

        trajectories = self.list_trajectories(status="completed")
        with open(output, "w") as f:
            for traj in trajectories:
                traj_dir = Path(traj["path"])
                success_rate = traj.get("successful_steps", 0) / max(traj.get("total_steps", 1), 1)
                if success_rate < min_success_rate:
                    continue

                for step_file in sorted(traj_dir.glob("step_*.json")):
                    if "_screen" in step_file.name:
                        continue
                    try:
                        step = json.loads(step_file.read_text())
                    except Exception:
                        continue

                    if not step.get("action_success"):
                        continue
                    if not step.get("llm_prompt") or not step.get("action"):
                        continue

                    record = {
                        "instruction": step["llm_prompt"],
                        "output": json.dumps(step["action"]),
                        "metadata": {
                            "task_id": traj.get("task_id"),
                            "task_category": traj.get("task_category"),
                            "app_context": traj.get("app_context"),
                            "step": step.get("step"),
                            "model": step.get("llm_model"),
                        },
                    }
                    f.write(json.dumps(record) + "\n")
                    count += 1

        logger.info(f"Exported {count} action training examples to {output}")
        return count

    def export_vision_training(self, output_path: str = "") -> int:
        """Export vision model training data as JSONL.

        Format: {"image": "relative/path.jpg", "conversations": [...]}
        Only includes steps where vision was used or screen had elements.
        """
        output = Path(output_path) if output_path else self.base / "vision_training.jsonl"
        count = 0

        trajectories = self.list_trajectories(status="completed")
        with open(output, "w") as f:
            for traj in trajectories:
                traj_dir = Path(traj["path"])

                for step_file in sorted(traj_dir.glob("step_*.json")):
                    if "_screen" in step_file.name:
                        continue
                    try:
                        step = json.loads(step_file.read_text())
                    except Exception:
                        continue

                    step_num = step.get("step", 0)
                    img_file = traj_dir / f"step_{step_num:03d}_screen.jpg"
                    if not img_file.exists():
                        continue
                    if not step.get("screen_context"):
                        continue

                    record = {
                        "image": str(img_file.relative_to(self.base)),
                        "conversations": [
                            {
                                "role": "user",
                                "content": (
                                    "Describe this Android phone screen in detail. "
                                    "List all visible UI elements with their text, type "
                                    "(button, text field, icon, label), and approximate "
                                    "pixel position (x, y) on a "
                                    f"{step.get('screen_width', 1080)}x"
                                    f"{step.get('screen_height', 2400)} screen."
                                ),
                            },
                            {
                                "role": "assistant",
                                "content": step["screen_context"],
                            },
                        ],
                        "metadata": {
                            "task_id": traj.get("task_id"),
                            "app_context": traj.get("app_context"),
                            "current_app": step.get("current_app"),
                            "element_count": step.get("element_count"),
                        },
                    }
                    f.write(json.dumps(record) + "\n")
                    count += 1

        logger.info(f"Exported {count} vision training examples to {output}")
        return count

    def stats(self) -> Dict[str, Any]:
        """Return trajectory collection statistics."""
        all_trajs = self.list_trajectories(status="")
        completed = [t for t in all_trajs if t.get("status") == "completed"]
        failed = [t for t in all_trajs if t.get("status") == "failed"]

        categories = {}
        for t in completed:
            cat = t.get("task_category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

        total_steps = sum(t.get("total_steps", 0) for t in completed)
        total_successful = sum(t.get("successful_steps", 0) for t in completed)

        return {
            "total_trajectories": len(all_trajs),
            "completed": len(completed),
            "failed": len(failed),
            "total_steps": total_steps,
            "successful_steps": total_successful,
            "step_success_rate": round(total_successful / max(total_steps, 1), 3),
            "categories": categories,
            "disk_usage_mb": self._disk_usage(),
        }

    def _disk_usage(self) -> float:
        total = 0
        if self.base.exists():
            for f in self.base.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        return round(total / 1048576, 1)
