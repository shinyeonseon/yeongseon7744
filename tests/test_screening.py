"""Screener funnel + ranking tests."""

from __future__ import annotations

from helpers import make_candles, make_uptrend
from tossai.screening.screener import Screener


def test_uptrend_passes(settings, uptrend_candles):
    res = Screener(settings).run("005930", uptrend_candles)
    assert res.passed is True
    assert res.score > 0
    assert res.signals["uptrend"] is True


def test_flat_fails(settings, flat_candles):
    res = Screener(settings).run("000660", flat_candles)
    assert res.passed is False
    assert "momentum" in res.reason or "volume" in res.reason


def test_insufficient_history(settings):
    res = Screener(settings).run("AAA", make_candles([100.0, 101.0, 102.0]))
    assert res.passed is False
    assert "insufficient" in res.reason


def test_screen_universe_ranks_and_caps(settings):
    # Build 5 passing symbols with different momentum so ranking is meaningful.
    candle_map = {}
    markets = {}
    for i, up in enumerate([1.5, 2.0, 2.5, 3.0, 3.5]):
        sym = f"S{i}"
        candle_map[sym] = make_uptrend(n=40, up=up)
        markets[sym] = "KRX"

    candidates = Screener(settings).screen_universe(candle_map, markets)
    # capped at claude_max_candidates (3 in fixture)
    assert len(candidates) == 3
    # ranked by score descending
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_bad_symbol_does_not_crash_universe(settings, uptrend_candles):
    candle_map = {"GOOD": uptrend_candles, "BAD": []}
    candidates = Screener(settings).screen_universe(candle_map, {"GOOD": "KRX", "BAD": "KRX"})
    syms = {c.symbol for c in candidates}
    assert "GOOD" in syms
    assert "BAD" not in syms
