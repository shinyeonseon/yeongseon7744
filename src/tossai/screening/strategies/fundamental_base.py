"""Base for fundamental (value/quality) strategies.

These need a ``FundamentalsProvider`` (injected by the ensemble, like the VIX is
injected into CAN SLIM). When no provider is set or a symbol has no data, the
strategy skips that symbol — the run continues on price-based strategies.
"""

from __future__ import annotations

from abc import abstractmethod

from tossai.config import Settings
from tossai.fundamentals.models import Fundamentals
from tossai.fundamentals.provider import FundamentalsProvider
from tossai.models import Candle
from tossai.screening.strategies.base import BaseStrategy, StrategyResult


class FundamentalStrategy(BaseStrategy):
    bucket = "value"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.required_history = 2  # only the latest price is needed
        self.provider: FundamentalsProvider | None = None

    def set_fundamentals_provider(self, provider: FundamentalsProvider | None) -> None:
        self.provider = provider

    def _price(self, candles: list[Candle]) -> float:
        return float(candles[-1].close) if candles else 0.0

    def _skip(self, symbol: str, reason: str) -> StrategyResult:
        return StrategyResult(
            symbol=symbol, score=0.0, signals={}, price=None, atr=None,
            bucket=self.bucket, strategy=self.name, passed=False, reason=reason,
        )

    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None:
        if self.provider is None:
            return self._skip(symbol, "no fundamentals provider")
        fund = self.provider.get(symbol, market)
        if fund is None:
            return self._skip(symbol, "no fundamentals data")
        return self.evaluate_fundamentals(symbol, fund, self._price(candles))

    @abstractmethod
    def evaluate_fundamentals(
        self, symbol: str, fund: Fundamentals, price: float
    ) -> StrategyResult | None: ...


def clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
