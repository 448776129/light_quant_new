"""market 服务层 — 历史行情拉取栏目业务逻辑。

能力：
  - import_csv_all()：把本地 gzip CSV 批量导入数据库（启动时/手动）
  - pull_updates(symbols=None)：按 stocks-tv 拉取最新 K 线，增量追加到本地
      （以库内已有最后时间为起点向后拉取，避免重复）
  - run_manual() / run_auto()：手动 / 定时触发入口
  - 配置读写：get_settings / save_settings（面板可改）
所有存储访问经 market.storage（归属校验），对外不暴露表结构。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

from ..core import config
from ..core.logger import get_logger
from . import client, storage

log = get_logger("market.service")

# 一次远程拉取的窗口上限（stocks-tv 单次 limit 上限保护）
MAX_REMOTE_LIMIT = 2000


# ── CSV 导入 ──
def import_csv_all(symbols: list[str] | None = None) -> dict:
    """导入本地 gzip CSV 到数据库。返回汇总统计。"""
    start = time.time()
    if symbols is None:
        symbols = client.list_csv_symbols()
    total_ins = total_upd = total_err = 0
    err_symbols = []
    for sym in symbols:
        try:
            rows = client.read_csv_gzip(sym)
        except client.DataSourceError as e:
            total_err += 1
            err_symbols.append(f"{sym}: {e}")
            continue
        if not rows:
            continue
        ins, upd = storage.upsert_kline(sym, "1d", rows)
        total_ins += ins
        total_upd += upd
    storage.add_log("import_csv", "", "1d", total_ins, total_upd, 0,
                    "; ".join(err_symbols[:5]) or "")
    log.info("import_csv_all", extra={"symbols": len(symbols), "inserted": total_ins,
                                      "updated": total_upd, "err": len(err_symbols)})
    return {"symbols": len(symbols), "inserted": total_ins, "updated": total_upd,
            "errors": total_err, "err_symbols": err_symbols[:20], "seconds": round(time.time() - start, 2)}


# ── 远程增量拉取 ──
def pull_updates(symbols: list[str] | None = None, interval: str = "1d") -> dict:
    """拉取最新 K 线并增量追加。symbols 空 = 全部已有标的。"""
    interval = interval if interval in client.VALID_INTERVALS else "1d"
    if symbols is None:
        symbols = storage.list_symbols_with_kline()
    if not symbols:
        storage.add_log("pull_remote", "", interval, 0, 0, 0, "无标的（请先导入 CSV）")
        return {"symbols": 0, "inserted": 0, "updated": 0, "errors": 0, "message": "无标的"}

    total_ins = total_upd = total_err = 0
    errs = []
    for sym in symbols:
        try:
            # 以库内已有最后时间为起点，向后多拉一段（覆盖缺口）再 upsert 去重
            last = storage.kline_range(sym, interval)["max_dt"]
            limit = 500
            if last:
                limit = 700          # 覆盖周末/长假缺口
            rows = client.fetch_kline(sym, interval, limit=limit)
            if not rows:
                continue
            ins, upd = storage.upsert_kline(sym, interval, rows)
            total_ins += ins
            total_upd += upd
        except client.DataSourceError as e:
            total_err += 1
            errs.append(f"{sym}: {e}")
        time.sleep(0.05)             # 温和限速，避免高频请求
    storage.add_log("pull_remote", "", interval, total_ins, total_upd, 0, "; ".join(errs[:5]) or "")
    log.info("pull_updates", extra={"symbols": len(symbols), "interval": interval,
                                    "inserted": total_ins, "updated": total_upd})
    return {"symbols": len(symbols), "interval": interval, "inserted": total_ins,
            "updated": total_upd, "errors": total_err, "err_symbols": errs[:20]}


def run_manual(symbols: str = "", interval: str = "") -> dict:
    """手动拉取：面板按钮触发。symbols 逗号分隔，空=全部（全部时建议走后台任务）。"""
    cfg = storage.get_settings()
    interval = interval or cfg.get("interval") or "1d"
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    return pull_updates(syms, interval)


# 后台全量拉取状态（页面轮询用）
BG_STATE: dict = {"running": False, "started_at": None, "finished_at": None,
                  "last_result": None, "symbols": 0}


async def run_manual_bg(symbols: str = "", interval: str = "") -> dict:
    """后台全量拉取：立即返回，任务在后台执行（避免 HTTP 长挂起）。"""
    import asyncio
    cfg = storage.get_settings()
    interval = interval or cfg.get("interval") or "1d"
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    if BG_STATE["running"]:
        return {"running": True, "message": "已有后台拉取任务在执行"}
    from datetime import datetime
    BG_STATE.update(running=True, started_at=datetime.now().isoformat(timespec="seconds"),
                    finished_at=None, last_result=None, symbols=len(syms) if syms else 0)
    asyncio.create_task(_bg_worker(syms, interval))
    return {"running": True, "started_at": BG_STATE["started_at"],
            "message": "后台拉取已启动"}


async def _bg_worker(symbols: list[str] | None, interval: str):
    """后台任务执行体。"""
    import asyncio
    from datetime import datetime
    try:
        result = await asyncio.to_thread(pull_updates, symbols, interval)
        BG_STATE["last_result"] = result
    except Exception as e:
        BG_STATE["last_result"] = {"error": str(e)}
    finally:
        BG_STATE["running"] = False
        BG_STATE["finished_at"] = datetime.now().isoformat(timespec="seconds")


def bg_status() -> dict:
    """后台任务状态（栏目页轮询展示）。"""
    return dict(BG_STATE)


# ── 47 平台 futu 实时行情服务 ──
# 最新行情缓存：symbol -> normalized quote（WS 推送或手动刷新时更新）
LIVE_QUOTES: dict[str, dict] = {}


def get_live_quote(symbol: str) -> dict:
    """实时报价（HTTP 拉取 + 更新缓存）。"""
    q = client.normalize_quote(client.fetch_quote(symbol))
    LIVE_QUOTES[symbol.upper()] = q
    return q


def get_live_orderbook(symbol: str) -> dict:
    """实时盘口（5 档）。"""
    return client.fetch_orderbook(symbol)


def ws_status() -> dict:
    """WS 连接状态 + 已订阅标的。"""
    from .ws import market_ws
    return {"connected": market_ws.connected, "subscribed": sorted(market_ws._subscribed)}


def ws_subscribe(symbols: list[str]) -> dict:
    """订阅实时行情（含延长时段）。"""
    from .ws import market_ws
    market_ws.subscribe([s.upper() for s in symbols])
    return {"subscribed": sorted(market_ws._subscribed)}


def ws_unsubscribe(symbols: list[str]) -> dict:
    from .ws import market_ws
    market_ws.unsubscribe([s.upper() for s in symbols])
    return {"subscribed": sorted(market_ws._subscribed)}


def _ws_to_quotes(mtype: str, data: Any) -> None:
    """WS 消息 → 缓存（type=quote 时更新）。"""
    if mtype == "quote" and isinstance(data, dict):
        sym = data.get("code") or data.get("symbol")
        if sym:
            LIVE_QUOTES[sym.upper()] = client.normalize_quote(data)


# ── 供其他模块调用的取数接口（经 main 组装注入，market 不依赖调用方）──
_KTYPE_INTERVAL_MAP = {
    "K_DAY": "1d", "K_1M": "1m", "K_5M": "5m", "K_15M": "15m",
    "K_30M": "30m", "K_60M": "1h", "K_WEEK": "1wk", "K_MON": "1mo",
}


def get_klines_dataframe(symbols: list[str] | None = None,
                         interval: str = "1d") -> "object":
    """返回 pandas DataFrame（symbol/date/open/high/low/close/volume/adj_close），
    供 factors 等模块计算因子用。interval 兼容 ktype 形式（K_DAY→1d）。
    symbols 空 = 全部已入库标的。
    """
    import pandas as pd
    interval = _KTYPE_INTERVAL_MAP.get(str(interval).upper(), interval)
    syms = symbols or storage.list_symbols_with_kline()
    if not syms:
        return pd.DataFrame()
    rows = []
    for sym in syms:
        rows.extend(storage.get_klines(sym, interval, limit=2000))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.rename(columns={"datetime": "date"})
    df["symbol"] = df["symbol"].astype(str)
    for col in ("open", "high", "low", "close", "adj_close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["date", "close"])


def get_settings() -> dict:
    """读取栏目配置（面板可改）。"""
    return storage.get_settings()


def run_auto() -> dict:
    """定时拉取：按配置的开关/间隔/周期执行。"""
    cfg = storage.get_settings()
    if cfg.get("enabled") != "true":
        return {"skipped": True, "message": "定时拉取未开启"}
    syms = None
    if cfg.get("symbols"):
        syms = [s.strip().upper() for s in cfg["symbols"].split(",") if s.strip()]
    return pull_updates(syms, cfg.get("interval") or "1d")
