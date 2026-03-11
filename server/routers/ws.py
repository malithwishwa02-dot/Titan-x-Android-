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


def init(device_manager: DeviceManager):
    global dm
    dm = device_manager


@router.websocket("/ws/screen/{device_id}")
async def ws_screen(websocket: WebSocket, device_id: str):
    await websocket.accept()
    dev = dm.get_device(device_id)
    if not dev:
        await websocket.close(1008, "Device not found")
        return

    try:
        while True:
            data = await dm.screenshot(device_id)
            if data:
                await websocket.send_bytes(data)
            await asyncio.sleep(0.25)  # ~4 FPS screencap
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
