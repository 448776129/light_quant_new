"""factors 服务层 — 策略 CRUD + 因子计算 + 信号评估。

跨模块解耦：本模块**不 import market**。需要行情时调用注入的
`klines_provider(symbols, start, end)` 回调（由 main.py 组装时注入
market 模块的取数函数）。这样 factors 与 market 零直接依赖。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd

from ..core import storage
from ..core.events import publish
from ..core.logger import get_logger
from . import factor_families as ff, storage as fstorage

log = get_logger("factors.service")

# 行情提供者（组装时注入）：fn(symbols: list[str], ktype: str) -> DataFrame
# DataFrame 列：symbol / date / open / high / low / close / volume
klines_provider: Optional[Callable] = None


def set_klines_provider(fn: Callable) -> None:
    """main.py 组装时注入行情取数函数（market 模块提供）。"""
    global klines_provider
    klines_provider = fn


# ── 策略 CRUD ──
def create_strategy(name: str, definition: dict, description: str = "",
                    enabled: bool = False) -> int:
    _validate_definition(definition)
    sid = fstorage.create_strategy(name, definition, description, enabled)
    log.info("strategy_created", extra={"id": sid, "name": name})
    return sid


def update_strategy(sid: int, definition: dict | None = None,
                    enabled: bool | None = None, name: str | None = None) -> bool:
    if definition is not None:
        _validate_definition(definition)
    return fstorage.update_strategy(sid, definition, enabled, name)


def list_strategies(enabled_only: bool = False) -> list[dict]:
    out = []
    for s in fstorage.list_strategies(enabled_only):
        s["definition"] = storage.loads(s.pop("definition_json", None)) or {}
        out.append(s)
    return out


def get_strategy(sid: int) -> Optional[dict]:
    s = fstorage.get_strategy(sid)
    if s:
        s["definition"] = storage.loads(s.pop("definition_json", None)) or {}
    return s


def delete_strategy(sid: int) -> bool:
    return fstorage.delete_strategy(sid)


def _validate_definition(defn: dict) -> None:
    if not isinstance(defn, dict):
        raise ValueError("definition 必须是对象")
    cat = defn.get("category", "single")
    if cat not in ("single", "screener"):
        raise ValueError(f"非法 category: {cat}")
    if cat == "single" and not defn.get("symbol"):
        raise ValueError("single 策略需要 definition.symbol")
    # combo 模式：因子组合规格
    combo = defn.get("combo")
    if combo is not None:
        if not isinstance(combo, list) or not combo:
            raise ValueError("combo 必须是非空列表 [{family, params}]")
        for spec in combo:
            if spec.get("family") not in ff.FAMILIES:
                raise ValueError(f"未知因子族: {spec.get('family')}")


# ── 因子计算 ──
def compute_factor(family: str, params: dict, ktype: str = "K_DAY",
                   symbols: list[str] | None = None) -> pd.DataFrame:
    """计算单因子 → date×symbol 宽表。"""
    df = _load_klines(symbols, ktype)
    if df is None or df.empty:
        return pd.DataFrame()
    s = ff.compute_raw(family, params, df)
    if s.empty:
        return pd.DataFrame()
    return s.unstack("symbol")


def _load_klines(symbols: list[str] | None, ktype: str) -> Optional[pd.DataFrame]:
    if klines_provider is None:
        raise RuntimeError("行情提供者未注入（main.py 未调用 factors.service.set_klines_provider）")
    return klines_provider(symbols, ktype)


# ── 信号评估 ──
def evaluate_screener(sid: int, ktype: str = "K_DAY",
                      symbols: list[str] | None = None) -> dict:
    """对 screener（combo）策略跑横截面打分 → 多空信号。

    流程：取股票池行情 → 各因子横截面 z → 等权复合分 → 最新交易日排序
    → 输出 top/bottom 信号并入库 + 发布事件。
    """
    strat = get_strategy(sid)
    if not strat:
        return {"error": "strategy not found"}
    defn = strat["definition"]
    combo = defn.get("combo")
    if not combo:
        return {"error": "该策略不是 combo 组合模式"}
    df = _load_klines(symbols, ktype)
    if df is None or df.empty:
        return {"error": "无行情数据"}
    # 各因子横截面 z（每因子 date×symbol 宽表 → 行 z）→ 等权平均
    zsum = None
    zcount = 0
    failed: list[dict] = []
    for spec in combo:
        fam = spec.get("family")
        params = spec.get("params") or {}
        try:
            series = ff.compute_raw(fam, params, df)
        except Exception as e:
            # 不静默吞掉：因子失败必须回传给用户，否则只表现为「信号变少」
            failed.append({"family": fam, "params": params, "reason": f"计算异常: {e}"})
            log.warning("factor_failed", extra={"strategy_id": sid, "family": fam,
                                                "err": str(e)})
            continue
        if series.empty:
            failed.append({"family": fam, "params": params,
                           "reason": "因子值为空（窗口参数超过数据长度？）"})
            log.warning("factor_empty", extra={"strategy_id": sid, "family": fam})
            continue
        w = series.unstack("symbol")
        z = ff.z_per_date(w)
        zsum = z if zsum is None else zsum.add(z, fill_value=0)
        zcount += 1
    if zcount == 0 or zsum is None:
        return {"error": f"全部 {len(combo)} 个因子均不可用", "failed_factors": failed}
    comp = zsum.div(zcount)                      # date×symbol 复合分
    last = comp.iloc[-1].dropna().sort_values(ascending=False)   # 最新交易日
    if last.empty:
        return {"error": "最新交易日无有效因子值"}
    n = len(last)
    long_pct = float(defn.get("long_pct") or 0.1)
    short_pct = float(defn.get("short_pct") or 0.1)
    top_n = max(1, int(n * long_pct))
    bot_n = max(1, int(n * short_pct))
    top = last.head(top_n)
    bottom = last.tail(bot_n)

    prices = _latest_prices(df, list(last.index))
    signals = []
    for sym, score in top.items():
        signals.append({"symbol": sym, "type": "buy", "score": round(float(score), 4),
                        "price": prices.get(sym)})
    for sym, score in bottom.items():
        signals.append({"symbol": sym, "type": "sell", "score": round(float(score), 4),
                        "price": prices.get(sym)})

    # 入库 + 发布事件（trading 模块订阅）
    stored = []
    for sg in signals:
        sig_id = fstorage.persist_signal(sid, sg["symbol"], sg["type"],
                                         sg["price"] or 0.0, sg["score"])
        stored.append({**sg, "id": sig_id})
    publish("signal.created", {"strategy_id": sid, "signals": stored})
    log.info("screener_eval", extra={"strategy_id": sid, "signals": len(stored),
                                     "failed": len(failed)})
    return {"strategy_id": sid, "date": str(comp.index[-1]), "universe": n,
            "signals": stored, "top": list(top.index), "bottom": list(bottom.index),
            "failed_factors": failed}


def evaluate_single(sid: int, ktype: str = "K_DAY") -> dict:
    """对 single 策略（条件树）做评估。条件树逻辑从旧系统提取的简化版。"""
    s = get_strategy(sid)
    if not s:
        return {"error": "strategy not found"}
    defn = s["definition"]
    symbol = defn.get("symbol", "")
    conditions = defn.get("conditions")
    if not conditions:
        return {"error": "single 策略需要 conditions"}
    df = _load_klines([symbol], ktype)
    if df is None or df.empty:
        return {"error": "无行情数据"}
    # 简化：对 conditions 树递归求值（此处仅支持单条件首版，完整树后续迭代）
    factor = conditions.get("factor")
    op = conditions.get("op")
    ref = conditions.get("value")
    if not factor or not op:
        return {"error": "conditions 仅支持单因子条件（factor/op/value）"}
    fam, params = _parse_factor_ref(factor)
    if fam not in ff.FAMILIES:
        return {"error": f"未知因子: {factor}"}
    s_series = ff.compute_raw(fam, params, df)
    if s_series.empty:
        return {"error": "因子值为空"}
    cur = float(s_series.iloc[-1])
    hit = _cmp(op, cur, ref)
    result = {"strategy_id": sid, "symbol": symbol, "factor": factor,
              "value": round(cur, 4), "ref": ref, "op": op, "hit": hit}
    if hit:
        sig_id = fstorage.persist_signal(sid, symbol, "buy", cur, cur)
        result["signal_id"] = sig_id
        publish("signal.created", {"strategy_id": sid, "signals": [{"id": sig_id,
                 "symbol": symbol, "type": "buy", "score": cur}]})
    return result


def _parse_factor_ref(ref: str) -> tuple[str, dict]:
    """'momentum(L=20,S=5)' → ('momentum', {'L':20,'S':5})。"""
    if "(" not in ref:
        return ref, {}
    name, rest = ref.split("(", 1)
    params = {}
    for kv in rest.rstrip(")").split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            try:
                params[k.strip()] = int(float(v))
            except ValueError:
                params[k.strip()] = float(v)
    return name, params


def _cmp(op: str, cur: float, ref: float) -> bool:
    try:
        if op == ">": return cur > ref
        if op == "<": return cur < ref
        if op == ">=": return cur >= ref
        if op == "<=": return cur <= ref
        if op == "==": return abs(cur - ref) < 1e-9
        if op == "!=": return abs(cur - ref) >= 1e-9
    except TypeError:
        return False
    return False


def _latest_prices(df: pd.DataFrame, symbols: list[str]) -> dict:
    out = {}
    d = df.sort_values("date").groupby("symbol").tail(1)
    for _, r in d.iterrows():
        if r["symbol"] in symbols:
            out[r["symbol"]] = float(r["close"])
    return out
