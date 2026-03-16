"""
Titan V11.3 — Settings Router
/api/settings/* — Configuration persistence
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _config_dir() -> Path:
    d = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("")
async def get_settings():
    settings_file = _config_dir() / "settings.json"
    if settings_file.exists():
        return json.loads(settings_file.read_text())
    return {"gpu_url": os.environ.get("TITAN_GPU_URL", ""), "stub": True}


ALLOWED_SETTINGS_KEYS = {
    "gpu_url", "titan_api_secret", "titan_data", "ollama_url",
    "vastai_host", "vastai_port", "theme", "auto_patch", "max_devices",
    "agent_model", "vision_model", "specialist_model",
}


@router.post("")
async def save_settings(request: Request):
    body = await request.json()
    filtered = {k: v for k, v in body.items() if k in ALLOWED_SETTINGS_KEYS}
    # Merge with existing settings so partial updates work
    settings_file = _config_dir() / "settings.json"
    existing = {}
    if settings_file.exists():
        try:
            existing = json.loads(settings_file.read_text())
        except Exception:
            pass
    existing.update(filtered)
    settings_file.write_text(json.dumps(existing, indent=2))
    return {"ok": True, "saved_keys": list(filtered.keys())}
