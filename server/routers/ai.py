"""
Titan V11.3 — AI Router
/api/ai/* — AI task routing, metrics, providers
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
async def ai_status():
    try:
        from ai_task_router import AITaskRouter
        ai_router = AITaskRouter()
        return {"providers": ai_router.get_provider_status()}
    except ImportError:
        return {"providers": {}, "stub": True}
