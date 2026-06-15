"""Market sentiment data (VIX).

Primary source is yfinance (``^VIX``) when installed — reliable and already a
dependency for fundamentals. Falls back to a Stooq CSV over httpx. Returns
``None`` on any failure so risk scans degrade gracefully.
"""

from __future__ import annotations

import contextlib
import csv
import io
import logging

import httpx

from tossai.config import Settings
from tossai.logging_setup import get_logger

log = get_logger(__name__)


def get_vix(settings: Settings, http: httpx.Client | None = None) -> float | None:
    """Return the latest VIX close, or None if unavailable."""
    v = _vix_from_yfinance()
    if v is not None:
        return v
    return _vix_from_stooq(settings, http)


def _vix_from_yfinance() -> float | None:
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        buf = io.StringIO()
        logging.disable(logging.CRITICAL)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            hist = yf.Ticker("^VIX").history(period="5d")
        if hist is not None and len(hist) and "Close" in hist:
            return float(hist["Close"].iloc[-1])
    except Exception as exc:  # yfinance is flaky; degrade
        log.debug("yfinance VIX failed: %s", exc)
    finally:
        logging.disable(logging.NOTSET)
    return None


def _vix_from_stooq(settings: Settings, http: httpx.Client | None = None) -> float | None:
    client = http or httpx.Client(timeout=10.0)
    own = http is None
    try:
        resp = client.get(settings.vix_source_url)
        resp.raise_for_status()
        return _parse_vix_csv(resp.text)
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("VIX fetch failed: %s", exc)
        return None
    finally:
        if own:
            client.close()


def _parse_vix_csv(text: str) -> float | None:
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        close = row.get("Close") or row.get("close")
        if close and close not in ("N/D", "-"):
            try:
                return float(close)
            except ValueError:
                return None
    return None
