"""Portfolio mode: holdings parsing, analyzer, position advice (all mocked)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx

from helpers import make_series
from tossai.analysis.claude_engine import ClaudeEngine
from tossai.models import AnalyzedPosition, PortfolioAction, Position, PositionAdvice
from tossai.portfolio.analyzer import PortfolioAnalyzer, _position_signals
from tossai.toss.auth import TossAuth
from tossai.toss.client import TossClient
from tossai.toss.schemas import AccountRaw, HoldingItemRaw

HOLDINGS = {
    "result": {
        "items": [
            {"symbol": "MU", "name": "마이크론", "marketCountry": "US", "currency": "USD",
             "quantity": "13", "lastPrice": "1070.45", "averagePurchasePrice": "382.84",
             "profitLoss": {"amount": "8938", "rate": "1.796"},
             "marketValue": {"amount": "13915.85"}},
            {"symbol": "ORCL", "name": "오라클", "marketCountry": "US", "currency": "USD",
             "quantity": "2", "lastPrice": "194.25", "averagePurchasePrice": "246.6",
             "profitLoss": {"amount": "-104", "rate": "-0.2123"},
             "marketValue": {"amount": "388.5"}},
        ]
    }
}


def test_holding_to_position():
    p = HoldingItemRaw.model_validate(HOLDINGS["result"]["items"][0]).to_position()
    assert p.symbol == "MU" and p.market == "US"
    assert p.quantity == 13 and p.avg_price == 382.84 and p.last_price == 1070.45
    assert p.pl_rate == 1.796 and p.market_value == 13915.85


def test_account_raw():
    a = AccountRaw.model_validate({"accountNo": "186", "accountSeq": 1, "accountType": "BROKERAGE"})
    assert a.accountSeq == 1


def test_client_get_holdings_and_accounts(settings, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "holdings" in url:
            return httpx.Response(200, json=HOLDINGS)
        if "accounts" in url:
            return httpx.Response(200, json={"result": [
                {"accountNo": "186", "accountSeq": 1, "accountType": "BROKERAGE"}]})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)
    auth = TossAuth(settings, cache_path=str(tmp_path / "t.json"),
                    http=httpx.Client(transport=transport))
    auth._token = "t"
    auth._expires_at = 9_999_999_999
    client = TossClient(settings, auth=auth,
                        http=httpx.Client(base_url=settings.toss_base_url, transport=transport))
    positions = client.get_holdings()
    assert [p.symbol for p in positions] == ["MU", "ORCL"]
    assert client.get_accounts()[0].accountSeq == 1


class _FakeClient:
    def __init__(self, positions):
        self._p = positions

    def get_holdings(self):
        return self._p

    def get_candles(self, symbol, count=200):
        return make_series([100.0 * (1.001 ** i) for i in range(260)])


class _FakeEngine:
    def __init__(self):
        self.calls = 0

    def analyze_position(self, position, signals):
        self.calls += 1
        return AnalyzedPosition(
            position=position,
            advice=PositionAdvice(action=PortfolioAction.HOLD, confidence=0.6,
                                  rationale="steady", risks=[]),
        )

    def estimated_cost_usd(self):
        return 0.0


def test_portfolio_analyzer(settings):
    positions = [Position(symbol="MU", market="US", quantity=13, avg_price=382.84,
                          last_price=1070.45, pl_rate=1.796)]
    report = PortfolioAnalyzer(settings, _FakeClient(positions), _FakeEngine()).run()
    assert report.positions_count == 1
    assert report.results[0].advice.action == PortfolioAction.HOLD


def test_portfolio_analyzer_skips_zero_quantity(settings):
    positions = [
        Position(symbol="MU", market="US", quantity=13, avg_price=382.84, last_price=1070.45),
        Position(symbol="SOXL", market="US", quantity=0, avg_price=226.64, last_price=271.32),
    ]
    report = PortfolioAnalyzer(settings, _FakeClient(positions), _FakeEngine()).run()
    assert report.positions_count == 1  # SOXL (0 shares) skipped
    assert report.results[0].position.symbol == "MU"


def test_portfolio_console_table_is_one_row_per_position(settings):
    from tossai.models import AnalyzedPosition, PositionAdvice
    from tossai.output.portfolio_report import PortfolioReport, console_table

    rep = PortfolioReport(positions_count=1, results=[
        AnalyzedPosition(
            position=Position(symbol="MU", market="US", quantity=13, avg_price=382.84,
                              last_price=1070.45, pl_rate=1.796),
            advice=PositionAdvice(
                action=PortfolioAction.HOLD, confidence=0.65,
                rationale="**Position Overview:**\n- Entry (avg cost) far below price\n- Momentum strong",
                risks=[]),
        ),
    ])
    out = console_table(rep)
    # the MU row must be a single line (rationale newlines flattened, not split)
    mu_lines = [ln for ln in out.splitlines() if ln.startswith("MU")]
    assert len(mu_lines) == 1 and "HOLD" in mu_lines[0]
    # no orphan rationale fragments on their own lines ("- "/"**"; dashes alone = divider)
    assert not any(ln.lstrip().startswith(("- ", "**")) for ln in out.splitlines())


def test_position_signals_snapshot():
    pos = Position(symbol="MU", market="US", avg_price=100.0, last_price=130.0)
    sig = _position_signals(make_series([100.0 * (1.001 ** i) for i in range(260)]), pos)
    assert "vs_avg_cost_pct" in sig and "rsi" in sig and "above_ma200" in sig


def test_position_signals_short_history():
    pos = Position(symbol="X", market="US", avg_price=10.0, last_price=12.0)
    sig = _position_signals(make_series([10.0, 11.0, 12.0]), pos)
    assert sig.get("note") == "insufficient price history"


def test_engine_analyze_position(settings):
    block = SimpleNamespace(
        type="tool_use", name="submit_position_advice",
        input={"action": "TRIM", "confidence": 0.7, "target_price": 1100.0,
               "rationale": "large unrealized gain, momentum cooling", "risks": ["concentration"]},
    )
    resp = SimpleNamespace(content=[block],
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))

    class _C:
        def __init__(self):
            self.messages = SimpleNamespace(create=lambda **k: resp)

    eng = ClaudeEngine(settings, client=_C())
    pos = Position(symbol="MU", market="US", avg_price=382.84, last_price=1070.45,
                   pl_rate=1.796, quantity=13)
    ap = eng.analyze_position(pos, {"rsi": 70})
    assert ap.advice.action == PortfolioAction.TRIM
    assert ap.input_tokens == 10
