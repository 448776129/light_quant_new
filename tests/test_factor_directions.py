"""BUG-002 因子方向：reversal 应为「短期反转」，与 FAMILIES 描述一致。

因子值约定（core）：越高越该做多。
  - momentum：过去 L 日收益，涨得多 → 分高
  - reversal：过去 W 日收益取负，涨得多 → 分低（均值回归）
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _two_symbols_df(n_common: int = 180, n_tail: int = 20) -> pd.DataFrame:
    """两个标的：前段走势一致，最后 n_tail 日 A 大涨、B 大跌。"""
    rng = np.random.default_rng(42)
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.005, n_common)))
    dates = [str(d.date()) for d in pd.bdate_range("2023-01-01", periods=n_common + n_tail)]

    rows = []
    for sym, tail_slope in (("WIN", 0.03), ("LOS", -0.03)):
        tail = base[-1] * np.exp(np.cumsum(np.full(n_tail, tail_slope)))
        prices = np.concatenate([base, tail])
        for d, px in zip(dates, prices):
            rows.append({"symbol": sym, "date": d, "open": px, "high": px, "low": px,
                         "close": px, "adj_close": px, "volume": 1e6})
    return pd.DataFrame(rows)


def _last_scores(family: str, params: dict) -> dict:
    from light_quant_new.factors import factor_families as ff
    df = _two_symbols_df()
    s = ff.compute_raw(family, params, df)
    wide = s.unstack("symbol")
    last = wide.iloc[-1]
    return {"WIN": float(last["WIN"]), "LOS": float(last["LOS"])}


def test_momentum_favours_recent_winner():
    """对照：momentum 给近期强势标的更高分。"""
    sc = _last_scores("momentum", {"L": 20, "S": 0})
    assert sc["WIN"] > sc["LOS"], f"momentum 方向异常: {sc}"


def test_reversal_favours_recent_loser():
    """reversal 是短期反转：近期涨幅大的标的应得分更低。"""
    sc = _last_scores("reversal", {"W": 20})
    assert sc["WIN"] < sc["LOS"], (
        f"reversal 方向反了：近期上涨标的分 {sc['WIN']:.4f} 反而高于下跌标的 "
        f"{sc['LOS']:.4f}；与 desc「过去 W 日收益的负值(均值回归)」矛盾")


def test_reversal_value_equals_negative_return():
    """reversal 值应等于过去 W 日收益的负值。"""
    from light_quant_new.factors import factor_families as ff
    df = _two_symbols_df()
    s = ff.compute_raw("reversal", {"W": 20}, df).rename("fac").reset_index()

    exp = df[["symbol", "date"]].copy()
    exp["exp"] = -df.groupby("symbol")["adj_close"].pct_change(20)
    m = s.merge(exp.dropna(), on=["date", "symbol"]).dropna()

    assert len(m) > 0, "无有效样本，测试数据构造有误"
    max_gap = float((m["fac"] - m["exp"]).abs().max())
    assert max_gap < 1e-9, f"reversal 与「-W 日收益」最大偏差 {max_gap:.3e}"
