"""Fundamental strategies + provider routing/caching (stubbed, no network)."""

from __future__ import annotations

from helpers import make_series
from tossai.fundamentals.models import Fundamentals
from tossai.fundamentals.provider import CachingProvider, MarketRoutingProvider
from tossai.screening.strategies.buffett_quality import BuffettQualityStrategy
from tossai.screening.strategies.graham import GrahamValueStrategy
from tossai.screening.strategies.magic_formula import MagicFormulaStrategy
from tossai.screening.strategies.piotroski import PiotroskiLiteStrategy


class StubProvider:
    def __init__(self, data: dict[str, Fundamentals | None]):
        self.data = data
        self.calls = 0

    def get(self, symbol: str, market: str) -> Fundamentals | None:
        self.calls += 1
        return self.data.get(symbol)


def _f(symbol="005930", market="KRX", **kw) -> Fundamentals:
    return Fundamentals(symbol=symbol, market=market, **kw)


def _candles():
    return make_series([100.0] * 5)


# ---- provider plumbing ----

def test_market_routing():
    krx = StubProvider({"005930": _f(per=10)})
    us = StubProvider({"AAPL": _f(symbol="AAPL", market="US", per=20)})
    router = MarketRoutingProvider(krx=krx, us=us)
    assert router.get("005930", "KRX").per == 10
    assert router.get("AAPL", "US").per == 20
    assert router.get("X", "FX") is None


def test_caching_provider_calls_once():
    inner = StubProvider({"005930": _f(per=10)})
    cached = CachingProvider(inner)
    cached.get("005930", "KRX")
    cached.get("005930", "KRX")
    assert inner.calls == 1


def test_caching_swallows_errors():
    class Boom:
        def get(self, s, m):
            raise RuntimeError("network down")

    assert CachingProvider(Boom()).get("X", "KRX") is None


# ---- Graham ----

def test_graham_passes_cheap_quality(settings):
    strat = GrahamValueStrategy(settings)
    strat.set_fundamentals_provider(StubProvider({"005930": _f(per=10, pbr=1.0, eps=5000, bps=50000)}))
    res = strat.evaluate("005930", make_series([70000.0] * 3), "KRX")
    assert res.passed is True and res.bucket == "value"


def test_graham_fails_expensive(settings):
    strat = GrahamValueStrategy(settings)
    strat.set_fundamentals_provider(StubProvider({"005930": _f(per=30, pbr=4.0, eps=100, bps=100)}))
    res = strat.evaluate("005930", _candles(), "KRX")
    assert res.passed is False


def test_graham_skips_without_provider(settings):
    res = GrahamValueStrategy(settings).evaluate("005930", _candles(), "KRX")
    assert res.passed is False
    assert "provider" in res.reason


# ---- Buffett ----

def test_buffett_passes_high_roe(settings):
    strat = BuffettQualityStrategy(settings)
    strat.set_fundamentals_provider(StubProvider({"AAPL": _f(symbol="AAPL", market="US", roe=0.25, per=18)}))
    res = strat.evaluate("AAPL", _candles(), "US")
    assert res.passed is True and res.score > 0


def test_buffett_fails_low_roe(settings):
    strat = BuffettQualityStrategy(settings)
    strat.set_fundamentals_provider(StubProvider({"AAPL": _f(symbol="AAPL", market="US", roe=0.05, per=18)}))
    assert strat.evaluate("AAPL", _candles(), "US").passed is False


# ---- Piotroski ----

def test_piotroski_lite_passes(settings):
    strat = PiotroskiLiteStrategy(settings)
    strat.set_fundamentals_provider(StubProvider({"X": _f(symbol="X", per=12, eps=500, roe=0.18)}))
    res = strat.evaluate("X", _candles(), "KRX")
    assert res.passed is True
    assert res.signals["scaled_0_9"] >= settings.piotroski_min_score


# ---- Magic Formula (cross-sectional) ----

def test_magic_formula_ranks_cross_section(settings):
    strat = MagicFormulaStrategy(settings)
    strat.set_fundamentals_provider(StubProvider({
        "CHEAP_GOOD": _f(symbol="CHEAP_GOOD", per=5, roe=0.30),    # high EY + high ROC
        "EXP_BAD": _f(symbol="EXP_BAD", per=40, roe=0.05),         # low EY + low ROC
        "MIXED": _f(symbol="MIXED", per=15, roe=0.15),
    }))
    candle_map = {"CHEAP_GOOD": _candles(), "EXP_BAD": _candles(), "MIXED": _candles()}
    results = strat.evaluate_all(candle_map, {s: "KRX" for s in candle_map})
    by_symbol = {r.symbol: r.score for r in results}
    assert by_symbol["CHEAP_GOOD"] > by_symbol["MIXED"] > by_symbol["EXP_BAD"]


def test_magic_formula_empty_without_provider(settings):
    assert MagicFormulaStrategy(settings).evaluate_all({"X": _candles()}, {"X": "KRX"}) == []
