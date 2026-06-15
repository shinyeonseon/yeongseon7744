"""Per-strategy pass/fail tests with deterministic synthetic candles."""

from __future__ import annotations

import pytest

from helpers import make_series
from tossai.config import Settings
from tossai.screening.strategies.canslim import CanSlimTechnicalStrategy
from tossai.screening.strategies.dual_momentum import DualMomentumStrategy
from tossai.screening.strategies.mean_reversion import MeanReversionStrategy
from tossai.screening.strategies.technical_swing import TechnicalSwingStrategy
from tossai.screening.strategies.trend_breakout import TrendBreakoutStrategy


@pytest.fixture
def s() -> Settings:
    return Settings(rsi_period=5, volume_ratio_min=1.0, claude_max_candidates=5, _env_file=None)


def test_dual_momentum_pass_and_fail(s):
    up = make_series([100 * (1 + 0.0015 * i) for i in range(260)])
    res = DualMomentumStrategy(s).evaluate("X", up, "KRX")
    assert res.passed is True and res.bucket == "long"
    assert res.signals["lookback_return"] > 0

    down = make_series([200 * (1 - 0.0015 * i) for i in range(260)])
    assert DualMomentumStrategy(s).evaluate("X", down, "KRX").passed is False


def test_canslim_pass_and_fail(s):
    closes = [100 + i * 0.5 for i in range(260)]
    vols = [1000.0] * 259 + [2000.0]
    res = CanSlimTechnicalStrategy(s).evaluate("X", make_series(closes, vols), "KRX")
    assert res.passed is True and res.bucket == "swing"
    assert "technical subset" in str(res.signals["note"])

    # Far below its 52-week high → fails.
    closes2 = [100 + i * 0.5 for i in range(200)] + [200 - i * 1.0 for i in range(60)]
    assert CanSlimTechnicalStrategy(s).evaluate("X", make_series(closes2), "KRX").passed is False


def test_canslim_vix_gate(s):
    closes = [100 + i * 0.5 for i in range(260)]
    vols = [1000.0] * 259 + [2000.0]
    strat = CanSlimTechnicalStrategy(s)
    strat.set_vix(40.0)  # stressed tape > canslim_max_vix (25)
    assert strat.evaluate("X", make_series(closes, vols), "KRX").passed is False
    strat.set_vix(None)  # no data → not suppressed
    assert strat.evaluate("X", make_series(closes, vols), "KRX").passed is True


def test_mean_reversion_pass_and_fail(s):
    closes = [100 + i * 1.0 for i in range(250)] + [349.0 - 6.0 * k for k in range(1, 9)]
    res = MeanReversionStrategy(s).evaluate("X", make_series(closes), "KRX")
    assert res.passed is True and res.signals["rsi"] < 35

    plain = make_series([100 + i * 1.0 for i in range(260)])
    assert MeanReversionStrategy(s).evaluate("X", plain, "KRX").passed is False


def test_trend_breakout_pass_and_fail(s):
    closes = [100.0] * 259 + [112.0]
    vols = [1000.0] * 259 + [2000.0]
    res = TrendBreakoutStrategy(s).evaluate("X", make_series(closes, vols), "KRX")
    assert res.passed is True and res.bucket == "long"
    assert res.signals["breakout_pct"] > 0

    flat = make_series([100.0] * 260)
    assert TrendBreakoutStrategy(s).evaluate("X", flat, "KRX").passed is False


def test_too_short_history(s):
    short = make_series([100.0] * 30)
    assert DualMomentumStrategy(s).evaluate("X", short, "KRX").passed is False


def test_technical_swing_matches_screener(s):
    # TechnicalSwing must reproduce the underlying Screener verdict.
    from helpers import make_uptrend
    from tossai.screening.screener import Screener
    candles = make_uptrend(n=40)
    swing = TechnicalSwingStrategy(s).evaluate("005930", candles, "KRX")
    base = Screener(s).run("005930", candles, "KRX")
    assert swing.passed == base.passed
    assert swing.score == base.score
    assert swing.bucket == "swing"
