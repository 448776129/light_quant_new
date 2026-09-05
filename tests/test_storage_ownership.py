"""BUG-004 表归属校验：DAO 必须自己声明 owner，不能依赖调用线程的身份。

factors/storage.py 的模块文档已明确「所有 DAO 函数内部显式使用 owner_scope(OWNER)，
与调用线程遗留的访问者状态解耦」。news.storage 的 4 个查询函数与 market.storage
的 list_logs 未遵守，实际身份取决于调用方。
"""
from __future__ import annotations

import pytest


def test_cross_module_query_is_still_rejected():
    """基线：跨模块直接查他人表必须被拒绝。"""
    from light_quant_new.core import storage as cs
    with cs.owner_scope("news"):
        with pytest.raises(cs.AccessError):
            cs.query("kline", "SELECT COUNT(*) n FROM kline")


@pytest.mark.parametrize("fn_name,args", [
    ("list_news", ()),
    ("news_stats", ()),
    ("latest_by_source", ()),
    ("list_logs", ()),
])
def test_news_dao_works_inside_foreign_scope(fn_name, args):
    """news 的查询函数在任意模块的归属上下文中都应能访问自己的表。"""
    from light_quant_new.core import storage as cs
    from light_quant_new.news import storage as nstorage

    with cs.owner_scope("factors"):
        getattr(nstorage, fn_name)(*args)      # 不应抛 AccessError


def test_market_logs_works_inside_foreign_scope():
    from light_quant_new.core import storage as cs
    from light_quant_new.market import storage as mstorage

    with cs.owner_scope("trading"):
        assert mstorage.list_logs(5) == []
