"""Mean reversion — buy oversold dips within a longer-term uptrend."""

from __future__ import annotations

import pandas as pd

from tossai.config import Settings
from tossai.models import Candle
from tossai.screening import indicators as ind
from tossai.screening.screener import candles_to_df
from tossai.screening.strategies.base import BaseStrategy, StrategyResult


class MeanReversionStrategy(BaseStrategy):
    name = "mean_reversion"
    bucket = "swing"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.required_history = max(settings.mean_rev_ma, settings.rsi_period) + 2

    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None:
        s = self.s
        if len(candles) < self.required_history:
            return self._too_short(symbol)

        df = candles_to_df(candles)
        close = df["close"]
        last = float(close.iloc[-1])

        ma_long = float(ind.sma(close, s.mean_rev_ma).iloc[-1])
        rsi_val = ind.rsi(close, s.rsi_period).iloc[-1]
        rsi_val = 100.0 if pd.isna(rsi_val) else float(rsi_val)
        rp = ind.range_position(close, s.mean_rev_support_lookback).iloc[-1]
        rp = 1.0 if pd.isna(rp) else float(rp)

        uptrend = last > ma_long
        oversold = rsi_val < s.mean_rev_rsi_low
        near_support = rp <= s.mean_rev_support_pos
        passed = uptrend and oversold and near_support

        trend_margin = _clip((last / ma_long - 1.0) / 0.10)
        depth = _clip((s.mean_rev_rsi_low - rsi_val) / s.mean_rev_rsi_low)
        score = (0.50 * depth + 0.25 * (1.0 - rp) + 0.25 * trend_margin) if passed else 0.0

        reasons = [n for n, ok in (
            ("uptrend", uptrend), ("oversold", oversold), ("near_support", near_support)
        ) if not ok]
        return StrategyResult(
            symbol=symbol, score=round(score, 4),
            signals={
                "rsi": round(rsi_val, 2),
                "sma_long": round(ma_long, 4),
                "above_long_ma": uptrend,
                "range_position": round(rp, 3),
            },
            price=last, atr=None, bucket=self.bucket, strategy=self.name,
            passed=passed, reason="" if passed else "failed: " + ",".join(reasons),
        )


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
