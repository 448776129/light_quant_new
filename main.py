"""light_quant_new 入口 — FastAPI 组装（服务端渲染，非前后端分离）。

启动：python -m light_quant_new.main   （工作区根目录下）
访问：http://127.0.0.1:3217/market
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .core import config, storage
from .core.logger import setup_logging
from .backtest import routes as backtest_routes
from .backtest import service as backtest_service
from .factors import routes as factors_routes
from .factors import service as factors_service
from .market import routes as market_routes
from .market import service as market_service
from .news import routes as news_routes
from .news import service as news_service
from .trading import routes as trading_routes
from .trading import service as trading_service

setup_logging()

# ── 定时任务：历史行情自动拉取 / 新闻自动入库 ──
_AUTO_TASK = None
_NEWS_TASK = None


async def _news_loop():
    """按配置间隔（分钟）自动入库新闻。"""
    from .core.logger import get_logger
    log = get_logger("scheduler")
    while True:
        try:
            cfg = news_service.get_settings()
            enabled = cfg.get("enabled") == "true"
            interval_min = max(5, int(cfg.get("interval_min") or 30))
        except Exception:
            enabled, interval_min = False, 30
        if enabled:
            try:
                r = await asyncio.to_thread(news_service.run_auto)
                log.info("news_auto", extra={k: v for k, v in r.items() if k != "err_symbols"})
            except Exception as e:
                log.warning("news_auto_failed", extra={"err": str(e)})
        await asyncio.sleep(interval_min * 60)


async def _auto_pull_loop():
    """按配置间隔定时拉取最新 K 线。"""
    from .core.logger import get_logger
    log = get_logger("scheduler")
    while True:
        try:
            cfg = market_service.get_settings()
            enabled = cfg.get("enabled") == "true"
            interval_sec = int(cfg.get("interval_sec") or 3600)
        except Exception:
            enabled, interval_sec = False, 3600
        if enabled:
            try:
                r = await asyncio.to_thread(market_service.run_auto)
                log.info("auto_pull", extra={k: v for k, v in r.items() if k != "message"})
            except Exception as e:
                log.warning("auto_pull_failed", extra={"err": str(e)})
        await asyncio.sleep(max(30, interval_sec))


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    # 启动时按配置自动导入本地 CSV（默认开启，幂等）
    try:
        cfg = market_service.get_settings()
        if cfg.get("auto_import_csv", "true") == "true":
            r = await asyncio.to_thread(market_service.import_csv_all)
            from .core.logger import get_logger
            get_logger("app").info("csv_import_at_startup", extra={k: v for k, v in r.items() if k != "err_symbols"})
    except Exception as e:
        from .core.logger import get_logger
        get_logger("app").warning("csv_import_failed", extra={"err": str(e)})
    global _AUTO_TASK, _NEWS_TASK
    _AUTO_TASK = asyncio.create_task(_auto_pull_loop())
    _NEWS_TASK = asyncio.create_task(_news_loop())
    # 47 futu 实时行情 WS
    from .market import ws as market_ws_mod
    market_ws_mod.market_ws.set_handler(market_service._ws_to_quotes)
    await market_ws_mod.market_ws.start()
    yield
    if _AUTO_TASK:
        _AUTO_TASK.cancel()
    if _NEWS_TASK:
        _NEWS_TASK.cancel()
    await market_ws_mod.market_ws.stop()
    storage.close()


app = FastAPI(title="light_quant_new", version="0.1.0", lifespan=lifespan)

# 静态资源（旧系统提取的 style.css 等）
STATIC_DIR = config.ROOT_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(market_routes.router)
app.include_router(news_routes.router)
app.include_router(factors_routes.router)
app.include_router(backtest_routes.router)
app.include_router(trading_routes.router)

# 组装：把 market 的取数函数注入各模块（解耦点——模块间不直接 import）
factors_service.set_klines_provider(market_service.get_klines_dataframe)
backtest_service.set_klines_provider(market_service.get_klines_dataframe)
# trading 订阅 factors 信号事件 → 自动下单（事件驱动解耦）
trading_service.setup()
# trading 栏目需策略列表（解耦注入，不 import factors）
trading_routes.set_strategies_provider(factors_service.list_strategies)


@app.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse("/market", status_code=302)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("light_quant_new.main:app", host=config.HOST, port=config.PORT, log_level="info")
