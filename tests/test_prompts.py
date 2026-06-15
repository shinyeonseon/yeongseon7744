"""Prompt payload includes strategy/bucket context."""

from __future__ import annotations

import json

from tossai.analysis.prompts import build_user_message
from tossai.models import Candidate


def test_user_message_includes_strategy_context():
    cand = Candidate(
        symbol="005930", market="KRX", price=70000.0, score=0.8,
        signals={"rsi": 55}, strategy="dual_momentum", bucket="long",
        flagged_by=["dual_momentum", "trend_breakout"],
    )
    msg = build_user_message(cand)
    # extract the JSON block
    payload = json.loads(msg.split("```json")[1].split("```")[0])
    assert payload["strategy"] == "dual_momentum"
    assert payload["bucket"] == "long"
    assert payload["flagged_by"] == ["dual_momentum", "trend_breakout"]
    assert payload["technical_signals"]["rsi"] == 55
