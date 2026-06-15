"""Pydantic models for Toss Open API payloads.

TODO(schema): the exact field names/shapes are NOT yet confirmed — the public
docs (developers.tossinvest.com) require auth and were not machine-readable at
build time. These models use ``extra="allow"`` so unknown fields are preserved,
and parsing is intentionally lenient. Confirm and tighten against the live API
using `python -m tossai doctor` once real credentials are in place. Keeping all
Toss-specific shapes here means schema fixes touch exactly one file.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from tossai.models import Candle


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    access_token: str
    # Some OAuth servers return token_type/expires_in; tolerate either casing.
    token_type: str = "Bearer"
    expires_in: int = 3600  # seconds; conservative default if absent


class QuoteResponse(BaseModel):
    """A latest-price snapshot. TODO(schema): confirm field names."""

    model_config = ConfigDict(extra="allow")

    symbol: str
    price: float


class CandleRaw(BaseModel):
    """One OHLCV bar as returned by Toss. TODO(schema): confirm field names.

    We accept a few likely aliases and normalize to the internal ``Candle``.
    """

    model_config = ConfigDict(extra="allow")

    # Accept any of these for the timestamp; resolved in ``to_candle``.
    ts: datetime | int | str | None = None
    dt: datetime | int | str | None = None
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def to_candle(self) -> Candle:
        raw_ts = self.ts if self.ts is not None else self.dt
        ts = _coerce_ts(raw_ts)
        return Candle(
            ts=ts,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


def _coerce_ts(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Heuristic: ms vs s epoch.
        secs = value / 1000.0 if value > 1e12 else float(value)
        return datetime.fromtimestamp(secs, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(tz=UTC)
