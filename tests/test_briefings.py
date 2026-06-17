"""Briefing generation tests (mocked screener + VIX)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from tossai.models import Candidate, Position
from tossai.scheduler import briefings
from tossai.slack import blocks as slack_blocks


def test_morning_briefing(settings, monkeypatch):
    settings.context_macro_enabled = False  # keep the test offline
    monkeypatch.setattr(briefings, "get_vix", lambda s: 18.0)
    monkeypatch.setattr(
        briefings, "_screen",
        lambda s: [Candidate(symbol="005930", market="KRX", price=70000.0, score=0.7)],
    )
    monkeypatch.setattr(briefings, "any_market_open", lambda *a, **k: True)
    bs = briefings.generate_morning_briefing(settings)
    text = "".join(str(b) for b in bs)
    assert "005930" in text
    assert "모닝 브리핑" in text
    # analysis-only: no order instructions
    assert "place order" not in text.lower()


def test_morning_briefing_survives_screen_failure(settings, monkeypatch):
    settings.context_macro_enabled = False
    monkeypatch.setattr(briefings, "get_vix", lambda s: None)

    def boom(s):
        raise RuntimeError("toss down")

    monkeypatch.setattr(briefings, "_screen", boom)
    monkeypatch.setattr(briefings, "any_market_open", lambda *a, **k: False)
    bs = briefings.generate_morning_briefing(settings)  # must not raise
    assert any(b.get("type") == "header" for b in bs)


def test_morning_briefing_blocks_render_macro_and_holdings():
    cand = [Candidate(symbol="NVDA", market="US", price=138.0, score=0.81)]
    holdings = {"count": 2, "avg_pl": 0.42, "lines": ["MU +175% ⚠️TRIM", "TEM -27% HOLD"]}
    bs = slack_blocks.morning_briefing_blocks(
        "US", False, 14.2, 30.0, cand, "2026-06-17",
        macro_line="실업률 4.0%  ·  FOMC D-2", holdings=holdings,
    )
    text = "".join(str(b) for b in bs)
    assert "🌐" in text and "FOMC D-2" in text
    assert "내 포트폴리오" in text and "MU +175% ⚠️TRIM" in text
    assert "+42.0%" in text  # value-weighted P/L
    assert "NVDA" in text


def test_holdings_summary_value_weight_and_advice(settings, tmp_path, monkeypatch):
    settings.reports_dir = str(tmp_path)
    settings.toss_account_seq = "1"
    (tmp_path / "portfolio_2026-06-16_090000.json").write_text(json.dumps(
        {"results": [{"position": {"symbol": "MU"}, "advice": {"action": "TRIM"}}]}
    ))

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_holdings(self):
            return [
                Position(symbol="MU", market="US", quantity=10, avg_price=40,
                         last_price=110, pl_rate=1.75, market_value=1100),
                Position(symbol="TEM", market="US", quantity=5, avg_price=30,
                         last_price=22, pl_rate=-0.27, market_value=110),
            ]

    monkeypatch.setattr("tossai.toss.client.TossClient", lambda s: _FakeClient())
    out = briefings._holdings_summary(settings)
    assert out["count"] == 2
    assert abs(out["avg_pl"] - (1100 * 1.75 + 110 * -0.27) / 1210) < 1e-9
    assert out["lines"][0].startswith("MU +175%")  # sorted by market value desc
    assert "⚠️TRIM" in out["lines"][0]


def test_holdings_summary_none_without_account(settings):
    settings.toss_account_seq = ""
    assert briefings._holdings_summary(settings) is None


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
