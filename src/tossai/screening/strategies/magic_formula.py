"""Joel Greenblatt's Magic Formula.

Ranks the universe by earnings yield (E/P) and by return on capital (approximated
here with ROE), then combines the two ranks — companies that are both cheap and
profitable rise to the top. This is inherently cross-sectional, so it overrides
``evaluate_all`` to rank across all symbols at once.
"""

from __future__ import annotations

from tossai.fundamentals.models import Fundamentals
from tossai.logging_setup import get_logger
from tossai.models import Candle
from tossai.screening.strategies.base import StrategyResult
from tossai.screening.strategies.fundamental_base import FundamentalStrategy, clip

log = get_logger(__name__)


class MagicFormulaStrategy(FundamentalStrategy):
    name = "magic_formula"
    bucket = "value"

    # Unused (we override evaluate_all), but required by the ABC.
    def evaluate_fundamentals(
        self, symbol: str, fund: Fundamentals, price: float
    ) -> StrategyResult | None:
        return None

    def evaluate_all(
        self, candle_map: dict[str, list[Candle]], markets: dict[str, str] | None = None
    ) -> list[StrategyResult]:
        markets = markets or {}
        if self.provider is None:
            return []

        rows = []  # (symbol, earnings_yield, roc, price, fund)
        for symbol, candles in candle_map.items():
            try:
                fund = self.provider.get(symbol, markets.get(symbol, "KRX"))
            except Exception as exc:
                log.warning("magic_formula fundamentals failed for %s: %s", symbol, exc)
                continue
            if fund is None:
                continue
            ey = fund.earnings_yield
            roc = fund.roe  # approximation of return on capital
            if ey is None or roc is None or ey <= 0:
                continue
            price = float(candles[-1].close) if candles else 0.0
            rows.append((symbol, ey, roc, price, fund))

        n = len(rows)
        if n == 0:
            return []
        if n == 1:
            sym, ey, roc, price, fund = rows[0]
            return [self._result(sym, ey, roc, price, fund, score=clip(ey / 0.10))]

        # Rank: 0 = best. Higher EY better, higher ROC better.
        ey_rank = {r[0]: i for i, r in enumerate(sorted(rows, key=lambda x: x[1], reverse=True))}
        roc_rank = {r[0]: i for i, r in enumerate(sorted(rows, key=lambda x: x[2], reverse=True))}

        out: list[StrategyResult] = []
        worst = 2 * (n - 1)
        for sym, ey, roc, price, fund in rows:
            combined = ey_rank[sym] + roc_rank[sym]
            score = 1.0 - combined / worst  # best combined rank → 1.0
            out.append(self._result(sym, ey, roc, price, fund, score=clip(score)))
        return out

    def _result(self, symbol, ey, roc, price, fund, score) -> StrategyResult:
        return StrategyResult(
            symbol=symbol, score=round(score, 4),
            signals={
                "earnings_yield": round(ey, 4),
                "return_on_capital": round(roc, 4),
                "per": fund.per,
                "note": "ROC approximated by ROE",
            },
            price=price, atr=None, bucket=self.bucket, strategy=self.name,
            passed=True, reason="",
        )
