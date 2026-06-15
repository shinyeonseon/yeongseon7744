"""Pydantic models for Toss Open API payloads.

Field names confirmed against live responses. Toss returns numeric values as
strings (e.g. "341500"); pydantic coerces them to float. ``extra="allow"`` keeps
any extra fields. All Toss-specific shapes live here so schema changes touch one
file.

Confirmed shapes:
  GET /api/v1/prices   -> {"result":[{"symbol","timestamp","lastPrice","currency"}]}
  GET /api/v1/candles  -> {"result":{"candles":[{"timestamp","openPrice",
                           "highPrice","lowPrice","closePrice","volume","currency"}]}}
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from tossai.models import Candle


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    access_token: str
    # Some OAuth servers return token_type/expires_in; tolerate either casing.
    token_type: str = "Bearer"
    expires_in: int = 3600  # seconds; conservative default if absent


class QuoteResponse(BaseModel):
    """A latest-price snapshot from GET /api/v1/prices.

    TODO(schema): confirm the exact price field name from a live response; until
    then ``price`` is best-effort (kept optional so doctor doesn't hard-fail).
    """

    model_config = ConfigDict(extra="allow")

    symbol: str
    price: float | None = None


class CandleRaw(BaseModel):
    """One OHLCV bar from GET /api/v1/candles (Toss field names; string values)."""

    model_config = ConfigDict(extra="allow")

    timestamp: datetime
    openPrice: float  # noqa: N815 - matches Toss field name
    highPrice: float  # noqa: N815
    lowPrice: float  # noqa: N815
    closePrice: float  # noqa: N815
    volume: float = 0.0

    def to_candle(self) -> Candle:
        return Candle(
            ts=self.timestamp,
            open=self.openPrice,
            high=self.highPrice,
            low=self.lowPrice,
            close=self.closePrice,
            volume=self.volume,
        )
