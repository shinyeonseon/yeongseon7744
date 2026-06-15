"""Market-hours / holiday / DST tests."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from tossai.market import calendar as cal

KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")


def test_krx_open_midday_weekday():
    # Thu 2026-06-11 11:00 KST
    now = datetime(2026, 6, 11, 11, 0, tzinfo=KST)
    assert cal.is_market_open("KRX", now) is True


def test_krx_closed_after_hours():
    now = datetime(2026, 6, 11, 16, 0, tzinfo=KST)
    assert cal.is_market_open("KRX", now) is False


def test_krx_closed_weekend():
    now = datetime(2026, 6, 13, 11, 0, tzinfo=KST)  # Saturday
    assert cal.is_market_open("KRX", now) is False


def test_krx_closed_holiday():
    now = datetime(2026, 1, 1, 11, 0, tzinfo=KST)  # New Year's Day
    assert cal.is_market_open("KRX", now) is False


def test_us_open_during_dst():
    # Wed 2026-06-10 10:00 ET (EDT) — market open
    now = datetime(2026, 6, 10, 10, 0, tzinfo=ET)
    assert cal.is_market_open("US", now) is True


def test_us_closed_before_open():
    now = datetime(2026, 6, 10, 9, 0, tzinfo=ET)
    assert cal.is_market_open("US", now) is False


def test_markets_for_both():
    assert cal.markets_for("BOTH") == ["KRX", "US"]
    assert cal.markets_for("KRX") == ["KRX"]


def test_any_market_open():
    # KRX midday, both expansion
    now = datetime(2026, 6, 11, 11, 0, tzinfo=KST)
    assert cal.any_market_open("BOTH", now) is True
