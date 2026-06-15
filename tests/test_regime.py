"""Market-regime classification tests."""

from __future__ import annotations

from tossai.config import Settings
from tossai.screening.regime import MarketRegime, RegimeProvider, classify_regime


def test_vix_bands():
    kw = {"neutral_vix": 20.0, "riskoff_vix": 28.0}
    assert classify_regime(15.0, **kw) == MarketRegime.RISK_ON
    assert classify_regime(22.0, **kw) == MarketRegime.NEUTRAL
    assert classify_regime(30.0, **kw) == MarketRegime.RISK_OFF


def test_vix_none_is_neutral():
    assert classify_regime(None, neutral_vix=20.0, riskoff_vix=28.0) == MarketRegime.NEUTRAL


def test_provider_caches_vix():
    calls = {"n": 0}

    def getter(_s):
        calls["n"] += 1
        return 18.0

    s = Settings(_env_file=None)
    p = RegimeProvider(s, vix_getter=getter)
    assert p.get_vix() == 18.0
    assert p.get_regime() == MarketRegime.RISK_ON
    assert calls["n"] == 1  # fetched once, cached
