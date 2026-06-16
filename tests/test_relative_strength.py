"""Relative strength vs the market (cross-sectional)."""

from __future__ import annotations

from helpers import make_series
from tossai.screening.strategies.relative_strength import RelativeStrengthStrategy


def _ramp(total_return: float, n: int = 140) -> list:
    """A smooth price series ending `total_return` above its start."""
    step = (1.0 + total_return) ** (1.0 / (n - 1))
    return make_series([100.0 * step**i for i in range(n)])


def test_only_market_beaters_pass(settings):
    # US universe: strong +50%, mid +10%, weak −10% → avg ≈ +16.7%.
    candle_map = {"STRONG": _ramp(0.50), "MID": _ramp(0.10), "WEAK": _ramp(-0.10)}
    markets = {s: "US" for s in candle_map}
    res = RelativeStrengthStrategy(settings).evaluate_all(candle_map, markets)
    passed = {r.symbol: r for r in res}
    assert "STRONG" in passed                      # beats the market
    assert "MID" not in passed and "WEAK" not in passed
    assert passed["STRONG"].signals["rs_vs_market"] > 0
    assert passed["STRONG"].bucket == "long"


def test_benchmark_is_per_market(settings):
    # A weak US name shouldn't be judged against a (different) KRX cohort.
    candle_map = {
        "US_HI": _ramp(0.40), "US_LO": _ramp(0.05),    # US avg ≈ +22%
        "KR_HI": _ramp(0.08), "KR_LO": _ramp(-0.20),   # KRX avg ≈ −6%
    }
    markets = {"US_HI": "US", "US_LO": "US", "KR_HI": "KRX", "KR_LO": "KRX"}
    passed = {r.symbol for r in RelativeStrengthStrategy(settings).evaluate_all(candle_map, markets)}
    # KR_HI (+8%) beats its KRX cohort (−6%) even though it lags the US cohort.
    assert "KR_HI" in passed and "US_HI" in passed
    assert "KR_LO" not in passed and "US_LO" not in passed


def test_too_short_history_skipped(settings):
    short = {"X": make_series([100.0, 101.0, 102.0])}
    assert RelativeStrengthStrategy(settings).evaluate_all(short, {"X": "US"}) == []


def test_registered_and_screen_universe(settings):
    from tossai.screening.strategies.ensemble import REGISTRY, build_strategy

    assert "relative_strength" in REGISTRY
    settings.strategy = "relative_strength"
    strat = build_strategy(settings)
    cands = strat.screen_universe(
        {"A": _ramp(0.50), "B": _ramp(-0.10)}, {"A": "US", "B": "US"})
    assert [c.symbol for c in cands] == ["A"]
