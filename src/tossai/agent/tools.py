"""Tools for the 박부장 advisor agent.

Read-only views over the user's own data: held positions + latest advice, the
newest watchlist recommendations, realized performance, and live quotes. The
agent grounds its answers in these instead of guessing. Analysis-only — no tool
places an order or mutates state.
"""

from __future__ import annotations

import json
from pathlib import Path

from tossai.config import Settings
from tossai.logging_setup import get_logger

log = get_logger(__name__)

ADVISOR_TOOLS = [
    {
        "name": "read_portfolio",
        "description": "사용자가 실제 보유한 종목과 가장 최근의 ADD/HOLD/TRIM/SELL 조언(근거 포함)을 읽는다. "
                       "보유 현황·손익·'내 종목 어때?' 류 질문에 사용.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_recommendations",
        "description": "워치리스트의 가장 최근 추천(매수 후보)과 BUY/HOLD/SELL 액션·확신도·근거를 읽는다. "
                       "'살 만한 거 있어?' 류 질문에 사용.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "performance",
        "description": "과거 추천(picks) 또는 보유 조언(portfolio)이 이후 가격으로 실제 맞았는지 "
                       "사후 성과(적중률·평균 수익)를 읽는다.",
        "input_schema": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["picks", "portfolio"]}},
            "required": ["kind"], "additionalProperties": False,
        },
    },
    {
        "name": "quote",
        "description": "한 종목의 현재가와 최근 1/5/20 거래일 등락률을 조회한다.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "티커 (예: NVDA)"}},
            "required": ["symbol"], "additionalProperties": False,
        },
    },
]


class AdvisorContext:
    """Holds settings and lazily opens one TossClient for the network tools."""

    def __init__(self, settings: Settings, client=None):
        self.s = settings
        self._client = client
        self._owns = False

    def client(self):
        if self._client is None:
            from tossai.toss.client import TossClient
            self._client = TossClient(self.s).__enter__()
            self._owns = True
        return self._client

    def close(self) -> None:
        if self._owns and self._client is not None:
            try:
                self._client.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self._client = None
            self._owns = False


def run_tool(name: str, args: dict, ctx: AdvisorContext) -> str:
    """Dispatch a tool call; always returns a string for the model (never raises)."""
    try:
        if name == "read_portfolio":
            return _read_portfolio(ctx.s)
        if name == "read_recommendations":
            return _read_recommendations(ctx.s)
        if name == "performance":
            return _performance(ctx, (args or {}).get("kind", "picks"))
        if name == "quote":
            return _quote(ctx, (args or {}).get("symbol", ""))
        return f"알 수 없는 도구: {name}"
    except Exception as exc:  # noqa: BLE001 - surface failures to the model as text
        log.warning("advisor tool %s failed: %s", name, exc)
        return f"도구 {name} 실행 실패: {exc}"


def _latest(reports_dir: str, portfolio: bool) -> dict | None:
    d = Path(reports_dir)
    if not d.exists():
        return None
    if portfolio:
        files = sorted(d.glob("portfolio_*.json"))
    else:
        files = sorted(p for p in d.glob("*.json") if not p.name.startswith("portfolio_"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_portfolio(settings: Settings) -> str:
    data = _latest(settings.reports_dir, portfolio=True)
    if not data:
        return "저장된 포트폴리오 조언이 아직 없습니다 (`portfolio`/`daily`를 먼저 실행)."
    rows = []
    for r in data.get("results", []):
        pos, adv = r.get("position", {}), r.get("advice", {})
        pl = pos.get("pl_rate")
        pl_s = f"{pl * 100:+.1f}%" if isinstance(pl, (int, float)) else "n/a"
        rows.append({
            "symbol": pos.get("symbol"), "market": pos.get("market"),
            "last_price": pos.get("last_price"), "avg_price": pos.get("avg_price"),
            "pl_rate": pl_s, "action": adv.get("action"),
            "confidence": adv.get("confidence"), "rationale": adv.get("rationale"),
        })
    return json.dumps({"as_of": data.get("generated_at"), "positions": rows}, ensure_ascii=False)


def _read_recommendations(settings: Settings) -> str:
    data = _latest(settings.reports_dir, portfolio=False)
    if not data:
        return "저장된 추천이 아직 없습니다 (`run-once`를 먼저 실행)."
    rows = []
    for r in data.get("results", []):
        cand, rec = r.get("candidate", {}), r.get("recommendation", {})
        rows.append({
            "symbol": cand.get("symbol"), "market": cand.get("market"),
            "price": cand.get("price"), "action": rec.get("action"),
            "confidence": rec.get("confidence"), "rationale": rec.get("rationale"),
        })
    return json.dumps({"as_of": data.get("generated_at"), "recommendations": rows}, ensure_ascii=False)


def _performance(ctx: AdvisorContext, kind: str) -> str:
    from tossai.performance import ledger, tracker

    portfolio = kind == "portfolio"
    if portfolio:
        ledger.backfill_from_portfolio_reports(ctx.s.reports_dir)
        records = ledger.load_ledger(ctx.s.reports_dir, ledger.PORTFOLIO_LEDGER_NAME)
    else:
        ledger.backfill_from_reports(ctx.s.reports_dir)
        records = ledger.load_ledger(ctx.s.reports_dir)
    if not records:
        return "아직 채점할 이력이 없습니다 (데이터가 며칠 쌓여야 합니다)."

    horizons = (5, 21, 63)
    need = max(horizons) + 5
    client = ctx.client()
    candle_map = {}
    for sym in sorted({r.symbol for r in records}):
        try:
            candle_map[sym] = client.get_candles(sym, count=ctx.s.resolved_candle_count(need))
        except Exception as exc:
            log.debug("perf candle fetch failed for %s: %s", sym, exc)
    summary = tracker.evaluate(records, candle_map, horizons=horizons, primary_horizon=21)
    title = "Portfolio advice performance" if portfolio else "Recommendation performance"
    return tracker.summary_table(summary, title)


def _quote(ctx: AdvisorContext, symbol: str) -> str:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return "티커가 비어 있습니다."
    candles = ctx.client().get_candles(symbol, count=ctx.s.resolved_candle_count(30))
    if not candles:
        return f"{symbol} 시세를 가져오지 못했습니다."
    closes = [c.close for c in candles]
    last = closes[-1]

    def ret(n: int):
        if len(closes) > n and closes[-1 - n] > 0:
            return f"{(last / closes[-1 - n] - 1) * 100:+.1f}%"
        return "n/a"

    return json.dumps({
        "symbol": symbol, "last_price": last,
        "ret_1d": ret(1), "ret_5d": ret(5), "ret_20d": ret(20),
        "as_of": candles[-1].ts.date().isoformat(),
    }, ensure_ascii=False)
