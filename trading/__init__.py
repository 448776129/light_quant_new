"""trading 模块 — 自动下单（订阅 factors 信号事件 → Alpaca paper 下单）。

跨模块解耦：
  - 订阅 core.events 的 "signal.created" 事件（factors 发布），自动执行
  - 不直接 import factors/market；信号数据由事件 payload 携带
  - Alpaca 密钥缺失时优雅降级（只记录不下单）
依赖：仅 core。表归属：trading_orders / trading_log。
"""
