"""trading 数据源客户端 — Alpaca paper 多账号下单（REST 直连）。

账号：
  - default：ALPACA_API_KEY / ALPACA_SECRET_KEY（默认模拟盘）
  - acct1/acct2...：ALPACA_PAPER_ACCOUNTS=`名称:key:secret;名称2:key2:secret2`
密钥缺失时 is_available()=False，服务层降级为仅记录。
端点：https://paper-api.alpaca.markets/v2
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core import config
from ..core.logger import get_logger

log = get_logger("trading.client")

PAPER_URL = "https://paper-api.alpaca.markets/v2"


class TradingUnavailable(RuntimeError):
    pass


@dataclass
class Account:
    id: str
    name: str
    api_key: str
    secret_key: str

    def public(self) -> dict:
        return {"id": self.id, "name": self.name}


def _parse_accounts() -> list[Account]:
    """解析 default + 多账号（ALPACA_PAPER_ACCOUNTS）。"""
    out: list[Account] = []
    seen: set[str] = set()

    def _add(a: Account):
        if a.api_key and a.secret_key and a.id not in seen:
            seen.add(a.id)
            out.append(a)

    if config.ALPACA_API_KEY and config.ALPACA_SECRET_KEY:
        _add(Account(id="default", name="默认模拟盘",
                     api_key=config.ALPACA_API_KEY,
                     secret_key=config.ALPACA_SECRET_KEY))
    for i, seg in enumerate(str(config.ALPACA_PAPER_ACCOUNTS or "").split(";"), start=1):
        seg = seg.strip()
        if not seg:
            continue
        parts = [p.strip() for p in seg.split(":")]
        if len(parts) < 3:
            log.warning("bad_account", extra={"seg": seg[:40]})
            continue
        name, key, secret = parts[0], parts[1], parts[2]
        _add(Account(id=f"acct{i}", name=name, api_key=key, secret_key=secret))
    return out


def accounts() -> list[Account]:
    return _parse_accounts()


def accounts_public() -> list[dict]:
    return [a.public() for a in accounts()]


def get_account_by_id(account_id: str) -> Optional[Account]:
    accs = accounts()
    if not account_id:
        return accs[0] if accs else None
    return next((a for a in accs if a.id == account_id), None)


def is_available() -> bool:
    return bool(accounts())


def _headers(acc: Account) -> dict:
    return {
        "APCA-API-KEY-ID": acc.api_key,
        "APCA-API-SECRET-KEY": acc.secret_key,
        "Content-Type": "application/json",
    }


def submit_order(symbol: str, side: str, qty: float,
                 order_type: str = "market",
                 limit_price: float | None = None,
                 time_in_force: str = "day",
                 account: str = "") -> dict:
    """提交市价/限价单到指定模拟账号（空=第一个账号）。返回 Alpaca 订单 dict。"""
    acc = get_account_by_id(account)
    if acc is None:
        raise TradingUnavailable("无可用 Alpaca 模拟账号（未配置密钥）")
    body = {
        "symbol": symbol.upper(),
        "qty": str(int(qty)) if qty == int(qty) else str(qty),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
    }
    if order_type == "limit" and limit_price:
        body["limit_price"] = str(limit_price)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{PAPER_URL}/orders", data=data, method="POST",
                                 headers=_headers(acc))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Alpaca 下单失败 {e.code}: {err}") from e


def get_account(account: str = "") -> dict:
    """指定账号的账户信息（默认第一个账号）。"""
    acc = get_account_by_id(account)
    if acc is None:
        raise TradingUnavailable("无可用 Alpaca 模拟账号")
    req = urllib.request.Request(f"{PAPER_URL}/account", headers=_headers(acc))
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def get_positions(account: str = "") -> list[dict]:
    """指定账号的持仓（默认第一个账号）。"""
    acc = get_account_by_id(account)
    if acc is None:
        raise TradingUnavailable("无可用 Alpaca 模拟账号")
    req = urllib.request.Request(f"{PAPER_URL}/positions", headers=_headers(acc))
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))