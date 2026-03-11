"""
Titan V11.3 — Cerberus Router
/api/cerberus/* — Card validation, batch, BIN intelligence
"""

import logging
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/cerberus", tags=["cerberus"])
logger = logging.getLogger("titan.cerberus")

_engine = None

def _get_engine():
    global _engine
    if _engine is None:
        try:
            from cerberus_core import CerberusValidator
            _engine = CerberusValidator()
            logger.info("CerberusEngine loaded from v11-release")
        except ImportError as e:
            logger.warning(f"CerberusEngine not available: {e}")
    return _engine


@router.post("/validate")
async def cerberus_validate(request: Request):
    body = await request.json()
    engine = _get_engine()
    if engine:
        try:
            card_input = body.get("card_input", body.get("number", ""))
            result = engine.validate(card_input)
            # Convert dataclass result to JSON-safe dict
            import dataclasses, json
            if dataclasses.is_dataclass(result):
                return json.loads(json.dumps(dataclasses.asdict(result), default=str))
            if hasattr(result, 'to_dict'):
                return result.to_dict()
            if hasattr(result, '__dict__'):
                return json.loads(json.dumps(result.__dict__, default=str))
            return {"raw": str(result)}
        except Exception as e:
            logger.exception("Cerberus validate error")
            return {"error": str(e), "status": "error"}
    return {"result": "cerberus_engine_unavailable", "stub": True}


@router.post("/batch")
async def cerberus_batch(request: Request):
    body = await request.json()
    cards = body.get("cards", [])
    engine = _get_engine()
    if not engine:
        return {"results": [], "stub": True}
    results = []
    for card_str in cards:
        try:
            parts = card_str.split("|")
            card_body = {"number": parts[0].replace(" ", "").replace("-", "")}
            if len(parts) >= 2: card_body["exp_month"] = parts[1]
            if len(parts) >= 3: card_body["exp_year"] = parts[2]
            if len(parts) >= 4: card_body["cvv"] = parts[3]
            r = engine.validate(card_str)
            results.append(r)
        except Exception as e:
            results.append({"card": card_str[:10] + "...", "error": str(e)})
    return {"results": results, "total": len(results)}


@router.post("/bin-lookup")
async def cerberus_bin_lookup(request: Request):
    body = await request.json()
    bin_prefix = body.get("bin", "")
    try:
        from bin_database import BINDatabase
        db = BINDatabase()
        result = db.lookup(bin_prefix)
        return {"bin": bin_prefix, "result": result}
    except ImportError:
        return {"bin": bin_prefix, "stub": True}


@router.post("/intelligence")
async def cerberus_intelligence(request: Request):
    body = await request.json()
    bin_prefix = body.get("bin", "")
    try:
        from bin_scanner import BINScanner
        scanner = BINScanner()
        result = scanner.scan(bin_prefix)
        return {"bin": bin_prefix, "result": result}
    except ImportError:
        return {"bin": bin_prefix, "stub": True}
