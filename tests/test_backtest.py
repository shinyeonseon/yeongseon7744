"""Backtest engine + metrics tests (deterministic, no network)."""

from __future__ import annotations

from helpers import make_series
from tossai.backtest.engine import walk_forward_backtest
from tossai.backtest.metrics import compute_metrics
from tossai.models import Candidate


def test_metrics_on_known_curve():
    # Equity doubling monotonically: total_return 1.0, no drawdown, all wins.
    equity = [1.0 * (1.01 ** i) for i in range(253)]  # ~1 year of +1%/day
    m = compute_metrics(equity)
    assert m.total_return > 0
    assert m.max_drawdown == 0.0
    assert m.win_rate == 1.0
    assert m.sharpe > 0


def test_metrics_drawdown():
    equity = [1.0, 1.2, 0.9, 1.0]  # peak 1.2 → trough 0.9 == -25%
    m = compute_metrics(equity)
    assert round(m.max_drawdown, 2) == -0.25


class _PickUp:
    """Stub strategy that always holds the trending 'UP' symbol."""

    required_history = 5

    def screen_universe(self, candle_map, markets=None):
        return [Candidate(symbol="UP", market="KRX", price=100.0, score=1.0)]


def test_walk_forward_beats_benchmark_on_uptrend():
    up = make_series([100.0 * (1.01 ** i) for i in range(120)])
    down = make_series([100.0 * (0.99 ** i) for i in range(120)])
    candle_map = {"UP": up, "DOWN": down}

    result = walk_forward_backtest(
        candle_map, _PickUp(), {"UP": "KRX", "DOWN": "KRX"},
        rebalance_days=21, top_n=1,
    )
    assert result.metrics.cagr > 0
    # holding only UP should beat the equal-weight UP+DOWN benchmark
    assert result.metrics.total_return > result.benchmark_metrics.total_return
    assert result.symbols == 2
    assert len(result.rebalances) >= 1


def test_walk_forward_insufficient_history():
    candle_map = {"X": make_series([100.0, 101.0, 102.0])}
    result = walk_forward_backtest(candle_map, _PickUp(), {"X": "KRX"})
    assert result.equity == [1.0]


def test_inverse_vol_weighting_runs():
    a = make_series([100.0 * (1.005 ** i) for i in range(120)])
    b = make_series([100.0 * (1.004 ** i) for i in range(120)])

    class _PickBoth:
        required_history = 5

        def screen_universe(self, candle_map, markets=None):
            return [
                Candidate(symbol="A", market="KRX", price=1.0, score=1.0),
                Candidate(symbol="B", market="KRX", price=1.0, score=0.9),
            ]

    result = walk_forward_backtest(
        {"A": a, "B": b}, _PickBoth(), {"A": "KRX", "B": "KRX"},
        weighting="inverse_vol", rebalance_days=21, top_n=2,
    )
    assert result.metrics.total_return > 0
