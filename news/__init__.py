"""news 模块 — 新闻/财报数据源客户端 + 入库 + 栏目页。

数据源：
  - eastmoney 东财 7x24 快讯：stocks-api2 /news-em
  - yahoo     雅虎香港头条：stocks-api2 /news-yh
  - finnhub   公司新闻（按标的）：stocks-api2 /finnhub 相关端点（旧系统经 47 平台代理，
    新系统优先 stocks-api2；不可用时留空）
依赖：仅 core。表归属：news / earnings。
"""
