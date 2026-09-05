"""测试夹具 — 每个用例使用独立 SQLite 库、干净的事件总线。"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

# 让测试能从仓库任意位置运行：找到包含 light_quant_new 包的工作区根目录并加入 sys.path
HERE = Path(__file__).resolve().parent
for _p in (HERE, *HERE.parents):
    if (_p / "light_quant_new").is_dir():
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
        break


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """隔离数据库：避免用例之间、以及与开发库互相污染。"""
    from light_quant_new.core import config, storage

    for mod in ("market.storage", "news.storage", "factors.storage",
                "backtest.storage", "trading.storage"):
        importlib.import_module(f"light_quant_new.{mod}")

    storage.close()
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "KLINE_CSV_DIR", str(tmp_path / "no_csv"))
    storage.init_db()
    yield
    storage.close()


@pytest.fixture(autouse=True)
def clean_events():
    """每个用例前后清空事件订阅，避免跨用例泄漏。"""
    from light_quant_new.core import events
    events.clear()
    yield
    events.clear()
