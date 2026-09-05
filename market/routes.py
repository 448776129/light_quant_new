"""market 路由 — 历史行情拉取栏目（服务端渲染页面 + 表单操作）。

页面（Jinja2 模板渲染，非前后端分离）：
  GET  /market                   栏目首页：统计 + 配置表单 + 日志 + 标的列表
操作：
  POST /market/import            手动导入本地 CSV（表单提交）
  POST /market/pull              手动拉取最新数据（表单提交）
  POST /market/settings          保存栏目配置（定时开关/间隔/周期/标的）
  GET  /market/bg-status         后台拉取任务状态（页面轮询 JSON）
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..core import storage
from ..core.templates import render
from . import client, service, storage as mstorage

router = APIRouter(prefix="/market", tags=["market"])


def _page_ctx(result: dict | None = None, result_msg: str = "",
              quote: dict | None = None, orderbook: dict | None = None) -> dict:
    stats = mstorage.kline_stats()
    cfg = mstorage.get_settings()
    logs = mstorage.list_logs(20)
    symbols = mstorage.list_symbols_with_kline()
    ctx = {
        "stats": stats,
        "csv_files": len(client.list_csv_symbols()),
        "csv_dir": client._csv_dir(),
        "tv_base": client._base_url(),
        "cfg": cfg,
        "intervals": client.VALID_INTERVALS,
        "logs": logs,
        "symbols": symbols[:200],
        "symbols_count": len(symbols),
        "result": None,
        "ws": service.ws_status(),
        "quote": quote,
        "orderbook": orderbook,
    }
    if result is not None:
        ctx["result"] = storage.dumps(result)
    if result_msg:
        ctx["result_msg"] = result_msg
    return ctx


@router.get("")
async def market_page(request: Request):
    return render(request, "market.html", active="market", ctx=_page_ctx())


@router.post("/import")
async def market_import(request: Request):
    result = await asyncio.to_thread(service.import_csv_all)
    return render(request, "market.html", active="market",
                  ctx=_page_ctx(result, f"✅ 导入完成：{result.get('inserted')} 新增 / "
                                        f"{result.get('updated')} 更新 / {result.get('errors')} 错误"))


@router.post("/pull")
async def market_pull(request: Request, symbols: str = Form("")):
    """拉取最新数据：指定标的同步返回（快）；空=全部走后台任务立即返回。"""
    if symbols and symbols.strip():
        result = await asyncio.to_thread(service.run_manual, symbols.strip())
        return render(request, "market.html", active="market",
                      ctx=_page_ctx(result, f"✅ 拉取完成：{result.get('inserted')} 新增 / "
                                            f"{result.get('updated')} 更新 / {result.get('errors')} 错误"))
    result = await service.run_manual_bg()
    return render(request, "market.html", active="market",
                  ctx=_page_ctx(result, result.get("message", "后台拉取已启动")))


@router.post("/settings")
async def market_settings(request: Request,
                          enabled: str = Form("false"),
                          interval_sec: str = Form("3600"),
                          interval: str = Form("1d"),
                          symbols: str = Form("")):
    mstorage.save_settings({
        "enabled": enabled,
        "interval_sec": interval_sec,
        "interval": interval,
        "symbols": symbols,
    })
    return RedirectResponse("/market", status_code=303)


@router.get("/bg-status")
async def market_bg_status():
    """后台拉取任务状态（页面轮询）。"""
    return JSONResponse(service.bg_status())


@router.post("/quote")
async def market_quote(request: Request, symbol: str = Form(...)):
    """47 平台 futu 实时报价 + 盘口（含延长时段）。"""
    try:
        quote = await asyncio.to_thread(service.get_live_quote, symbol.strip().upper())
        orderbook = await asyncio.to_thread(service.get_live_orderbook, symbol.strip().upper())
        return render(request, "market.html", active="market",
                      ctx=_page_ctx(quote=quote, orderbook=orderbook))
    except Exception as e:
        return render(request, "market.html", active="market",
                      ctx=_page_ctx(result={"error": str(e)}))


@router.post("/subscribe")
async def market_subscribe(request: Request, symbols: str = Form("")):
    """订阅 47 futu WS 实时行情推送。"""
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if syms:
        service.ws_subscribe(syms)
    return render(request, "market.html", active="market",
                  ctx=_page_ctx(result={"msg": f"已订阅 {len(syms)} 个标的: {', '.join(syms)}"}))
