"""Trend breakout — close above the prior N-bar high with volume confirmation."""

from __future__ import annotations

import pandas as pd

from tossai.config import Settings
from tossai.models import Candle
from tossai.screening import indicators as ind
from tossai.screening.screener import candles_to_df
from tossai.screening.strategies.base import BaseStrategy, StrategyResult


class TrendBreakoutStrategy(BaseStrategy):
    name = "trend_breakout"
    bucket = "long"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.required_history = max(settings.breakout_lookback, settings.trend_ma) + 2

    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None:
        s = self.s
        if len(candles) < self.required_history:
            return self._too_short(symbol)

        df = candles_to_df(candles)
        close = df["close"]
        last = float(close.iloc[-1])

        # Prior high excludes today's bar (shift(1)) so a fresh close above it
        # is a genuine breakout.
        prev_high = ind.rolling_high(close, s.breakout_lookback).shift(1).iloc[-1]
        prev_high = None if pd.isna(prev_high) else float(prev_high)
        vol_ratio = ind.volume_ratio(df["volume"], s.breakout_vol_window).iloc[-1]
        vol_ratio = 0.0 if pd.isna(vol_ratio) else float(vol_ratio)
        ma_t = float(ind.sma(close, s.trend_ma).iloc[-1]) if len(close) >= s.trend_ma else last

        broke_out = prev_high is not None and last > prev_high
        vol_ok = vol_ratio >= s.breakout_vol_ratio_min
        trend_ok = last > ma_t
        passed = broke_out and vol_ok and trend_ok

        breakout_pct = (last / prev_high - 1.0) if prev_high else 0.0
        trend_margin = _clip((last / ma_t - 1.0) / 0.10)
        score = (
            0.45 * _clip(breakout_pct / 0.05)
            + 0.35 * _clip(vol_ratio - 1.0)
            + 0.20 * trend_margin
        ) if passed else 0.0

        reasons = [n for n, ok in (
            ("breakout", broke_out), ("volume", vol_ok), ("trend", trend_ok)) if not ok]
        return StrategyResult(
            symbol=symbol, score=round(score, 4),
            signals={
                "prior_high": round(prev_high, 4) if prev_high else None,
                "breakout_pct": round(breakout_pct * 100, 2),
                "volume_ratio": round(vol_ratio, 3),
                "above_trend_ma": last > ma_t,
            },
            price=last, atr=None, bucket=self.bucket, strategy=self.name,
            passed=passed, reason="" if passed else "failed: " + ",".join(reasons),
        )


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
