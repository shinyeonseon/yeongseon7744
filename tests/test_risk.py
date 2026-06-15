"""Risk evaluators, dedupe, and VIX parsing tests."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from helpers import make_candles
from tossai.risk import sentiment
from tossai.risk.evaluators import evaluate_blackswan, evaluate_gap_down
from tossai.risk.models import RiskKind
from tossai.risk.state import AlertDeduper


def test_blackswan_triggers_above_threshold():
    alert = evaluate_blackswan(35.0, 30.0)
    assert alert is not None and alert.kind == RiskKind.BLACKSWAN
    assert alert.value == 35.0


def test_blackswan_silent_below_and_none():
    assert evaluate_blackswan(20.0, 30.0) is None
    assert evaluate_blackswan(None, 30.0) is None


def test_gap_down_triggers():
    # prior close 100, latest open 92 → -8%
    candles = make_candles([100.0, 92.0])
    candles[-1].open = 92.0
    alert = evaluate_gap_down("AAPL", candles, 5.0)
    assert alert is not None and alert.symbol == "AAPL"
    assert alert.value < -5.0


def test_gap_down_silent_on_small_move():
    candles = make_candles([100.0, 99.0])
    candles[-1].open = 99.0
    assert evaluate_gap_down("AAPL", candles, 5.0) is None


def test_gap_down_insufficient_data():
    assert evaluate_gap_down("AAPL", make_candles([100.0]), 5.0) is None


def test_deduper_suppresses_repeat(tmp_path):
    d = AlertDeduper(str(tmp_path))
    alert = evaluate_blackswan(40.0, 30.0)
    now = datetime(2026, 6, 15, tzinfo=UTC)
    assert d.should_send(alert, now=now) is True
    assert d.should_send(alert, now=now) is False  # same day → suppressed


def test_deduper_resets_next_day(tmp_path):
    d = AlertDeduper(str(tmp_path))
    alert = evaluate_blackswan(40.0, 30.0)
    day1 = datetime(2026, 6, 15, tzinfo=UTC)
    day2 = datetime(2026, 6, 16, tzinfo=UTC)
    assert d.should_send(alert, now=day1) is True
    assert d.should_send(alert, now=day2) is True  # new day → allowed


def test_deduper_persists(tmp_path):
    alert = evaluate_blackswan(40.0, 30.0)
    now = datetime(2026, 6, 15, tzinfo=UTC)
    d1 = AlertDeduper(str(tmp_path))
    assert d1.should_send(alert, now=now) is True
    d2 = AlertDeduper(str(tmp_path))  # reload from disk
    assert d2.should_send(alert, now=now) is False


def test_get_vix_parses_csv(settings):
    csv_text = "Symbol,Date,Time,Open,High,Low,Close,Volume\n^VIX,2026-06-15,21:00:00,18.0,19.0,17.5,18.42,0\n"

    def handler(request):
        return httpx.Response(200, text=csv_text)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert sentiment.get_vix(settings, http=http) == 18.42


def test_get_vix_none_on_error(settings):
    def handler(request):
        return httpx.Response(500, text="error")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert sentiment.get_vix(settings, http=http) is None
