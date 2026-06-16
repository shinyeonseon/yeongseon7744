"""Score recorded recommendations against subsequent prices.

Direction-adjusted forward return: for a BUY we credit the raw forward return,
for a SELL we credit its negative (a correct SELL = price fell). HOLD is not
scored. A call is a "win" when its direction-adjusted return is positive.
"""

from __future__ import annotations

from tossai.models import Candle
from tossai.performance.models import HorizonStat, PerformanceSummary, RecoRecord

_DIRECTIONAL = {"BUY": 1.0, "SELL": -1.0}


def _entry_index(candles: list[Candle], iso_date: str) -> int | None:
    """First bar on/after the recommendation date."""
    for i, c in enumerate(candles):
        if c.ts.date().isoformat() >= iso_date:
            return i
    return None


def _forward_return(candles: list[Candle], entry: int, horizon: int) -> float | None:
    j = entry + horizon
    if j >= len(candles) or candles[entry].close <= 0:
        return None
    return candles[j].close / candles[entry].close - 1.0


def evaluate(
    records: list[RecoRecord],
    candle_map: dict[str, list[Candle]],
    horizons: tuple[int, ...] = (5, 21, 63),
    primary_horizon: int = 21,
    min_confidence: float = 0.0,
) -> PerformanceSummary:
    directional = [
        r for r in records
        if r.action in _DIRECTIONAL and r.confidence >= min_confidence
    ]
    # Collect direction-adjusted returns per horizon.
    per_h: dict[int, list[float]] = {h: [] for h in horizons}
    per_action: dict[str, list[float]] = {"BUY": [], "SELL": []}
    hi, lo = [], []
    scored = pending = 0

    for r in directional:
        candles = candle_map.get(r.symbol) or []
        entry = _entry_index(candles, r.date) if candles else None
        if entry is None:
            pending += 1
            continue
        sign = _DIRECTIONAL[r.action]
        scored_primary = False
        for h in horizons:
            fr = _forward_return(candles, entry, h)
            if fr is None:
                continue
            adj = sign * fr
            per_h[h].append(adj)
            if h == primary_horizon:
                scored_primary = True
                per_action[r.action].append(adj)
                (hi if r.confidence >= 0.7 else lo).append(adj)
        if scored_primary:
            scored += 1
        else:
            pending += 1

    return PerformanceSummary(
        total=len(records),
        directional=len(directional),
        scored=scored,
        pending=pending,
        primary_horizon=primary_horizon,
        horizons=[_stat(h, per_h[h]) for h in horizons],
        by_action={a: _stat(primary_horizon, per_action[a]) for a in per_action},
        high_conf_avg=_avg(hi),
        low_conf_avg=_avg(lo),
    )


def _stat(horizon: int, vals: list[float]) -> HorizonStat:
    if not vals:
        return HorizonStat(horizon=horizon)
    wins = sum(1 for v in vals if v > 0)
    return HorizonStat(
        horizon=horizon, n=len(vals),
        win_rate=wins / len(vals),
        avg_return=sum(vals) / len(vals),
    )


def _avg(vals: list[float]) -> float | None:
    return sum(vals) / len(vals) if vals else None


def summary_table(s: PerformanceSummary) -> str:
    lines = [
        f"=== Recommendation performance ({s.scored} scored, {s.pending} pending, "
        f"{s.total} logged) ===",
        "direction-adjusted forward return (BUY=+ret, SELL=−ret); win = right direction",
        f"{'HORIZON':<9}{'N':>5}{'WIN%':>8}{'AVG RET':>10}",
    ]
    for h in s.horizons:
        lines.append(f"{str(h.horizon) + 'd':<9}{h.n:>5}{h.win_rate:>7.0%}{h.avg_return:>10.2%}")
    lines.append("")
    for action, st in s.by_action.items():
        lines.append(f"  {action:<5} @{st.horizon}d: n={st.n} win={st.win_rate:.0%} "
                     f"avg={st.avg_return:+.2%}")
    if s.high_conf_avg is not None or s.low_conf_avg is not None:
        hi = f"{s.high_conf_avg:+.2%}" if s.high_conf_avg is not None else "—"
        lo = f"{s.low_conf_avg:+.2%}" if s.low_conf_avg is not None else "—"
        lines.append(f"  confidence@{s.primary_horizon}d:  ≥0.7 {hi}   <0.7 {lo}  "
                     "(higher should beat lower if confidence is informative)")
    return "\n".join(lines)
