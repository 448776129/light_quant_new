"""trading 存储 — trading_orders / trading_log 表（归属 trading 模块）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..core import storage

OWNER = "trading"

_SCHEMAS = {
    "trading_orders": """
        CREATE TABLE IF NOT EXISTS trading_orders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id       INTEGER,
            strategy_id     INTEGER,
            symbol          TEXT,
            side            TEXT,
            qty             REAL,
            order_type      TEXT,
            status          TEXT,       -- submitted / filled / rejected / failed
            alpaca_order_id TEXT,
            message         TEXT,
            created_at      TEXT
        )""",
    "trading_log": """
        CREATE TABLE IF NOT EXISTS trading_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event       TEXT,
            message     TEXT,
            created_at  TEXT
        )""",
}

for _t, _sql in _SCHEMAS.items():
    storage.register_table(_t, OWNER, _sql)


def save_order(signal_id: int, strategy_id: int, symbol: str, side: str,
               qty: float, order_type: str, status: str,
               alpaca_order_id: str = "", message: str = "") -> int:
    with storage.owner_scope(OWNER):
        return storage.insert("trading_orders", {
            "signal_id": signal_id, "strategy_id": strategy_id,
            "symbol": symbol, "side": side, "qty": qty,
            "order_type": order_type, "status": status,
            "alpaca_order_id": alpaca_order_id,
            "message": (message or "")[:500],
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })


def list_orders(limit: int = 50) -> list[dict]:
    with storage.owner_scope(OWNER):
        return storage.query(
            "trading_orders", "SELECT * FROM trading_orders ORDER BY id DESC LIMIT ?",
            [int(limit)])


def add_log(event: str, message: str) -> None:
    with storage.owner_scope(OWNER):
        storage.insert("trading_log", {
            "event": event, "message": (message or "")[:500],
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })


def list_logs(limit: int = 30) -> list[dict]:
    with storage.owner_scope(OWNER):
        return storage.query(
            "trading_log", "SELECT * FROM trading_log ORDER BY id DESC LIMIT ?", [int(limit)])


def trading_stats() -> dict:
    with storage.owner_scope(OWNER):
        r = storage.query_one("trading_orders",
                              "SELECT COUNT(*) n, SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) sub "
                              "FROM trading_orders")
    return {"total": (r or {}).get("n", 0), "submitted": (r or {}).get("sub", 0) or 0}


# ── 配置（独立 key-value 表）──
_SCHEMAS["trading_settings"] = """
    CREATE TABLE IF NOT EXISTS trading_settings (
        key         TEXT PRIMARY KEY,
        value       TEXT,
        updated_at  TEXT
    )"""
storage.register_table("trading_settings", OWNER, _SCHEMAS["trading_settings"])


def _settings() -> dict:
    with storage.owner_scope(OWNER):
        rows = storage.query("trading_settings", "SELECT key, value FROM trading_settings")
    return {r["key"]: r["value"] for r in rows}


def _save_settings(updates: dict) -> None:
    from datetime import datetime
    now = datetime.now().isoformat(timespec="seconds")
    with storage.owner_scope(OWNER):
        for k, v in updates.items():
            storage.upsert("trading_settings",
                           {"key": k, "value": str(v), "updated_at": now}, ["key"])
