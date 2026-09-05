"""backtest 服务层 — 取数（注入 provider）+ 跑回测 + 结果入库。"""
from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd

from ..core.logger import get_logger
from . import engine, storage

log = get_logger("backtest.service")

# 行情提供者（main 组装时注入 market 的取数函数）
klines_provider: Optional[Callable] = None


def set_klines_provider(fn: Callable) -> None:
    global klines_provider
    klines_provider = fn


def run(symbol: str, template: str = "dual_ma",
        params: dict | None = None, initial_capital: float = 10000.0,
        ktype: str = "K_DAY") -> dict:
    """对指定标的跑回测并入库。"""
    if klines_provider is None:
        return {"error": "行情提供者未注入"}
    df = klines_provider([symbol], ktype)
    if df is None or df.empty:
        return {"error": f"无 {symbol} 行情数据"}
    result = engine.run_backtest(df, template, params, initial_capital)
    if result.get("error"):
        return result
    bid = storage.save_backtest(symbol, template, result.get("params", {}), result)
    result["backtest_id"] = bid
    log.info("backtest_run", extra={"symbol": symbol, "template": template,
                                    "return_pct": result.get("return_pct")})
    return result


def list_history(limit: int = 50) -> list[dict]:
    return storage.list_backtests(limit)


def stats() -> dict:
    return storage.backtest_stats()
