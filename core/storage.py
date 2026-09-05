"""存储层 — 单 SQLite 库 + 表归属隔离（模块解耦的数据基础）

设计：
  - 所有模块共享一个业务库（config.DB_PATH），SQLite WAL 模式
  - 每张表登记 owner 模块；core.storage 校验「访问者」是否是该表 owner，
    跨模块直接查表会被拒绝（AccessError），强制数据经模块服务层交换
  - 提供与旧系统兼容的 row->dict 行为（sqlite3.Row）
  - 自动建表：模块在 core.storage 注册 SCHEMA（建表 SQL + 表名 + owner）

访问者标记用 threading.local：asyncio.to_thread 工作线程与主线程隔离，
避免主线程遗留的 owner 污染线程池中其他模块的 DAO 调用。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Callable, Optional

from . import config
from .logger import get_logger

log = get_logger("storage")

# ── 表归属注册表：table -> owner_module ──
# 由各模块在 import 时调用 register_table() 登记
_TABLE_OWNERS: dict[str, str] = {}
# 建表 SQL 注册表：table -> CREATE TABLE 语句（由各模块提供）
_SCHEMAS: dict[str, str] = {}
# 当前访问者（线程局部：主线程 / to_thread 工作线程各自独立）
_owner_local = threading.local()

_lock = threading.Lock()
_db_conn: Optional[sqlite3.Connection] = None


class AccessError(PermissionError):
    """跨模块表访问被拒绝。"""


def register_table(table: str, owner: str, create_sql: str) -> None:
    """模块登记自己拥有的表：owner 模块名 + 建表 SQL。

    同表重复登记以首次为准（幂等）。
    """
    with _lock:
        if table not in _TABLE_OWNERS:
            _TABLE_OWNERS[table] = owner
            _SCHEMAS[table] = create_sql


def owner_of(table: str) -> Optional[str]:
    return _TABLE_OWNERS.get(table)


def _get_owner() -> Optional[str]:
    return getattr(_owner_local, "owner", None)


def _check_access(table: str) -> None:
    """校验当前访问者是否是该表 owner；未启用校验或表未登记时不拦截。"""
    cur = _get_owner()
    if cur is None:
        return
    owner = _TABLE_OWNERS.get(table)
    if owner is not None and owner != cur:
        raise AccessError(
            f"表 {table} 归属模块 {owner}，{cur} 无权直接访问；"
            f"请通过 {owner} 模块的服务层获取数据")


def set_owner(owner: Optional[str]) -> None:
    """进入某模块 DAO 调用前设置访问者（context 方式见 owner_scope）。"""
    _owner_local.owner = owner


class owner_scope:
    """with storage.owner_scope("factors"): ...  — 限定块内可访问的表。"""

    def __init__(self, owner: str):
        self._owner = owner
        self._prev: Optional[str] = None

    def __enter__(self) -> "owner_scope":
        self._prev = getattr(_owner_local, "owner", None)
        _owner_local.owner = self._owner
        return self

    def __exit__(self, *exc) -> None:
        _owner_local.owner = self._prev


# ── 连接管理 ──
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None          # 自动提交（与旧系统一致）
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _conn() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        with _lock:
            if _db_conn is None:
                _db_conn = _connect()
    return _db_conn


def init_db() -> None:
    """建库 + 按已登记 schema 建表（幂等）。"""
    c = _conn()
    for table, sql in _SCHEMAS.items():
        try:
            c.execute(sql)
        except sqlite3.Error as e:
            log.warning("init_db", extra={"table": table, "err": str(e)})


# ── 通用读写接口（均带归属校验）──
def execute(table: str, sql: str, params: list | tuple = ()) -> int:
    """执行写语句，返回 rowcount。"""
    _check_access(table)
    cur = _conn().execute(sql, params)
    return cur.rowcount if cur.rowcount is not None else 0


def query(table: str, sql: str, params: list | tuple = ()) -> list[dict]:
    """查询，返回 dict 列表。"""
    _check_access(table)
    rows = _conn().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_one(table: str, sql: str, params: list | tuple = ()) -> Optional[dict]:
    rows = query(table, sql, params)
    return rows[0] if rows else None


def insert(table: str, data: dict) -> int:
    """插入一行，返回自增 id（无自增列返回 0）。"""
    _check_access(table)
    cols = list(data.keys())
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
    cur = _conn().execute(sql, [data[c] for c in cols])
    return cur.lastrowid or 0


def upsert(table: str, data: dict, key_cols: list[str]) -> int:
    """按唯一键 upsert（INSERT OR REPLACE 语义）。key_cols 为唯一键列名。

    用于 key-value 配置表（key 为主键）：重复保存同一 key 时覆盖而非报错。
    返回影响的上一行（replace 计 2，新插入计 1）。
    """
    _check_access(table)
    cols = list(data.keys())
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
    cur = _conn().execute(sql, [data[c] for c in cols])
    return cur.rowcount or 0


def update(table: str, data: dict, where: str, params: list | tuple = ()) -> int:
    """按 where 更新（where 由调用方提供，只允许本模块表）。"""
    _check_access(table)
    sets = ", ".join(f"{c}=?" for c in data.keys())
    sql = f"UPDATE {table} SET {sets} WHERE {where}"
    cur = _conn().execute(sql, list(data.values()) + list(params))
    return cur.rowcount or 0


def exists(table: str, where: str, params: list | tuple = ()) -> bool:
    rows = query(table, f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", params)
    return bool(rows)


def count(table: str, where: str = "", params: list | tuple = ()) -> int:
    sql = f"SELECT COUNT(*) n FROM {table}" + (f" WHERE {where}" if where else "")
    r = query_one(table, sql, params)
    return int((r or {}).get("n", 0))


def close() -> None:
    global _db_conn
    if _db_conn is not None:
        try:
            _db_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        _db_conn.close()
        _db_conn = None


# ── JSON 工具（序列化列）──
def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def loads(s: Any) -> Any:
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return s
