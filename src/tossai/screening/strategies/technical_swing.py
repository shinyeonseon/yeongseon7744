"""Technical swing strategy — wraps the existing Screener funnel verbatim."""

from __future__ import annotations

from tossai.config import Settings
from tossai.models import Candle
from tossai.screening.screener import Screener
from tossai.screening.strategies.base import BaseStrategy, StrategyResult


class TechnicalSwingStrategy(BaseStrategy):
    name = "technical_swing"
    bucket = "swing"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._screener = Screener(settings)
        self.required_history = max(settings.sma_slow, settings.rsi_period) + 2

    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None:
        res = self._screener.run(symbol, candles, market=market)
        return StrategyResult(
            symbol=res.symbol,
            score=res.score,
            signals=dict(res.signals),
            price=res.price,
            atr=res.atr,
            bucket=self.bucket,
            strategy=self.name,
            passed=res.passed,
            reason=res.reason,
        )
