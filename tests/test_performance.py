"""Recommendation performance tracking: ledger + forward-return scoring."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from helpers import make_series
from tossai.models import Candle
from tossai.performance import ledger, tracker
from tossai.performance.models import RecoRecord


def _candles_from(prices: list[float], start: datetime) -> list[Candle]:
    return [Candle(ts=start + timedelta(days=i), open=p, high=p, low=p, close=p, volume=1.0)
            for i, p in enumerate(prices)]


# ---- ledger ----

def test_append_is_idempotent(tmp_path):
    recs = [RecoRecord(date="2026-06-01", symbol="AAPL", market="US", action="BUY",
                       confidence=0.8, price=100.0)]
    assert ledger.append_records(recs, str(tmp_path)) == 1
    assert ledger.append_records(recs, str(tmp_path)) == 0   # duplicate skipped
    assert [r.symbol for r in ledger.load_ledger(str(tmp_path))] == ["AAPL"]


def test_backfill_from_reports(tmp_path):
    report = {
        "generated_at": "2026-06-01T09:00:00+00:00",
        "results": [
            {"candidate": {"symbol": "AAPL", "market": "US", "price": 100.0},
             "recommendation": {"action": "BUY", "confidence": 0.8}},
            {"candidate": {"symbol": "MSFT", "market": "US", "price": 200.0},
             "recommendation": {"action": "HOLD", "confidence": 0.5}},
        ],
    }
    (tmp_path / "2026-06-01_090000.json").write_text(json.dumps(report))
    (tmp_path / "portfolio_2026-06-01.json").write_text(json.dumps({"x": 1}))  # ignored
    n = ledger.backfill_from_reports(str(tmp_path))
    assert n == 2
    syms = {r.symbol for r in ledger.load_ledger(str(tmp_path))}
    assert syms == {"AAPL", "MSFT"}


# ---- scoring ----

def test_buy_scored_as_win_when_price_rises():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rising = _candles_from([100.0 + i for i in range(40)], start)  # monotonic up
    rec = RecoRecord(date="2026-01-01", symbol="UP", market="US", action="BUY",
                     confidence=0.8, price=100.0)
    s = tracker.evaluate([rec], {"UP": rising}, horizons=(5, 21), primary_horizon=21)
    assert s.scored == 1 and s.pending == 0
    h21 = next(h for h in s.horizons if h.horizon == 21)
    assert h21.n == 1 and h21.win_rate == 1.0 and h21.avg_return > 0


def test_sell_is_correct_when_price_falls():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    falling = _candles_from([100.0 - i for i in range(40)], start)
    rec = RecoRecord(date="2026-01-01", symbol="DN", market="US", action="SELL",
                     confidence=0.9, price=100.0)
    s = tracker.evaluate([rec], {"DN": falling}, horizons=(21,), primary_horizon=21)
    # SELL + price fell => direction-adjusted return positive => a win
    assert s.by_action["SELL"].win_rate == 1.0
    assert s.by_action["SELL"].avg_return > 0


def test_recent_reco_is_pending_not_scored():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    short = _candles_from([100.0, 101.0, 102.0], start)  # not enough for 21d
    rec = RecoRecord(date="2026-01-01", symbol="X", market="US", action="BUY", confidence=0.7)
    s = tracker.evaluate([rec], {"X": short}, horizons=(21,), primary_horizon=21)
    assert s.scored == 0 and s.pending == 1


def test_hold_and_low_confidence_excluded():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    series = _candles_from([100.0 + i for i in range(40)], start)
    recs = [
        RecoRecord(date="2026-01-01", symbol="A", market="US", action="HOLD", confidence=0.9),
        RecoRecord(date="2026-01-01", symbol="A", market="US", action="BUY", confidence=0.4),
    ]
    s = tracker.evaluate(recs, {"A": series}, horizons=(21,), primary_horizon=21,
                         min_confidence=0.6)
    assert s.directional == 0  # HOLD excluded by action, BUY excluded by confidence


def test_confidence_buckets_split():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    up = _candles_from([100.0 + i for i in range(40)], start)
    down = _candles_from([100.0 - i for i in range(40)], start)
    recs = [
        RecoRecord(date="2026-01-01", symbol="UP", market="US", action="BUY", confidence=0.8),
        RecoRecord(date="2026-01-01", symbol="DN", market="US", action="BUY", confidence=0.5),
    ]
    s = tracker.evaluate(recs, {"UP": up, "DN": down}, horizons=(21,), primary_horizon=21)
    assert s.high_conf_avg is not None and s.low_conf_avg is not None
    assert s.high_conf_avg > s.low_conf_avg  # high-conf BUY rose, low-conf BUY fell


def test_summary_table_renders():
    series = make_series([100.0 + i for i in range(40)])
    rec = RecoRecord(date=series[0].ts.date().isoformat(), symbol="A", market="US",
                     action="BUY", confidence=0.8)
    s = tracker.evaluate([rec], {"A": series}, horizons=(5, 21), primary_horizon=21)
    out = tracker.summary_table(s)
    assert "performance" in out and "WIN%" in out
