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


def test_trading_costs_reduce_return():
    up = make_series([100.0 * (1.01 ** i) for i in range(120)])
    down = make_series([100.0 * (0.99 ** i) for i in range(120)])
    candle_map = {"UP": up, "DOWN": down}

    free = walk_forward_backtest(candle_map, _PickUp(), {"UP": "KRX", "DOWN": "KRX"},
                                 rebalance_days=21, top_n=1, cost_bps=0.0)
    costly = walk_forward_backtest(candle_map, _PickUp(), {"UP": "KRX", "DOWN": "KRX"},
                                   rebalance_days=21, top_n=1, cost_bps=50.0)
    # costs can only drag the strategy's realized return down
    assert costly.metrics.total_return < free.metrics.total_return
    assert costly.cost_bps == 50.0


def test_trend_filter_cuts_drawdown_on_trend_break():
    # Long steady rise (well above MA200), then a trend break + crash.
    rise = [100.0 + i * 0.8 for i in range(230)]          # 100 → ~283, MA200 trails below
    crash = [rise[-1] * (0.97 ** (i + 1)) for i in range(50)]  # sharp decline below trend
    series = make_series(rise + crash)
    candle_map = {"UP": series}

    filtered = walk_forward_backtest(
        candle_map, _PickUp(), {"UP": "KRX"},
        rebalance_days=21, top_n=1, trend_filter=True, trend_ma=200,
    )
    held = walk_forward_backtest(
        candle_map, _PickUp(), {"UP": "KRX"},
        rebalance_days=21, top_n=1, trend_filter=False,
    )
    # Moving to cash on the trend break should cushion the crash:
    assert filtered.metrics.max_drawdown > held.metrics.max_drawdown  # less negative
    assert filtered.metrics.total_return > held.metrics.total_return
    # Some bars were de-risked to cash, so average exposure is below full.
    assert filtered.avg_exposure < 1.0
    assert "exposure" in filtered.summary()


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
