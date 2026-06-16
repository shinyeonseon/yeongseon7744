"""Relative Strength vs the market.

Classic momentum-quality lens (the "RS" in CAN SLIM): is this name beating the
market, not just rising? We use each market's own universe as the benchmark —
a symbol's lookback return minus the equal-weight average return of every symbol
in the same market. Positive = outperforming. Cross-sectional, so it overrides
``evaluate_all`` to compute the benchmark once across all symbols.
"""

from __future__ import annotations

from tossai.models import Candle
from tossai.screening.strategies.base import BaseStrategy, StrategyResult


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


class RelativeStrengthStrategy(BaseStrategy):
    name = "relative_strength"
    bucket = "long"

    def __init__(self, settings):
        super().__init__(settings)
        self.required_history = settings.rs_lookback + 2

    # Per-symbol path is unused (cross-sectional), but the ABC requires it.
    def evaluate(self, symbol: str, candles: list[Candle], market: str) -> StrategyResult | None:
        return None

    def evaluate_all(
        self, candle_map: dict[str, list[Candle]], markets: dict[str, str] | None = None
    ) -> list[StrategyResult]:
        markets = markets or {}
        lookback = self.s.rs_lookback
        # 1) lookback return per symbol (skip too-short / bad data).
        rets: dict[str, tuple[str, float, float]] = {}  # symbol -> (market, ret, price)
        for symbol, candles in candle_map.items():
            if len(candles) < lookback + 2:
                continue
            base = candles[-1 - lookback].close
            last = candles[-1].close
            if base <= 0:
                continue
            rets[symbol] = (markets.get(symbol, "KRX"), last / base - 1.0, last)

        # 2) benchmark = equal-weight average return within each market.
        by_market: dict[str, list[float]] = {}
        for _, (mk, r, _price) in rets.items():
            by_market.setdefault(mk, []).append(r)
        bench = {mk: sum(v) / len(v) for mk, v in by_market.items() if v}

        # 3) relative strength = symbol return − market return; outperformers pass.
        out: list[StrategyResult] = []
        cap = self.s.rs_score_cap or 0.30
        for symbol, (mk, r, price) in rets.items():
            rel = r - bench.get(mk, 0.0)
            if rel <= self.s.rs_min_rel:
                continue
            out.append(StrategyResult(
                symbol=symbol, score=round(_clip(rel / cap), 4),
                signals={
                    "rs_return": round(r, 4),
                    "market_return": round(bench.get(mk, 0.0), 4),
                    "rs_vs_market": round(rel, 4),
                    "note": f"{lookback}d return vs {mk} universe avg",
                },
                price=price, atr=None, bucket=self.bucket, strategy=self.name,
                passed=True, reason="",
            ))
        return out
