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


@router.post("")
async def save_settings(request: Request):
    body = await request.json()
    (_config_dir() / "settings.json").write_text(json.dumps(body, indent=2))
    return {"ok": True}
