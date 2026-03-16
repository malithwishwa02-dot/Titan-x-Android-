"""
Titan V11.3 — Agent Router
/api/agent/* — Autonomous AI device control via GPU LLM
"""

import json
import logging
import os
import urllib.request
from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from device_manager import DeviceManager

router = APIRouter(prefix="/api/agent", tags=["agent"])
logger = logging.getLogger("titan.agent")

dm: DeviceManager = None
_agents: Dict[str, "DeviceAgent"] = {}


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


def cleanup_agent(device_id: str):
    """Remove agent for a deleted device."""
    _agents.pop(device_id, None)


def _get_agent(device_id: str):
    from device_agent import DeviceAgent
    dev = dm.get_device(device_id)
    if not dev:
        raise HTTPException(404, "Device not found")
    if device_id not in _agents:
        # LRU cap: evict oldest if too many agents
        if len(_agents) >= 20:
            oldest = next(iter(_agents))
            _agents.pop(oldest, None)
        _agents[device_id] = DeviceAgent(adb_target=dev.adb_target)
    return _agents[device_id]


class AgentTaskBody(BaseModel):
    prompt: str = ""
    template: str = ""
    template_params: Dict[str, str] = {}
    model: str = ""
    max_steps: int = 30
    persona: Dict[str, str] = {}


@router.post("/task/{device_id}")
async def agent_start_task(device_id: str, body: AgentTaskBody):
    agent = _get_agent(device_id)
    if body.model:
        agent.model = body.model
    task_id = agent.start_task(
        prompt=body.prompt, persona=body.persona if body.persona else None,
        template=body.template if body.template else None,
        template_params=body.template_params if body.template_params else None,
        max_steps=body.max_steps,
    )
    return {"task_id": task_id, "device_id": device_id, "status": "started"}


@router.get("/task/{device_id}/{task_id}")
async def agent_task_status(device_id: str, task_id: str):
    agent = _get_agent(device_id)
    task = agent.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task.to_dict()


@router.post("/stop/{device_id}/{task_id}")
async def agent_stop_task(device_id: str, task_id: str):
    agent = _get_agent(device_id)
    ok = agent.stop_task(task_id)
    return {"stopped": ok, "task_id": task_id}


@router.get("/tasks/{device_id}")
async def agent_list_tasks(device_id: str):
    agent = _get_agent(device_id)
    return {"tasks": agent.list_tasks()}


@router.get("/screen/{device_id}")
async def agent_analyze_screen(device_id: str):
    agent = _get_agent(device_id)
    return agent.analyze_screen()


@router.get("/templates")
async def agent_templates():
    from device_agent import TASK_TEMPLATES
    return {"templates": {k: {"params": v["params"], "prompt": v["prompt"]}
                          for k, v in TASK_TEMPLATES.items()}}


@router.get("/models")
async def agent_models():
    gpu_url = os.environ.get("TITAN_GPU_OLLAMA", "http://127.0.0.1:11435")
    try:
        req = urllib.request.Request(f"{gpu_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1)}
                      for m in data.get("models", [])]
            return {"models": models, "gpu_url": gpu_url, "status": "connected"}
    except Exception as e:
        return {"models": [], "gpu_url": gpu_url, "status": "disconnected", "error": str(e)}
