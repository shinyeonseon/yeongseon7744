"""Briefing generation tests (mocked screener + VIX)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from tossai.models import Candidate
from tossai.scheduler import briefings


def test_morning_briefing(settings, monkeypatch):
    monkeypatch.setattr(briefings, "get_vix", lambda s: 18.0)
    monkeypatch.setattr(
        briefings, "_screen",
        lambda s: [Candidate(symbol="005930", market="KRX", price=70000.0, score=0.7)],
    )
    monkeypatch.setattr(briefings, "any_market_open", lambda *a, **k: True)
    bs = briefings.generate_morning_briefing(settings)
    text = "".join(str(b) for b in bs)
    assert "005930" in text
    assert "Morning Briefing" in text
    # analysis-only: no order instructions
    assert "place order" not in text.lower()


def test_morning_briefing_survives_screen_failure(settings, monkeypatch):
    monkeypatch.setattr(briefings, "get_vix", lambda s: None)

    def boom(s):
        raise RuntimeError("toss down")

    monkeypatch.setattr(briefings, "_screen", boom)
    monkeypatch.setattr(briefings, "any_market_open", lambda *a, **k: False)
    bs = briefings.generate_morning_briefing(settings)  # must not raise
    assert any(b.get("type") == "header" for b in bs)


def test_weekly_briefing_aggregates_reports(settings, tmp_path, monkeypatch):
    settings.reports_dir = str(tmp_path)
    now = datetime(2026, 6, 15, tzinfo=UTC)
    recent = {
        "generated_at": (now - timedelta(days=1)).isoformat(),
        "universe_size": 5,
        "results": [
            {"candidate": {"symbol": "005930"},
             "recommendation": {"action": "BUY", "confidence": 0.8}},
            {"candidate": {"symbol": "AAPL"},
             "recommendation": {"action": "HOLD", "confidence": 0.5}},
        ],
    }
    old = {
        "generated_at": (now - timedelta(days=30)).isoformat(),
        "universe_size": 5,
        "results": [{"candidate": {"symbol": "ZZZZ"},
                     "recommendation": {"action": "BUY", "confidence": 0.9}}],
    }
    (tmp_path / "recent.json").write_text(json.dumps(recent))
    (tmp_path / "old.json").write_text(json.dumps(old))

    monkeypatch.setattr(briefings, "get_vix", lambda s: 18.0)
    bs = briefings.generate_weekly_briefing(settings, now=now)
    text = "".join(str(b) for b in bs)
    assert "005930" in text
    assert "ZZZZ" not in text  # outside the 7-day window
