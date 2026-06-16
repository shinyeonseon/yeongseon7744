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
    signals: dict[str, float | bool | str | None] = Field(default_factory=dict)
    atr: float | None = None
    # Which strategy/bucket flagged this candidate (ensemble fills these in).
    strategy: str | None = None
    bucket: str | None = None
    flagged_by: list[str] = Field(default_factory=list)


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


class PortfolioAction(str, Enum):
    ADD = "ADD"      # 추가매수
    HOLD = "HOLD"    # 유지
    TRIM = "TRIM"    # 축소
    SELL = "SELL"    # 전량 매도
    ANALYSIS_FAILED = "ANALYSIS_FAILED"


class Position(BaseModel):
    """A held position from the Toss holdings endpoint."""

    symbol: str
    market: str
    name: str | None = None
    quantity: float = 0.0
    avg_price: float = 0.0
    last_price: float = 0.0
    pl_rate: float | None = None       # fraction, 1.796 == +179.6%
    market_value: float = 0.0
    currency: str | None = None


class PositionAdvice(BaseModel):
    """Claude's position-aware advice (analysis only — never an order)."""

    action: PortfolioAction
    confidence: float = Field(ge=0.0, le=1.0)
    target_price: float | None = None
    rationale: str = ""
    risks: list[str] = Field(default_factory=list)


class AnalyzedPosition(BaseModel):
    position: Position
    advice: PositionAdvice
    input_tokens: int = 0
    output_tokens: int = 0


DISCLAIMER = (
    "본 결과는 정보 제공용 자동 분석이며 투자 자문이 아닙니다. "
    "주문은 실행되지 않습니다. 투자에는 원금 손실 위험이 있습니다."
)
