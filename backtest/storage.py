"""backtest 存储 — backtests 表（归属 backtest 模块）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..core import storage

OWNER = "backtest"

_SCHEMAS = {
    "backtests": """
        CREATE TABLE IF NOT EXISTS backtests (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT,
            template    TEXT,
            params_json TEXT,
            result_json TEXT,
            created_at  TEXT
        )""",
}

for _t, _sql in _SCHEMAS.items():
    storage.register_table(_t, OWNER, _sql)


def save_backtest(symbol: str, template: str, params: dict, result: dict) -> int:
    with storage.owner_scope(OWNER):
        return storage.insert("backtests", {
            "symbol": symbol, "template": template,
            "params_json": storage.dumps(params),
            "result_json": storage.dumps(result),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })


def list_backtests(limit: int = 50) -> list[dict]:
    with storage.owner_scope(OWNER):
        rows = storage.query(
            "backtests", "SELECT * FROM backtests ORDER BY id DESC LIMIT ?", [int(limit)])
    out = []
    for r in rows:
        r["params"] = storage.loads(r.pop("params_json", None)) or {}
        r["result"] = storage.loads(r.pop("result_json", None)) or {}
        out.append(r)
    return out


def get_backtest(bid: int) -> Optional[dict]:
    with storage.owner_scope(OWNER):
        r = storage.query_one("backtests", "SELECT * FROM backtests WHERE id=?", [bid])
    if r:
        r["params"] = storage.loads(r.pop("params_json", None)) or {}
        r["result"] = storage.loads(r.pop("result_json", None)) or {}
    return r


def backtest_stats() -> dict:
    with storage.owner_scope(OWNER):
        r = storage.query_one("backtests",
                              "SELECT COUNT(*) n, COUNT(DISTINCT symbol) syms FROM backtests")
    return {"total": (r or {}).get("n", 0), "symbols": (r or {}).get("syms", 0)}
