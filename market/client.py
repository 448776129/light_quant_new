"""行情数据源客户端 — stocks-tv TradingView 管道（历史K线）+ 本地 CSV(gzip) 导入。

职责（纯数据层，不碰存储）：
  - fetch_kline(symbol, interval, limit)：HTTP 拉取最新 K 线（JSON，asc 排序）
  - read_csv_gzip(symbol, base_dir)：读取本地 gzip CSV 历史数据
数据字段统一为：Datetime / Open / High / Low / Close / Adj Close / Volume
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..core import config
from ..core.logger import get_logger

log = get_logger("market.client")

VALID_INTERVALS = ("1d", "1m", "5m", "15m", "30m", "1h", "1wk", "1mo")


class DataSourceError(RuntimeError):
    pass


def fetch_kline(symbol: str, interval: str = "1d", limit: int = 5) -> list[dict]:
    """从 stocks-tv 拉取 K 线。返回字段与 CSV 一致的数据列表（时间升序）。"""
    interval = interval.lower()
    if interval not in VALID_INTERVALS:
        raise DataSourceError(f"非法 interval: {interval}（可用 {VALID_INTERVALS}）")
    url = f"{config.STOCKS_TV_BASE}/kline?symbol={urllib.parse.quote(symbol)}" \
          f"&interval={interval}&limit={int(limit)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=config.STOCKS_TV_TIMEOUT) as r:
            raw = r.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except Exception as e:
        raise DataSourceError(f"stocks-tv 拉取失败: {e}") from e
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise DataSourceError(f"stocks-tv 返回异常: {raw[:200]}")
    return items


def list_csv_symbols(base_dir: str | None = None) -> list[str]:
    """列出本地 CSV 数据目录下的全部标的（去 .csv 后缀，排序）。"""
    base = Path(base_dir or config.KLINE_CSV_DIR) / "us" / "kline"
    if not base.exists():
        return []
    return sorted(p.stem for p in base.glob("*.csv"))


def read_csv_gzip(symbol: str, base_dir: str | None = None) -> list[dict]:
    """读取单标的历史 CSV（gzip 压缩）。返回字段标准化后的 dict 列表（时间升序）。"""
    base = Path(base_dir or config.KLINE_CSV_DIR) / "us" / "kline"
    path = base / f"{symbol.upper()}.csv"
    if not path.exists():
        raise DataSourceError(f"本地 CSV 不存在: {path}")
    try:
        with gzip.open(path, "rt", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
    except Exception as e:
        raise DataSourceError(f"CSV 读取失败 {path}: {e}") from e
    return _normalize_rows(rows)


def _normalize_rows(rows: list[dict]) -> list[dict]:
    """字段标准化：确保 Datetime/Open/High/Low/Close/Adj Close/Volume 都存在，数值转 float。"""
    out = []
    for r in rows:
        item = {
            "Datetime": str(r.get("Datetime", "")).strip(),
            "Open": _num(r.get("Open")),
            "High": _num(r.get("High")),
            "Low": _num(r.get("Low")),
            "Close": _num(r.get("Close")),
            "Adj Close": _num(r.get("Adj Close") or r.get("Close")),
            "Volume": _num(r.get("Volume"), int),
        }
        if item["Datetime"] and item["Close"] is not None:
            out.append(item)
    return out


def _num(v: Any, cast=float):
    if v is None or str(v).strip() == "":
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def _csv_dir() -> str:
    """本地 CSV 根目录（展示用）。"""
    return str(config.KLINE_CSV_DIR)


def _base_url() -> str:
    """stocks-tv 数据源地址（展示用）。"""
    return config.STOCKS_TV_BASE


# ── 47 平台 futu 实时行情（quote / orderbook，含延长时段）──
PLATFORM_BASE = getattr(config, "PLATFORM_BASE_URL", "http://47.103.124.40:3215")
PLATFORM_TIMEOUT = getattr(config, "PLATFORM_TIMEOUT", 15)


def fetch_quote(symbol: str) -> dict:
    """47 平台实时报价（futu 源，含延长时段最新价）。"""
    url = f"{PLATFORM_BASE}/api/quote/{urllib.parse.quote(symbol.upper())}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=PLATFORM_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        raise DataSourceError(f"47 平台 quote 失败: {e}") from e


def fetch_orderbook(symbol: str) -> dict:
    """47 平台实时盘口（5 档）。"""
    url = f"{PLATFORM_BASE}/api/orderbook/{urllib.parse.quote(symbol.upper())}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=PLATFORM_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        raise DataSourceError(f"47 平台 orderbook 失败: {e}") from e


def normalize_quote(q: dict) -> dict:
    """quote 字段标准化 → 前端展示统一结构。"""
    return {
        "symbol": q.get("code", ""),
        "last_price": q.get("last_price"),
        "open": q.get("open_price"),
        "high": q.get("high_price"),
        "low": q.get("low_price"),
        "prev_close": q.get("prev_close_price"),
        "volume": q.get("volume"),
        "turnover": q.get("turnover"),
        "timestamp": q.get("timestamp"),
        "change_pct": (round((q.get("last_price", 0) / q.get("prev_close_price", 1) - 1) * 100, 2)
                       if q.get("last_price") and q.get("prev_close_price") else None),
    }
