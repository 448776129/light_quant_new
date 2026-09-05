"""backtest 路由 — 历史回测栏目（服务端渲染）。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, Request

from ..core import storage
from ..core.templates import render
from . import engine, service, storage as bstorage

router = APIRouter(prefix="/backtest", tags=["backtest"])


def _ctx(result: dict | None = None, last_symbol: str = "",
         last_template: str = "dual_ma") -> dict:
    return {
        "templates": engine.TEMPLATES,
        "templates_json": storage.dumps(engine.TEMPLATES),
        "stats": service.stats(),
        "history": service.list_history(30),
        "result": result,
        "last_symbol": last_symbol,
        "last_template": last_template,
    }


@router.get("")
async def backtest_page(request: Request):
    return render(request, "backtest.html", active="backtest", ctx=_ctx())


@router.post("/run")
async def backtest_run(request: Request):
    form = await request.form()
    symbol = str(form.get("symbol", "")).strip().upper()
    template = str(form.get("template") or "dual_ma")
    try:
        initial_capital = float(form.get("initial_capital") or 10000)
    except (TypeError, ValueError):
        initial_capital = 10000.0
    params = {}
    tpl = engine.TEMPLATES.get(template)
    if tpl:
        for k, d in tpl["default"].items():
            raw = form.get(f"param_{k}")
            try:
                params[k] = int(float(raw)) if isinstance(d, int) else float(raw)
            except (TypeError, ValueError):
                params[k] = d
    result = await asyncio.to_thread(
        service.run, symbol, template, params, initial_capital)
    return render(request, "backtest.html", active="backtest",
                  ctx=_ctx(result, symbol, template))
