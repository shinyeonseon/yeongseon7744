"""Performance metrics over a daily equity curve. Pure, deterministic."""

from __future__ import annotations

import math
from dataclasses import dataclass

_TRADING_DAYS = 252


@dataclass
class PerformanceMetrics:
    periods: int
    total_return: float
    cagr: float
    annual_volatility: float
    sharpe: float
    max_drawdown: float
    win_rate: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "periods": self.periods,
            "total_return": round(self.total_return, 4),
            "cagr": round(self.cagr, 4),
            "annual_volatility": round(self.annual_volatility, 4),
            "sharpe": round(self.sharpe, 3),
            "max_drawdown": round(self.max_drawdown, 4),
            "win_rate": round(self.win_rate, 4),
        }


def compute_metrics(equity: list[float], periods_per_year: int = _TRADING_DAYS) -> PerformanceMetrics:
    """Compute metrics from an equity curve (starts at any positive value)."""
    n = len(equity)
    if n < 2 or equity[0] <= 0:
        return PerformanceMetrics(n, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    total_return = equity[-1] / equity[0] - 1.0
    years = (n - 1) / periods_per_year
    cagr = (equity[-1] / equity[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0

    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, n)]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    std = math.sqrt(var)
    annual_vol = std * math.sqrt(periods_per_year)
    sharpe = (mean / std * math.sqrt(periods_per_year)) if std > 0 else 0.0

    # Max drawdown over the curve.
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = v / peak - 1.0
        max_dd = min(max_dd, dd)

    win_rate = sum(1 for r in rets if r > 0) / len(rets)
    return PerformanceMetrics(
        periods=n, total_return=total_return, cagr=cagr,
        annual_volatility=annual_vol, sharpe=sharpe,
        max_drawdown=max_dd, win_rate=win_rate,
    )
