"""Shared domain models used across screening, analysis, and output."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Action(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"


class Candle(BaseModel):
    """A single OHLCV bar."""

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class Candidate(BaseModel):
    """A symbol that passed screening, carrying the deterministic signals
    that Claude reasons over."""

    symbol: str
    market: str
    name: str | None = None
    price: float
    score: float
    signals: dict[str, float | bool | None] = Field(default_factory=dict)
    atr: float | None = None


class Recommendation(BaseModel):
    """Claude's structured judgment for one candidate. Mirrors the tool schema
    in analysis/claude_engine.py."""

    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    target_price: float | None = None
    rationale: str = ""
    risks: list[str] = Field(default_factory=list)
    time_horizon: str = ""


class AnalyzedCandidate(BaseModel):
    """A candidate joined with its recommendation and token usage."""

    candidate: Candidate
    recommendation: Recommendation
    input_tokens: int = 0
    output_tokens: int = 0


DISCLAIMER = (
    "This output is automated analysis for informational purposes only and is "
    "NOT financial advice. No orders are placed. Markets carry risk of loss."
)
