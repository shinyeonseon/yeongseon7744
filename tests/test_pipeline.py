"""End-to-end orchestrator test with all externals mocked."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from helpers import make_uptrend
from tossai.analysis.claude_engine import ClaudeEngine
from tossai.models import Action
from tossai.pipeline.orchestrator import Orchestrator


class _FakeTossClient:
    """Returns uptrend candles for every symbol."""

    def __init__(self):
        self._candles = make_uptrend(n=40)

    def get_candles(self, symbol, interval="1d", count=120):
        return self._candles


def _fake_anthropic():
    block = SimpleNamespace(
        type="tool_use", name="submit_recommendation",
        input={"action": "BUY", "confidence": 0.7, "target_price": 130.0,
               "rationale": "uptrend", "risks": ["macro"], "time_horizon": "weeks"},
    )
    usage = SimpleNamespace(input_tokens=50, output_tokens=20)
    resp = SimpleNamespace(content=[block], usage=usage)

    class _Client:
        def __init__(self):
            self.messages = SimpleNamespace(create=lambda **kw: resp)

    return _Client()


@pytest.fixture(autouse=True)
def _universe(tmp_path, settings, monkeypatch):
    uni = tmp_path / "universe.yaml"
    uni.write_text("KRX:\n  - {symbol: '005930', name: 'Samsung'}\n  - '000660'\n")
    settings.universe_file = str(uni)
    settings.reports_dir = str(tmp_path / "reports")
    return settings


def test_run_once_end_to_end(settings, monkeypatch):
    engine = ClaudeEngine(settings, client=_fake_anthropic())
    orch = Orchestrator(settings, client=_FakeTossClient(), engine=engine)

    # Force market open so dispatch runs; ConsoleNotifier prints harmlessly.
    monkeypatch.setattr(
        "tossai.pipeline.orchestrator.any_market_open", lambda *a, **k: True
    )
    report = orch.run_once()

    assert report.universe_size == 2
    assert report.screened_count >= 1
    assert all(r.recommendation.action == Action.BUY for r in report.results)
    assert report.estimated_cost_usd >= 0


def test_screen_only_no_claude(settings):
    orch = Orchestrator(settings, client=_FakeTossClient())
    candidates = orch.screen_only()
    assert len(candidates) >= 1
