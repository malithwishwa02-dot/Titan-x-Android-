"""
Titan V11.3 — Cerberus Router
/api/cerberus/* — Card validation, batch, BIN
"""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/cerberus", tags=["cerberus"])


@router.post("/validate")
async def cerberus_validate(request: Request):
    body = await request.json()
    try:
        from cerberus_core import CerberusEngine
        engine = CerberusEngine()
        result = engine.validate_card(body)
        return result
    except ImportError:
        return {"result": "cerberus_stub", "stub": True}
