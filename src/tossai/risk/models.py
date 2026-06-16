"""Risk alert model. Carries informational text only — never an action."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class RiskKind(str, Enum):
    BLACKSWAN = "blackswan"
    GAP_DOWN = "gap_down"
    POSITION_STOP = "position_stop"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class RiskAlert(BaseModel):
    kind: RiskKind
    severity: Severity = Severity.WARNING
    message: str
    symbol: str | None = None
    value: float | None = None
    threshold: float | None = None
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def dedupe_key(self, trading_date: str) -> str:
        return f"{self.kind.value}:{self.symbol or '-'}:{trading_date}"
