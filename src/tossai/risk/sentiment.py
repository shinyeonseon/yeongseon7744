"""Market sentiment data (VIX).

Fetches the VIX from a pluggable CSV endpoint (Stooq by default) using httpx —
no heavy data dependency. Returns ``None`` on any failure so risk scans degrade
gracefully rather than crashing.
"""

from __future__ import annotations

import csv
import io

import httpx

from tossai.config import Settings
from tossai.logging_setup import get_logger

log = get_logger(__name__)


def get_vix(settings: Settings, http: httpx.Client | None = None) -> float | None:
    """Return the latest VIX close, or None if unavailable.

    Stooq CSV columns: Symbol,Date,Time,Open,High,Low,Close,Volume.
    """
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
