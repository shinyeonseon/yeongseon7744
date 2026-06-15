"""Test helpers shared across test modules (importable via pythonpath=tests)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tossai.models import Candle


def make_candles(
    closes: list[float],
    volumes: list[float] | None = None,
    start: datetime | None = None,
) -> list[Candle]:
    """Build daily candles from a close-price series. High/low straddle close."""
    start = start or datetime(2026, 1, 1, tzinfo=UTC)
    volumes = volumes or [1000.0] * len(closes)
    candles: list[Candle] = []
    for i, (c, v) in enumerate(zip(closes, volumes, strict=False)):
        candles.append(
            Candle(
                ts=start + timedelta(days=i),
                open=c,
                high=c * 1.01,
                low=c * 0.99,
                close=c,
                volume=v,
            )
        )
    return candles


def make_series(closes: list[float], volumes: list[float] | None = None) -> list[Candle]:
    """Alias for make_candles, for readability in long-history strategy tests."""
    return make_candles(closes, volumes)


def make_uptrend(
    n: int = 40, up: float = 2.5, down: float = 3.0, vol_spike: float = 2.5
) -> list[Candle]:
    """A realistic uptrend: three up-steps then a pullback (sawtooth).

    Unlike a monotonic line (which yields RSI=100 and trips the overbought
    gate), this keeps RSI moderate while staying in an uptrend — so it passes
    screening. The final bar carries a volume spike. Larger ``up`` => stronger
    momentum => higher screen score.
    """
    closes = [100.0]
    for i in range(n - 1):
        step = -down if (i % 4 == 2) else up
        closes.append(closes[-1] + step)
    volumes = [1000.0] * (n - 1) + [1000.0 * vol_spike]
    return make_candles(closes, volumes)
