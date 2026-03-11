"""
Titan V11.3 — Targets Router
/api/targets/* — Site analysis, WAF detection, DNS, SSL, scoring
"""

import logging
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/targets", tags=["targets"])
logger = logging.getLogger("titan.targets")


@router.post("/analyze")
async def target_analyze(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from webcheck_engine import WebCheckEngine
        engine = WebCheckEngine()
        result = engine.full_analysis(domain)
        return result
    except ImportError:
        return {"domain": domain, "stub": True, "message": "webcheck_engine not available"}


@router.post("/waf")
async def target_waf(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from waf_detector import WAFDetector
        detector = WAFDetector()
        result = detector.detect(domain)
        return {"domain": domain, "result": result}
    except ImportError:
        return {"domain": domain, "stub": True}


@router.post("/dns")
async def target_dns(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from dns_intel import DNSIntel
        intel = DNSIntel()
        result = intel.lookup(domain)
        return {"domain": domain, "result": result}
    except ImportError:
        return {"domain": domain, "stub": True}


@router.post("/profiler")
async def target_profiler(request: Request):
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from target_profiler import TargetProfiler
        profiler = TargetProfiler()
        result = profiler.profile(domain)
        return {"domain": domain, "result": result}
    except ImportError:
        return {"domain": domain, "stub": True}
