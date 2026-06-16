"""Position-stop risk evaluator (hard stop + ATR trailing stop)."""

from __future__ import annotations

from helpers import make_candles
from tossai.models import Position
from tossai.risk.evaluators import evaluate_position_stop
from tossai.risk.models import RiskKind, Severity

PARAMS = dict(stop_loss_pct=0.15, atr_mult=2.5, atr_period=14, high_lookback=63)


def test_hard_stop_triggers_on_big_loss():
    pos = Position(symbol="X", market="US", avg_price=100.0, last_price=80.0, pl_rate=-0.20)
    alert = evaluate_position_stop(pos, [], **PARAMS)
    assert alert is not None
    assert alert.kind == RiskKind.POSITION_STOP and alert.severity == Severity.CRITICAL
    assert "손절" in alert.message and alert.symbol == "X"


def test_no_alert_when_in_profit_and_in_trend():
    rising = make_candles([100.0 + i for i in range(80)])  # last == recent high
    pos = Position(symbol="UP", market="US", avg_price=50.0, last_price=179.0, pl_rate=2.58)
    assert evaluate_position_stop(pos, rising, **PARAMS) is None


def test_atr_trailing_stop_triggers_on_trend_break():
    # rise to ~180 then sharply drop well below recent high − 2.5*ATR
    prices = [100.0 + i for i in range(70)] + [165.0, 150.0, 135.0, 120.0, 110.0]
    candles = make_candles(prices)
    pos = Position(symbol="BRK", market="US", avg_price=60.0, last_price=110.0, pl_rate=0.83)
    alert = evaluate_position_stop(pos, candles, **PARAMS)
    assert alert is not None
    assert alert.severity == Severity.WARNING and "ATR" in alert.message


def test_hard_stop_takes_priority_over_atr():
    prices = [100.0 + i for i in range(70)] + [165.0, 150.0, 135.0, 120.0, 110.0]
    pos = Position(symbol="X", market="US", avg_price=200.0, last_price=110.0, pl_rate=-0.45)
    alert = evaluate_position_stop(pos, make_candles(prices), **PARAMS)
    assert alert.severity == Severity.CRITICAL  # hard stop wins


def test_disabled_thresholds_yield_no_alert():
    pos = Position(symbol="X", market="US", avg_price=100.0, last_price=80.0, pl_rate=-0.20)
    assert evaluate_position_stop(pos, [], stop_loss_pct=0.0, atr_mult=0.0) is None
