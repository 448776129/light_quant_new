"""news 路由 — 新闻快讯栏目（服务端渲染）。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ..core import storage
from ..core.templates import render
from . import client, service, storage as nstorage

router = APIRouter(prefix="/news", tags=["news"])


def _ctx(result: dict | None = None, symbol_news: list | None = None,
         earnings: list | None = None) -> dict:
    return {
        "stats": nstorage.news_stats(),
        "cfg": nstorage.get_settings(),
        "groups": nstorage.latest_by_source(8),
        "logs": nstorage.list_logs(20),
        "result": storage.dumps(result) if result is not None else None,
        "symbol_news": symbol_news or [],
        "earnings": earnings if earnings is not None else nstorage.list_earnings(30),
        "earnings_stats": nstorage.earnings_stats(),
    }


@router.get("")
async def news_page(request: Request):
    return render(request, "news.html", active="news", ctx=_ctx())


@router.post("/ingest")
async def news_ingest(request: Request):
    result = await asyncio.to_thread(service.ingest)
    return render(request, "news.html", active="news",
                  ctx=_ctx({"msg": f"入库完成：{result.get('inserted')} 条新增 / "
                                   f"{result.get('errors')} 错误",
                            **result}))


@router.post("/settings")
async def news_settings(request: Request,
                        enabled: str = Form("false"),
                        interval_min: str = Form("30")):
    nstorage.save_settings({"enabled": enabled, "interval_min": interval_min})
    return RedirectResponse("/news", status_code=303)


@router.post("/symbol")
async def news_symbol(request: Request,
                      symbol: str = Form(...),
                      days: int = Form(3)):
    """拉取 47 平台 finnhub 标的新股并展示。"""
    from . import client as nclient
    from . import service as nservice
    try:
        items = await asyncio.to_thread(nclient.fetch_platform_news, symbol.strip().upper(), days)
        ins, _ = await asyncio.to_thread(nstorage.upsert_news, items)
        result = {"symbol": symbol.strip().upper(), "inserted": ins, "fetched": len(items)}
    except Exception as e:
        result = {"symbol": symbol.strip().upper(), "error": str(e)}
        items = []
    return render(request, "news.html", active="news",
                  ctx=_ctx(result, items))


@router.post("/earnings")
async def news_earnings(request: Request,
                        days: int = Form(30),
                        symbol: str = Form("")):
    """拉取 47 平台财报日历并入库。"""
    from . import service as nservice
    result = await asyncio.to_thread(nservice.ingest_earnings, days, symbol.strip())
    return render(request, "news.html", active="news",
                  ctx=_ctx(result, earnings=nstorage.list_earnings(50)))
