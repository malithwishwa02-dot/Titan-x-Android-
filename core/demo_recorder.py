"""
Titan V11.3 — Human Demonstration Recorder
============================================
Records human operator actions on a device as expert demonstration
trajectories for fine-tuning AI agent models.

Flow:
  1. Operator starts a recording session via API
  2. System captures screenshot before each action
  3. Operator sends actions (tap, type, swipe, back, etc.) via API
  4. Each action + screenshot pair is saved as a trajectory step
  5. Session ends → trajectory saved in standard format

The recorded trajectories use the same format as TrajectoryLogger
so they can be directly exported for training.

Usage via API:
    POST /api/demo/start/{device_id}  {"prompt": "Install Chase app", "task_category": "install"}
    POST /api/demo/action/{session_id}  {"action": "tap", "x": 540, "y": 1200, "reason": "..."}
    POST /api/demo/stop/{session_id}
    GET  /api/demo/sessions
"""

import asyncio
import base64
import io
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("titan.demo-recorder")

TRAJECTORY_DIR = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "trajectories"


@dataclass
class DemoSession:
    """Active human demonstration recording session."""
    session_id: str = ""
    device_id: str = ""
    pad_code: str = ""
    prompt: str = ""
    task_category: str = ""
    app_context: str = ""
    started_at: float = 0.0
    status: str = "recording"  # recording | completed | aborted
    steps: int = 0
    _dir: str = ""


class DemoRecorder:
    """Records human demonstrations as training trajectories."""

    def __init__(self):
        self._sessions: Dict[str, DemoSession] = {}

    def start_session(self, device_id: str, pad_code: str = "",
                      prompt: str = "", task_category: str = "",
                      app_context: str = "") -> DemoSession:
        """Start a new recording session."""
        sid = f"demo-{uuid.uuid4().hex[:8]}"
        traj_dir = TRAJECTORY_DIR / sid
        traj_dir.mkdir(parents=True, exist_ok=True)

        session = DemoSession(
            session_id=sid,
            device_id=device_id,
            pad_code=pad_code,
            prompt=prompt,
            task_category=task_category,
            app_context=app_context,
            started_at=time.time(),
            _dir=str(traj_dir),
        )
        self._sessions[sid] = session

        # Write initial metadata
        meta = {
            "task_id": sid,
            "device_id": device_id,
            "device_type": "vmos_cloud" if pad_code else "redroid",
            "prompt": prompt,
            "model": "human_demo",
            "persona": {},
            "template": "",
            "app_context": app_context,
            "task_category": task_category,
            "started_at": session.started_at,
            "completed_at": 0.0,
            "status": "recording",
            "total_steps": 0,
            "successful_steps": 0,
            "duration": 0.0,
            "is_demo": True,
        }
        with open(traj_dir / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2)

        logger.info(f"Demo session started: {sid} on {device_id}")
        return session

    async def record_action(self, session_id: str,
                            action_type: str, params: Dict[str, Any] = None,
                            reason: str = "",
                            screen_b64: str = "",
                            screen_context: str = "") -> Dict[str, Any]:
        """Record a single human action with current screen state."""
        session = self._sessions.get(session_id)
        if not session:
            return {"error": "Session not found"}
        if session.status != "recording":
            return {"error": f"Session is {session.status}"}

        session.steps += 1
        step = session.steps
        params = params or {}
        traj_dir = Path(session._dir)

        # Build action dict
        action = {"action": action_type, "reason": reason}
        action.update(params)

        # Save step JSON
        step_data = {
            "step": step,
            "timestamp": time.time(),
            "screen_context": screen_context[:3000],
            "screen_width": 0,
            "screen_height": 0,
            "current_app": "",
            "element_count": 0,
            "has_screenshot": bool(screen_b64),
            "vision_used": False,
            "vision_description": "",
            "llm_prompt": "",
            "llm_response": "",
            "llm_model": "human_demo",
            "action": action,
            "action_type": action_type,
            "action_success": True,  # human actions assumed successful
            "action_reasoning": reason,
            "screen_changed": True,
            "error": "",
        }

        try:
            with open(traj_dir / f"step_{step:03d}.json", "w") as f:
                json.dump(step_data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write step {step}: {e}")

        # Save screenshot
        if screen_b64:
            try:
                raw = base64.b64decode(screen_b64)
                try:
                    from PIL import Image
                    img = Image.open(io.BytesIO(raw)).convert("RGB")
                    w, h = img.size
                    step_data["screen_width"] = w
                    step_data["screen_height"] = h
                    if w > 768:
                        ratio = 768 / w
                        img = img.resize((768, int(h * ratio)), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=70)
                    jpg = buf.getvalue()
                except ImportError:
                    jpg = raw
                with open(traj_dir / f"step_{step:03d}_screen.jpg", "wb") as f:
                    f.write(jpg)
            except Exception as e:
                logger.debug(f"Screenshot save failed: {e}")

        return {"session_id": session_id, "step": step, "action": action_type}

    async def capture_screen_for_session(self, session_id: str) -> str:
        """Capture current device screen for the session. Returns b64."""
        session = self._sessions.get(session_id)
        if not session or not session.pad_code:
            return ""

        try:
            from vmos_agent_adapter import VMOSScreenAdapter
            adapter = VMOSScreenAdapter(pad_code=session.pad_code)
            state = adapter.capture_and_analyze(use_ui_dump=False)
            return state.screenshot_b64 or ""
        except Exception as e:
            logger.warning(f"Screen capture failed: {e}")
            return ""

    def stop_session(self, session_id: str, status: str = "completed") -> Dict:
        """Stop recording and finalize the trajectory."""
        session = self._sessions.get(session_id)
        if not session:
            return {"error": "Session not found"}

        session.status = status
        traj_dir = Path(session._dir)
        duration = time.time() - session.started_at

        # Update metadata
        try:
            meta_file = traj_dir / "metadata.json"
            meta = json.loads(meta_file.read_text())
            meta["status"] = status
            meta["completed_at"] = time.time()
            meta["total_steps"] = session.steps
            meta["successful_steps"] = session.steps  # human demos = all success
            meta["duration"] = round(duration, 1)
            with open(meta_file, "w") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to finalize metadata: {e}")

        logger.info(f"Demo session {session_id} {status}: {session.steps} steps, {duration:.1f}s")
        return {
            "session_id": session_id,
            "status": status,
            "steps": session.steps,
            "duration": round(duration, 1),
        }

    def list_sessions(self) -> List[Dict]:
        """List all recording sessions."""
        return [
            {
                "session_id": s.session_id,
                "device_id": s.device_id,
                "prompt": s.prompt[:80],
                "task_category": s.task_category,
                "status": s.status,
                "steps": s.steps,
                "started_at": s.started_at,
            }
            for s in self._sessions.values()
        ]

    def get_session(self, session_id: str) -> Optional[DemoSession]:
        return self._sessions.get(session_id)
