"""Rule funnel that turns raw candles into ranked Candidates.

The screener is the cost lever: it narrows a large universe down to a handful
of survivors so Claude only reasons over the best ideas.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.models import Candidate, Candle
from tossai.screening import indicators as ind

log = get_logger(__name__)


@dataclass
class ScreenResult:
    symbol: str
    passed: bool
    score: float
    signals: dict[str, float | bool | None]
    price: float | None
    atr: float | None
    reason: str = ""


def candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame([c.model_dump() for c in candles])
    if not df.empty:
        df = df.sort_values("ts").reset_index(drop=True)
    return df


class Screener:
    """Applies a configurable technical funnel and scores survivors."""

    def __init__(self, settings: Settings):
        self.s = settings

    def run(self, symbol: str, candles: list[Candle], market: str = "KRX") -> ScreenResult:
        s = self.s
        min_bars = max(s.sma_slow, s.rsi_period) + 2
        if len(candles) < min_bars:
            return ScreenResult(
                symbol, False, 0.0, {}, None, None,
                reason=f"insufficient history ({len(candles)}<{min_bars})",
            )

        df = candles_to_df(candles)
        close = df["close"]

        sma_fast = ind.sma(close, s.sma_fast)
        sma_slow = ind.sma(close, s.sma_slow)
        rsi_val = ind.rsi(close, s.rsi_period)
        vol_ratio = ind.volume_ratio(df["volume"], s.sma_fast)
        mom = ind.momentum(close, n=10)
        atr_val = ind.atr(df, s.rsi_period)

        latest_price = float(close.iloc[-1])
        f = float(sma_fast.iloc[-1])
        sl = float(sma_slow.iloc[-1])
        r = float(rsi_val.iloc[-1])
        vr = float(vol_ratio.iloc[-1]) if not pd.isna(vol_ratio.iloc[-1]) else 0.0
        m = float(mom.iloc[-1]) if not pd.isna(mom.iloc[-1]) else 0.0
        gc = ind.golden_cross(sma_fast, sma_slow)
        a = float(atr_val.iloc[-1]) if not pd.isna(atr_val.iloc[-1]) else None

        signals: dict[str, float | bool | None] = {
            "price": round(latest_price, 4),
            "sma_fast": round(f, 4),
            "sma_slow": round(sl, 4),
            "uptrend": f > sl,
            "golden_cross": gc,
            "rsi": round(r, 2),
            "rsi_overbought": r >= s.rsi_overbought,
            "volume_ratio": round(vr, 3),
            "momentum_10": round(m, 4),
            "atr": round(a, 4) if a is not None else None,
        }

        # ---- Rule funnel: must pass all gates ----
        gates = {
            "trend": (f > sl) or gc,
            "not_overbought": r < s.rsi_overbought,
            "volume": vr >= s.volume_ratio_min,
            "momentum": m > 0.0,
        }
        passed = all(gates.values())

        # ---- Score (only meaningful for survivors) ----
        score = 0.0
        if passed:
            score += 0.25 if gc else 0.10  # fresh cross worth more
            score += min(max((vr - 1.0), 0.0), 1.0) * 0.25  # volume conviction
            score += min(max(m, 0.0), 0.20) / 0.20 * 0.25  # momentum, capped at +20%
            # Prefer RSI in a constructive 40–60 band, penalize extremes.
            rsi_quality = 1.0 - abs(r - 50.0) / 50.0
            score += max(rsi_quality, 0.0) * 0.25
            score = round(score, 4)

        reason = "" if passed else "failed: " + ",".join(k for k, v in gates.items() if not v)
        return ScreenResult(symbol, passed, score, signals, latest_price, a, reason)

    def screen_universe(
        self, candle_map: dict[str, list[Candle]], markets: dict[str, str] | None = None
    ) -> list[Candidate]:
        """Screen many symbols and return ranked, passing Candidates only.

        ``candle_map``: symbol -> candles. ``markets``: symbol -> market label.
        Bounded to ``claude_max_candidates`` survivors.
        """
        markets = markets or {}
        results: list[ScreenResult] = []
        for symbol, candles in candle_map.items():
            try:
                res = self.run(symbol, candles, market=markets.get(symbol, "KRX"))
            except Exception as exc:  # never let one bad symbol kill the run
                log.warning("screening failed for %s: %s", symbol, exc)
                continue
            if not res.passed:
                log.debug("skip %s (%s)", symbol, res.reason)
                continue
            if res.score < self.s.screen_min_score:
                continue
            results.append(res)

        results.sort(key=lambda r: r.score, reverse=True)
        top = results[: self.s.claude_max_candidates]
        return [
            Candidate(
                symbol=r.symbol,
                market=markets.get(r.symbol, "KRX"),
                price=r.price or 0.0,
                score=r.score,
                signals=r.signals,
                atr=r.atr,
            )
            for r in top
        ]
