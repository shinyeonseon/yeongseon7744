"""Walk-forward backtest over the strategy ensemble.

No look-ahead: at bar ``k`` the strategy only sees candles up to ``k``; the
portfolio then earns the ``k → k+1`` return. Rebalances every ``rebalance_days``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tossai.backtest.metrics import PerformanceMetrics, compute_metrics
from tossai.logging_setup import get_logger
from tossai.models import Candle
from tossai.screening.allocation import inverse_vol_weights

log = get_logger(__name__)


@dataclass
class BacktestResult:
    equity: list[float]
    metrics: PerformanceMetrics
    benchmark_equity: list[float]
    benchmark_metrics: PerformanceMetrics
    rebalances: list[tuple[int, list[str]]] = field(default_factory=list)
    symbols: int = 0
    cost_bps: float = 0.0

    def summary(self) -> str:
        m, b = self.metrics.as_dict(), self.benchmark_metrics.as_dict()
        return (
            f"Backtest: {self.symbols} symbols, {self.metrics.periods} days, "
            f"{len(self.rebalances)} rebalances, cost {self.cost_bps:.0f}bps/turnover\n"
            f"  strategy : CAGR {m['cagr']:.1%}  Sharpe {m['sharpe']}  "
            f"MaxDD {m['max_drawdown']:.1%}  win {m['win_rate']:.1%}\n"
            f"  buy&hold : CAGR {b['cagr']:.1%}  Sharpe {b['sharpe']}  "
            f"MaxDD {b['max_drawdown']:.1%}"
        )


def _aligned_closes(candle_map: dict[str, list[Candle]]) -> tuple[dict[str, list[float]], int]:
    """Truncate every symbol to a common length (last L bars) and return closes."""
    lengths = [len(c) for c in candle_map.values() if c]
    if not lengths:
        return {}, 0
    length = min(lengths)
    closes = {sym: [c.close for c in candles[-length:]] for sym, candles in candle_map.items() if candles}
    return closes, length


def walk_forward_backtest(
    candle_map: dict[str, list[Candle]],
    strategy,
    markets: dict[str, str] | None = None,
    *,
    rebalance_days: int = 21,
    top_n: int = 5,
    weighting: str = "equal",
    risk_parity_lookback: int = 63,
    cost_bps: float = 0.0,
) -> BacktestResult:
    markets = markets or {}
    closes, length = _aligned_closes(candle_map)
    aligned = {sym: candles[-length:] for sym, candles in candle_map.items() if candles}
    start = max(int(getattr(strategy, "required_history", 2)), 2)
    cost_rate = max(0.0, cost_bps) / 10_000.0  # per unit of turnover traded

    if length - 1 <= start:
        empty = compute_metrics([1.0])
        return BacktestResult([1.0], empty, [1.0], empty, [], len(closes))

    equity = [1.0]
    bench = [1.0]
    holdings: list[str] = []
    weights: dict[str, float] = {}
    prev_weights: dict[str, float] = {}
    rebalances: list[tuple[int, list[str]]] = []
    bench_syms = list(closes.keys())
    pending_cost = 0.0           # strategy turnover cost, applied to the next bar
    bench_pending = cost_rate    # benchmark pays its one initial purchase cost

    step = 0
    for k in range(start, length - 1):
        if step % rebalance_days == 0:
            sliced = {sym: candles[: k + 1] for sym, candles in aligned.items()}
            candidates = strategy.screen_universe(sliced, markets)
            holdings = [c.symbol for c in candidates[:top_n]]
            weights = _weights(holdings, sliced, weighting, risk_parity_lookback)
            # Cost on turnover (sum of |Δweight|), charged forward so the $1 base
            # is preserved and the drag is visible in returns.
            turnover = sum(
                abs(weights.get(s, 0.0) - prev_weights.get(s, 0.0))
                for s in set(weights) | set(prev_weights)
            )
            pending_cost += turnover * cost_rate
            prev_weights = weights
            rebalances.append((k, list(holdings)))

        eq_ret = _portfolio_return(holdings, weights, closes, k)
        equity.append(equity[-1] * (1.0 - pending_cost) * (1.0 + eq_ret))
        pending_cost = 0.0
        bench.append(bench[-1] * (1.0 - bench_pending) * (1.0 + _equal_return(bench_syms, closes, k)))
        bench_pending = 0.0
        step += 1

    return BacktestResult(
        equity=equity, metrics=compute_metrics(equity),
        benchmark_equity=bench, benchmark_metrics=compute_metrics(bench),
        rebalances=rebalances, symbols=len(closes), cost_bps=cost_bps,
    )


def _weights(holdings, sliced, weighting, lookback) -> dict[str, float]:
    if not holdings:
        return {}
    if weighting == "inverse_vol":
        w = inverse_vol_weights({s: sliced[s] for s in holdings if s in sliced}, lookback)
        if w:
            total = sum(w.get(s, 0.0) for s in holdings)
            if total > 0:
                return {s: w.get(s, 0.0) / total for s in holdings}
    eq = 1.0 / len(holdings)
    return {s: eq for s in holdings}


def _portfolio_return(holdings, weights, closes, k) -> float:
    r = 0.0
    for s in holdings:
        series = closes.get(s)
        if series and k + 1 < len(series) and series[k] > 0:
            r += weights.get(s, 0.0) * (series[k + 1] / series[k] - 1.0)
    return r


def _equal_return(symbols, closes, k) -> float:
    rets = []
    for s in symbols:
        series = closes.get(s)
        if series and k + 1 < len(series) and series[k] > 0:
            rets.append(series[k + 1] / series[k] - 1.0)
    return sum(rets) / len(rets) if rets else 0.0
