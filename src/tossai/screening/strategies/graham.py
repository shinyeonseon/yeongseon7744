"""Benjamin Graham defensive value.

Gates: low P/E, low P/B, the Graham product (P/E × P/B ≤ 22.5), and price at or
below the Graham number sqrt(22.5 × EPS × BPS). Cheaper (lower combined multiple)
scores higher.
"""

from __future__ import annotations

from math import sqrt

from tossai.fundamentals.models import Fundamentals
from tossai.screening.strategies.base import StrategyResult
from tossai.screening.strategies.fundamental_base import FundamentalStrategy, clip


class GrahamValueStrategy(FundamentalStrategy):
    name = "graham"
    bucket = "value"

    def evaluate_fundamentals(
        self, symbol: str, fund: Fundamentals, price: float
    ) -> StrategyResult | None:
        s = self.s
        if fund.per is None or fund.pbr is None or fund.per <= 0 or fund.pbr <= 0:
            return self._skip(symbol, "missing PER/PBR")

        product = fund.per * fund.pbr
        graham_number = None
        below_graham = True
        if fund.eps is not None and fund.bps is not None and fund.eps > 0 and fund.bps > 0:
            graham_number = sqrt(22.5 * fund.eps * fund.bps)
            below_graham = price <= graham_number if price > 0 else True

        pe_ok = fund.per <= s.graham_max_pe
        pb_ok = fund.pbr <= s.graham_max_pb
        product_ok = product <= 22.5
        passed = pe_ok and pb_ok and product_ok and below_graham

        # Cheaper product → higher score (22.5 maps to 0, 0 maps to 1).
        score = clip(1.0 - product / 22.5) if passed else 0.0
        reasons = [n for n, ok in (
            ("pe", pe_ok), ("pb", pb_ok), ("product", product_ok),
            ("graham_number", below_graham)) if not ok]
        return StrategyResult(
            symbol=symbol, score=round(score, 4),
            signals={
                "per": fund.per, "pbr": fund.pbr, "pe_pb_product": round(product, 2),
                "graham_number": round(graham_number, 2) if graham_number else None,
                "below_graham_number": below_graham,
            },
            price=price, atr=None, bucket=self.bucket, strategy=self.name,
            passed=passed, reason="" if passed else "failed: " + ",".join(reasons),
        )
