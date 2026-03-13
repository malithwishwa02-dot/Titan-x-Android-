"""
Titan V11.3 — AI Router
/api/ai/* — AI task routing, screen agent, faceswap, vision
"""

import asyncio
import logging
import os
from typing import Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from device_manager import DeviceManager

router = APIRouter(prefix="/api/ai", tags=["ai"])
logger = logging.getLogger("titan.ai")

dm: DeviceManager = None
_agents: Dict[str, object] = {}


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


class ScreenTaskBody(BaseModel):
    task: str
    max_steps: int = 25


class ScreenTapBody(BaseModel):
    x: int
    y: int


class ScreenTypeBody(BaseModel):
    text: str


class FaceSwapBody(BaseModel):
    source_b64: str  # base64 source face image
    target_b64: str  # base64 target image/frame


def _get_agent(pad_code: str):
    """Get or create a VMOSScreenAgent for a device."""
    if pad_code not in _agents:
        try:
            from vmos_screen_agent import VMOSScreenAgent
            _agents[pad_code] = VMOSScreenAgent(pad_code=pad_code)
        except Exception as e:
            logger.error(f"Failed to create agent: {e}")
            return None
    return _agents[pad_code]


@router.get("/status")
async def ai_status():
    """AI system status — Ollama models, vision, faceswap."""
    ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_ok = False
    models = []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ollama_url}/api/tags")
            if resp.status_code == 200:
                ollama_ok = True
                models = [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        pass

    faceswap_ok = False
    try:
        import insightface
        faceswap_ok = True
    except ImportError:
        pass

    return {
        "ollama": {"connected": ollama_ok, "url": ollama_url, "models": models},
        "vision_model": os.environ.get("TITAN_VISION_MODEL", "minicpm-v:8b"),
        "faceswap": {"available": faceswap_ok},
        "active_agents": list(_agents.keys()),
    }


@router.post("/query")
async def ai_query(request: Request):
    """Generic AI text query via Ollama."""
    body = await request.json()
    prompt = body.get("prompt", "")
    model = body.get("model", "minicpm-v:8b")
    ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{ollama_url}/api/generate", json={
                "model": model, "prompt": prompt, "stream": False,
            })
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# SCREEN AGENT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/screen/{device_id}")
async def ai_read_screen(device_id: str):
    """Read the current screen of a VMOS device using vision AI."""
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        raise HTTPException(404, "Device not found")
    if getattr(dev, "device_type", "") != "vmos_cloud":
        raise HTTPException(400, "Screen agent only works with VMOS Cloud devices")

    pad_code = getattr(dev, "vmos_pad_code", "") or device_id
    agent = _get_agent(pad_code)
    if not agent:
        raise HTTPException(500, "Failed to initialize screen agent")

    result = await agent.read_screen()
    return {"device_id": device_id, "pad_code": pad_code, **result}


@router.post("/screen/{device_id}/task")
async def ai_execute_task(device_id: str, body: ScreenTaskBody):
    """Execute a natural language task on the device screen.

    The AI will read the screen, plan actions, and execute them like a human.
    Examples:
      - "Open Chrome and search for weather in NYC"
      - "Go to Settings and turn on WiFi"
      - "Open Instagram and like the first post"
    """
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        raise HTTPException(404, "Device not found")
    if getattr(dev, "device_type", "") != "vmos_cloud":
        raise HTTPException(400, "Screen agent only works with VMOS Cloud devices")

    pad_code = getattr(dev, "vmos_pad_code", "") or device_id
    agent = _get_agent(pad_code)
    if not agent:
        raise HTTPException(500, "Failed to initialize screen agent")

    result = await agent.execute_task(body.task, max_steps=body.max_steps)
    return {"device_id": device_id, "pad_code": pad_code, **result.to_dict()}


@router.post("/screen/{device_id}/tap")
async def ai_tap(device_id: str, body: ScreenTapBody):
    """Tap at specific screen coordinates."""
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        raise HTTPException(404, "Device not found")

    pad_code = getattr(dev, "vmos_pad_code", "") or device_id
    agent = _get_agent(pad_code)
    if not agent:
        raise HTTPException(500, "Failed to initialize screen agent")

    ok = await agent.tap_at(body.x, body.y)
    return {"ok": ok, "x": body.x, "y": body.y}


@router.post("/screen/{device_id}/type")
async def ai_type(device_id: str, body: ScreenTypeBody):
    """Type text into the focused field."""
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        raise HTTPException(404, "Device not found")

    pad_code = getattr(dev, "vmos_pad_code", "") or device_id
    agent = _get_agent(pad_code)
    if not agent:
        raise HTTPException(500, "Failed to initialize screen agent")

    ok = await agent.type_in_focused(body.text)
    return {"ok": ok, "text": body.text}


@router.post("/screen/{device_id}/home")
async def ai_home(device_id: str):
    """Press home button."""
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        raise HTTPException(404, "Device not found")
    pad_code = getattr(dev, "vmos_pad_code", "") or device_id
    agent = _get_agent(pad_code)
    if not agent:
        raise HTTPException(500, "Agent unavailable")
    ok = await agent.go_home()
    return {"ok": ok}


@router.post("/screen/{device_id}/back")
async def ai_back(device_id: str):
    """Press back button."""
    dev = dm.get_device(device_id) if dm else None
    if not dev:
        raise HTTPException(404, "Device not found")
    pad_code = getattr(dev, "vmos_pad_code", "") or device_id
    agent = _get_agent(pad_code)
    if not agent:
        raise HTTPException(500, "Agent unavailable")
    ok = await agent.go_back()
    return {"ok": ok}


@router.post("/screen/{device_id}/open-app")
async def ai_open_app(device_id: str, request: Request):
    """Open an app by package name."""
    body = await request.json()
    package = body.get("package", "")
    if not package:
        raise HTTPException(400, "package required")

    dev = dm.get_device(device_id) if dm else None
    if not dev:
        raise HTTPException(404, "Device not found")

    pad_code = getattr(dev, "vmos_pad_code", "") or device_id
    agent = _get_agent(pad_code)
    if not agent:
        raise HTTPException(500, "Agent unavailable")
    ok = await agent.open_app(package)
    return {"ok": ok, "package": package}


# ═══════════════════════════════════════════════════════════════════════
# FACE SWAP ENDPOINT
# ═══════════════════════════════════════════════════════════════════════

@router.post("/faceswap")
async def ai_faceswap(body: FaceSwapBody):
    """Swap face from source image onto target image.

    Both images should be base64-encoded JPEG/PNG.
    Returns the result image as base64.
    """
    try:
        import insightface
        import numpy as np
        from PIL import Image
        import onnxruntime
        import base64
        import io

        # Decode images
        src_bytes = base64.b64decode(body.source_b64)
        tgt_bytes = base64.b64decode(body.target_b64)

        src_img = np.array(Image.open(io.BytesIO(src_bytes)).convert("RGB"))
        tgt_img = np.array(Image.open(io.BytesIO(tgt_bytes)).convert("RGB"))

        # Detect faces
        face_analyzer = insightface.app.FaceAnalysis(
            name="buffalo_l", providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
        )
        face_analyzer.prepare(ctx_id=0, det_size=(640, 640))

        src_faces = face_analyzer.get(src_img[:, :, ::-1])  # RGB->BGR
        tgt_faces = face_analyzer.get(tgt_img[:, :, ::-1])

        if not src_faces:
            return {"error": "No face detected in source image"}
        if not tgt_faces:
            return {"error": "No face detected in target image"}

        # Load face swapper model
        model_path = "/opt/Deep-Live-Cam/models/inswapper_128.onnx"
        if not os.path.exists(model_path):
            return {"error": "Face swap model not found. Install Deep-Live-Cam first."}

        swapper = insightface.model_zoo.get_model(model_path)

        # Swap face
        result_img = tgt_img.copy()
        for face in tgt_faces:
            result_img = swapper.get(result_img[:, :, ::-1], face, src_faces[0], paste_back=True)
            result_img = result_img[:, :, ::-1]  # BGR->RGB

        # Encode result
        pil_result = Image.fromarray(result_img)
        buf = io.BytesIO()
        pil_result.save(buf, format="JPEG", quality=85)
        result_b64 = base64.b64encode(buf.getvalue()).decode()

        return {"result_b64": result_b64, "faces_detected": len(tgt_faces)}

    except ImportError as e:
        return {"error": f"Missing dependency: {e}. Install insightface and onnxruntime-gpu."}
    except Exception as e:
        logger.exception("Face swap failed")
        return {"error": str(e)}
