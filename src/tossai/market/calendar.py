"""Market-hours and holiday awareness for KRX and US exchanges.

Times are computed in each market's own timezone (KST / US-Eastern), never the
server's local time. Holidays are a static list — a known yearly-maintenance
item; update the sets below each year (or swap in `pandas-market-calendars`).
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
US_EASTERN = ZoneInfo("America/New_York")

# Regular session hours (local market time).
_HOURS = {
    "KRX": (time(9, 0), time(15, 30), KST),
    "US": (time(9, 30), time(16, 0), US_EASTERN),
}

# Static holiday lists (YYYY-MM-DD). TODO: refresh annually.
_HOLIDAYS = {
    "KRX": {
        "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-01",
        "2026-03-02", "2026-05-05", "2026-05-24", "2026-05-25", "2026-06-06",
        "2026-08-15", "2026-08-17", "2026-09-24", "2026-09-25", "2026-09-26",
        "2026-10-03", "2026-10-05", "2026-10-09", "2026-12-25", "2026-12-31",
    },
    "US": {
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
        "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    },
}


def now_in_market(market: str, now: datetime | None = None) -> datetime:
    tz = _HOURS[market][2]
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def is_holiday(market: str, local_dt: datetime) -> bool:
    return local_dt.strftime("%Y-%m-%d") in _HOLIDAYS.get(market, set())


def is_market_open(market: str, now: datetime | None = None) -> bool:
    """True if ``market`` is in its regular trading session right now."""
    if market not in _HOURS:
        raise ValueError(f"unknown market: {market}")
    local = now_in_market(market, now)
    if local.weekday() >= 5:  # Sat/Sun
        return False
    if is_holiday(market, local):
        return False
    open_t, close_t, _ = _HOURS[market]
    return open_t <= local.time() <= close_t


def markets_for(market_setting: str) -> list[str]:
    """Expand the MARKET setting into concrete market labels."""
    m = market_setting.upper()
    if m == "BOTH":
        return ["KRX", "US"]
    return [m]


def any_market_open(market_setting: str, now: datetime | None = None) -> bool:
    return any(is_market_open(m, now) for m in markets_for(market_setting))
