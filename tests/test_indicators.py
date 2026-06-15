"""Deterministic golden-value tests for indicators — the math backbone."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tossai.screening import indicators as ind


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    result = ind.sma(s, 3)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[4] == pytest.approx(4.0)


def test_ema_converges():
    s = pd.Series([10.0] * 10)
    result = ind.ema(s, 3)
    assert result.iloc[-1] == pytest.approx(10.0)


def test_rsi_all_gains_is_100():
    s = pd.Series([float(i) for i in range(1, 20)])
    result = ind.rsi(s, 5)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_all_losses_is_zero():
    s = pd.Series([float(i) for i in range(20, 1, -1)])
    result = ind.rsi(s, 5)
    assert result.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_rsi_known_value():
    # Classic Wilder example-style: oscillating series stays mid-range.
    prices = [44, 44.25, 44.5, 43.75, 44.5, 45, 45.25, 45.5, 45.25, 46, 47, 46.75]
    s = pd.Series(prices, dtype=float)
    result = ind.rsi(s, 5)
    assert 50.0 < result.iloc[-1] <= 100.0  # net upward → bullish RSI


def test_rsi_warmup_is_nan():
    s = pd.Series([float(i) for i in range(10)])
    result = ind.rsi(s, 5)
    assert result.iloc[:4].isna().all()


def test_volume_ratio():
    v = pd.Series([100.0] * 9 + [300.0])
    result = ind.volume_ratio(v, 5)
    # last value vs avg of last 5 (which includes the spike)
    assert result.iloc[-1] == pytest.approx(300.0 / ((100 * 4 + 300) / 5))


def test_momentum():
    s = pd.Series([100.0, 100, 100, 100, 100, 110])
    result = ind.momentum(s, 5)
    assert result.iloc[-1] == pytest.approx(0.10)


def test_atr_positive():
    df = pd.DataFrame(
        {
            "high": [10, 11, 12, 11, 13, 14],
            "low": [9, 10, 11, 10, 12, 13],
            "close": [9.5, 10.5, 11.5, 10.5, 12.5, 13.5],
        },
        dtype=float,
    )
    result = ind.atr(df, 3)
    assert result.iloc[-1] > 0


def test_golden_cross_detected():
    fast = pd.Series([1.0, 2.0, 3.0])  # crossing up
    slow = pd.Series([2.5, 2.5, 2.5])
    assert ind.golden_cross(fast, slow) is True


def test_golden_cross_not_when_already_above():
    fast = pd.Series([5.0, 6.0])
    slow = pd.Series([1.0, 1.0])
    assert ind.golden_cross(fast, slow) is False
