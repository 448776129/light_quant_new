"""因子计算 — 纯 pandas 技术因子族（提取自旧系统 factor_families，无财报依赖）。

输入 DataFrame 需含列：symbol / date / open / high / low / close / volume
（price 优先用 adj_close 列，缺失回退 close）。
输出 MultiIndex[date, symbol] Series，值已带经济方向（越高越该做多）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FAMILIES: dict = {
    "momentum": {"desc": "动量: 过去 L 日收益, 跳过最近 S 日(避免短期反转污染)",
                 "params": {"L": (20, 250, int), "S": (0, 20, int)}, "sign": +1},
    "reversal": {"desc": "短期反转: 过去 W 日收益的负值(均值回归)",
                 "params": {"W": (5, 30, int)}, "sign": +1},
    "volatility": {"desc": "波动率: 过去 W 日年化波动率, 取负(低波偏好)",
                   "params": {"W": (10, 60, int)}, "sign": -1},
    "volume": {"desc": "量能: 过去 W 日成交量均值(相对放量)",
               "params": {"W": (10, 40, int)}, "sign": +1},
    "ma_dist": {"desc": "均线偏离: close/MA(P)-1(站上均线)",
                "params": {"P": (20, 250, int)}, "sign": +1},
    "amihud": {"desc": "Amihud 非流动性: |日收益|/成交额, 取负(高流动性偏好)",
               "params": {"W": (10, 60, int)}, "sign": -1},
}


def _price_col(df: pd.DataFrame) -> str:
    return "adj_close" if "adj_close" in df.columns else "close"


def _raw_fn(family: str, df: pd.DataFrame, params: dict) -> pd.Series:
    """原始因子 Series（RangeIndex，未带方向）。"""
    p = _price_col(df)
    g = df.groupby("symbol")[p]
    v = df["volume"]
    if family == "momentum":
        L = int(params.get("L", 120)); S = int(params.get("S", 0))
        return g.shift(S) / g.shift(L + S) - 1
    if family == "reversal":
        W = int(params.get("W", 20))
        return df.groupby("symbol")[p].pct_change(W)
    if family == "volatility":
        W = int(params.get("W", 20))
        ret = df.groupby("symbol")[p].pct_change(1)
        sd = ret.groupby(df["symbol"]).transform(lambda s: s.rolling(W, min_periods=W).std())
        return sd * np.sqrt(252)
    if family == "volume":
        W = int(params.get("W", 20))
        return v.groupby(df["symbol"]).transform(lambda s: s.rolling(W, min_periods=W).mean())
    if family == "ma_dist":
        P = int(params.get("P", 60))
        ma = df.groupby("symbol")[p].transform(lambda s: s.rolling(P, min_periods=P).mean())
        return df[p] / ma - 1
    if family == "amihud":
        W = int(params.get("W", 20))
        ret = df.groupby("symbol")[p].pct_change(1).abs()
        dv = v.groupby(df["symbol"]).transform(lambda s: s.rolling(W, min_periods=W).mean()) * df[p]
        return ret / dv.replace(0, np.nan)
    raise ValueError(f"未知因子族: {family}")


def compute_raw(family: str, params: dict, df: pd.DataFrame) -> pd.Series:
    """计算因子值 → MultiIndex[date,symbol]，已带经济方向。"""
    if family not in FAMILIES:
        raise ValueError(f"未知因子族: {family}")
    meta = FAMILIES[family]
    raw = _raw_fn(family, df, params) * meta["sign"]
    raw = raw.dropna()
    if raw.empty:
        return raw
    mi = pd.MultiIndex.from_frame(df.loc[raw.index, ["date", "symbol"]])
    return raw.set_axis(mi)


def compute_multi(combo: list[dict], df: pd.DataFrame) -> pd.DataFrame:
    """按 combo 规格 [{family, params}] 计算各因子，返回 date×symbol 宽表（列=因子名）。"""
    frames = {}
    for spec in combo:
        fam = spec["family"]
        params = spec.get("params") or {}
        key = f"{fam}({_fmt_params(params)})"
        s = compute_raw(fam, params, df)
        if s.empty:
            continue
        w = s.unstack("symbol")          # date × symbol
        frames[key] = w
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=1) if len(frames) > 1 else frames[list(frames)[0]]
    return out


def z_per_date(wide: pd.DataFrame) -> pd.DataFrame:
    """date×symbol 宽表 → 同日横截面 z-score。"""
    mu = wide.mean(axis=1)
    sd = wide.std(axis=1).replace(0, np.nan)
    return wide.sub(mu, axis=0).div(sd, axis=0)


def composite_score(wide: pd.DataFrame) -> pd.DataFrame:
    """多因子等权合成：各因子 z-score 平均 → date×symbol 复合分。"""
    z = z_per_date(wide)
    return z.mean(axis=1).unstack("symbol") if isinstance(z.index, pd.MultiIndex) else z


def _fmt_params(params: dict) -> str:
    return ",".join(f"{k}={v}" for k, v in sorted(params.items()))


def list_families() -> list[dict]:
    """因子族清单（栏目展示）。"""
    return [{"name": k, "desc": v["desc"], "params": {
        p: {"lo": lo, "hi": hi, "type": t.__name__} for p, (lo, hi, t) in v["params"].items()}}
        for k, v in FAMILIES.items()]
