"""CAN SLIM — technical subset only (no fundamentals).

Implements the chart-readable parts: proximity to the 52-week high (L/N),
relative strength within the annual range (RS), volume surge (S), stacked MAs
(trend), and the market-direction gate (M) via VIX. Fundamental criteria
(C/A earnings, I institutional) are an explicit future hook — not implemented.
"""

from __future__ import annotations

import pandas as pd

from tossai.config import Settings
from tossai.models import Candle
from tossai.screening import indicators as ind
from tossai.screening.screener import candles_to_df
from tossai.screening.strategies.base import BaseStrategy, StrategyResult


class CanSlimTechnicalStrategy(BaseStrategy):
    name = "canslim"
    bucket = "swing"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.required_history = max(settings.canslim_rs_lookback, 200) + 2
        self.vix: float | None = None

    def set_vix(self, vix: float | None) -> None:
        self.vix = vix

    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None:
        s = self.s
        if len(candles) < self.required_history:
            return self._too_short(symbol)

        df = candles_to_df(candles)
        close = df["close"]
        last = float(close.iloc[-1])

        hi52 = float(ind.rolling_high(close, s.canslim_rs_lookback).iloc[-1])
        rs_pos = ind.range_position(close, s.canslim_rs_lookback).iloc[-1]
        rs_pos = 0.0 if pd.isna(rs_pos) else float(rs_pos)
        vol_ratio = ind.volume_ratio(df["volume"], 50).iloc[-1]
        vol_ratio = 0.0 if pd.isna(vol_ratio) else float(vol_ratio)
        ma50 = float(ind.sma(close, 50).iloc[-1])
        ma200 = float(ind.sma(close, 200).iloc[-1])
        ann_return = ind.total_return(close, s.canslim_rs_lookback) or 0.0

        near_high = last >= hi52 * (1.0 - s.canslim_high_proximity_pct)
        rs_ok = rs_pos >= s.canslim_rs_min and ann_return > 0
        vol_ok = vol_ratio >= s.canslim_vol_ratio_min
        trend_ok = last > ma50 > ma200
        # Market direction (M): suppress in a stressed tape. None == no data → allow.
        market_ok = self.vix is None or self.vix <= s.canslim_max_vix

        passed = near_high and rs_ok and vol_ok and trend_ok and market_ok

        proximity = _clip(1.0 - (hi52 - last) / (hi52 * s.canslim_high_proximity_pct))
        trend_margin = _clip((last / ma200 - 1.0) / 0.10)
        score = (
            0.30 * rs_pos
            + 0.25 * proximity
            + 0.25 * _clip(vol_ratio - 1.0)
            + 0.20 * trend_margin
        ) if passed else 0.0

        reasons = [n for n, ok in (
            ("near_high", near_high), ("rs", rs_ok), ("volume", vol_ok),
            ("trend", trend_ok), ("market", market_ok)) if not ok]
        return StrategyResult(
            symbol=symbol, score=round(score, 4),
            signals={
                "hi_52w": round(hi52, 4),
                "dist_to_high_pct": round((hi52 - last) / hi52 * 100, 2),
                "range_position": round(rs_pos, 3),
                "volume_ratio_50": round(vol_ratio, 3),
                "above_ma50": last > ma50,
                "above_ma200": last > ma200,
                "vix": self.vix,
                "market_ok": market_ok,
                "note": "technical subset — no fundamentals",
            },
            price=last, atr=None, bucket=self.bucket, strategy=self.name,
            passed=passed, reason="" if passed else "failed: " + ",".join(reasons),
        )


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
