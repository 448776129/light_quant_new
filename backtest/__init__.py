"""backtest 模块 — 历史回测（内置策略模板）+ 绩效报告。

跨模块解耦：K 线经注入的 klines_provider（main 组装时注入 market 的
取数函数），不直接 import market。
表归属：backtests。
"""
