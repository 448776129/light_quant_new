# light_quant_new — 轻量量化系统

从臃肿旧系统提取的**模块化重构版**：单进程多包，5 个业务模块共享 `core`，
服务端渲染（FastAPI + Jinja2 模板，非前后端分离），数据统一落在单文件 SQLite。

- **行情**：本地 CSV 批量入库 + 远程增量拉取 + futu 实时行情 WebSocket
- **新闻**：三源快讯（东财 / 雅虎 / 聚合）+ 个股新闻 + 财报日历
- **因子**：6 大技术因子族，支持多因子选股（screener）与单标的信号（single）
- **回测**：双均线 / 动量突破 / RSI 均值回归 三个内置模板，纯 pandas 实现
- **交易**：Alpaca 模拟盘下单，支持事件驱动的自动交易与多模拟账号

---

## 快速开始

```bash
# 1. 依赖（Python 3.10+）
pip install -r requirements.txt

# 2. 启动（注意：在项目「父目录」执行，包名即目录名）
python -m light_quant_new.main

# 3. 打开
http://127.0.0.1:3217/market
```

默认端口 **3217**（旧系统常用 3216，这里刻意错开，避免冲突）。
`/` 会重定向到 `/market`。

启动时会自动：建库建表 → 按配置导入本地 CSV（幂等）→ 拉起两个定时循环 → 连接实时行情 WS。

---

## 目录结构

```
light_quant_new/
├── core/            # 共享基础设施（唯一允许被所有模块依赖的层）
│   ├── config.py      # 配置：环境变量优先，.env 可选，缺省即用默认值
│   ├── logger.py      # 标准 logging（控制台 + server.log）
│   ├── storage.py     # SQLite 封装 + 表归属隔离
│   ├── events.py      # 事件总线（发布/订阅）
│   └── templates.py   # Jinja2 渲染封装
├── market/          # 历史行情（CSV 导入 / 增量拉取）+ futu 实时行情 WS
├── news/            # 快讯三源入库、个股新闻、财报日历
├── factors/         # 因子计算、策略 CRUD、信号评估
├── backtest/        # 内置模板回测
├── trading/         # Alpaca 模拟盘下单（自动 + 手动）
├── static/          # 静态资源
├── templates/       # Jinja2 页面模板
├── main.py          # FastAPI 组装 + 定时任务 + 依赖注入
└── requirements.txt
```

---

## 模块能力

### market — 历史行情拉取

- **导入**：把本地 gzip CSV（默认 `C:/Users/a4487/Desktop/111/us/kline/*.csv`）批量入库，幂等；启动时可自动执行
- **拉取**：从 stocks-tv 增量追加最新 K 线（以库内最后时间为起点向后拉，upsert 去重），
  指定标的同步返回，全量标的走后台任务 + 页面轮询状态
- **定时**：面板可改「开关 / 间隔秒 / K线周期 / 指定标的」，改完自动生效
- **周期**：`1d / 1m / 5m / 15m / 30m / 1h / 1wk / 1mo`
- **实时**：47 平台 futu WebSocket 行情推送（自动重连 + 重连恢复订阅）、实时报价与盘口（含延长时段）

### news — 新闻财报

- 三源快讯：`eastmoney`（东财 7x24）、`yahoo`（雅虎头条）、`aggregate`（聚合频道）
- 个股新闻：47 平台 finnhub 代理，按标的 + 天数拉取
- 财报日历：EPS / 营收的预期值与实际值
- 定时入库开关与间隔（分钟）可在面板配置

### factors — 因子策略

内置 6 个因子族（值已带经济方向，越高越该做多）：

| 因子族 | 含义 | 参数 |
|---|---|---|
| `momentum` | 过去 L 日收益，跳过最近 S 日 | L, S |
| `reversal` | 短期反转（过去 W 日收益取负） | W |
| `volatility` | 年化波动率取负（低波偏好） | W |
| `volume` | 成交量均值（相对放量） | W |
| `ma_dist` | 均线偏离 `close/MA(P)-1` | P |
| `amihud` | Amihud 非流动性取负（高流动性偏好） | W |

两种策略形态：

- **screener（多因子选股）**：多因子合成打分，按 `long_pct` / `short_pct` 取多空两端
- **single（单标的信号）**：形如 `momentum(L=20,S=0) > 0.05` 的条件表达式触发买卖信号

信号产出后 `publish("signal.created", ...)`，由 trading 模块决定是否下单。

### backtest — 历史回测

| 模板 | 说明 | 默认参数 |
|---|---|---|
| `dual_ma` | 双均线趋势：快线上穿慢线全仓买入，下穿清仓 | fast=10, slow=30 |
| `momentum` | 动量突破：创 N 日新高买入，跌破 N 日低点清仓 | lookback=20 |
| `rsi` | RSI 均值回归：超卖买入，超买卖出 | period=14, 30/70 |

输出：`final_capital` / `return_pct` / `win_rate` / `max_drawdown_pct` / `trade_count` / `trades` / `equity_curve`。

### trading — 自动下单（Alpaca 模拟盘）

- 自动交易**默认关闭**（`enabled=false`），需显式开启
- 链路：factors 发布 `signal.created` → trading 按策略白名单过滤 → 下到指定模拟账号
- 支持手动下单、账户概览、持仓查询、订单与日志留痕
- 多模拟账号：`ALPACA_PAPER_ACCOUNTS=名称:key:secret;名称2:key2:secret2`
- **未配置密钥时不会崩溃**，订单降级记为 `failed`

---

## 解耦铁律

1. **业务模块之间零直接 import**——禁止 `from market import ...` 出现在 news/factors 等模块
2. 业务模块**只依赖 core**
3. 跨模块数据一律走 `core.storage`（表归属隔离）或 `core.events`（事件总线）
4. 取数依赖用**注入**而非 import：main 里 `factors/backtest.set_klines_provider(market.get_klines_dataframe)`，
   `trading` 需要的策略列表也由 `trading_routes.set_strategies_provider(factors.list_strategies)` 注入
5. 每张表登记 owner 模块；跨模块直接查表抛 `AccessError`

---

## 数据表归属

| 表 | owner | 说明 |
|---|---|---|
| kline | market | K 线数据（symbol+interval+datetime 主键） |
| pull_settings | market | 历史行情拉取配置（面板可改） |
| pull_log | market | 拉取/导入操作日志 |
| news | news | 快讯（title/url/time/digest/source） |
| news_settings | news | 定时入库配置 |
| news_log | news | 入库日志 |
| earnings | news | 财报日历（EPS / 营收预期与实际） |
| strategies | factors | 策略定义（JSON）与启用状态 |
| signals | factors | 信号，含 trading 回写的执行状态 |
| backtests | backtest | 回测参数与结果 |
| trading_orders | trading | 订单记录（含 Alpaca 订单号） |
| trading_log | trading | 交易事件日志 |
| trading_settings | trading | 自动交易配置 |

---

## 页面与接口

| 页面 | 说明 |
|---|---|
| `/market` | 行情：统计 / CSV 导入 / 增量拉取 / 定时配置 / 实时报价+盘口 / WS 订阅 |
| `/news` | 新闻：三源入库 / 个股新闻 / 财报日历 / 定时配置 |
| `/factors` | 因子策略：创建 / 启用切换 / 评估，查看信号 |
| `/backtest` | 回测：选标的 + 模板 + 参数，查看权益曲线 |
| `/trading` | 交易：自动交易配置 / 手动下单 / 账户 / 持仓 / 订单日志 |

补充接口：`GET /market/bg-status`（后台任务状态轮询，页面用）、`GET /trading/account/{account}`（账号概览）。

---

## 环境变量

不配置也能启动（内置默认值）。需要覆盖时，在工作区根目录放 `.env`，或直接设环境变量。

| 变量 | 默认 | 说明 |
|---|---|---|
| `LQN_PORT` | 3217 | 服务端口（刻意不复用旧系统 `PORT=3216`） |
| `HOST` | 127.0.0.1 | 监听地址 |
| `LOG_LEVEL` | INFO | 日志级别 |
| `LOG_FILE` | `<pkg>/server.log` | 日志文件 |
| `DB_PATH` | `<pkg>/data/quant.db` | SQLite 库路径 |
| `STOCKS_TV_BASE` | https://stocks-tv.365200.xyz | 历史 K 线数据源 |
| `STOCKS_API2_BASE` | https://stocks-api2.365200.xyz | 新闻/快讯数据源 |
| `PLATFORM_BASE_URL` | http://47.103.124.40:3215 | 47 平台（finnhub 代理 + futu 行情 WS） |
| `KLINE_CSV_DIR` | `C:/Users/a4487/Desktop/111` | 本地 gzip CSV 根目录 |
| `HISTORY_PULL_INTERVAL` | 3600 | 历史行情定时拉取间隔（秒） |
| `HISTORY_PULL_ENABLED` | false | 定时拉取总开关 |
| `ALPACA_API_KEY` | 空 | Alpaca Key（default 账号） |
| `ALPACA_SECRET_KEY` | 空 | Alpaca Secret |
| `ALPACA_TRADING_MODE` | paper | paper / live |
| `ALPACA_ENABLE_LIVE` | false | 实盘开关 |
| `ALPACA_PAPER_ACCOUNTS` | 空 | 多模拟账号 |

---

## 安全提示

- **密钥只走环境变量**，代码中不含任何硬编码凭据；`.env` 与 `data/*.db` 已在 `.gitignore` 中排除
- 自动交易默认关闭，开启前请确认 Alpaca 走的是模拟盘（`ALPACA_TRADING_MODE=paper`）
- 历史行情与新闻依赖第三方数据源，请自行评估可用性与合规风险

---

## 路线图

- [ ] factors：因子 IC / 分层回测
- [ ] backtest：组合级回测（当前为单标的）
- [ ] news：新闻情绪打分接入因子
- [ ] 模块级单元测试
