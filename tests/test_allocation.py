"""Risk-parity inverse-volatility weighting tests."""

from __future__ import annotations

from helpers import make_series
from tossai.screening.allocation import inverse_vol_weights


def _vol_series(daily_move: float, n: int = 80) -> list:
    """Series alternating ± daily_move → controlled volatility."""
    closes = []
    price = 100.0
    for i in range(n):
        price *= (1 + daily_move) if i % 2 == 0 else (1 - daily_move)
        closes.append(price)
    return make_series(closes)


def test_weights_sum_to_one_and_favor_low_vol():
    candle_map = {
        "LOWVOL": _vol_series(0.005),   # calm
        "HIGHVOL": _vol_series(0.05),   # choppy
    }
    weights = inverse_vol_weights(candle_map, lookback=60)
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert weights["LOWVOL"] > weights["HIGHVOL"]


def test_empty_when_insufficient_history():
    weights = inverse_vol_weights({"X": make_series([100.0, 101.0])}, lookback=60)
    assert weights == {}
