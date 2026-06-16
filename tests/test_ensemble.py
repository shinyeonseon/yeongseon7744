"""Ensemble merge/dedupe/cap + factory tests."""

from __future__ import annotations

import pytest

from helpers import make_uptrend
from tossai.config import Settings
from tossai.screening.regime import RegimeProvider
from tossai.screening.strategies.base import BaseStrategy, StrategyResult
from tossai.screening.strategies.ensemble import StrategyEnsemble, build_strategy
from tossai.screening.strategies.technical_swing import TechnicalSwingStrategy


class _StubStrategy(BaseStrategy):
    """Flags given symbols with a fixed score/bucket — for merge tests."""

    def __init__(self, settings, name, bucket, scores: dict[str, float]):
        super().__init__(settings)
        self.name = name
        self.bucket = bucket
        self._scores = scores
        self.required_history = 1

    def evaluate(self, symbol, candles, market):
        if symbol not in self._scores:
            return StrategyResult(symbol, 0.0, {}, None, None, self.bucket, self.name, passed=False)
        return StrategyResult(
            symbol, self._scores[symbol], {"k": 1.0}, 100.0, None,
            self.bucket, self.name, passed=True,
        )


@pytest.fixture
def s():
    return Settings(claude_max_candidates=5, screen_min_score=0.0, _env_file=None)


def _no_vix(settings):
    return None


def test_merge_dedupe_and_flagged_by(s):
    a = _StubStrategy(s, "alpha", "long", {"AAA": 0.4, "BBB": 0.9})
    b = _StubStrategy(s, "beta", "swing", {"AAA": 0.7})
    ens = StrategyEnsemble([a, b], s, RegimeProvider(s, vix_getter=_no_vix))
    candle_map = {"AAA": [], "BBB": []}
    cands = ens.screen_universe(candle_map, {"AAA": "KRX", "BBB": "KRX"})

    by_symbol = {c.symbol: c for c in cands}
    # AAA flagged by both, keeps the higher score (0.7 from beta)
    assert sorted(by_symbol["AAA"].flagged_by) == ["alpha", "beta"]
    assert by_symbol["AAA"].score == pytest.approx(0.7)
    # namespaced signals from both strategies preserved
    assert "alpha.k" in by_symbol["AAA"].signals and "beta.k" in by_symbol["AAA"].signals
    # BBB only from alpha
    assert by_symbol["BBB"].flagged_by == ["alpha"]


def test_cap_to_max_candidates():
    s = Settings(claude_max_candidates=2, _env_file=None)
    scores = {f"S{i}": 0.1 * (i + 1) for i in range(5)}
    a = _StubStrategy(s, "alpha", "long", scores)
    ens = StrategyEnsemble([a], s, RegimeProvider(s, vix_getter=lambda x: None))
    cm = {k: [] for k in scores}
    cands = ens.screen_universe(cm, {k: "KRX" for k in scores})
    assert len(cands) == 2
    assert cands[0].score >= cands[1].score  # sorted desc


def test_consensus_breaks_score_ties(s):
    # Two names tie at 1.0; CONSENSUS is flagged by two strategies, SOLO by one.
    a = _StubStrategy(s, "alpha", "long", {"CONSENSUS": 1.0, "SOLO": 1.0})
    b = _StubStrategy(s, "beta", "long", {"CONSENSUS": 1.0})
    ens = StrategyEnsemble([a, b], s, RegimeProvider(s, vix_getter=_no_vix))
    cm = {"CONSENSUS": [], "SOLO": []}
    cands = ens.screen_universe(cm, {k: "KRX" for k in cm})
    assert cands[0].symbol == "CONSENSUS"  # broader agreement wins the tie
    assert len(cands[0].flagged_by) == 2 and len(cands[1].flagged_by) == 1


def test_riskoff_downweights_long_bucket(s):
    a = _StubStrategy(s, "alpha", "long", {"AAA": 1.0})
    # VIX well above riskoff threshold (28) → long bucket halved (weight 0.5)
    ens = StrategyEnsemble([a], s, RegimeProvider(s, vix_getter=lambda x: 40.0))
    cands = ens.screen_universe({"AAA": []}, {"AAA": "KRX"})
    assert cands[0].score == pytest.approx(0.5)


def test_build_strategy_single_returns_plain(s):
    s.strategy = "technical_swing"
    strat = build_strategy(s)
    assert isinstance(strat, TechnicalSwingStrategy)


def test_build_strategy_multi_returns_ensemble(s):
    s.strategy = "technical_swing,dual_momentum"
    strat = build_strategy(s)
    assert isinstance(strat, StrategyEnsemble)
    # dual momentum (lookback+skip+2) drives the requirement above technical_swing
    assert strat.required_history == s.dm_lookback_days + s.dm_skip_days + 2


def test_build_strategy_unknown_skipped(s):
    s.strategy = "technical_swing,bogus"
    strat = build_strategy(s)  # bogus skipped, leaves one → plain
    assert isinstance(strat, TechnicalSwingStrategy)


def test_build_strategy_empty_falls_back(s):
    s.strategy = "bogus,nope"
    strat = build_strategy(s)
    assert isinstance(strat, TechnicalSwingStrategy)


def test_ensemble_end_to_end_on_real_candles(s):
    # technical_swing flags an uptrend even when longer strategies lack history.
    s.strategy = "technical_swing,dual_momentum"
    s.sma_fast, s.sma_slow, s.rsi_period, s.volume_ratio_min = 5, 10, 5, 1.0
    strat = build_strategy(s, RegimeProvider(s, vix_getter=lambda x: None))
    cands = strat.screen_universe({"005930": make_uptrend(n=40)}, {"005930": "KRX"})
    assert len(cands) == 1
    assert "technical_swing" in cands[0].flagged_by
