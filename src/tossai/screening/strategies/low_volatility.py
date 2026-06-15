"""Low-volatility factor.

The low-vol anomaly: lower-volatility stocks have historically delivered strong
risk-adjusted returns. Screens for low realized volatility, restricted to names
in an uptrend (above the 200-day SMA) so it isn't just picking dead money.
"""

from __future__ import annotations

import pandas as pd

from tossai.config import Settings
from tossai.models import Candle
from tossai.screening import indicators as ind
from tossai.screening.screener import candles_to_df
from tossai.screening.strategies.base import BaseStrategy, StrategyResult


class LowVolatilityStrategy(BaseStrategy):
    name = "low_volatility"
    bucket = "long"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.required_history = max(settings.lowvol_lookback, settings.trend_ma) + 2

    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None:
        s = self.s
        if len(candles) < self.required_history:
            return self._too_short(symbol)
        df = candles_to_df(candles)
        close = df["close"]
        price = float(close.iloc[-1])

        rets = close.pct_change().dropna().iloc[-s.lowvol_lookback:]
        vol = float(rets.std()) if len(rets) else 0.0
        ma_t = ind.sma(close, s.trend_ma).iloc[-1]
        above = pd.notna(ma_t) and price > float(ma_t)

        passed = above and vol > 0.0
        score = _clip(1.0 - vol / s.lowvol_vol_cap) if passed else 0.0
        return StrategyResult(
            symbol=symbol, score=round(score, 4),
            signals={
                "daily_vol": round(vol, 5),
                "vol_cap": s.lowvol_vol_cap,
                "above_trend_ma": above,
            },
            price=price, atr=None, bucket=self.bucket, strategy=self.name,
            passed=passed, reason="" if passed else "not low-vol uptrend",
        )


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
