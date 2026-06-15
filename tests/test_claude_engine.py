"""Claude engine tests with a mocked Anthropic client."""

from __future__ import annotations

from types import SimpleNamespace

from tossai.analysis.claude_engine import ClaudeEngine
from tossai.models import Action, Candidate


def _fake_response(tool_input: dict, in_tok: int = 100, out_tok: int = 50):
    block = SimpleNamespace(type="tool_use", name="submit_recommendation", input=tool_input)
    usage = SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok)
    return SimpleNamespace(content=[block], usage=usage)


class _FakeClient:
    def __init__(self, response):
        self._response = response
        self.calls = 0

        class _Messages:
            def __init__(outer):
                outer._parent = self

            def create(outer, **kwargs):
                self.calls += 1
                self.last_kwargs = kwargs
                return self._response

        self.messages = _Messages()


def _candidate():
    return Candidate(symbol="005930", market="KRX", price=70000.0, score=0.8,
                     signals={"rsi": 55, "uptrend": True})


def test_analyze_parses_recommendation(settings):
    resp = _fake_response(
        {"action": "BUY", "confidence": 0.75, "target_price": 80000,
         "rationale": "uptrend with volume", "risks": ["macro"], "time_horizon": "weeks"}
    )
    engine = ClaudeEngine(settings, client=_FakeClient(resp))
    result = engine.analyze(_candidate())
    assert result.recommendation.action == Action.BUY
    assert result.recommendation.confidence == 0.75
    assert result.input_tokens == 100


def test_forced_tool_choice_used(settings):
    resp = _fake_response(
        {"action": "HOLD", "confidence": 0.5, "rationale": "mixed", "risks": []}
    )
    fake = _FakeClient(resp)
    engine = ClaudeEngine(settings, client=fake)
    engine.analyze(_candidate())
    assert fake.last_kwargs["tool_choice"] == {"type": "tool", "name": "submit_recommendation"}


def test_malformed_response_marked_failed(settings):
    # Response with no tool_use block → analysis fails gracefully.
    bad = SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    engine = ClaudeEngine(settings, client=_FakeClient(bad))
    result = engine.analyze(_candidate())
    assert result.recommendation.action == Action.ANALYSIS_FAILED


def test_caps_candidate_count(settings):
    resp = _fake_response(
        {"action": "HOLD", "confidence": 0.5, "rationale": "x", "risks": []}
    )
    fake = _FakeClient(resp)
    engine = ClaudeEngine(settings, client=fake)
    # 5 candidates but claude_max_candidates=3 in fixture
    cands = [_candidate() for _ in range(5)]
    engine.analyze_all(cands)
    assert fake.calls == 3


def test_cost_estimate_accumulates(settings):
    resp = _fake_response(
        {"action": "BUY", "confidence": 0.6, "rationale": "x", "risks": []},
        in_tok=1_000_000, out_tok=0,
    )
    engine = ClaudeEngine(settings, client=_FakeClient(resp))
    engine.analyze(_candidate())
    # sonnet input price 3.0/Mtok → ~$3 for 1M input tokens
    assert engine.estimated_cost_usd() > 0
