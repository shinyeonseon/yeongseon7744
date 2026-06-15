"""Meb Faber GTAA — long-only trend timing on the 10-month (~200d) SMA.

The classic rule: hold the asset only while price is above its 10-month moving
average, otherwise move to cash. As a screen, a symbol passes when it is in that
"risk-on" trend; score scales with how far above the average it is.
"""

from __future__ import annotations

from tossai.config import Settings
from tossai.models import Candle
from tossai.screening import indicators as ind
from tossai.screening.screener import candles_to_df
from tossai.screening.strategies.base import BaseStrategy, StrategyResult


class MebFaberTrendStrategy(BaseStrategy):
    name = "meb_faber"
    bucket = "long"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.required_history = settings.meb_faber_ma + 2

    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None:
        if len(candles) < self.required_history:
            return self._too_short(symbol)
        df = candles_to_df(candles)
        close = df["close"]
        last = float(close.iloc[-1])
        ma = float(ind.sma(close, self.s.meb_faber_ma).iloc[-1])

        above = last > ma
        score = _clip((last / ma - 1.0) / 0.10) if above else 0.0
        return StrategyResult(
            symbol=symbol, score=round(score, 4),
            signals={
                "sma": round(ma, 4),
                "above_sma": above,
                "pct_above": round((last / ma - 1.0) * 100, 2),
                "ma_window": self.s.meb_faber_ma,
            },
            price=last, atr=None, bucket=self.bucket, strategy=self.name,
            passed=above, reason="" if above else "below 10-month SMA",
        )


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
