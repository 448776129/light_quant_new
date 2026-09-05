"""回测引擎 — 内置策略模板 + 状态机回测（纯 pandas，无 backtrader 依赖）。

模板：dual_ma(双均线) / momentum(动量突破) / rsi(RSI 均值回归)
输出契约：final_capital / return_pct / win_rate / max_drawdown_pct /
         trade_count / trades / equity_curve
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

TEMPLATES: dict[str, dict] = {
    "dual_ma": {
        "label": "双均线趋势",
        "params": {"fast": (5, 50, int), "slow": (20, 200, int)},
        "default": {"fast": 10, "slow": 30},
        "desc": "快线上穿慢线全仓买入，下穿清仓（趋势跟随）",
    },
    "momentum": {
        "label": "动量突破",
        "params": {"lookback": (10, 120, int)},
        "default": {"lookback": 20},
        "desc": "收盘创 N 日新高买入，跌破 N 日低点清仓（突破跟踪）",
    },
    "rsi": {
        "label": "RSI 均值回归",
        "params": {"period": (5, 30, int), "oversold": (10, 35, int), "overbought": (65, 90, int)},
        "default": {"period": 14, "oversold": 30, "overbought": 70},
        "desc": "RSI 超卖买入，超买卖出（逆势）",
    },
}


def run_backtest(df: pd.DataFrame, template: str = "dual_ma",
                 params: dict | None = None,
                 initial_capital: float = 10000.0) -> dict:
    """对单标的日 K 跑内置模板回测。df 需含 date/close（可含 volume）。"""
    if template not in TEMPLATES:
        return {"error": f"未知模板: {template}"}
    tpl = TEMPLATES[template]
    p = {**tpl["default"], **(params or {})}

    d = df.copy().sort_values("date").reset_index(drop=True)
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d = d.dropna(subset=["close"])
    if len(d) < 50:
        return {"error": f"K线不足（{len(d)} 根，至少 50）"}

    close = d["close"]
    # ── 信号 ──
    if template == "dual_ma":
        fast = int(p["fast"]); slow = int(p["slow"])
        if slow <= fast:
            return {"error": "slow 必须大于 fast"}
        ma_f = close.rolling(fast).mean()
        ma_s = close.rolling(slow).mean()
        buy = (ma_f > ma_s) & (ma_f.shift(1) <= ma_s.shift(1))
        sell = (ma_f < ma_s) & (ma_f.shift(1) >= ma_s.shift(1))
    elif template == "momentum":
        lb = int(p["lookback"])
        hi = close.rolling(lb).max().shift(1)
        lo = close.rolling(lb).min().shift(1)
        buy = close > hi
        sell = close < lo
    elif template == "rsi":
        period = int(p["period"]); os_ = float(p["oversold"]); ob_ = float(p["overbought"])
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = (100 - 100 / (1 + rs)).fillna(50)
        buy = rsi < os_
        sell = rsi > ob_

    # ── 状态机（全仓 buy & close，零佣金）──
    cash, shares = initial_capital, 0.0
    entry_price, entry_time = None, None
    trades: list[dict] = []
    equity_curve: list[dict] = []

    for i in range(len(d)):
        row = d.iloc[i]
        price, ts = float(row["close"]), str(row["date"])
        if bool(sell.iloc[i]) and shares > 0:
            pnl = (price - entry_price) / entry_price * 100 if entry_price else 0.0
            trades.append({"entry_time": entry_time or ts, "entry_price": round(entry_price or 0, 4),
                           "exit_time": ts, "exit_price": round(price, 4), "pnl_pct": round(pnl, 4)})
            cash, shares = shares * price, 0.0
            entry_price = entry_time = None
        if bool(buy.iloc[i]) and shares == 0 and cash > 0:
            entry_price, entry_time = price, ts
            shares, cash = cash / price, 0.0
        equity_curve.append({"time": ts, "equity": round(cash + shares * price, 2)})

    if shares > 0:
        last_price = float(d.iloc[-1]["close"])
        pnl = (last_price - entry_price) / entry_price * 100 if entry_price else 0.0
        trades.append({"entry_time": entry_time or str(d.iloc[-1]["date"]),
                       "entry_price": round(entry_price or 0, 4),
                       "exit_time": str(d.iloc[-1]["date"]), "exit_price": round(last_price, 4),
                       "pnl_pct": round(pnl, 4)})
        cash = shares * last_price

    eq = [e["equity"] for e in equity_curve]
    final_capital = cash
    return_pct = (final_capital / initial_capital - 1) * 100 if initial_capital else 0.0
    win_rate = round(sum(1 for t in trades if t["pnl_pct"] > 0) / len(trades), 4) if trades else None
    peak, mdd = -1e18, 0.0
    for e in eq:
        peak = max(peak, e)
        if peak > 0:
            mdd = min(mdd, (e - peak) / peak * 100)

    # 买入持有基准
    bh = (d.iloc[-1]["close"] / d.iloc[0]["close"] - 1) * 100 if len(d) else 0.0

    return {
        "implemented": True,
        "template": template,
        "params": p,
        "final_capital": round(final_capital, 2),
        "return_pct": round(return_pct, 4),
        "buy_hold_pct": round(bh, 4),
        "win_rate": win_rate,
        "max_drawdown_pct": round(mdd, 4),
        "trade_count": len(trades),
        "trades": trades,
        "equity_curve": equity_curve,
        "start": str(d.iloc[0]["date"]), "end": str(d.iloc[-1]["date"]),
        "bars": len(d),
    }
