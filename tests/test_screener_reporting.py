"""BUG-005 因子失败静默吞掉

evaluate_screener 对 combo 中每个因子用 `except Exception: continue` 兜住，
失败与「因子值为空」都不留痕。用户看到的是流程正常完成、只是信号变少，
无法判断是数据不足还是因子本身算错了。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

KTYPE = "K_DAY"


def _fake_provider(n_sym: int = 6, n_day: int = 200):
    rng = np.random.default_rng(11)
    dates = pd.bdate_range("2024-01-01", periods=n_day)
    rows = []
    for i in range(n_sym):
        sym = f"S{i}"
        px = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.018, n_day)))
        for d, p in zip(dates, px):
            rows.append({"symbol": sym, "date": str(d.date()), "open": p, "high": p * 1.01,
                         "low": p * 0.99, "close": p, "adj_close": p,
                         "volume": float(rng.integers(1e5, 9e6))})
    df = pd.DataFrame(rows)

    def provider(symbols=None, ktype=KTYPE):
        return df
    return provider


def _create_screener(combo: list[dict]) -> int:
    from light_quant_new.factors import service as fsvc
    fsvc.set_klines_provider(_fake_provider())
    return fsvc.create_strategy(
        "t", {"category": "screener", "ktype": KTYPE, "combo": combo,
              "long_pct": 0.2, "short_pct": 0.2})


def test_failed_factor_is_reported():
    """combo 中某因子抛异常时，结果必须显式上报，而不是静默跳过。"""
    from light_quant_new.factors import service as fsvc
    sid = _create_screener([
        {"family": "momentum", "params": {"L": 20, "S": 0}},   # 正常
        {"family": "volume", "params": {"W": -1}},             # rolling(-1) 抛 ValueError
    ])
    result = fsvc.evaluate_screener(sid, KTYPE)

    assert "error" not in result, f"整体失败: {result}"
    failed = result.get("failed_factors") or []
    assert any("volume" in str(f) for f in failed), (
        f"volume 因子计算失败但未被上报，result keys={sorted(result.keys())}")


def test_empty_factor_is_reported():
    """因子因窗口超过数据长度而全空时，也应上报原因。"""
    from light_quant_new.factors import service as fsvc
    sid = _create_screener([
        {"family": "momentum", "params": {"L": 20, "S": 0}},
        {"family": "volatility", "params": {"W": 99999}},      # 窗口远超数据长度 → 全空
    ])
    result = fsvc.evaluate_screener(sid, KTYPE)

    assert "error" not in result, f"整体失败: {result}"
    failed = result.get("failed_factors") or []
    assert any("volatility" in str(f) for f in failed), (
        f"volatility 因子为空但未被上报，result keys={sorted(result.keys())}")


def test_all_factors_ok_reports_no_failure():
    """正常情况下不应有误报。"""
    from light_quant_new.factors import service as fsvc
    sid = _create_screener([
        {"family": "momentum", "params": {"L": 20, "S": 0}},
        {"family": "reversal", "params": {"W": 10}},
    ])
    result = fsvc.evaluate_screener(sid, KTYPE)

    assert "error" not in result, f"整体失败: {result}"
    assert not result.get("failed_factors"), f"误报失败: {result.get('failed_factors')}"
    assert result.get("signals"), "未产出信号"
