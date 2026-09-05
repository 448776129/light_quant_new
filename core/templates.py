"""模板渲染 — Jinja2 服务端渲染（非前后端分离）。

提供 base 布局的导航定义与全局上下文（nav / db_rows / session_label）。
各模块页面模板继承 base.html，内容由模块自身渲染。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from . import config

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 导航定义：key / label / href / icon(SVG)
# 模块新增页面时在此登记（顺序即侧栏顺序）
NAV_ITEMS: list[dict] = [
    {
        "key": "market", "label": "行情拉取", "href": "/market",
        "icon": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                'stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="8" ry="3"/>'
                '<path d="M4 5v6c0 1.66 3.58 3 8 3s8-1.34 8-3V5"/><path d="M4 11v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6"/></svg>',
    },
    {
        "key": "news", "label": "新闻与财报", "href": "/news",
        "icon": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h13a2 2 0 0 1 2 2v12a2 2 0 0 0 2-2V8"/>'
                '<path d="M4 4v16h15"/><line x1="7" y1="8" x2="14" y2="8"/><line x1="7" y1="12" x2="14" y2="12"/>'
                '<line x1="7" y1="16" x2="11" y2="16"/></svg>',
    },
    {
        "key": "factors", "label": "因子策略", "href": "/factors",
        "icon": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/>'
                '<circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></svg>',
    },
    {
        "key": "backtest", "label": "历史回测", "href": "/backtest",
        "icon": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/>'
                '<line x1="8" y1="17" x2="8" y2="11"/><line x1="12" y1="17" x2="12" y2="7"/>'
                '<line x1="16" y1="17" x2="16" y2="13"/></svg>',
    },
    {
        "key": "trading", "label": "自动交易", "href": "/trading",
        "icon": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                'stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/>'
                '<path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/>'
                '<path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>',
    },
]


def _db_rows() -> int:
    """顶栏 DB 行数统计（跨表 sum，仅展示用；失败返回 -）。"""
    try:
        from . import storage as s
        tables = list(s._TABLE_OWNERS.keys())
        total = 0
        for t in tables:
            total += s.count(t) if t in _COUNTABLE else 0
        return total
    except Exception:
        return -1


# 可统计行数的表（避免对无行概念的表计数）
_COUNTABLE = {"kline", "pull_log", "pull_settings", "news", "earnings", "signals", "strategies", "backtests"}


def render(request: Request, name: str, active: str, ctx: dict | None = None) -> Any:
    """渲染页面：注入 base 布局上下文 + 模块上下文。"""
    base = {
        "title": _title_for(active),
        "nav": NAV_ITEMS,
        "active": active,
        "db_rows": _db_rows(),
        "session_label": "量化系统",
        "request": request,
    }
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(request, name, base)


def _title_for(active: str) -> str:
    for item in NAV_ITEMS:
        if item["key"] == active:
            return item["label"]
    return "量化系统"
