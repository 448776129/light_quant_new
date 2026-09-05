"""news 数据源客户端 — stocks-api2 快讯三源（em / yh / 聚合频道）。

字段统一为：title / url / time / digest / source / extra
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from ..core import config
from ..core.logger import get_logger

log = get_logger("news.client")

# stocks-api2 基础地址（与 market 的 stocks-tv 不同管道；独立可配）
BASE = getattr(config, "STOCKS_API2_BASE", "https://stocks-api2.365200.xyz")
TIMEOUT = getattr(config, "STOCKS_API2_TIMEOUT", 20)

SOURCES = ("eastmoney", "yahoo", "aggregate")

# 各源端点构造
_ENDPOINTS = {
    "eastmoney": "/news-em",       # 东财 7x24 快讯
    "yahoo": "/news-yh",           # 雅虎香港头条
    "aggregate": "/news",          # 聚合频道（channel: sina 等）
}


class NewsSourceError(RuntimeError):
    pass


def _get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    full = f"{BASE}{url}?{qs}"
    try:
        req = urllib.request.Request(full, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception as e:
        raise NewsSourceError(f"stocks-api2 拉取失败 {full[:100]}: {e}") from e


def fetch(source: str, limit: int = 30, symbol: str = "") -> list[dict]:
    """拉取指定源新闻，返回统一字段列表。"""
    source = source if source in _ENDPOINTS else "eastmoney"
    params = {"limit": int(limit)}
    if source == "aggregate" and symbol:
        params["symbol"] = symbol
    data = _get(_ENDPOINTS[source], params)
    items = data.get("items") or data.get("data") or []
    if not isinstance(items, list):
        return []
    if source == "eastmoney":
        return [_norm_em(n) for n in items]
    if source == "yahoo":
        return [_norm_yh(n) for n in items]
    return [_norm_agg(n) for n in items]


def _norm_em(n: dict) -> dict:
    return {
        "title": n.get("title", ""),
        "url": n.get("url_pc") or n.get("url_mobile") or n.get("url", ""),
        "time": n.get("showtime", ""),
        "digest": n.get("digest", ""),
        "source": "东方财富",
        "extra": (f"{n.get('comment_num')} 评论" if n.get("comment_num") else ""),
    }


def _norm_yh(n: dict) -> dict:
    t = n.get("pub_time", "") or ""
    return {
        "title": n.get("title", ""),
        "url": n.get("url", ""),
        "time": t.replace("T", " ")[:16] if t else (n.get("rel_time", "") or ""),
        "digest": "",
        "source": "雅虎",
        "extra": "",
    }


def _norm_agg(n: dict) -> dict:
    return {
        "title": n.get("title", ""),
        "url": n.get("url", ""),
        "time": n.get("pub_time", "") or n.get("create_time", "") or "",
        "digest": n.get("digest", ""),
        "source": n.get("channel", "聚合") or "聚合",
        "extra": n.get("publisher", ""),
    }


# ── 47 平台 finnhub 标的新闻（公司新闻）──
PLATFORM_BASE = getattr(config, "PLATFORM_BASE_URL", "http://47.103.124.40:3215")
PLATFORM_TIMEOUT = getattr(config, "PLATFORM_TIMEOUT", 15)


def fetch_platform_news(symbol: str, days: int = 3, limit: int = 20) -> list[dict]:
    """47 平台 finnhub 公司新闻。GET /api/news/{symbol}?days=N。"""
    url = f"{PLATFORM_BASE}/api/news/{urllib.parse.quote(symbol.upper())}?days={int(days)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=PLATFORM_TIMEOUT) as r:
            raw = r.read().decode("utf-8", errors="replace")
        items = json.loads(raw)
    except Exception as e:
        raise NewsSourceError(f"47 平台 finnhub 新闻失败: {e}") from e
    if not isinstance(items, list):
        return []
    out = []
    for n in items[:limit]:
        if not isinstance(n, dict):
            continue
        out.append({
            "title": n.get("headline") or n.get("title", ""),
            "url": n.get("url", ""),
            "time": _ts_to_str(n.get("datetime")),
            "digest": n.get("summary", ""),
            "source": n.get("source", "finnhub"),
            "extra": n.get("related", ""),
        })
    return out


def _ts_to_str(ts) -> str:
    """Finnhub 秒级时间戳 → 可读字符串。"""
    if ts is None:
        return ""
    try:
        from datetime import datetime
        v = float(ts)
        if v > 1e12:
            v /= 1000
        return datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return str(ts)[:16]


def fetch_earnings(days: int = 30, symbol: str = "") -> list[dict]:
    """47 平台财报日历。GET /api/earnings-calendar?days=N[&symbol=S]。"""
    params = {"days": int(days)}
    if symbol:
        params["symbol"] = symbol.upper()
    qs = urllib.parse.urlencode(params)
    url = f"{PLATFORM_BASE}/api/earnings-calendar?{qs}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=PLATFORM_TIMEOUT) as r:
            items = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        raise NewsSourceError(f"47 平台财报日历失败: {e}") from e
    return items if isinstance(items, list) else []
