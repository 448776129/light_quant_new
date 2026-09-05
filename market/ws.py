"""market WS — 47 平台 futu 实时行情 WebSocket 客户端（含延长时段）。

协议（与旧系统一致）：ws://{PLATFORM_BASE}/ws/stream
  发送：{"type": "subscribe", "symbols": ["AAPL", ...]}  /  unsubscribe
  接收：{"type": "...", "data": {...}}  — 逐条转发给订阅回调
自动重连（指数退避）+ 重连后恢复订阅。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Optional

from ..core import config
from ..core.logger import get_logger

log = get_logger("market.ws")

MessageHandler = Callable[[str, Any], Any]


class MarketWS:
    def __init__(self, on_message: MessageHandler | None = None):
        self.on_message = on_message
        self._ws = None
        self._task: Optional[asyncio.Task] = None
        self._subscribed: set[str] = set()
        self._running = False
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def set_handler(self, handler: MessageHandler) -> None:
        self.on_message = handler

    def subscribe(self, symbols: list[str]) -> None:
        self._subscribed.update(symbols)
        if self._connected and self._ws:
            self._send_safe({"type": "subscribe", "symbols": symbols})

    def unsubscribe(self, symbols: list[str]) -> None:
        for s in symbols:
            self._subscribed.discard(s)
        if self._connected and self._ws:
            self._send_safe({"type": "unsubscribe", "symbols": symbols})

    def _send_safe(self, msg: dict) -> None:
        try:
            asyncio.get_running_loop().create_task(self._ws.send(json.dumps(msg)))
        except Exception:
            pass

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()

    async def _run_loop(self) -> None:
        import websockets
        ws_url = config.PLATFORM_BASE_URL.replace("http", "ws", 1) + "/ws/stream"
        delay = 3.0
        while self._running:
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self._ws = ws
                    self._connected = True
                    delay = 3.0
                    log.info("ws_connected", extra={"url": ws_url})
                    if self._subscribed:
                        await ws.send(json.dumps({"type": "subscribe", "symbols": list(self._subscribed)}))
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        mtype = msg.get("type", "")
                        if self.on_message:
                            try:
                                self.on_message(mtype, msg.get("data", {}))
                            except Exception as e:
                                log.warning("ws_handler", extra={"type": mtype, "err": str(e)})
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._ws = None
                if delay == 3.0:
                    log.warning("ws_disconnect", extra={"err": str(e), "retry_s": round(delay, 1)})
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    break
                delay = min(delay * 2, 60)


# 全局单例
market_ws = MarketWS()
