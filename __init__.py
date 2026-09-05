# light_quant_new — 轻量量化系统
#
# 单进程多包架构，5 个业务模块共享 core：
#   market  /  news  /  factors  /  backtest  /  trading
#
# 解耦铁律：
#   1. 业务模块之间零直接 import（禁止跨模块引用内部实现）
#   2. 业务模块只依赖 core
#   3. 跨模块数据一律走 core.storage（表归属隔离）或 core.events（事件总线）
#   4. 服务端渲染（Jinja2 模板），不使用前后端分离
