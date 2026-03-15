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
    import asyncio
    try:
        from mullvad_vpn import MullvadVPN
        vpn = MullvadVPN()
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, vpn.get_status),
            timeout=3.0,
        )
        return result
    except asyncio.TimeoutError:
        return {"vpn": "timeout", "connected": False, "stub": True, "available": False}
    except (ImportError, AttributeError):
        try:
            from mullvad_vpn import get_mullvad_status
            import asyncio as _aio
            loop = _aio.get_event_loop()
            result = await _aio.wait_for(
                loop.run_in_executor(None, get_mullvad_status), timeout=3.0
            )
            return result
        except Exception:
            return {"vpn": "not_configured", "stub": True, "available": False}


@router.post("/vpn/connect")
async def vpn_connect(request: Request):
    import asyncio, functools
    body = await request.json()
    try:
        from mullvad_vpn import MullvadVPN
        vpn = MullvadVPN()
        loop = asyncio.get_event_loop()
        fn = functools.partial(vpn.connect, country=body.get("country", ""), city=body.get("city", ""))
        result = await asyncio.wait_for(loop.run_in_executor(None, fn), timeout=10.0)
        return result
    except asyncio.TimeoutError:
        return {"status": "timeout", "stub": True, "available": False}
    except ImportError:
        return {"status": "vpn_module_unavailable", "stub": True, "available": False}


@router.post("/vpn/disconnect")
async def vpn_disconnect():
    import asyncio
    try:
        from mullvad_vpn import MullvadVPN
        vpn = MullvadVPN()
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(loop.run_in_executor(None, vpn.disconnect), timeout=10.0)
        return result
    except asyncio.TimeoutError:
        return {"status": "timeout", "stub": True, "available": False}
    except ImportError:
        return {"status": "vpn_module_unavailable", "stub": True, "available": False}


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
    import asyncio
    try:
        from forensic_monitor import ForensicMonitor
        monitor = ForensicMonitor()
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(loop.run_in_executor(None, monitor.scan_system_state), timeout=15.0)
        return result
    except asyncio.TimeoutError:
        return {"stub": True, "available": False, "error": "forensic scan timed out"}
    except (ImportError, AttributeError, Exception) as e:
        return {"stub": True, "available": False, "error": str(e)}


@router.get("/shield")
async def network_shield():
    import asyncio
    try:
        from network_shield import NetworkShield
        shield = NetworkShield()
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(loop.run_in_executor(None, shield.get_status), timeout=15.0)
        return result
    except asyncio.TimeoutError:
        return {"stub": True, "available": False, "error": "network shield timed out"}
    except (ImportError, AttributeError, Exception) as e:
        return {"stub": True, "available": False, "error": str(e)}
