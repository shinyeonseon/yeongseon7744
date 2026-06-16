"""Lazy, fail-soft data sources for market context.

Every fetcher imports its heavy/network dependency *inside* the function and
returns an empty/None result on any failure, so an unreachable source never
breaks a run (mirrors the fundamentals providers).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx

from tossai.config import Settings
from tossai.context.models import MacroSnapshot, NewsItem
from tossai.logging_setup import get_logger

log = get_logger(__name__)

# FOMC meeting end-dates are published a year ahead, so a static table gives a
# reliable "next event" without any API key. (2026 schedule.)
_FOMC_2026 = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]


def yf_ticker(symbol: str, market: str) -> str:
    """Map our symbol/market to a yfinance ticker. KRX numeric codes need a
    market suffix; we try KOSPI (.KS) and the caller falls back to KOSDAQ."""
    if (market or "").upper() == "KRX" and symbol.isdigit():
        return f"{symbol}.KS"
    return symbol


def _yf_candidates(symbol: str, market: str) -> list[str]:
    if (market or "").upper() == "KRX" and symbol.isdigit():
        return [f"{symbol}.KS", f"{symbol}.KQ"]
    return [symbol]


def fetch_news(symbol: str, market: str, limit: int = 3) -> list[NewsItem]:
    """Recent headlines via yfinance. Best-effort; returns [] on any problem."""
    try:
        import yfinance as yf
    except ImportError:
        log.debug("yfinance not installed; news unavailable")
        return []
    for ticker in _yf_candidates(symbol, market):
        try:
            raw = yf.Ticker(ticker).news or []
        except Exception as exc:
            log.debug("news fetch failed for %s: %s", ticker, exc)
            continue
        items = _parse_yf_news(raw, limit)
        if items:
            return items
    return []


def _parse_yf_news(raw: list, limit: int) -> list[NewsItem]:
    """yfinance has shipped two shapes: flat {'title','publisher',...} and the
    newer {'content': {'title','provider':{...},'pubDate'}}. Handle both."""
    out: list[NewsItem] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content") if isinstance(entry.get("content"), dict) else entry
        title = content.get("title") or content.get("headline")
        if not title:
            continue
        pub = content.get("publisher")
        if not pub and isinstance(content.get("provider"), dict):
            pub = content["provider"].get("displayName")
        out.append(NewsItem(title=str(title).strip(),
                            publisher=str(pub).strip() if pub else None,
                            published=_news_date(content)))
        if len(out) >= limit:
            break
    return out


def _news_date(content: dict) -> str | None:
    ts = content.get("providerPublishTime")
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts, tz=UTC).date().isoformat()
        except Exception:
            return None
    pub = content.get("pubDate") or content.get("displayTime")
    if isinstance(pub, str) and len(pub) >= 10:
        return pub[:10]
    return None


def fetch_next_earnings(symbol: str, market: str) -> str | None:
    """Next earnings date (ISO) via yfinance calendar. None if unknown."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    for ticker in _yf_candidates(symbol, market):
        try:
            cal = yf.Ticker(ticker).calendar
        except Exception as exc:
            log.debug("earnings fetch failed for %s: %s", ticker, exc)
            continue
        d = _parse_earnings_date(cal)
        if d:
            return d
    return None


def _parse_earnings_date(cal) -> str | None:
    if not cal:
        return None
    value = cal.get("Earnings Date") if isinstance(cal, dict) else None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    s = str(value)
    return s[:10] if len(s) >= 10 else None


def next_fomc(today: date | None = None) -> str | None:
    today = today or datetime.now(UTC).date()
    for d in _FOMC_2026:
        meeting = date.fromisoformat(d)
        if meeting >= today:
            return f"FOMC {d} (D-{(meeting - today).days})"
    return None


# FRED series → human label and whether the latest observation is already the
# value we want (rate) vs needs a 12-month YoY computation (price index).
_FRED_LEVEL = {"UNRATE": "실업률", "FEDFUNDS": "기준금리", "DGS10": "미 10년물"}
_FRED_YOY = {"CPIAUCSL": "CPI(YoY)"}


def fetch_macro(settings: Settings, *, http: httpx.Client | None = None,
                today: date | None = None) -> MacroSnapshot:
    """Macro backdrop: FRED indicator values (needs FRED_API_KEY) + the next
    FOMC date (static schedule, no key needed). Degrades to whatever is available."""
    indicators: dict[str, str] = {}
    key = settings.fred_api_key
    if key:
        client = http or httpx.Client(timeout=settings.toss_timeout_s)
        try:
            for series, label in _FRED_LEVEL.items():
                v = _fred_latest(client, series, key)
                if v is not None:
                    indicators[label] = f"{v:.2f}%"
            for series, label in _FRED_YOY.items():
                v = _fred_yoy(client, series, key)
                if v is not None:
                    indicators[label] = f"{v:+.1f}%"
        except Exception as exc:
            log.debug("FRED macro fetch failed: %s", exc)
        finally:
            if http is None:
                client.close()
    upcoming = []
    fomc = next_fomc(today)
    if fomc:
        upcoming.append(fomc)
    return MacroSnapshot(indicators=indicators, upcoming=upcoming)


def _fred_obs(client: httpx.Client, series: str, key: str, limit: int) -> list[float]:
    url = "https://api.stlouisfed.org/fred/series/observations"
    resp = client.get(url, params={
        "series_id": series, "api_key": key, "file_type": "json",
        "sort_order": "desc", "limit": limit,
    })
    resp.raise_for_status()
    vals = []
    for o in resp.json().get("observations", []):
        try:
            vals.append(float(o["value"]))
        except (KeyError, ValueError):
            continue
    return vals


def _fred_latest(client: httpx.Client, series: str, key: str) -> float | None:
    vals = _fred_obs(client, series, key, 1)
    return vals[0] if vals else None


def _fred_yoy(client: httpx.Client, series: str, key: str) -> float | None:
    vals = _fred_obs(client, series, key, 13)  # newest first
    if len(vals) >= 13 and vals[12]:
        return (vals[0] / vals[12] - 1.0) * 100.0
    return None
