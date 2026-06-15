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


def test_slack_scheduler_risk_packages_have_no_order_path():
    # The new presentation/triggering layers must never IMPORT the orders module
    # or CALL an order function. Parse the AST so prose in docstrings (e.g.
    # "nothing here imports orders") doesn't trip the check.
    import ast
    import glob
    import os

    import tossai

    base = os.path.dirname(tossai.__file__)
    suspect = []
    for pkg in ("slack", "scheduler", "risk"):
        for path in glob.glob(os.path.join(base, pkg, "*.py")):
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and "orders" in node.module:
                    suspect.append(path)
                if isinstance(node, ast.Import) and any("orders" in n.name for n in node.names):
                    suspect.append(path)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
                        node.func.id in ("place_order", "cancel_order"):
                    suspect.append(path)
    assert suspect == [], f"order path leaked into: {suspect}"
