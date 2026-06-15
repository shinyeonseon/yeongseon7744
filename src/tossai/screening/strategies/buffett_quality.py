"""Buffett-style quality-at-a-reasonable-price.

Favors durable profitability (high ROE) bought at a sane multiple (moderate
P/E), with a low-leverage preference when debt data is available.
"""

from __future__ import annotations

from tossai.fundamentals.models import Fundamentals
from tossai.screening.strategies.base import StrategyResult
from tossai.screening.strategies.fundamental_base import FundamentalStrategy, clip


class BuffettQualityStrategy(FundamentalStrategy):
    name = "buffett_quality"
    bucket = "value"

    def evaluate_fundamentals(
        self, symbol: str, fund: Fundamentals, price: float
    ) -> StrategyResult | None:
        s = self.s
        if fund.roe is None or fund.per is None or fund.per <= 0:
            return self._skip(symbol, "missing ROE/PER")

        roe_ok = fund.roe >= s.buffett_min_roe
        pe_ok = fund.per <= s.buffett_max_pe
        # Low-leverage preference only when debt data exists (don't penalize gaps).
        debt_ok = fund.debt_to_equity is None or fund.debt_to_equity <= 200.0
        passed = roe_ok and pe_ok and debt_ok

        # Quality (ROE) blended with value (earnings yield).
        ey = fund.earnings_yield or 0.0
        score = (0.6 * clip(fund.roe / 0.30) + 0.4 * clip(ey / 0.10)) if passed else 0.0
        reasons = [n for n, ok in (
            ("roe", roe_ok), ("pe", pe_ok), ("debt", debt_ok)) if not ok]
        return StrategyResult(
            symbol=symbol, score=round(score, 4),
            signals={
                "roe": round(fund.roe, 4), "per": fund.per,
                "earnings_yield": round(ey, 4),
                "debt_to_equity": fund.debt_to_equity,
            },
            price=price, atr=None, bucket=self.bucket, strategy=self.name,
            passed=passed, reason="" if passed else "failed: " + ",".join(reasons),
        )
