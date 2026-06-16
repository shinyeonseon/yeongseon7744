"""Data models for recommendation performance tracking."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RecoRecord(BaseModel):
    """One recorded recommendation (the unit we later score)."""

    date: str            # ISO date (YYYY-MM-DD) the recommendation was made
    symbol: str
    market: str
    action: str          # BUY / SELL / HOLD
    confidence: float = 0.0
    price: float | None = None  # price at recommendation time

    def key(self) -> tuple[str, str, str]:
        return (self.date, self.symbol, self.action)


class HorizonStat(BaseModel):
    horizon: int          # trading days forward
    n: int = 0            # scored directional calls
    win_rate: float = 0.0  # fraction where the direction was right
    avg_return: float = 0.0  # mean direction-adjusted return (BUY=ret, SELL=-ret)


class PerformanceSummary(BaseModel):
    total: int = 0                # records in the ledger
    directional: int = 0          # BUY/SELL records considered
    scored: int = 0               # had enough forward data for the primary horizon
    pending: int = 0              # too recent to score at the primary horizon
    primary_horizon: int = 21
    horizons: list[HorizonStat] = Field(default_factory=list)
    by_action: dict[str, HorizonStat] = Field(default_factory=dict)
    high_conf_avg: float | None = None  # avg dir-return for confidence >= 0.7
    low_conf_avg: float | None = None   # avg dir-return for confidence < 0.7
