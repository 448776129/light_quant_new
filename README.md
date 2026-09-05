# light_quant_new — 轻量量化系统

从臃肿的旧系统提取的模块化重构版：**单进程多包**，5 个业务模块共享 core，
**服务端渲染**（FastAPI + HTML 模板，非前后端分离）。

## 模块结构

```
light_quant_new/
├── core/          # 共享基础设施（唯一允许被所有模块依赖的层）
│   ├── config.py    # 配置（环境变量优先）
│   ├── logger.py    # 标准 logging
│   ├── storage.py   # SQLite + 表归属隔离（模块解耦的数据基础）
│   └── events.py    # 事件总线（发布/订阅）
├── market/        # 实时行情 + 历史行情拉取
├── news/          # 新闻财报（规划）
├── factors/       # 因子策略（规划）
├── backtest/      # 历史回测（规划）
├── trading/       # 自动下单（规划）
├── main.py        # FastAPI 组装 + 定时任务
└── requirements.txt
```

## 解耦铁律

1. **业务模块之间零直接 import**——禁止 `from market import ...` 出现在 news/factors 等模块
2. 业务模块**只依赖 core**
3. 跨模块数据一律走 `core.storage`（表归属隔离）或 `core.events`（事件总线）
4. 每张表登记 owner 模块；跨模块直接查表抛 `AccessError`

## 表归属（当前）

| 表 | owner | 说明 |
|---|---|---|
| kline | market | K线数据（symbol+interval+datetime 主键） |
| pull_settings | market | 历史行情拉取配置（面板可改） |
| pull_log | market | 拉取操作日志 |

## 启动

```bash
# 工作区根目录
python -m light_quant_new.main
# 访问 http://127.0.0.1:3217/market
```

端口用 `LQN_PORT` 环境变量控制（默认 3217，避免与旧系统 3216 冲突）。

## 历史行情拉取栏目（/market）

- **导入**：把本地 gzip CSV（默认 `C:/Users/a4487/Desktop/111/us/kline/*.csv`）批量入库，启动时自动导入（幂等）
- **拉取**：从 stocks-tv（`https://stocks-tv.365200.xyz/kline`）增量追加最新数据；
  指定标的同步快速返回，全部标的走后台任务（页面轮询状态）
- **配置**：定时开关 / 间隔秒 / K线周期 / 指定标的，面板表单可改，定时任务自动生效
- 数据字段：Datetime / Open / High / Low / Close / Adj Close / Volume（与 CSV、stocks-tv 一致）

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| LQN_PORT | 3217 | 服务端口 |
| DB_PATH | light_quant_new/data/quant.db | 数据库文件 |
| KLINE_CSV_DIR | C:/Users/a4487/Desktop/111 | 本地 CSV 根目录 |
| STOCKS_TV_BASE | https://stocks-tv.365200.xyz | stocks-tv 数据源 |
| HISTORY_PULL_INTERVAL | 3600 | 定时拉取间隔（秒）默认 |
