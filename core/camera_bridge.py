"""
Titan V11.3 — Redroid Camera Bridge (v4l2loopback Deepfake Injection)
Injects deepfake video into Redroid containers via v4l2loopback virtual camera.

Architecture:
  1. Host creates /dev/video10-13 via v4l2loopback kernel module
  2. ffmpeg encodes deepfaked frames → v4l2 device
  3. Redroid container mounts /dev/video10 as its camera
  4. Android apps see a real camera device for selfie/liveness/KYC

Modes:
  - STATIC: Single face photo → micro-movement video loop
  - PREVIEW: Pre-generated deepfake video → v4l2 injection
  - LIVE: Real-time GPU deepfake (InsightFace) → v4l2 streaming

Usage:
    bridge = CameraBridge(device_id="dev-abc123", video_device="/dev/video10")
    bridge.inject_static("/path/to/face.jpg")
    bridge.inject_live(gpu_url="http://127.0.0.1:8765")
    bridge.stop()
"""

import asyncio
import io
import json
import logging
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("titan.camera-bridge")

TITAN_DATA = Path(os.environ.get("TITAN_DATA", "/opt/titan/data"))
GPU_URL = os.environ.get("TITAN_GPU_URL", "http://127.0.0.1:8765")


@dataclass
class CameraState:
    device_id: str = ""
    video_device: str = "/dev/video10"
    mode: str = "off"  # off, static, preview, live
    active: bool = False
    pid: int = 0
    face_path: str = ""
    gpu_ready: bool = False
    fps: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id, "video_device": self.video_device,
            "mode": self.mode, "active": self.active, "pid": self.pid,
            "face_path": self.face_path, "gpu_ready": self.gpu_ready,
            "fps": self.fps, "error": self.error,
        }


# ═══════════════════════════════════════════════════════════════════════
# V4L2 HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _check_v4l2_device(video_device: str) -> bool:
    """Check if v4l2loopback device exists."""
    return os.path.exists(video_device)


def _get_v4l2_device_for_index(index: int) -> str:
    """Map device index (0-7) to v4l2 device (/dev/video10-17)."""
    return f"/dev/video{10 + index}"


def _generate_micro_movement(face_path: str, output_path: str, duration: int = 10) -> bool:
    """Generate micro-movement video from static face image.
    Adds subtle blink, head movement, and breathing to look alive."""
    try:
        # Create a 10-second loop with subtle zoom/pan to simulate life
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", face_path,
            "-t", str(duration),
            "-vf", (
                "scale=640:480,"
                "zoompan=z='1+0.002*sin(2*PI*t/4)':x='iw/2-(iw/zoom/2)+10*sin(2*PI*t/3)':y='ih/2-(ih/zoom/2)+5*sin(2*PI*t/5)':d=1:s=640x480:fps=30,"
                "eq=brightness=0.02*sin(2*PI*t/6)"
            ),
            "-c:v", "rawvideo", "-pix_fmt", "yuyv422",
            "-r", "30",
            output_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception as e:
        logger.error(f"Micro-movement generation failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
# CAMERA BRIDGE
# ═══════════════════════════════════════════════════════════════════════

class CameraBridge:
    """Injects deepfake video into Redroid via v4l2loopback."""

    def __init__(self, device_id: str, video_device: str = "/dev/video10"):
        self.state = CameraState(device_id=device_id, video_device=video_device)
        self._proc: Optional[subprocess.Popen] = None
        self._live_task: Optional[asyncio.Task] = None

    def get_status(self) -> Dict[str, Any]:
        return self.state.to_dict()

    # ─── MODE 1: STATIC — Single face → micro-movement loop ──────────

    def inject_static(self, face_path: str) -> Dict[str, Any]:
        """Inject static face with micro-movements into v4l2 device."""
        self.stop()

        if not os.path.exists(face_path):
            return {"ok": False, "error": f"Face image not found: {face_path}"}
        if not _check_v4l2_device(self.state.video_device):
            return {"ok": False, "error": f"v4l2 device not found: {self.state.video_device}"}

        # Generate micro-movement video
        tmp_video = tempfile.mktemp(suffix=".raw")
        logger.info(f"Generating micro-movement from {face_path}")
        if not _generate_micro_movement(face_path, tmp_video):
            return {"ok": False, "error": "Failed to generate micro-movement video"}

        # Stream to v4l2 in a loop
        cmd = [
            "ffmpeg", "-re", "-stream_loop", "-1",
            "-i", tmp_video,
            "-f", "v4l2", "-pix_fmt", "yuyv422",
            self.state.video_device,
        ]

        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.state.mode = "static"
            self.state.active = True
            self.state.pid = self._proc.pid
            self.state.face_path = face_path
            self.state.fps = 30.0
            logger.info(f"Static injection started: PID {self._proc.pid}")
            return {"ok": True, "mode": "static", "pid": self._proc.pid}
        except Exception as e:
            self.state.error = str(e)
            return {"ok": False, "error": str(e)}

    # ─── MODE 2: PREVIEW — Pre-generated deepfake video ───────────────

    def inject_preview(self, video_path: str) -> Dict[str, Any]:
        """Inject pre-generated deepfake video file into v4l2 device."""
        self.stop()

        if not os.path.exists(video_path):
            return {"ok": False, "error": f"Video not found: {video_path}"}
        if not _check_v4l2_device(self.state.video_device):
            return {"ok": False, "error": f"v4l2 device not found: {self.state.video_device}"}

        cmd = [
            "ffmpeg", "-re", "-stream_loop", "-1",
            "-i", video_path,
            "-vf", "scale=640:480",
            "-f", "v4l2", "-pix_fmt", "yuyv422",
            self.state.video_device,
        ]

        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.state.mode = "preview"
            self.state.active = True
            self.state.pid = self._proc.pid
            self.state.fps = 30.0
            logger.info(f"Preview injection started: PID {self._proc.pid}")
            return {"ok": True, "mode": "preview", "pid": self._proc.pid}
        except Exception as e:
            self.state.error = str(e)
            return {"ok": False, "error": str(e)}

    # ─── MODE 3: LIVE — Real-time GPU deepfake stream ─────────────────

    async def inject_live(self, gpu_url: str = "") -> Dict[str, Any]:
        """Start real-time deepfake stream from GPU server → v4l2 device."""
        self.stop()

        gpu = gpu_url or GPU_URL
        if not _check_v4l2_device(self.state.video_device):
            return {"ok": False, "error": f"v4l2 device not found: {self.state.video_device}"}

        # Check GPU server connectivity
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{gpu}/status")
                if r.status_code != 200:
                    return {"ok": False, "error": "GPU server not responding"}
                self.state.gpu_ready = True
        except Exception as e:
            return {"ok": False, "error": f"GPU server unreachable: {e}"}

        # Start live streaming task
        self.state.mode = "live"
        self.state.active = True

        self._live_task = asyncio.create_task(self._live_stream_loop(gpu))
        logger.info("Live deepfake injection started")
        return {"ok": True, "mode": "live", "gpu_url": gpu}

    async def _live_stream_loop(self, gpu_url: str):
        """Continuously fetch deepfaked frames from GPU and push to v4l2."""
        import httpx

        # Open v4l2 device for writing via ffmpeg pipe
        cmd = [
            "ffmpeg", "-y",
            "-f", "image2pipe", "-framerate", "5", "-i", "-",
            "-vf", "scale=640:480",
            "-f", "v4l2", "-pix_fmt", "yuyv422",
            self.state.video_device,
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._proc = proc

        frame_count = 0
        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                while self.state.active:
                    try:
                        r = await client.get(f"{gpu_url}/swap", timeout=5)
                        if r.status_code == 200 and proc.stdin:
                            proc.stdin.write(r.content)
                            proc.stdin.flush()
                            frame_count += 1
                            elapsed = time.time() - start_time
                            if elapsed > 0:
                                self.state.fps = round(frame_count / elapsed, 1)
                    except Exception as e:
                        logger.warning(f"Live frame fetch error: {e}")
                    await asyncio.sleep(0.2)  # ~5 FPS target
        except asyncio.CancelledError:
            pass
        finally:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            self.state.active = False
            logger.info(f"Live stream ended: {frame_count} frames")

    # ─── STOP ─────────────────────────────────────────────────────────

    def stop(self) -> Dict[str, Any]:
        """Stop all camera injection."""
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

        if self._live_task and not self._live_task.done():
            self._live_task.cancel()
            self._live_task = None

        was_active = self.state.active
        self.state.mode = "off"
        self.state.active = False
        self.state.pid = 0
        self.state.fps = 0.0

        if was_active:
            logger.info("Camera injection stopped")
        return {"ok": True, "mode": "off"}

    # ─── UPLOAD FACE ──────────────────────────────────────────────────

    def save_face(self, face_data: bytes) -> str:
        """Save uploaded face image and return path."""
        faces_dir = TITAN_DATA / "faces" / self.state.device_id
        faces_dir.mkdir(parents=True, exist_ok=True)
        face_path = faces_dir / "target_face.jpg"
        face_path.write_bytes(face_data)
        self.state.face_path = str(face_path)
        logger.info(f"Face saved: {face_path} ({len(face_data)} bytes)")
        return str(face_path)


# ═══════════════════════════════════════════════════════════════════════
# BRIDGE MANAGER — one bridge per device
# ═══════════════════════════════════════════════════════════════════════

class CameraBridgeManager:
    """Manages camera bridges for all devices."""

    def __init__(self):
        self._bridges: Dict[str, CameraBridge] = {}

    def get_bridge(self, device_id: str, device_index: int = 0) -> CameraBridge:
        if device_id not in self._bridges:
            video_dev = _get_v4l2_device_for_index(device_index)
            self._bridges[device_id] = CameraBridge(device_id, video_dev)
        return self._bridges[device_id]

    def stop_all(self):
        for bridge in self._bridges.values():
            bridge.stop()
        self._bridges.clear()

    def get_all_status(self) -> Dict[str, Any]:
        return {dev_id: bridge.get_status() for dev_id, bridge in self._bridges.items()}
