"""
Titan V11.3 — Targets Router
/api/targets/* — OSINT, WAF, SSL, scoring
"""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/targets", tags=["targets"])


@router.post("/analyze")
async def target_analyze(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from webcheck_engine import WebCheckEngine
        engine = WebCheckEngine()
        result = engine.full_scan(domain)
        return result
    except ImportError:
        return {"domain": domain, "stub": True}
