"""news 服务层 — 快讯三源入库 + 定时触发。"""
from __future__ import annotations

from ..core.logger import get_logger
from . import client, storage

log = get_logger("news.service")


def ingest(sources: list[str] | None = None, limit: int = 30) -> dict:
    """拉取并入库。sources 空 = 全部三源。返回汇总。"""
    sources = [s for s in (sources or list(client.SOURCES)) if s in client.SOURCES]
    if not sources:
        sources = list(client.SOURCES)
    total_ins = total_err = 0
    errs = []
    per_source = {}
    for src in sources:
        try:
            items = client.fetch(src, limit=limit)
            ins, skipped = storage.upsert_news(items)
            per_source[src] = ins
            total_ins += ins
        except client.NewsSourceError as e:
            total_err += 1
            errs.append(f"{src}: {e}")
    storage.add_log("ingest", ",".join(sources), total_ins, "; ".join(errs[:3]) or "")
    log.info("news_ingest", extra={"sources": sources, "inserted": total_ins,
                                   "per_source": per_source, "err": total_err})
    return {"sources": sources, "inserted": total_ins, "errors": total_err,
            "per_source": per_source, "err_symbols": errs[:10]}


def run_auto() -> dict:
    """定时入库：按配置开关/间隔触发（调度器调用）。"""
    cfg = storage.get_settings()
    if cfg.get("enabled") != "true":
        return {"skipped": True, "message": "新闻定时入库未开启"}
    return ingest(limit=int(cfg.get("limit") or 30))


def ingest_symbol_news(symbol: str, days: int = 3, limit: int = 20) -> dict:
    """拉取并入库 47 平台 finnhub 标的新股。返回汇总。"""
    symbol = symbol.strip().upper()
    try:
        items = client.fetch_platform_news(symbol, days, limit)
    except client.NewsSourceError as e:
        storage.add_log("symbol_news", f"{symbol}: {e}", 0, str(e))
        return {"symbol": symbol, "inserted": 0, "error": str(e)}
    ins, skipped = storage.upsert_news(items)
    storage.add_log("symbol_news", f"{symbol} finnhub", ins, "")
    log.info("symbol_news", extra={"symbol": symbol, "inserted": ins, "skipped": skipped})
    return {"symbol": symbol, "inserted": ins, "skipped": skipped}


def ingest_earnings(days: int = 30, symbol: str = "") -> dict:
    """拉取并入库 47 平台财报日历。返回汇总。"""
    try:
        items = client.fetch_earnings(days, symbol)
    except client.NewsSourceError as e:
        storage.add_log("earnings", f"{symbol or '全部'}: {e}", 0, str(e))
        return {"inserted": 0, "error": str(e)}
    ins, upd = storage.upsert_earnings(items)
    storage.add_log("earnings", f"{symbol or '全部'} days={days}", ins, "")
    log.info("earnings", extra={"days": days, "symbol": symbol or "all",
                                "inserted": ins, "updated": upd, "fetched": len(items)})
    return {"inserted": ins, "updated": upd, "fetched": len(items)}
