"""Strategy abstraction and shared rank/cap/build lifecycle."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.models import Candidate, Candle

log = get_logger(__name__)


@dataclass
class StrategyResult:
    symbol: str
    score: float
    signals: dict[str, float | bool | str | None]
    price: float | None
    atr: float | None
    bucket: str
    strategy: str
    passed: bool = True
    reason: str = ""


@runtime_checkable
class Strategy(Protocol):
    name: str
    bucket: str
    required_history: int

    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None: ...

    def screen_universe(
        self, candle_map: dict[str, list[Candle]], markets: dict[str, str] | None = None
    ) -> list[Candidate]: ...


class BaseStrategy(ABC):
    """Implements the shared loop (per-symbol eval → filter → rank → cap → build).

    Subclasses implement ``evaluate`` only.
    """

    name: str = "base"
    bucket: str = "swing"
    required_history: int = 0

    def __init__(self, settings: Settings):
        self.s = settings
        self.min_score = settings.screen_min_score

    @abstractmethod
    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None:
        ...

    def _too_short(self, symbol: str) -> StrategyResult:
        return StrategyResult(
            symbol=symbol, score=0.0, signals={}, price=None, atr=None,
            bucket=self.bucket, strategy=self.name, passed=False,
            reason="insufficient history",
        )

    def evaluate_all(
        self, candle_map: dict[str, list[Candle]], markets: dict[str, str] | None = None
    ) -> list[StrategyResult]:
        """Evaluate every symbol, returning passing results (unsorted, uncapped)."""
        markets = markets or {}
        out: list[StrategyResult] = []
        for symbol, candles in candle_map.items():
            try:
                res = self.evaluate(symbol, candles, markets.get(symbol, "KRX"))
            except Exception as exc:  # never let one bad symbol kill the run
                log.warning("%s failed for %s: %s", self.name, symbol, exc)
                continue
            if res is None or not res.passed:
                if res is not None:
                    log.debug("skip %s (%s: %s)", symbol, self.name, res.reason)
                continue
            if res.score < self.min_score:
                continue
            out.append(res)
        return out

    def screen_universe(
        self, candle_map: dict[str, list[Candle]], markets: dict[str, str] | None = None
    ) -> list[Candidate]:
        markets = markets or {}
        results = self.evaluate_all(candle_map, markets)
        results.sort(key=lambda r: r.score, reverse=True)
        top = results[: self.s.claude_max_candidates]
        return [_to_candidate(r, markets.get(r.symbol, "KRX")) for r in top]


def _to_candidate(r: StrategyResult, market: str) -> Candidate:
    return Candidate(
        symbol=r.symbol,
        market=market,
        price=r.price or 0.0,
        score=r.score,
        signals=dict(r.signals),
        atr=r.atr,
        strategy=r.strategy,
        bucket=r.bucket,
        flagged_by=[r.strategy],
    )
