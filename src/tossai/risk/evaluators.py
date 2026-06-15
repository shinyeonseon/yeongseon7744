"""Risk evaluators — pure functions over already-fetched data.

Each returns a ``RiskAlert`` or ``None``. They never raise on bad/missing data
(callers pass ``None`` VIX or short candle lists) so a flaky data source can't
crash or spam the scheduler.
"""

from __future__ import annotations

from tossai.models import Candle
from tossai.risk.models import RiskAlert, RiskKind, Severity


def evaluate_blackswan(vix: float | None, threshold: float) -> RiskAlert | None:
    if vix is None:
        return None
    if vix >= threshold:
        return RiskAlert(
            kind=RiskKind.BLACKSWAN,
            severity=Severity.CRITICAL,
            message=f"VIX *{vix:.2f}* ≥ threshold {threshold:.1f} — elevated market stress.",
            value=vix,
            threshold=threshold,
        )
    return None


def evaluate_gap_down(
    symbol: str, candles: list[Candle], pct_threshold: float
) -> RiskAlert | None:
    """Alert if the latest bar's open gapped down vs the prior close by >= pct."""
    if len(candles) < 2:
        return None
    prev_close = candles[-2].close
    latest_open = candles[-1].open
    if prev_close <= 0:
        return None
    gap_pct = (latest_open - prev_close) / prev_close * 100.0
    if gap_pct <= -abs(pct_threshold):
        return RiskAlert(
            kind=RiskKind.GAP_DOWN,
            severity=Severity.WARNING,
            message=(
                f"Gapped down *{gap_pct:.1f}%* at open "
                f"({prev_close:.2f} → {latest_open:.2f})."
            ),
            symbol=symbol,
            value=gap_pct,
            threshold=-abs(pct_threshold),
        )
    return None
