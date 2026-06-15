"""Safety guards: no orders, ever; trading flag refused."""

from __future__ import annotations

import pytest

from tossai.config import Settings, TradingEnabledError
from tossai.toss import orders


def test_place_order_always_raises():
    with pytest.raises(orders.OrdersDisabledError):
        orders.place_order("005930", qty=1, price=100)


def test_cancel_order_always_raises():
    with pytest.raises(orders.OrdersDisabledError):
        orders.cancel_order("order-id")


def test_enable_trading_true_refused():
    s = Settings(enable_trading=True)
    with pytest.raises(TradingEnabledError):
        s.enforce_safety()


def test_enable_trading_false_ok():
    s = Settings(enable_trading=False)
    s.enforce_safety()  # must not raise


def test_orchestrator_has_no_order_path():
    # The orchestrator module must neither import the orders module nor call
    # any order function.
    import tossai.pipeline.orchestrator as orch

    with open(orch.__file__, encoding="utf-8") as fh:
        text = fh.read()
    assert "place_order" not in text
    assert "cancel_order" not in text
    assert "toss.orders" not in text
    assert "import orders" not in text
