"""Piotroski F-Score — best-effort "lite" version.

The full 9-point F-Score needs year-over-year financial-statement detail that
free sources (pykrx/yfinance) don't reliably expose. This computes the subset
that IS available from normalized fundamentals (positive earnings, positive ROE,
profitability strength) and is clearly labeled partial. Symbols without enough
data skip.
"""

from __future__ import annotations

from tossai.fundamentals.models import Fundamentals
from tossai.screening.strategies.base import StrategyResult
from tossai.screening.strategies.fundamental_base import FundamentalStrategy

# Number of checks this lite version can evaluate from available fields.
_MAX_LITE = 4


class PiotroskiLiteStrategy(FundamentalStrategy):
    name = "piotroski"
    bucket = "value"

    def evaluate_fundamentals(
        self, symbol: str, fund: Fundamentals, price: float
    ) -> StrategyResult | None:
        checks: dict[str, bool] = {}
        if fund.eps is not None:
            checks["positive_eps"] = fund.eps > 0
        if fund.roe is not None:
            checks["positive_roe"] = fund.roe > 0
            checks["strong_roe"] = fund.roe >= 0.10
        if fund.per is not None:
            checks["positive_earnings"] = fund.per > 0

        if not checks:
            return self._skip(symbol, "no fundamentals for F-score")

        score_points = sum(1 for ok in checks.values() if ok)
        # Scale the lite score to the conventional 0–9 range for the gate.
        scaled = round(score_points / len(checks) * 9)
        passed = scaled >= self.s.piotroski_min_score
        score = score_points / _MAX_LITE if passed else 0.0

        return StrategyResult(
            symbol=symbol, score=round(min(score, 1.0), 4),
            signals={
                "f_score_lite": score_points,
                "checks_available": len(checks),
                "scaled_0_9": scaled,
                **{k: v for k, v in checks.items()},
                "note": "partial F-score — limited free fundamentals",
            },
            price=price, atr=None, bucket=self.bucket, strategy=self.name,
            passed=passed,
            reason="" if passed else f"f_score_lite {scaled}<{self.s.piotroski_min_score}",
        )
