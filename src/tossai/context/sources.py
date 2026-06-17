"""Lazy, fail-soft data sources for market context.

Every fetcher imports its heavy/network dependency *inside* the function and
returns an empty/None result on any failure, so an unreachable source never
breaks a run (mirrors the fundamentals providers).
"""

from __future__ import annotations

import contextlib
import io
import logging
from datetime import UTC, date, datetime

import httpx

from tossai.config import Settings
from tossai.context.models import MacroSnapshot, NewsItem
from tossai.logging_setup import get_logger

log = get_logger(__name__)


@contextlib.contextmanager
def _quiet():
    """Silence yfinance's noisy 404/ERROR logs + prints during a fetch (ETFs and
    some symbols legitimately have no news/earnings — handled as empty)."""
    buf = io.StringIO()
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            yield
    finally:
        logging.disable(logging.NOTSET)

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
            with _quiet():
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
            with _quiet():
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
# Spreads: yield-curve (inverts before recessions) and high-yield credit
# (widens when risk appetite falls). Reported in percentage points, signed.
_FRED_SPREAD = {"T10Y2Y": "10Y-2Y", "BAMLH0A0HYM2": "HY스프레드"}

# CNN Fear & Greed Index (composite market sentiment, 0–100). No API key.
# CNN's CDN bot-filters thin requests, so send a full browser header set.
_FNG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_FNG_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://edition.cnn.com/markets/fear-and-greed",
}
_FNG_RATING_KO = {
    "extreme fear": "극단적공포", "fear": "공포", "neutral": "중립",
    "greed": "탐욕", "extreme greed": "극단적탐욕",
}


def fetch_fear_greed(settings: Settings, *, http: httpx.Client | None = None) -> tuple[float, str] | None:
    """CNN Fear & Greed Index as (score 0–100, KO rating). None if unavailable."""
    client = http or httpx.Client(timeout=settings.toss_timeout_s)
    try:
        resp = client.get(_FNG_URL, headers=_FNG_HEADERS)
        resp.raise_for_status()
        fg = resp.json().get("fear_and_greed", {})
        score = fg.get("score")
        if score is None:
            return None
        rating = str(fg.get("rating", "")).lower()
        return float(score), _FNG_RATING_KO.get(rating, rating or "—")
    except Exception as exc:
        log.debug("fear&greed fetch failed: %s", exc)
        return None
    finally:
        if http is None:
            client.close()


def fetch_macro(settings: Settings, *, http: httpx.Client | None = None,
                today: date | None = None) -> MacroSnapshot:
    """Macro backdrop: FRED indicators + yield-curve/credit spreads (needs
    FRED_API_KEY), CNN Fear & Greed (no key), and the next FOMC date.
    Degrades to whatever is available."""
    indicators: dict[str, str] = {}
    client = http or httpx.Client(timeout=settings.toss_timeout_s)
    try:
        key = settings.fred_api_key
        if key:
            try:
                for series, label in _FRED_LEVEL.items():
                    v = _fred_latest(client, series, key)
                    if v is not None:
                        indicators[label] = f"{v:.2f}%"
                for series, label in _FRED_SPREAD.items():
                    v = _fred_latest(client, series, key)
                    if v is not None:
                        indicators[label] = f"{v:+.2f}%p"
                for series, label in _FRED_YOY.items():
                    v = _fred_yoy(client, series, key)
                    if v is not None:
                        indicators[label] = f"{v:+.1f}%"
            except Exception as exc:
                log.debug("FRED macro fetch failed: %s", exc)
        try:
            fg = fetch_fear_greed(settings, http=client)
            if fg:
                indicators["공포탐욕"] = f"{fg[0]:.0f}({fg[1]})"
        except Exception as exc:
            log.debug("fear&greed merge failed: %s", exc)
    finally:
        if http is None:
            client.close()
    upcoming = []
    fomc = next_fomc(today)
    if fomc:
        upcoming.append(fomc)
    return MacroSnapshot(indicators=indicators, upcoming=upcoming)


def _fred_obs(client: httpx.Client, series: str, key: str, limit: int) -> list[float]:
    """Latest `limit` numeric observations (newest first). Resilient: a single
    series failing returns [] so it doesn't abort the other indicators."""
    url = "https://api.stlouisfed.org/fred/series/observations"
    try:
        resp = client.get(url, params={
            "series_id": series, "api_key": key, "file_type": "json",
            "sort_order": "desc", "limit": limit,
        })
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
    except Exception as exc:
        log.debug("FRED %s fetch failed: %s", series, exc)
        return []
    vals = []
    for o in observations:
        try:
            vals.append(float(o["value"]))
        except (KeyError, ValueError):
            continue  # skip "." placeholder rows (holidays / pending release)
    return vals


def _fred_latest(client: httpx.Client, series: str, key: str) -> float | None:
    # Fetch a few: daily series carry "." on holidays, which _fred_obs skips.
    vals = _fred_obs(client, series, key, 5)
    return vals[0] if vals else None


def _fred_yoy(client: httpx.Client, series: str, key: str) -> float | None:
    # Fetch 14 (not 13) so a pending "." row for the current month — which
    # _fred_obs drops — still leaves 13 valid months for the YoY comparison.
    vals = _fred_obs(client, series, key, 14)  # newest first
    if len(vals) >= 13 and vals[12]:
        return (vals[0] / vals[12] - 1.0) * 100.0
    return None
