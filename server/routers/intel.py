"""
Titan V11.3 — Intelligence Router
/api/intel/* — AI copilot, recon
"""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/intel", tags=["intel"])


@router.post("/copilot")
async def intel_copilot(request: Request):
    body = await request.json()
    query = body.get("query", "")
    try:
        from ai_intelligence_engine import recon_target
        result = recon_target(query)
        return {"result": result}
    except ImportError:
        return {"result": f"AI copilot stub response for: {query}", "stub": True}


@router.post("/recon")
async def intel_recon(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from target_intelligence import TargetProfiler
        profiler = TargetProfiler()
        result = profiler.profile(domain)
        return {"result": result}
    except ImportError:
        return {"domain": domain, "stub": True}
