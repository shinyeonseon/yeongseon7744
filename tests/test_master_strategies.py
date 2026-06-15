"""Price-based investment-master strategies (Meb Faber, momentum quality, low-vol)."""

from __future__ import annotations

from helpers import make_series
from tossai.screening.strategies.low_volatility import LowVolatilityStrategy
from tossai.screening.strategies.meb_faber import MebFaberTrendStrategy
from tossai.screening.strategies.momentum_quality import MomentumQualityStrategy


def smooth_uptrend(n: int = 290, drift: float = 1.0006, wobble: float = 0.003) -> list:
    """A long, low-noise uptrend: steady drift with a tiny ± wobble (vol > 0)."""
    closes = []
    for i in range(n):
        base = 100.0 * (drift ** i)
        closes.append(base * (1.0 + wobble if i % 2 == 0 else 1.0 - wobble))
    return make_series(closes)


def downtrend(n: int = 290) -> list:
    closes = [100.0 * (0.997 ** i) for i in range(n)]
    return make_series(closes)


def test_meb_faber_passes_in_uptrend(settings):
    res = MebFaberTrendStrategy(settings).evaluate("005930", smooth_uptrend(), "KRX")
    assert res.passed is True
    assert res.bucket == "long"
    assert res.signals["above_sma"] is True


def test_meb_faber_fails_in_downtrend(settings):
    res = MebFaberTrendStrategy(settings).evaluate("005930", downtrend(), "KRX")
    assert res.passed is False


def test_momentum_quality_passes(settings):
    res = MomentumQualityStrategy(settings).evaluate("AAPL", smooth_uptrend(), "US")
    assert res.passed is True
    assert res.signals["momentum_12_1"] > 0
    assert 0.0 <= res.signals["smoothness"] <= 1.0


def test_momentum_quality_fails_downtrend(settings):
    res = MomentumQualityStrategy(settings).evaluate("AAPL", downtrend(), "US")
    assert res.passed is False


def test_low_volatility_passes_smooth_uptrend(settings):
    res = LowVolatilityStrategy(settings).evaluate("MSFT", smooth_uptrend(), "US")
    assert res.passed is True
    assert res.signals["daily_vol"] > 0
    assert res.score > 0


def test_low_volatility_too_short(settings):
    res = LowVolatilityStrategy(settings).evaluate("X", make_series([100.0] * 50), "US")
    assert res.passed is False
