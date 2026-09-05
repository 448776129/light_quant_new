"""配置加载 — 环境变量优先，缺省用内置默认值。

新系统设计原则：不依赖 .env 文件也能启动（用默认值），
.env 存在时自动加载覆盖。路径统一基于项目根目录。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent          # light_quant_new/
BASE_DIR = ROOT_DIR.parent                                  # 工作区根


def _load_dotenv() -> None:
    """若工作区根有 .env 则加载（仅设置未定义的环境变量，不覆盖已有）。"""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# ── 服务 ──
HOST = _env("HOST", "127.0.0.1")
# 新系统独立端口：用 LQN_PORT 环境变量（默认 3217），
# 避免被工作区 .env 里旧系统的 PORT=3216 覆盖导致端口冲突
PORT = _env_int("LQN_PORT", 3217)
LOG_LEVEL = _env("LOG_LEVEL", "INFO")
LOG_FILE = _env("LOG_FILE", str(ROOT_DIR / "server.log"))

# ── 存储 ──
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
# 单文件 SQLite：所有模块共享一个业务库，表归属由 core.storage 隔离
DB_PATH = _env("DB_PATH", str(DATA_DIR / "quant.db"))

# ── 数据源：历史 K 线（stocks-tv TradingView 管道）──
STOCKS_TV_BASE = _env("STOCKS_TV_BASE", "https://stocks-tv.365200.xyz")
STOCKS_TV_TIMEOUT = _env_int("STOCKS_TV_TIMEOUT", 20)
# 新闻/快讯管道（stocks-api2 Yahoo/东财 管道）
STOCKS_API2_BASE = _env("STOCKS_API2_BASE", "https://stocks-api2.365200.xyz")
STOCKS_API2_TIMEOUT = _env_int("STOCKS_API2_TIMEOUT", 20)
# 47 平台（finnhub 新闻代理 + futu 实时行情/WS）
PLATFORM_BASE_URL = _env("PLATFORM_BASE_URL", "http://47.103.124.40:3215")
PLATFORM_TIMEOUT = _env_int("PLATFORM_TIMEOUT", 15)
# 历史行情 CSV 数据目录（gzip 压缩，us/kline/*.csv）
KLINE_CSV_DIR = _env("KLINE_CSV_DIR", r"C:/Users/a4487/Desktop/111")
# 历史行情拉取栏目配置（定时间隔秒、启用开关）
HISTORY_PULL_INTERVAL = _env_int("HISTORY_PULL_INTERVAL", 3600)
HISTORY_PULL_ENABLED = _env_bool("HISTORY_PULL_ENABLED", False)

# ── 自动下单（Alpaca，可选；未配置密钥则下单模块仅报错不崩溃）──
ALPACA_API_KEY = _env("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = _env("ALPACA_SECRET_KEY", "")
ALPACA_TRADING_MODE = _env("ALPACA_TRADING_MODE", "paper")
ALPACA_ENABLE_LIVE = _env_bool("ALPACA_ENABLE_LIVE", False)
# 多模拟盘账号：`名称:api_key:secret_key;名称2:key2:secret2`（default 用 ALPACA_API_KEY/SECRET）
ALPACA_PAPER_ACCOUNTS = _env("ALPACA_PAPER_ACCOUNTS", "")
