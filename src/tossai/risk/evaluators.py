"""Risk evaluators — pure functions over already-fetched data.

Each returns a ``RiskAlert`` or ``None``. They never raise on bad/missing data
(callers pass ``None`` VIX or short candle lists) so a flaky data source can't
crash or spam the scheduler.
"""

from __future__ import annotations

from tossai.models import Candle, Position
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


def evaluate_position_stop(
    position: Position,
    candles: list[Candle],
    *,
    stop_loss_pct: float,
    atr_mult: float,
    atr_period: int = 14,
    high_lookback: int = 63,
) -> RiskAlert | None:
    """Stop alert for a held position. Two triggers, most-severe wins:

    A) hard stop — unrealized P&L at/below ``-stop_loss_pct`` (fraction) from cost.
    B) ATR trailing stop — price falls below ``recent_high - atr_mult*ATR`` (a
       trend break that protects open gains even while still in profit).
    """
    last = position.last_price
    # A) hard stop from average cost.
    if (stop_loss_pct > 0 and position.pl_rate is not None
            and position.pl_rate <= -abs(stop_loss_pct)):
        return RiskAlert(
            kind=RiskKind.POSITION_STOP,
            severity=Severity.CRITICAL,
            message=(f"손절 도달: 평단 대비 *{position.pl_rate * 100:+.1f}%* "
                     f"(기준 −{abs(stop_loss_pct) * 100:.0f}%)."),
            symbol=position.symbol,
            value=position.pl_rate,
            threshold=-abs(stop_loss_pct),
        )
    # B) ATR trailing stop (needs candles).
    if atr_mult > 0 and last and len(candles) >= atr_period + 1:
        from tossai.screening import indicators as ind
        from tossai.screening.screener import candles_to_df

        df = candles_to_df(candles)
        atr = float(ind.atr(df, atr_period).iloc[-1])
        recent_high = float(df["high"].iloc[-high_lookback:].max())
        stop_level = recent_high - atr_mult * atr
        if atr > 0 and last < stop_level:
            return RiskAlert(
                kind=RiskKind.POSITION_STOP,
                severity=Severity.WARNING,
                message=(f"ATR 추세 이탈: 현재가 {last:.2f} < 최근고점 {recent_high:.2f} "
                         f"− {atr_mult:g}×ATR({atr:.2f}) = {stop_level:.2f}."),
                symbol=position.symbol,
                value=last,
                threshold=stop_level,
            )
    return None
