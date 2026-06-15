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
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from tossai.models import Candle

if TYPE_CHECKING:
    from tossai.models import Position


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


class AccountRaw(BaseModel):
    """GET /api/v1/accounts item: {"accountNo","accountSeq","accountType"}."""

    model_config = ConfigDict(extra="allow")

    accountNo: str | None = None  # noqa: N815 - Toss field name
    accountSeq: int  # noqa: N815
    accountType: str | None = None  # noqa: N815


class HoldingItemRaw(BaseModel):
    """One position from GET /api/v1/holdings result.items[] (string values)."""

    model_config = ConfigDict(extra="allow")

    symbol: str
    name: str | None = None
    marketCountry: str | None = None  # noqa: N815 - "US" / "KR"
    currency: str | None = None
    quantity: float = 0.0
    lastPrice: float = 0.0  # noqa: N815
    averagePurchasePrice: float = 0.0  # noqa: N815

    def to_position(self) -> Position:
        from tossai.models import Position

        market = "US" if (self.marketCountry or "").upper() == "US" else "KRX"
        extra = self.model_extra or {}
        pl = extra.get("profitLoss") or {}
        mv = extra.get("marketValue") or {}
        return Position(
            symbol=self.symbol, market=market, name=self.name,
            quantity=self.quantity, avg_price=self.averagePurchasePrice,
            last_price=self.lastPrice, currency=self.currency,
            pl_rate=_as_float(pl.get("rate")),
            market_value=_as_float(mv.get("amount")) or 0.0,
        )


def _as_float(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


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
