"""Block Kit formatter tests."""

from __future__ import annotations

from tossai.models import (
    Action,
    AnalyzedCandidate,
    Candidate,
    Recommendation,
)
from tossai.output.report import Report
from tossai.risk.models import RiskAlert, RiskKind, Severity
from tossai.slack import blocks


def _report(action=Action.BUY, conf=0.8):
    cand = Candidate(symbol="005930", market="KRX", price=70000.0, score=0.8,
                     signals={"rsi": 55})
    rec = Recommendation(action=action, confidence=conf, target_price=80000.0,
                         rationale="uptrend with volume", risks=["macro"])
    return Report(
        market="KRX", market_open=True, universe_size=5, screened_count=1,
        results=[AnalyzedCandidate(candidate=cand, recommendation=rec)],
        estimated_cost_usd=0.01,
    )


def _has_disclaimer(bs: list[dict]) -> bool:
    return any(b.get("type") == "context" for b in bs)


def test_report_blocks_structure():
    bs = blocks.report_blocks(_report(), min_confidence=0.6)
    assert bs[0]["type"] == "header"
    assert _has_disclaimer(bs)
    # the recommendation line mentions the symbol and action
    text = "".join(str(b) for b in bs)
    assert "005930" in text and "BUY" in text


def test_report_blocks_empty():
    rep = Report(market="US", market_open=False, universe_size=0, screened_count=0)
    bs = blocks.report_blocks(rep)
    text = "".join(str(b) for b in bs)
    assert "No candidates" in text
    assert _has_disclaimer(bs)


def test_screen_blocks():
    cands = [Candidate(symbol="AAPL", market="US", price=190.0, score=0.5)]
    bs = blocks.screen_blocks(cands)
    assert "AAPL" in "".join(str(b) for b in bs)
    assert _has_disclaimer(bs)


def test_morning_briefing_vix_bands():
    cands = [Candidate(symbol="005930", market="KRX", price=70000.0, score=0.7)]
    bs = blocks.morning_briefing_blocks("KRX", True, 35.0, 30.0, cands, "2026-06-15")
    text = "".join(str(b) for b in bs)
    assert "stressed" in text  # vix above threshold
    assert "005930" in text


def test_weekly_briefing():
    bs = blocks.weekly_briefing_blocks(
        "2026-06-15", 5, {"BUY": 3, "HOLD": 2}, [("005930", 4)], 0.72, 18.0, 30.0
    )
    text = "".join(str(b) for b in bs)
    assert "005930" in text and "calm" in text


def test_risk_alert_blocks_no_action_words():
    alert = RiskAlert(
        kind=RiskKind.BLACKSWAN, severity=Severity.CRITICAL,
        message="VIX 52.0 >= 30.0", value=52.0, threshold=30.0,
    )
    bs = blocks.risk_alert_blocks(alert)
    text = "".join(str(b) for b in bs).lower()
    assert "blackswan" in text
    # analysis-only: must not instruct an order
    assert "place order" not in text and "buy now" not in text
    assert _has_disclaimer(bs)


def test_help_and_status():
    assert blocks.help_blocks()[0]["type"] == "header"
    sb = blocks.status_blocks({"market": "KRX", "slack_enabled": True})
    assert "market" in "".join(str(b) for b in sb)


def test_truncate_long_rationale():
    long = "x" * 500
    rep = _report()
    rep.results[0].recommendation.rationale = long
    bs = blocks.report_blocks(rep)
    text = "".join(str(b) for b in bs)
    assert "…" in text  # truncated
