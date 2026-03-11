"""
Titan V11.3 — Network Router
/api/network/* — VPN, proxy, shield
"""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/network", tags=["network"])


@router.get("/status")
async def network_status():
    try:
        from mullvad_vpn import get_mullvad_status
        return get_mullvad_status()
    except ImportError:
        return {"vpn": "not_connected", "stub": True}


@router.post("/vpn/connect")
async def vpn_connect(request: Request):
    return {"status": "vpn_connect_queued", "stub": True}


@router.post("/proxy-test")
async def proxy_test(request: Request):
    body = await request.json()
    proxy = body.get("proxy", "")
    if not proxy:
        return {"reachable": False, "error": "No proxy specified"}
    # Stub — real implementation tests proxy connectivity
    return {"reachable": False, "proxy": proxy, "stub": True}
