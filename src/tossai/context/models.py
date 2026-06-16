"""Data models for the market-context layer (news / earnings / macro)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    title: str
    publisher: str | None = None
    published: str | None = None  # ISO date (YYYY-MM-DD) when known

    def as_line(self) -> str:
        bits = [self.published, self.title]
        if self.publisher:
            bits.append(f"({self.publisher})")
        return " ".join(b for b in bits if b).strip()


class SymbolContext(BaseModel):
    """Per-symbol qualitative context handed to Claude as reference."""

    symbol: str
    market: str
    news: list[NewsItem] = Field(default_factory=list)
    next_earnings: str | None = None  # ISO date

    def to_payload(self) -> dict:
        out: dict = {}
        if self.news:
            out["recent_news"] = [n.as_line() for n in self.news]
        if self.next_earnings:
            out["next_earnings_date"] = self.next_earnings
        return out

    def is_empty(self) -> bool:
        return not self.news and not self.next_earnings


class MacroSnapshot(BaseModel):
    """Shared macro backdrop: latest key indicators + upcoming scheduled events."""

    indicators: dict[str, str] = Field(default_factory=dict)  # {"실업률": "4.0%", ...}
    upcoming: list[str] = Field(default_factory=list)         # ["FOMC 2026-06-17 (D-2)", ...]

    def to_payload(self) -> dict:
        out: dict = {}
        if self.indicators:
            out["indicators"] = self.indicators
        if self.upcoming:
            out["upcoming_events"] = self.upcoming
        return out

    def is_empty(self) -> bool:
        return not self.indicators and not self.upcoming

    def as_line(self) -> str:
        """Compact one-line summary for a Slack header (or '' when empty)."""
        parts = [f"{k} {v}" for k, v in self.indicators.items()]
        parts += self.upcoming
        return "  ·  ".join(parts)
