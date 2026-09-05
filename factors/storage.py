"""factors 存储 — strategies / signals 表（归属 factors 模块）。

所有 DAO 函数内部显式使用 owner_scope(OWNER)：与调用线程遗留的
访问者状态解耦——无论谁在哪个线程调用，访问都被正确校验为 factors。

注意：kline 行情数据归 market 模块，factors 不得直接查 kline；
取行情须经 market 模块服务层（main 组装时注入 klines_provider）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..core import storage

OWNER = "factors"

_SCHEMAS = {
    "strategies": """
        CREATE TABLE IF NOT EXISTS strategies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            description     TEXT,
            definition_json TEXT,
            version         INTEGER DEFAULT 1,
            enabled         INTEGER DEFAULT 0,
            created_at      TEXT,
            updated_at      TEXT
        )""",
    "signals": """
        CREATE TABLE IF NOT EXISTS signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id     INTEGER,
            symbol          TEXT,
            signal_type     TEXT,       -- buy / sell
            price           REAL,
            score           REAL,
            detail_json     TEXT,
            execution_json  TEXT,       -- trading 模块回写执行状态（经事件总线）
            created_at      TEXT
        )""",
}

for _t, _sql in _SCHEMAS.items():
    storage.register_table(_t, OWNER, _sql)


# ── strategies ──
def create_strategy(name: str, definition: dict, description: str = "",
                    enabled: bool = False) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with storage.owner_scope(OWNER):
        return storage.insert("strategies", {
            "name": name, "description": description,
            "definition_json": storage.dumps(definition),
            "version": 1, "enabled": 1 if enabled else 0,
            "created_at": now, "updated_at": now,
        })


def list_strategies(enabled_only: bool = False) -> list[dict]:
    where, params = "", []
    if enabled_only:
        where, params = "enabled=1", []
    sql = f"SELECT * FROM strategies {'WHERE ' + where if where else ''} ORDER BY id DESC"
    with storage.owner_scope(OWNER):
        return [dict(r) for r in storage.query("strategies", sql, params)]


def get_strategy(sid: int) -> Optional[dict]:
    with storage.owner_scope(OWNER):
        return storage.query_one("strategies", "SELECT * FROM strategies WHERE id=?", [sid])


def update_strategy(sid: int, definition: dict | None = None,
                    enabled: bool | None = None, name: str | None = None) -> bool:
    data = {"updated_at": datetime.now().isoformat(timespec="seconds")}
    if definition is not None:
        data["definition_json"] = storage.dumps(definition)
        cur = get_strategy(sid)
        data["version"] = (cur or {}).get("version", 1) + 1
    if enabled is not None:
        data["enabled"] = 1 if enabled else 0
    if name is not None:
        data["name"] = name
    with storage.owner_scope(OWNER):
        return storage.update("strategies", data, "id=?", [sid]) > 0


def delete_strategy(sid: int) -> bool:
    with storage.owner_scope(OWNER):
        return storage.execute("strategies", "DELETE FROM strategies WHERE id=?", [sid]) > 0


def strategy_stats() -> dict:
    with storage.owner_scope(OWNER):
        r = storage.query_one("strategies",
                              "SELECT COUNT(*) n, SUM(enabled) en FROM strategies")
    return {"total": (r or {}).get("n", 0), "enabled": (r or {}).get("en", 0) or 0}


# ── signals ──
def persist_signal(strategy_id: int, symbol: str, signal_type: str,
                   price: float, score: float, detail: dict | None = None) -> int:
    with storage.owner_scope(OWNER):
        return storage.insert("signals", {
            "strategy_id": strategy_id, "symbol": symbol, "signal_type": signal_type,
            "price": price, "score": score,
            "detail_json": storage.dumps(detail or {}),
            "execution_json": None,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })


def list_signals(strategy_id: int | None = None, limit: int = 100) -> list[dict]:
    where, params = "", []
    if strategy_id is not None:
        where, params = "strategy_id=?", [strategy_id]
    sql = f"SELECT * FROM signals {'WHERE ' + where if where else ''} ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with storage.owner_scope(OWNER):
        return storage.query("signals", sql, params)


def latest_signal(strategy_id: int) -> Optional[dict]:
    with storage.owner_scope(OWNER):
        return storage.query_one(
            "signals", "SELECT * FROM signals WHERE strategy_id=? ORDER BY id DESC LIMIT 1",
            [strategy_id])


def set_signal_execution(signal_id: int, exec_json: dict) -> bool:
    """回写信号执行状态（由 trading 模块经事件总线调用，非直接查表）。"""
    with storage.owner_scope(OWNER):
        return storage.update("signals", {"execution_json": storage.dumps(exec_json)},
                              "id=?", [signal_id]) > 0
