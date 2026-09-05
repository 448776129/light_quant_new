"""BUG-001 自动交易重复下单（P0，资金安全）

现象：`python -m light_quant_new.main` 时模块级代码被执行两次（一次作为 __main__，
一次由 uvicorn 以 "light_quant_new.main:app" 字符串导入），trading.setup() 重复调用，
signal.created 订阅被注册多次 → 同一信号触发多笔下单。
"""
from __future__ import annotations


def _publish_one_signal():
    from light_quant_new.core import events
    events.publish("signal.created", {
        "strategy_id": 1,
        "signals": [{"id": 1, "symbol": "AAPL", "type": "buy", "score": 1.0}],
    })


def test_setup_called_twice_only_creates_one_order():
    """模块被二次导入后，发布 1 次信号仍只应产生 1 笔订单。"""
    from light_quant_new.trading import service as tsvc
    from light_quant_new.trading import storage as tstorage

    tsvc.save_settings({"enabled": "true", "strategy_ids": ""})
    tsvc.setup()
    tsvc.setup()                      # 模拟 __main__ + uvicorn 双重执行

    _publish_one_signal()

    orders = [o for o in tstorage.list_orders(50) if o["symbol"] == "AAPL"]
    assert len(orders) == 1, (
        f"发布 1 次信号产生了 {len(orders)} 笔订单（重复注册事件处理器）；"
        f"自动交易下会导致双倍仓位")


def test_setup_is_idempotent_after_three_calls():
    from light_quant_new.trading import service as tsvc
    from light_quant_new.trading import storage as tstorage

    tsvc.save_settings({"enabled": "true", "strategy_ids": ""})
    for _ in range(3):
        tsvc.setup()

    _publish_one_signal()

    orders = [o for o in tstorage.list_orders(50) if o["symbol"] == "AAPL"]
    assert len(orders) == 1
