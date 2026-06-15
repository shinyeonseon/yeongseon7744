"""Normalized fundamentals. Every field is optional — sources vary in coverage
and the value/quality strategies must degrade gracefully when data is missing.
"""

from __future__ import annotations

from pydantic import BaseModel


class Fundamentals(BaseModel):
    symbol: str
    market: str
    per: float | None = None            # price / earnings
    pbr: float | None = None            # price / book
    eps: float | None = None            # earnings per share
    bps: float | None = None            # book value per share
    roe: float | None = None            # return on equity (fraction, 0.15 == 15%)
    dividend_yield: float | None = None  # fraction
    market_cap: float | None = None
    debt_to_equity: float | None = None

    @property
    def earnings_yield(self) -> float | None:
        """E/P. Derived from PER when available (and positive)."""
        if self.per is not None and self.per > 0:
            return 1.0 / self.per
        return None
