"""market 存储 — kline / pull_settings / pull_log 表（归属 market 模块）。

所有访问均通过 core.storage 的归属校验；其他模块要行情数据，
必须经 market 服务层（market.service）获取，禁止直接查 kline 表。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..core import storage

OWNER = "market"

_SCHEMAS = {
    "kline": """
        CREATE TABLE IF NOT EXISTS kline (
            symbol      TEXT NOT NULL,
            interval    TEXT NOT NULL,
            datetime    TEXT NOT NULL,
            open        REAL, high REAL, low REAL,
            close       REAL, adj_close REAL,
            volume      INTEGER,
            PRIMARY KEY (symbol, interval, datetime)
        )""",
    "pull_settings": """
        CREATE TABLE IF NOT EXISTS pull_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT
        )""",
    "pull_log": """
        CREATE TABLE IF NOT EXISTS pull_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            action      TEXT NOT NULL,      -- import_csv / pull_remote / manual / auto
            symbol      TEXT,
            interval    TEXT,
            inserted    INTEGER DEFAULT 0,
            updated     INTEGER DEFAULT 0,
            skipped     INTEGER DEFAULT 0,
            error       TEXT,
            created_at  TEXT
        )""",
}

for _t, _sql in _SCHEMAS.items():
    storage.register_table(_t, OWNER, _sql)


# ── kline ──
def upsert_kline(symbol: str, interval: str, rows: list[dict]) -> tuple[int, int]:
    """批量 upsert K 线。返回 (inserted, updated)。主键 (symbol, interval, datetime)。

    优化：先按 datetime 去重（同批次保留最后一条），再一次性区分
    「新行 / 已有行」，分别用一条 executemany 完成 INSERT / UPDATE，
    避免逐行「先 UPDATE 再 INSERT」带来的双倍 SQL 往返（数百标的
    批量导入时从分钟级降到秒级）。
    """
    # 抽取并清洗：跳过空 datetime；按 datetime 去重
    by_dt: dict[str, tuple] = {}
    for r in rows:
        dt = str(r.get("Datetime", "")).strip()
        if not dt:
            continue
        by_dt[dt] = (r.get("Open"), r.get("High"), r.get("Low"),
                     r.get("Close"), r.get("Adj Close"), r.get("Volume"))
    if not by_dt:
        return (0, 0)

    with storage.owner_scope(OWNER):
        existing = {row["datetime"] for row in storage.query(
            "kline",
            "SELECT datetime FROM kline WHERE symbol=? AND interval=?",
            [symbol, interval])}
        new = [(dt, v) for dt, v in by_dt.items() if dt not in existing]
        old = [(dt, v) for dt, v in by_dt.items() if dt in existing]

        if new:
            storage.executemany(
                "kline",
                "INSERT INTO kline (symbol,interval,datetime,open,high,low,close,adj_close,volume) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                [(symbol, interval, dt, v[0], v[1], v[2], v[3], v[4], v[5])
                 for dt, v in new])
        if old:
            storage.executemany(
                "kline",
                "UPDATE kline SET open=?,high=?,low=?,close=?,adj_close=?,volume=? "
                "WHERE symbol=? AND interval=? AND datetime=?",
                [(v[0], v[1], v[2], v[3], v[4], v[5], symbol, interval, dt)
                 for dt, v in old])
    return len(new), len(old)


def get_klines(symbol: str, interval: str = "1d",
               start: str = "", end: str = "", limit: int = 0) -> list[dict]:
    """查询 K 线（时间升序）。"""
    where = "symbol=? AND interval=?"
    params: list = [symbol, interval]
    if start:
        where += " AND datetime>=?"
        params.append(start)
    if end:
        where += " AND datetime<=?"
        params.append(end)
    sql = f"SELECT * FROM kline WHERE {where} ORDER BY datetime"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with storage.owner_scope(OWNER):
        return storage.query("kline", sql, params)


def kline_range(symbol: str, interval: str = "1d") -> dict:
    """查询某标的某周期的数据范围（最早/最晚时间、条数）。"""
    with storage.owner_scope(OWNER):
        r = storage.query_one(
            "kline",
            "SELECT MIN(datetime) min_dt, MAX(datetime) max_dt, COUNT(*) n "
            "FROM kline WHERE symbol=? AND interval=?",
            [symbol, interval],
        )
    return r or {"min_dt": None, "max_dt": None, "n": 0}


def kline_stats() -> dict:
    """全部标的覆盖统计（栏目首页展示）。"""
    with storage.owner_scope(OWNER):
        r = storage.query_one(
            "kline",
            "SELECT COUNT(DISTINCT symbol) symbols, COUNT(DISTINCT interval) intervals, "
            "COUNT(*) rows, MAX(datetime) max_dt FROM kline")
    return r or {"symbols": 0, "intervals": 0, "rows": 0, "max_dt": None}


def list_symbols_with_kline() -> list[str]:
    with storage.owner_scope(OWNER):
        rows = storage.query(
            "kline", "SELECT DISTINCT symbol FROM kline ORDER BY symbol")
    return [r["symbol"] for r in rows]


# ── pull_settings（栏目配置，面板可改）──
_DEFAULTS: dict[str, str] = {
    "enabled": "false",              # 定时拉取开关
    "interval_sec": "3600",          # 定时拉取间隔（秒）
    "interval": "1d",                # K 线周期
    "limit": "500",                  # 每次拉取最新 N 根
    "symbols": "",                   # 指定标的列表（逗号分隔；空=全部已有标的）
    "auto_import_csv": "true",       # 启动时是否自动导入本地 CSV
}


def get_settings() -> dict:
    with storage.owner_scope(OWNER):
        rows = storage.query("pull_settings", "SELECT key, value FROM pull_settings")
    out = dict(_DEFAULTS)
    for r in rows:
        out[r["key"]] = r["value"]
    return out


def save_settings(updates: dict) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    with storage.owner_scope(OWNER):
        for k, v in updates.items():
            storage.upsert("pull_settings",
                           {"key": k, "value": str(v), "updated_at": now}, ["key"])
    return get_settings()


# ── pull_log ──
def add_log(action: str, symbol: str, interval: str,
            inserted: int = 0, updated: int = 0, skipped: int = 0,
            error: str = "") -> None:
    with storage.owner_scope(OWNER):
        storage.insert("pull_log", {
            "action": action, "symbol": symbol or "", "interval": interval or "",
            "inserted": inserted, "updated": updated, "skipped": skipped,
            "error": (error or "")[:500],
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })


def list_logs(limit: int = 50) -> list[dict]:
    with storage.owner_scope(OWNER):
        return storage.query(
            "pull_log", "SELECT * FROM pull_log ORDER BY id DESC LIMIT ?", [int(limit)])
