"""
Titan V11.3 — AI Router
/api/ai/* — AI task routing, metrics, providers
"""

import logging
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/ai", tags=["ai"])
logger = logging.getLogger("titan.ai")


@router.get("/status")
async def ai_status():
    try:
        from ai_task_router import AITaskRouter
        ai_router = AITaskRouter()
        return {"providers": ai_router.get_provider_status()}
    except ImportError:
        return {"providers": {}, "stub": True}


@router.post("/query")
async def ai_query(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    model = body.get("model", "")
    try:
        from ai_task_router import AITaskRouter
        ai_router = AITaskRouter()
        result = ai_router.route_query(prompt, model=model)
        return {"result": result}
    except ImportError:
        return {"stub": True}
