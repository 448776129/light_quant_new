"""trading 服务层 — 自动交易（自动交易栏目）+ 手动下单 + 持仓/账户。

自动交易配置（存 trading_settings，自动交易栏目可改）：
  - enabled: true/false          全局开关
  - strategy_ids: "1,2,3"        参与自动交易的策略 id 白名单
  - account: "default"/"acct1"   下单的模拟账号
  - qty: 1                       每信号股数
  - order_type: market/limit     订单类型

自动交易链路：factors 发布 signal.created → on_signal_created
  → 仅处理 strategy_id 在白名单的信号 → 下到配置账号
  （解耦：本模块不 import factors，事件 payload 携带策略 id 与信号）
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ..core import config, events
from ..core.logger import get_logger
from . import client, storage

log = get_logger("trading.service")

DEFAULTS: dict = {
    "enabled": "false",       # 自动执行总开关（默认关，安全）
    "strategy_ids": "",       # 逗号分隔的策略 id 白名单
    "account": "default",     # 下单模拟账号
    "qty": 1,
    "order_type": "market",
}


def get_settings() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(storage._settings())
    return cfg


def save_settings(updates: dict) -> dict:
    storage._save_settings(updates)
    return get_settings()


def active_strategy_ids() -> list[int]:
    """解析启用的策略 id 白名单。"""
    ids = []
    for s in str(get_settings().get("strategy_ids") or "").split(","):
        s = s.strip()
        if s:
            try:
                ids.append(int(s))
            except ValueError:
                pass
    return ids


def setup() -> None:
    """注册事件订阅（main 组装时调用一次）。

    幂等性由 core.events.subscribe 保证（同一 handler 对同一事件只注册一次），
    此处不使用模块级 done 标志——那会让 events.clear() 之后无法重新注册。
    """
    events.subscribe("signal.created", on_signal_created)
    log.info("trading_setup", extra={"accounts": len(client.accounts()),
                                     "mode": config.ALPACA_TRADING_MODE})


def on_signal_created(payload: Any) -> None:
    """处理 factors 发布的信号事件：仅对选中策略、选中账号自动下单。"""
    if not payload:
        return
    cfg = get_settings()
    if cfg.get("enabled") != "true":
        return
    strategy_id = payload.get("strategy_id")
    allow = active_strategy_ids()
    # 白名单为空 = 全部策略；非空则仅白名单内
    if allow and strategy_id is not None and strategy_id not in allow:
        return
    signals = payload.get("signals") or []
    for sg in signals:
        try:
            execute_signal(sg, strategy_id, account=cfg.get("account") or "default",
                           qty=float(cfg.get("qty") or 1),
                           order_type=cfg.get("order_type") or "market")
        except Exception as e:
            storage.add_log("exec_error", f"{sg.get('symbol')}: {e}")
            log.warning("exec_error", extra={"err": str(e), "symbol": sg.get("symbol")})


def execute_signal(signal: dict, strategy_id: int | None = None,
                   account: str = "", qty: float = 1.0,
                   order_type: str = "market") -> dict:
    """对单条信号下单到指定账号。无账号 → 记录 failed 降级。"""
    symbol = str(signal.get("symbol", "")).upper()
    side = str(signal.get("type", "buy")).lower()
    if side not in ("buy", "sell"):
        side = "buy"
    if order_type not in ("market", "limit"):
        order_type = "market"

    if not client.is_available():
        bid = storage.save_order(signal.get("id") or 0, strategy_id or 0, symbol,
                                 side, qty, order_type, "failed",
                                 message="无可用 Alpaca 模拟账号")
        return {"ok": False, "reason": "no_account", "order_id": bid}

    acc = client.get_account_by_id(account) or client.accounts()[0]
    try:
        order = client.submit_order(symbol, side, qty, order_type, account=acc.id)
        status = str(order.get("status") or "submitted")
        bid = storage.save_order(signal.get("id") or 0, strategy_id or 0, symbol,
                                 side, qty, order_type, status,
                                 alpaca_order_id=order.get("id") or "",
                                 message=f"{acc.id}: {order.get('status')}")
        storage.add_log("order_submitted",
                        f"{acc.id} {symbol} {side} qty={qty} id={order.get('id')}")
        log.info("order_submitted", extra={"account": acc.id, "symbol": symbol,
                                           "side": side, "qty": qty,
                                           "order_id": order.get("id")})
        return {"ok": True, "order_id": bid, "alpaca_id": order.get("id"),
                "status": status, "account": acc.id}
    except RuntimeError as e:
        bid = storage.save_order(signal.get("id") or 0, strategy_id or 0, symbol,
                                 side, qty, order_type, "rejected",
                                 message=str(e))
        storage.add_log("order_rejected", f"{symbol}: {e}")
        return {"ok": False, "reason": str(e), "order_id": bid}


def manual_order(symbol: str, side: str, qty: float, account: str = "") -> dict:
    """面板手动下单（指定账号，空=第一个）。"""
    symbol = symbol.strip().upper()
    side = side.lower()
    if not client.is_available():
        return {"ok": False, "error": "无可用 Alpaca 模拟账号"}
    try:
        order = client.submit_order(symbol, side, qty, account=account)
        bid = storage.save_order(0, 0, symbol, side, qty, "market",
                                 str(order.get("status") or "submitted"),
                                 alpaca_order_id=order.get("id") or "",
                                 message=account or "default")
        return {"ok": True, "order_id": bid, "alpaca_id": order.get("id"),
                "status": order.get("status")}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}


def account_summary(account: str = "") -> dict:
    """指定账号的账户概览。"""
    if not client.is_available():
        return {"available": False}
    try:
        acc = client.get_account(account)
        return {
            "available": True,
            "account": (client.get_account_by_id(account) or client.accounts()[0]).id,
            "equity": float(acc.get("equity") or 0),
            "cash": float(acc.get("cash") or 0),
            "buying_power": float(acc.get("buying_power") or 0),
            "currency": acc.get("currency", "USD"),
        }
    except Exception as e:
        return {"available": True, "error": str(e)}


def positions(account: str = "") -> list[dict]:
    """指定账号的当前持仓。"""
    if not client.is_available():
        return []
    try:
        return client.get_positions(account)
    except Exception as e:
        log.warning("positions_error", extra={"err": str(e)})
        return []