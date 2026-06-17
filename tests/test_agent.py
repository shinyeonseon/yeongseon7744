"""박부장 advisor agent: tools, tool-use loop, memory, and Slack dispatch."""

from __future__ import annotations

import json

from helpers import make_candles
from tossai.agent.advisor import Advisor, ConversationStore
from tossai.agent.tools import AdvisorContext, run_tool
from tossai.slack.commands import dispatch_command


def _write_portfolio(reports_dir, symbol="MU"):
    import pathlib
    d = pathlib.Path(reports_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "portfolio_2026-06-16_090000.json").write_text(json.dumps({
        "generated_at": "2026-06-16T09:00:00+00:00",
        "results": [{
            "position": {"symbol": symbol, "market": "US", "last_price": 100.0,
                         "avg_price": 80.0, "pl_rate": 0.25},
            "advice": {"action": "TRIM", "confidence": 0.7, "rationale": "과열 구간"},
        }],
    }))


class _Resp:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class _FakeClient:
    """Scripted Anthropic client: returns queued responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                return outer._responses.pop(0)

        self.messages = _Messages()


class _FakeToss:
    def __init__(self, candles):
        self._candles = candles

    def get_candles(self, symbol, count=200, **kw):
        return self._candles


# ---- tools ---------------------------------------------------------------

def test_read_portfolio_tool(settings, tmp_path):
    settings.reports_dir = str(tmp_path)
    _write_portfolio(tmp_path, symbol="NVDA")
    out = run_tool("read_portfolio", {}, AdvisorContext(settings))
    data = json.loads(out)
    assert data["positions"][0]["symbol"] == "NVDA"
    assert data["positions"][0]["action"] == "TRIM"
    assert data["positions"][0]["pl_rate"] == "+25.0%"


def test_quote_tool(settings):
    candles = make_candles([100.0, 101.0, 102.0, 103.0, 110.0])
    ctx = AdvisorContext(settings, client=_FakeToss(candles))
    out = run_tool("quote", {"symbol": "nvda"}, ctx)
    data = json.loads(out)
    assert data["symbol"] == "NVDA"
    assert data["last_price"] == 110.0
    assert data["ret_1d"] == "+6.8%"  # 110/103 - 1


def test_unknown_tool_returns_text(settings):
    out = run_tool("does_not_exist", {}, AdvisorContext(settings))
    assert "알 수 없는 도구" in out


def test_market_overview_tool(settings, monkeypatch):
    import tossai.context.sources as sources
    import tossai.risk.sentiment as sentiment
    from tossai.context.models import MacroSnapshot

    settings.vix_blackswan_threshold = 30.0
    monkeypatch.setattr(sentiment, "get_vix", lambda s, *a, **k: 18.5)
    monkeypatch.setattr(sources, "fetch_macro", lambda s, **k: MacroSnapshot(
        indicators={"기준금리": "4.50%", "공포탐욕": "62(탐욕)"},
        upcoming=["FOMC 2026-06-17 (D-0)"]))
    out = run_tool("market_overview", {}, AdvisorContext(settings))
    data = json.loads(out)
    assert data["vix"] == {"value": 18.5, "band": "안정", "threshold": 30.0}
    assert data["indicators"]["기준금리"] == "4.50%"
    assert "FOMC 2026-06-17 (D-0)" in data["upcoming_events"]


def test_news_tool(settings, monkeypatch):
    import tossai.context.sources as sources
    from tossai.context.models import NewsItem

    monkeypatch.setattr(sources, "fetch_news", lambda sym, mkt, limit=5: [
        NewsItem(title="신제품 발표", publisher="Reuters", published="2026-06-17")])
    out = run_tool("news", {"symbol": "nvda"}, AdvisorContext(settings))
    data = json.loads(out)
    assert data["symbol"] == "NVDA"
    assert "신제품 발표" in data["news"][0]


def test_news_tool_empty(settings, monkeypatch):
    import tossai.context.sources as sources

    monkeypatch.setattr(sources, "fetch_news", lambda sym, mkt, limit=5: [])
    out = run_tool("news", {"symbol": "ZZZZ"}, AdvisorContext(settings))
    assert "찾지 못했습니다" in out


# ---- advisor tool-use loop ----------------------------------------------

def test_advisor_calls_tool_then_answers(settings, tmp_path):
    settings.reports_dir = str(tmp_path)
    _write_portfolio(tmp_path, symbol="MU")
    fake = _FakeClient([
        _Resp([{"type": "tool_use", "id": "t1", "name": "read_portfolio", "input": {}}],
              "tool_use"),
        _Resp([{"type": "text", "text": "보유 종목 MU는 축소(TRIM) 의견입니다."}], "end_turn"),
    ])
    advisor = Advisor(settings, client=fake)
    text, history = advisor.answer("내 포트폴리오 어때?")

    assert "MU" in text
    assert len(fake.calls) == 2
    # The conversation must include a tool_result turn carrying the portfolio data.
    tool_turns = [
        m for m in history
        if m["role"] == "user" and isinstance(m["content"], list)
        and m["content"] and m["content"][0].get("type") == "tool_result"
    ]
    assert tool_turns and "MU" in tool_turns[0]["content"][0]["content"]


def test_advisor_history_continues(settings):
    fake = _FakeClient([_Resp([{"type": "text", "text": "안녕하세요, 박부장입니다."}], "end_turn")])
    advisor = Advisor(settings, client=fake)
    text, history = advisor.answer("안녕", [])
    assert "박부장" in text
    # user turn + assistant turn recorded for the next round.
    assert history[0] == {"role": "user", "content": "안녕"}
    assert history[1]["role"] == "assistant"


def test_advisor_stops_at_max_steps(settings, tmp_path):
    settings.reports_dir = str(tmp_path)
    _write_portfolio(tmp_path)
    # Always asks for a tool → loop must bail out gracefully.
    loop = [_Resp([{"type": "tool_use", "id": f"t{i}", "name": "read_portfolio", "input": {}}],
                  "tool_use") for i in range(10)]
    advisor = Advisor(settings, client=_FakeClient(loop))
    text, _ = advisor.answer("끝없이")
    assert "좁혀" in text or "정리" in text


# ---- conversation store --------------------------------------------------

def test_conversation_store_roundtrip_and_cap():
    store = ConversationStore(max_turns=2, ttl_sec=3600)
    store.set("c:u", [{"a": 1}, {"b": 2}, {"c": 3}])
    assert store.get("c:u") == [{"b": 2}, {"c": 3}]  # capped to last 2
    store.reset("c:u")
    assert store.get("c:u") == []


def test_conversation_store_ttl():
    store = ConversationStore(ttl_sec=0)
    store.set("c:u", [{"a": 1}])
    assert store.get("c:u") == []  # already expired


# ---- slack dispatch ------------------------------------------------------

def test_slash_bakbujang_defers_with_meta(settings):
    res = dispatch_command(
        "/박부장",
        {"text": "내 포트폴리오 어때?", "channel_id": "C1", "user_id": "U1"},
        settings,
    )
    assert res.deferred_kind == "advisor"
    assert res.meta["text"] == "내 포트폴리오 어때?"
    assert res.meta["channel_id"] == "C1"


def test_slash_bakbujang_requires_text(settings):
    res = dispatch_command("/박부장", {"text": "  "}, settings)
    assert res.deferred_kind is None
    assert res.inline_blocks is not None
