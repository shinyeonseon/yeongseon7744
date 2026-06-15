"""Dual momentum (Gary Antonacci): absolute + relative momentum."""

from __future__ import annotations

import pandas as pd

from tossai.config import Settings
from tossai.models import Candle
from tossai.screening import indicators as ind
from tossai.screening.screener import candles_to_df
from tossai.screening.strategies.base import BaseStrategy, StrategyResult


class DualMomentumStrategy(BaseStrategy):
    name = "dual_momentum"
    bucket = "long"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.required_history = settings.dm_lookback_days + settings.dm_skip_days + 2

    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None:
        s = self.s
        if len(candles) < self.required_history:
            return self._too_short(symbol)

        df = candles_to_df(candles)
        close = df["close"]
        r = ind.total_return(close, s.dm_lookback_days, skip=s.dm_skip_days)
        if r is None:
            return self._too_short(symbol)

        price = float(close.iloc[-1])
        above_sma200 = True
        if s.dm_require_trend and len(close) >= 200:
            sma200 = ind.sma(close, 200).iloc[-1]
            above_sma200 = not pd.isna(sma200) and price > float(sma200)

        # Absolute momentum gate: beat the threshold (default 0 == cash) and,
        # optionally, be in an uptrend.
        passed_abs = r > s.dm_abs_threshold
        passed = passed_abs and (above_sma200 or not s.dm_require_trend)

        # Relative momentum ranking: monotonic map of return → score so the
        # cross-symbol sort reproduces the relative ranking.
        score = _clip(r / s.dm_score_cap) if passed else 0.0

        return StrategyResult(
            symbol=symbol, score=round(score, 4),
            signals={
                "lookback_return": round(r, 4),
                "lookback_days": s.dm_lookback_days,
                "skip_days": s.dm_skip_days,
                "abs_threshold": s.dm_abs_threshold,
                "above_sma200": above_sma200,
                "passed_abs": passed_abs,
            },
            price=price, atr=None, bucket=self.bucket, strategy=self.name,
            passed=passed,
            reason="" if passed else "abs_momentum/trend filter",
        )


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
