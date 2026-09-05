"""news 存储 — news / news_settings / news_log 表（归属 news 模块）。

字段设计对齐旧系统 news 表（title/url/time/digest/source/extra + 去重主键）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..core import storage

OWNER = "news"

_SCHEMAS = {
    "news": """
        CREATE TABLE IF NOT EXISTS news (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            url         TEXT,
            time        TEXT,
            digest      TEXT,
            source      TEXT,
            extra       TEXT,
            created_at  TEXT
        )""",
    "news_settings": """
        CREATE TABLE IF NOT EXISTS news_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT
        )""",
    "news_log": """
        CREATE TABLE IF NOT EXISTS news_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            action      TEXT,
            source      TEXT,
            inserted    INTEGER DEFAULT 0,
            error       TEXT,
            created_at  TEXT
        )""",
    "earnings": """
        CREATE TABLE IF NOT EXISTS earnings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL,
            date            TEXT,
            hour            TEXT,
            quarter         INTEGER,
            year            INTEGER,
            eps_estimate    REAL,
            eps_actual      REAL,
            revenue_estimate REAL,
            revenue_actual  REAL,
            created_at      TEXT
        )""",
}

for _t, _sql in _SCHEMAS.items():
    storage.register_table(_t, OWNER, _sql)


def upsert_news(items: list[dict]) -> tuple[int, int]:
    """批量入库新闻（按 url 去重：已存在则跳过）。返回 (inserted, skipped)。"""
    inserted = skipped = 0
    with storage.owner_scope(OWNER):
        for it in items:
            url = it.get("url") or ""
            if url and storage.exists("news", "url=?", [url]):
                skipped += 1
                continue
            storage.insert("news", {
                "title": (it.get("title") or "")[:500],
                "url": url,
                "time": it.get("time") or "",
                "digest": (it.get("digest") or "")[:2000],
                "source": it.get("source") or "",
                "extra": it.get("extra") or "",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })
            inserted += 1
    return inserted, skipped


def list_news(limit: int = 100, source: str = "") -> list[dict]:
    where, params = "", []
    if source:
        where, params = "source=?", [source]
    sql = f"SELECT * FROM news {'WHERE ' + where if where else ''} ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with storage.owner_scope(OWNER):
        return storage.query("news", sql, params)


def news_stats() -> dict:
    with storage.owner_scope(OWNER):
        r = storage.query_one("news",
                              "SELECT COUNT(*) n, COUNT(DISTINCT source) srcs FROM news")
    return {"rows": (r or {}).get("n", 0), "sources": (r or {}).get("srcs", 0)}


def latest_by_source(limit_per: int = 5) -> dict[str, list[dict]]:
    """按源分组取最近 N 条（栏目横排卡片）。"""
    with storage.owner_scope(OWNER):
        srcs = [r["source"] for r in storage.query(
            "news", "SELECT DISTINCT source FROM news ORDER BY source")]
    out = {}
    for s in srcs:
        out[s] = list_news(limit_per, s)
    return out


# ── 配置（定时入库）──
_DEFAULTS: dict[str, str] = {
    "enabled": "false",
    "interval_min": "30",
    "limit": "30",
}


def get_settings() -> dict:
    with storage.owner_scope(OWNER):
        rows = storage.query("news_settings", "SELECT key, value FROM news_settings")
    out = dict(_DEFAULTS)
    for r in rows:
        out[r["key"]] = r["value"]
    return out


def save_settings(updates: dict) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    with storage.owner_scope(OWNER):
        for k, v in updates.items():
            storage.upsert("news_settings",
                           {"key": k, "value": str(v), "updated_at": now}, ["key"])
    return get_settings()


def add_log(action: str, source: str, inserted: int = 0, error: str = "") -> None:
    with storage.owner_scope(OWNER):
        storage.insert("news_log", {
            "action": action, "source": source or "", "inserted": inserted,
            "error": (error or "")[:500],
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })


def list_logs(limit: int = 20) -> list[dict]:
    with storage.owner_scope(OWNER):
        return storage.query(
            "news_log", "SELECT * FROM news_log ORDER BY id DESC LIMIT ?", [int(limit)])


# ── earnings（财报）──
def upsert_earnings(items: list[dict]) -> tuple[int, int]:
    """批量入库财报日历（按 symbol+date 去重）。返回 (inserted, updated)。"""
    inserted = updated = 0
    with storage.owner_scope(OWNER):
        for it in items:
            sym = str(it.get("symbol", "")).upper()
            date = str(it.get("date") or "")
            if not sym or not date:
                continue
            n = storage.update("earnings", {
                "hour": it.get("hour") or "",
                "quarter": it.get("quarter"),
                "year": it.get("year"),
                "eps_estimate": it.get("epsEstimate"),
                "eps_actual": it.get("epsActual"),
                "revenue_estimate": it.get("revenueEstimate"),
                "revenue_actual": it.get("revenueActual"),
            }, "symbol=? AND date=?", [sym, date])
            if n:
                updated += 1
            else:
                storage.insert("earnings", {
                    "symbol": sym, "date": date, "hour": it.get("hour") or "",
                    "quarter": it.get("quarter"), "year": it.get("year"),
                    "eps_estimate": it.get("epsEstimate"), "eps_actual": it.get("epsActual"),
                    "revenue_estimate": it.get("revenueEstimate"),
                    "revenue_actual": it.get("revenueActual"),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                })
                inserted += 1
    return inserted, updated


def list_earnings(limit: int = 50, upcoming_only: bool = True) -> list[dict]:
    """财报列表（默认只显示未发布/即将发布的）。"""
    where, params = "", []
    if upcoming_only:
        where, params = "date >= date('now') OR eps_actual IS NULL", []
    sql = f"SELECT * FROM earnings {'WHERE ' + where if where else ''} ORDER BY date LIMIT ?"
    params.append(int(limit))
    with storage.owner_scope(OWNER):
        return storage.query("earnings", sql, params)


def earnings_stats() -> dict:
    with storage.owner_scope(OWNER):
        r = storage.query_one("earnings", "SELECT COUNT(*) n, COUNT(DISTINCT symbol) syms FROM earnings")
    return {"total": (r or {}).get("n", 0), "symbols": (r or {}).get("syms", 0)}
