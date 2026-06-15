"""Order placement — DISABLED in v1.

This module exists ONLY as a guard rail and a placeholder for a future,
explicitly-opt-in trading version. Every entry point raises. Nothing in the
pipeline imports or calls these functions; ``test_safety.py`` enforces that.
"""

from __future__ import annotations


class OrdersDisabledError(RuntimeError):
    """Raised whenever order placement is attempted. v1 is analysis-only."""


def place_order(*args: object, **kwargs: object) -> None:
    raise OrdersDisabledError(
        "Order placement is permanently disabled in this analysis-only build. "
        "No real orders are ever sent."
    )


def cancel_order(*args: object, **kwargs: object) -> None:
    raise OrdersDisabledError("Order cancellation is disabled in this analysis-only build.")
