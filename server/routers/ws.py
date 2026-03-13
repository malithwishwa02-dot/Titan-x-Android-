"""
Titan V11.3 — WebSocket Router
/ws/* — Screen streaming, log streaming
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from device_manager import DeviceManager

router = APIRouter(tags=["websocket"])
logger = logging.getLogger("titan.ws")

dm: DeviceManager = None
_vmos_bridge = None


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


def _get_vmos():
    global _vmos_bridge
    if _vmos_bridge is None:
        try:
            from vmos_cloud_bridge import VMOSCloudBridge
            _vmos_bridge = VMOSCloudBridge()
        except Exception:
            pass
    return _vmos_bridge


@router.websocket("/ws/screen/{device_id}")
async def ws_screen(websocket: WebSocket, device_id: str):
    await websocket.accept()
    dev = dm.get_device(device_id)
    if not dev:
        await websocket.close(1008, "Device not found")
        return

    try:
        # VMOS Cloud path: fetch screenshot URL, download PNG, relay
        if getattr(dev, "device_type", "redroid") == "vmos_cloud":
            bridge = _get_vmos()
            if not bridge:
                await websocket.close(1011, "VMOS bridge unavailable")
                return
            pad_code = getattr(dev, "vmos_pad_code", "") or device_id
            while True:
                url = await bridge.screenshot(pad_code)
                if url:
                    try:
                        import httpx
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            resp = await client.get(url)
                            if resp.status_code == 200:
                                await websocket.send_bytes(resp.content)
                    except Exception as e:
                        logger.warning(f"VMOS screenshot fetch error: {e}")
                await asyncio.sleep(1.0)  # ~1 FPS for URL-based screenshots
        else:
            # Redroid / ADB path: ~4 FPS screencap
            while True:
                data = await dm.screenshot(device_id)
                if data:
                    await websocket.send_bytes(data)
                await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS screen error: {e}")


@router.websocket("/ws/logs/{device_id}")
async def ws_logs(websocket: WebSocket, device_id: str):
    """Stream device logcat over WebSocket."""
    await websocket.accept()
    dev = dm.get_device(device_id)
    if not dev:
        await websocket.close(1008, "Device not found")
        return

    try:
        proc = await asyncio.create_subprocess_exec(
            "adb", "-s", dev.adb_target, "logcat", "-v", "time",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode("utf-8", errors="replace"))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS logs error: {e}")
    finally:
        try:
            proc.kill()
        except Exception:
            pass
