"""Quantitative momentum with quality (Wesley Gray style).

12-1 momentum (trailing 12-month return skipping the most recent month) gated by
an uptrend, scored with a "frog-in-the-pan" (FIP) smoothness adjustment so that
steady, low-noise trends rank above jumpy ones.
"""

from __future__ import annotations

import pandas as pd

from tossai.config import Settings
from tossai.models import Candle
from tossai.screening import indicators as ind
from tossai.screening.screener import candles_to_df
from tossai.screening.strategies.base import BaseStrategy, StrategyResult


class MomentumQualityStrategy(BaseStrategy):
    name = "momentum_quality"
    bucket = "long"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.required_history = settings.momq_lookback + settings.momq_skip + 2

    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None:
        s = self.s
        if len(candles) < self.required_history:
            return self._too_short(symbol)
        df = candles_to_df(candles)
        close = df["close"]
        r = ind.total_return(close, s.momq_lookback, skip=s.momq_skip)
        if r is None:
            return self._too_short(symbol)
        price = float(close.iloc[-1])

        # FIP: sign(R) * (%down days - %up days) over the lookback window.
        window = close.iloc[-(s.momq_lookback + s.momq_skip):]
        rets = window.pct_change().dropna()
        up = float((rets > 0).mean()) if len(rets) else 0.0
        down = float((rets < 0).mean()) if len(rets) else 0.0
        sign = 1.0 if r >= 0 else -1.0
        fip = sign * (down - up)          # negative == smooth uptrend (good)
        smoothness = _clip((1.0 - fip) / 2.0)

        ma_t = ind.sma(close, self.s.trend_ma).iloc[-1]
        above = pd.notna(ma_t) and price > float(ma_t)
        passed = r > 0 and above
        score = (0.7 * _clip(r / s.momq_score_cap) + 0.3 * smoothness) if passed else 0.0

        return StrategyResult(
            symbol=symbol, score=round(score, 4),
            signals={
                "momentum_12_1": round(r, 4),
                "fip": round(fip, 4),
                "smoothness": round(smoothness, 3),
                "above_trend_ma": above,
            },
            price=price, atr=None, bucket=self.bucket, strategy=self.name,
            passed=passed, reason="" if passed else "momentum/trend filter",
        )


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
