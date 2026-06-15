"""Walk-forward backtesting for the strategy ensemble (analysis/simulation only).

Reuses the exact ``screen_universe`` seam: at each rebalance date the strategy is
run on history-up-to-that-date, the top names are held equal-weight (or
inverse-vol) until the next rebalance, and a daily equity curve + performance
metrics are produced. No orders, no live API needed — it runs on any candle
history (Toss, pykrx, yfinance, …).
"""

from __future__ import annotations

from tossai.backtest.engine import BacktestResult, walk_forward_backtest
from tossai.backtest.metrics import PerformanceMetrics, compute_metrics

__all__ = [
    "BacktestResult",
    "walk_forward_backtest",
    "PerformanceMetrics",
    "compute_metrics",
]
