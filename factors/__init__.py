"""factors 模块 — 因子计算 + 策略定义/评估 + 信号。

设计（提取自旧系统 factor_families，去掉财报依赖，纯技术因子）：
  - compute_raw(family, params, df)：DataFrame(symbol,date,open,high,low,close,volume)
    → MultiIndex[date,symbol] 因子值（已带经济方向）
  - z_per_date(wide)：横截面 z-score
  - 策略 definition 用 JSON 表达（category/conditions 或 combo 因子组合）
  - eval：对股票池算因子 → 横截面打分 → 多空信号
依赖：仅 core。表归属：strategies / signals。
"""
