"""factors 路由 — 因子策略栏目（服务端渲染）。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ..core import storage
from ..core.templates import render
from . import factor_families as ff, service, storage as fstorage

router = APIRouter(prefix="/factors", tags=["factors"])

# 默认 screener 定义（实证最优组合风格）
DEFAULT_SCREENER = {
    "category": "screener",
    "ktype": "K_DAY",
    "combo": [
        {"family": "volume", "params": {"W": 13}},
        {"family": "amihud", "params": {"W": 37}},
        {"family": "momentum", "params": {"L": 158, "S": 14}},
        {"family": "volume", "params": {"W": 39}},
    ],
    "long_pct": 0.1, "short_pct": 0.1,
}
DEFAULT_SINGLE = {
    "category": "single",
    "symbol": "AAPL",
    "ktype": "K_DAY",
    "conditions": {"factor": "momentum(L=20,S=0)", "op": ">", "value": 0.05},
}


def _ctx(result: dict | None = None) -> dict:
    strategies = service.list_strategies()
    for s in strategies:
        d = s.get("definition") or {}
        combo = d.get("combo") or d.get("conditions")
        s["definition_json_short"] = storage.dumps(combo or d)[:80]
    return {
        "families": ff.list_families(),
        "strategies": strategies,
        "signals": fstorage.list_signals(limit=30),
        "default_def": storage.dumps(DEFAULT_SCREENER),
        "result": result,
    }


@router.get("")
async def factors_page(request: Request):
    return render(request, "factors.html", active="factors", ctx=_ctx())


@router.post("/create")
async def factors_create(request: Request, name: str = Form(...),
                         category: str = Form("screener"),
                         definition: str = Form(...)):
    try:
        defn = storage.loads(definition)
        if not isinstance(defn, dict):
            raise ValueError("定义必须是 JSON 对象")
        defn["category"] = category
        sid = await asyncio.to_thread(service.create_strategy, name, defn)
        result = {"ok": True, "id": sid, "msg": f"策略创建成功 #{sid}"}
    except Exception as e:
        result = {"error": str(e)}
    return render(request, "factors.html", active="factors", ctx=_ctx(result))


@router.post("/{sid}/toggle")
async def factors_toggle(sid: int):
    s = await asyncio.to_thread(service.get_strategy, sid)
    if s:
        await asyncio.to_thread(service.update_strategy, sid, enabled=not s.get("enabled"))
    return RedirectResponse("/factors", status_code=303)


@router.post("/{sid}/evaluate")
async def factors_evaluate(sid: int, request: Request):
    s = await asyncio.to_thread(service.get_strategy, sid)
    if not s:
        return RedirectResponse("/factors", status_code=303)
    ktype = (s.get("definition") or {}).get("ktype", "K_DAY")
    cat = (s.get("definition") or {}).get("category", "single")
    try:
        if cat == "screener":
            result = await asyncio.to_thread(service.evaluate_screener, sid, ktype)
        else:
            result = await asyncio.to_thread(service.evaluate_single, sid, ktype)
    except Exception as e:
        result = {"error": str(e)}
    return render(request, "factors.html", active="factors", ctx=_ctx(result))
