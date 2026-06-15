"""Walk-forward backtest over the strategy ensemble.

No look-ahead: at bar ``k`` the strategy only sees candles up to ``k``; the
portfolio then earns the ``k → k+1`` return. Rebalances every ``rebalance_days``.
"""

from __future__ import annotations

import math
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
    trend_filter: bool = False
    trend_ma: int = 0
    avg_exposure: float = 1.0
    vol_target: float = 0.0

    def summary(self) -> str:
        m, b = self.metrics.as_dict(), self.benchmark_metrics.as_dict()
        if self.trend_filter:
            tf = f"trend-filter MA{self.trend_ma}"
        else:
            tf = "trend-filter off"
        vt = f", voltgt {self.vol_target:.0%}" if self.vol_target > 0 else ""
        return (
            f"Backtest: {self.symbols} symbols, {self.metrics.periods} days, "
            f"{len(self.rebalances)} rebalances, cost {self.cost_bps:.0f}bps/turnover, "
            f"{tf}{vt}, exposure {self.avg_exposure:.0%}\n"
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


def _ma_series(series: list[float], window: int) -> list[float | None]:
    """Trailing simple moving average; None until ``window`` bars are available."""
    out: list[float | None] = []
    running = 0.0
    for i, v in enumerate(series):
        running += v
        if i >= window:
            running -= series[i - window]
        out.append(running / window if i >= window - 1 else None)
    return out


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
    trend_filter: bool = False,
    trend_ma: int = 200,
    vol_target: float = 0.0,
    vol_lookback: int = 20,
) -> BacktestResult:
    markets = markets or {}
    closes, length = _aligned_closes(candle_map)
    aligned = {sym: candles[-length:] for sym, candles in candle_map.items() if candles}
    start = max(int(getattr(strategy, "required_history", 2)), 2)
    cost_rate = max(0.0, cost_bps) / 10_000.0  # per unit of turnover traded
    # Per-symbol trailing MA, precomputed once. A held symbol only earns its return
    # while close[k] > ma[k]; below trend its weight sits in cash (return 0).
    ma_map = {s: _ma_series(c, trend_ma) for s, c in closes.items()} if trend_filter else None

    if length - 1 <= start:
        empty = compute_metrics([1.0])
        return BacktestResult([1.0], empty, [1.0], empty, [], len(closes),
                              cost_bps, trend_filter, trend_ma, 1.0, vol_target)

    equity = [1.0]
    bench = [1.0]
    holdings: list[str] = []
    weights: dict[str, float] = {}
    prev_weights: dict[str, float] = {}
    rebalances: list[tuple[int, list[str]]] = []
    bench_syms = list(closes.keys())
    pending_cost = 0.0           # strategy turnover cost, applied to the next bar
    bench_pending = cost_rate    # benchmark pays its one initial purchase cost
    exposure_sum = 0.0           # invested fraction each bar (vs cash), for averaging
    recent_rets: list[float] = []  # realized strategy returns, for vol targeting

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

        eq_ret, invested = _portfolio_return(holdings, weights, closes, k, ma_map)
        # Volatility target: scale total exposure so the portfolio's own trailing
        # realized vol stays near vol_target. Uses only past returns (no look-ahead);
        # the spare weight sits in cash. Stacks multiplicatively with the trend filter.
        scale = _vol_scale(recent_rets, vol_target, vol_lookback)
        eq_ret *= scale
        invested *= scale
        recent_rets.append(eq_ret)
        exposure_sum += invested
        equity.append(equity[-1] * (1.0 - pending_cost) * (1.0 + eq_ret))
        pending_cost = 0.0
        bench.append(bench[-1] * (1.0 - bench_pending) * (1.0 + _equal_return(bench_syms, closes, k)))
        bench_pending = 0.0
        step += 1

    bars = max(len(equity) - 1, 1)
    return BacktestResult(
        equity=equity, metrics=compute_metrics(equity),
        benchmark_equity=bench, benchmark_metrics=compute_metrics(bench),
        rebalances=rebalances, symbols=len(closes), cost_bps=cost_bps,
        trend_filter=trend_filter, trend_ma=trend_ma,
        avg_exposure=exposure_sum / bars, vol_target=vol_target,
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


def _portfolio_return(holdings, weights, closes, k, ma_map=None) -> tuple[float, float]:
    """Return (weighted portfolio return, invested fraction) for bar k → k+1.

    With a trend filter (``ma_map`` provided), a holding contributes only while
    its close is above its trailing MA; otherwise that weight sits in cash (0%
    return) and is excluded from the invested fraction.
    """
    r = 0.0
    invested = 0.0
    for s in holdings:
        series = closes.get(s)
        if not (series and k + 1 < len(series) and series[k] > 0):
            continue
        if ma_map is not None:
            ma = ma_map.get(s)
            ma_k = ma[k] if ma and k < len(ma) else None
            if ma_k is None or series[k] <= ma_k:
                continue  # below trend → hold as cash
        w = weights.get(s, 0.0)
        r += w * (series[k + 1] / series[k] - 1.0)
        invested += w
    return r, invested


def _vol_scale(recent_rets: list[float], vol_target: float, lookback: int,
               periods_per_year: int = 252) -> float:
    """Exposure multiplier so trailing realized vol ≈ ``vol_target`` (annualized).

    Returns 1.0 when targeting is off, history is too short, or realized vol is
    already at/under target. Caps at 1.0 (never levers up).
    """
    if vol_target <= 0 or len(recent_rets) < lookback:
        return 1.0
    window = recent_rets[-lookback:]
    mean = sum(window) / len(window)
    var = sum((r - mean) ** 2 for r in window) / len(window)
    realized = math.sqrt(var) * math.sqrt(periods_per_year)
    if realized <= 0:
        return 1.0
    return min(1.0, vol_target / realized)


def _equal_return(symbols, closes, k) -> float:
    rets = []
    for s in symbols:
        series = closes.get(s)
        if series and k + 1 < len(series) and series[k] > 0:
            rets.append(series[k + 1] / series[k] - 1.0)
    return sum(rets) / len(rets) if rets else 0.0
