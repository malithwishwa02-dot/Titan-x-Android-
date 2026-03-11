"""
Titan V11.3 — Intelligence Router
/api/intel/* — AI copilot, recon, OSINT, 3DS strategy, dark web
"""

import logging
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/intel", tags=["intel"])
logger = logging.getLogger("titan.intel")


@router.post("/copilot")
async def intel_copilot(request: Request):
    body = await request.json()
    query = body.get("query", "")
    try:
        from ai_intelligence_engine import AIIntelligenceEngine
        engine = AIIntelligenceEngine()
        result = engine.copilot_query(query)
        return {"result": result}
    except (ImportError, AttributeError):
        try:
            from ai_intelligence_engine import recon_target
            result = recon_target(query)
            return {"result": result}
        except ImportError:
            return {"result": f"AI engine not available. Query: {query}", "stub": True}


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


@router.post("/osint")
async def intel_osint(request: Request):
    """Run OSINT tools (Sherlock, Maigret, Holehe, etc.) on a target."""
    body = await request.json()
    try:
        from osint_orchestrator import OSINTOrchestrator
        orch = OSINTOrchestrator()
        result = orch.investigate(
            name=body.get("name", ""),
            email=body.get("email", ""),
            username=body.get("username", ""),
            phone=body.get("phone", ""),
            domain=body.get("domain", ""),
        )
        return {"result": result}
    except ImportError:
        return {"stub": True, "message": "osint_orchestrator not available"}


@router.post("/3ds-strategy")
async def intel_3ds_strategy(request: Request):
    body = await request.json()
    try:
        from three_ds_strategy import ThreeDSStrategy
        strategy = ThreeDSStrategy()
        result = strategy.analyze(
            merchant=body.get("merchant", ""),
            card_bin=body.get("bin", ""),
            amount=body.get("amount", 0),
        )
        return {"result": result}
    except ImportError:
        return {"stub": True}


@router.post("/darkweb")
async def intel_darkweb(request: Request):
    body = await request.json()
    query = body.get("query", "")
    try:
        from onion_search_engine import OnionSearchEngine
        engine = OnionSearchEngine()
        result = engine.search(query)
        return {"result": result}
    except ImportError:
        return {"query": query, "stub": True}
