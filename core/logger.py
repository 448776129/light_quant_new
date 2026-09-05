"""日志 — 标准 logging 封装，模块名作 logger 名，简单可靠。"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from . import config


def get_logger(name: str) -> logging.Logger:
    """按模块名取 logger（如 market, factors.trading）。"""
    return logging.getLogger(f"lqn.{name}")


def setup_logging() -> None:
    root = logging.getLogger("lqn")
    if root.handlers:          # 已初始化
        return
    root.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # 控制台
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    # 文件（轮转 10MB×3）
    try:
        fh = RotatingFileHandler(config.LOG_FILE, maxBytes=10_485_760,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass  # 文件不可写时仅控制台输出，不阻断
