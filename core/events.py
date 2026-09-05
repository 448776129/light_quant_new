"""事件总线 — 模块间解耦通信（发布/订阅）。

用途示例：
  - factors 模块产出新信号 → publish("signal.created", signal)
  - trading 模块 subscribe("signal.created") → 自动执行
  发布方不知道订阅方是谁，订阅方不知道发布方是谁 → 模块零直接依赖。
"""
from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from typing import Any, Awaitable, Callable

from .logger import get_logger

log = get_logger("events")

_handlers: dict[str, list[Callable]] = defaultdict(list)
_async_handlers: dict[str, list[Callable]] = defaultdict(list)


def subscribe(event: str, handler: Callable) -> None:
    """注册事件处理器。async 函数走异步队列，同步函数同步执行。

    幂等：同一 handler 对同一事件只注册一次。
    原因：入口模块可能被重复执行（`python -m light_quant_new.main` 时
    __main__ 与 uvicorn 的字符串导入各一次），若不幂等，signal.created
    会被订阅多次，导致同一信号触发多笔下单。
    """
    bucket = _async_handlers if inspect.iscoroutinefunction(handler) else _handlers
    if any(h is handler for h in bucket[event]):
        return
    bucket[event].append(handler)


def publish(event: str, payload: Any = None) -> None:
    """同步发布：执行所有同步处理器；异步处理器由调用方 poll 异步分发。"""
    for h in _handlers.get(event, []):
        try:
            h(payload)
        except Exception as e:
            log.exception("publish", exc_info=e, extra={"event": event, "handler": getattr(h, "__name__", "?")})


async def publish_async(event: str, payload: Any = None) -> None:
    """异步发布：同步处理器直接执行，异步处理器 await。"""
    for h in _handlers.get(event, []):
        try:
            h(payload)
        except Exception as e:
            log.exception("publish", exc_info=e, extra={"event": event})
    for h in _async_handlers.get(event, []):
        try:
            await h(payload)
        except Exception as e:
            log.exception("publish", exc_info=e, extra={"event": event})


def clear() -> None:
    """清空所有订阅（测试用）。"""
    _handlers.clear()
    _async_handlers.clear()
