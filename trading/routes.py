"""trading 路由 — 自动交易栏目（服务端渲染）。

栏目功能：选择策略 + 勾选模拟账号 → 自动交易；手动下单；账户/持仓/订单/日志。
策略列表经 main 注入的 strategies_provider 获取（解耦点，不直接 import factors）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ..core import storage
from ..core.templates import render
from . import client as tclient
from . import service, storage as tstorage

router = APIRouter(prefix="/trading", tags=["trading"])

# 策略列表提供者（main 组装时注入 factors 的 list_strategies）
strategies_provider: Optional[Callable] = None


def set_strategies_provider(fn: Callable) -> None:
    global strategies_provider
    strategies_provider = fn


def _ctx(order_result: str = "", active_sid: int | None = None,
         view_account: str = "") -> dict:
    cfg = service.get_settings()
    acc_list = tclient.accounts_public()
    # 查看账号：显式指定 > 自动交易配置账号 > 第一个账号
    selected_account = view_account or cfg.get("account") or "default"
    if not any(a["id"] == selected_account for a in acc_list):
        selected_account = acc_list[0]["id"] if acc_list else "default"
    strategies = strategies_provider() if strategies_provider else []
    active_ids = service.active_strategy_ids()
    for s in strategies:
        s["auto_selected"] = (not active_ids) or int(s["id"]) in active_ids

    return {
        "acc": service.account_summary(selected_account),
        "cfg": cfg,
        "accounts": acc_list,
        "strategies": strategies,
        "active_ids": active_ids,
        "selected_account": selected_account,
        "stats": tstorage.trading_stats(),
        "orders": tstorage.list_orders(30),
        "logs": tstorage.list_logs(20),
        "positions": service.positions(selected_account),
        "order_result": order_result or None,
        "active_sid": active_sid,
    }


@router.get("")
async def trading_page(request: Request):
    return render(request, "trading.html", active="trading", ctx=_ctx())


@router.post("/settings")
async def trading_settings(request: Request,
                           enabled: str = Form("false"),
                           strategy_ids: str = Form(""),
                           account: str = Form("default"),
                           qty: str = Form("1"),
                           order_type: str = Form("market")):
    """保存自动交易配置：总开关 + 选中策略 + 模拟账号。"""
    service.save_settings({
        "enabled": enabled,
        "strategy_ids": ",".join(s.strip() for s in strategy_ids.split(",") if s.strip()),
        "account": account,
        "qty": qty,
        "order_type": order_type,
    })
    return RedirectResponse("/trading", status_code=303)


@router.post("/order")
async def trading_order(request: Request,
                        symbol: str = Form(...),
                        side: str = Form("buy"),
                        qty: float = Form(1.0),
                        account: str = Form("")):
    result = await asyncio.to_thread(service.manual_order, symbol, side, qty, account)
    return render(request, "trading.html", active="trading",
                  ctx=_ctx(storage.dumps(result)))


@router.get("/account/{account}")
async def trading_account(account: str, request: Request):
    """切换查看账号的账户/持仓（栏目内切换）。"""
    return render(request, "trading.html", active="trading",
                  ctx=_ctx(view_account=account))