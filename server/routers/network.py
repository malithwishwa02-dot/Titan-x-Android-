"""
Titan V11.3 — Network Router
/api/network/* — VPN, proxy, shield, forensic
"""

import logging
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/network", tags=["network"])
logger = logging.getLogger("titan.network")


@router.get("/status")
async def network_status():
    try:
        from mullvad_vpn import MullvadVPN
        vpn = MullvadVPN()
        return vpn.get_status()
    except (ImportError, AttributeError):
        try:
            from mullvad_vpn import get_mullvad_status
            return get_mullvad_status()
        except ImportError:
            return {"vpn": "not_configured", "stub": True}


@router.post("/vpn/connect")
async def vpn_connect(request: Request):
    body = await request.json()
    try:
        from mullvad_vpn import MullvadVPN
        vpn = MullvadVPN()
        result = vpn.connect(
            country=body.get("country", ""),
            city=body.get("city", ""),
        )
        return result
    except ImportError:
        return {"status": "vpn_module_unavailable", "stub": True}


@router.post("/vpn/disconnect")
async def vpn_disconnect():
    try:
        from mullvad_vpn import MullvadVPN
        vpn = MullvadVPN()
        return vpn.disconnect()
    except ImportError:
        return {"status": "vpn_module_unavailable", "stub": True}


@router.post("/proxy-test")
async def proxy_test(request: Request):
    body = await request.json()
    proxy = body.get("proxy", "")
    if not proxy:
        return {"reachable": False, "error": "No proxy specified"}
    try:
        from proxy_quality_scorer import ProxyQualityScorer
        scorer = ProxyQualityScorer()
        result = scorer.test_proxy(proxy)
        return result
    except ImportError:
        # Basic fallback test
        import httpx
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=10) as client:
                r = await client.get("https://httpbin.org/ip")
                return {"reachable": True, "proxy": proxy, "ip": r.json().get("origin", ""), "latency_ms": int(r.elapsed.total_seconds() * 1000)}
        except Exception as e:
            return {"reachable": False, "proxy": proxy, "error": str(e)}


@router.get("/forensic")
async def network_forensic():
    try:
        from forensic_monitor import ForensicMonitor
        monitor = ForensicMonitor()
        return monitor.get_report()
    except ImportError:
        return {"stub": True}


@router.get("/shield")
async def network_shield():
    try:
        from network_shield import NetworkShield
        shield = NetworkShield()
        return shield.get_status()
    except ImportError:
        return {"stub": True}
