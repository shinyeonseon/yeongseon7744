"""Block Kit formatters (pure functions, no I/O).

Mirror the content of ``output/report.console_table`` / ``WebhookNotifier`` but
as Slack blocks. Every message ends with the DISCLAIMER context block. These
are the most-tested pieces of the Slack layer.
"""

from __future__ import annotations

from tossai.models import DISCLAIMER, Action, AnalyzedCandidate, Candidate
from tossai.output.portfolio_report import PortfolioReport
from tossai.output.report import Report
from tossai.risk.models import RiskAlert

_ACTION_EMOJI = {
    Action.BUY: "🟢",
    Action.SELL: "🔴",
    Action.HOLD: "⚪",
    Action.ANALYSIS_FAILED: "⚠️",
}

# Portfolio advice actions (ADD/HOLD/TRIM/SELL) keyed by their string value.
_PORTFOLIO_EMOJI = {"ADD": "🟢", "HOLD": "⚪", "TRIM": "🟠", "SELL": "🔴", "ANALYSIS_FAILED": "⚠️"}

# Korean labels for action codes (shown alongside the code in Slack messages).
_ACTION_KO = {
    "BUY": "매수", "SELL": "매도", "HOLD": "보유",
    "ADD": "추가매수", "TRIM": "축소", "ANALYSIS_FAILED": "분석실패",
}


def _action_ko(value: str) -> str:
    ko = _ACTION_KO.get(value)
    return f"{ko}({value})" if ko else value


def _truncate(text: str, n: int = 280) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _header(text: str) -> dict:
    return {"type": "header", "text": {"type": "plain_text", "text": _truncate(text, 150)}}


def _disclaimer_block() -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": DISCLAIMER}]}


def _recommendation_line(item: AnalyzedCandidate) -> str:
    c = item.candidate
    rec = item.recommendation
    emoji = _ACTION_EMOJI.get(rec.action, "•")
    target = f" → *{rec.target_price:.2f}*" if rec.target_price is not None else ""
    return (
        f"{emoji} *{c.symbol}* [{c.market}] *{_action_ko(rec.action.value)}* "
        f"({rec.confidence:.0%}){target}\n_{_truncate(rec.rationale, 220)}_"
    )


def report_blocks(report: Report, min_confidence: float = 0.0) -> list[dict]:
    """Recommendation signals from a run. Includes all results; the actionable
    count (BUY/SELL ≥ confidence) is summarized at the top."""
    actionable = report.actionable(min_confidence)
    blocks: list[dict] = [
        _header("📈 Toss AI — 추천 시그널"),
        _section(
            f"*{report.generated_at:%Y-%m-%d %H:%M UTC}*  ·  시장 `{report.market}` "
            f"(개장={report.market_open})\n"
            f"유니버스 *{report.universe_size}*  ·  스크리닝 *{report.screened_count}*  ·  "
            f"실행대상 *{len(actionable)}*  ·  ~${report.estimated_cost_usd:.4f}"
        ),
    ]
    if not report.results:
        blocks.append(_section("_스크리닝을 통과한 종목이 없습니다._"))
    for item in report.results:
        blocks.append(_section(_recommendation_line(item)))
    blocks.append({"type": "divider"})
    blocks.append(_disclaimer_block())
    return blocks


def _portfolio_line(item) -> str:
    p, a = item.position, item.advice
    emoji = _PORTFOLIO_EMOJI.get(a.action.value, "•")
    pl = f"  P&L *{p.pl_rate * 100:+.1f}%*" if p.pl_rate is not None else ""
    rationale = " ".join((a.rationale or "").split())
    return (
        f"{emoji} *{p.symbol}* [{p.market}] *{_action_ko(a.action.value)}* "
        f"({a.confidence:.0%}){pl}\n_{_truncate(rationale, 220)}_"
    )


def portfolio_blocks(report: PortfolioReport, min_confidence: float = 0.0) -> list[dict]:
    """Held-position advice (ADD/HOLD/TRIM/SELL) as Block Kit. Shows every
    position; rationale newlines are flattened so each stays one section."""
    blocks: list[dict] = [
        _header("💼 보유 포트폴리오 조언"),
        _section(
            f"*{report.generated_at:%Y-%m-%d %H:%M UTC}*  ·  "
            f"보유종목 *{report.positions_count}*  ·  ~${report.estimated_cost_usd:.4f}"
        ),
    ]
    shown = [r for r in report.results if r.advice.confidence >= min_confidence]
    if not shown:
        blocks.append(_section("_조회된 보유종목이 없습니다 (TOSS_ACCOUNT_SEQ 확인)._"))
    for item in shown:
        blocks.append(_section(_portfolio_line(item)))
    blocks.append({"type": "divider"})
    blocks.append(_disclaimer_block())
    return blocks


def screen_blocks(candidates: list[Candidate]) -> list[dict]:
    blocks: list[dict] = [_header("🔎 Toss AI — 스크리닝")]
    if not candidates:
        blocks.append(_section("_스크리닝을 통과한 종목이 없습니다._"))
    else:
        lines = [
            f"• *{c.symbol}* [{c.market}]  점수 *{c.score:.3f}*  가격 {c.price}"
            for c in candidates
        ]
        blocks.append(_section("\n".join(lines)))
    blocks.append(_disclaimer_block())
    return blocks


def morning_briefing_blocks(
    market_label: str,
    market_open: bool,
    vix: float | None,
    vix_threshold: float,
    candidates: list[Candidate],
    date_label: str,
) -> list[dict]:
    vix_text = _vix_phrase(vix, vix_threshold)
    blocks: list[dict] = [
        _header("🌅 모닝 브리핑"),
        _section(f"*{date_label}*  ·  시장 `{market_label}` (개장={market_open})\n{vix_text}"),
    ]
    if candidates:
        lines = [
            f"• *{c.symbol}* [{c.market}]  점수 *{c.score:.3f}*  가격 {c.price}"
            for c in candidates[:10]
        ]
        blocks.append(_section("*오늘의 스크리닝 관심종목*\n" + "\n".join(lines)))
    else:
        blocks.append(_section("_오늘은 주목할 만한 종목이 없습니다._"))
    blocks.append(_disclaimer_block())
    return blocks


def weekly_briefing_blocks(
    date_label: str,
    universe_size: int,
    action_counts: dict[str, int],
    top_symbols: list[tuple[str, int]],
    avg_confidence: float | None,
    vix: float | None,
    vix_threshold: float,
) -> list[dict]:
    counts = "  ·  ".join(f"{k} *{v}*" for k, v in action_counts.items()) or "시그널 없음"
    top = ", ".join(f"{s} ({n})" for s, n in top_symbols) or "—"
    conf = f"{avg_confidence:.0%}" if avg_confidence is not None else "—"
    blocks = [
        _header("🗓️ 주간 브리핑"),
        _section(
            f"*{date_label}*  ·  유니버스 *{universe_size}*\n"
            f"이번 주 시그널: {counts}\n"
            f"최다 스크리닝: {top}\n"
            f"평균 확신도: *{conf}*\n{_vix_phrase(vix, vix_threshold)}"
        ),
        _disclaimer_block(),
    ]
    return blocks


def risk_alert_blocks(alert: RiskAlert) -> list[dict]:
    icon = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(alert.severity.value, "⚠️")
    sym = f" · *{alert.symbol}*" if alert.symbol else ""
    return [
        _header(f"{icon} 리스크 경보 — {alert.kind.value}"),
        _section(f"{alert.message}{sym}"),
        _disclaimer_block(),
    ]


def status_blocks(summary: dict[str, object]) -> list[dict]:
    lines = [f"• `{k}`: {v}" for k, v in summary.items()]
    return [_header("⚙️ 상태"), _section("\n".join(lines))]


def help_blocks() -> list[dict]:
    return [
        _header("🤖 Toss AI — 명령어"),
        _section(
            "*/recommend* — 전체 분석 실행(스크리닝 + Claude) 후 시그널 게시\n"
            "*/screen* — 스크리닝만(무료, Claude 미사용)\n"
            "*/briefing* — 모닝 브리핑 지금 게시\n"
            "*/status* — 설정/상태 표시\n"
            "*/help* — 이 도움말"
        ),
        _disclaimer_block(),
    ]


def error_blocks(message: str) -> list[dict]:
    return [_section(f"⚠️ {_truncate(message, 280)}")]


def _vix_phrase(vix: float | None, threshold: float) -> str:
    if vix is None:
        return "VIX: _조회 불가_"
    if vix >= threshold:
        band = "🚨 불안정"
    elif vix >= threshold * 0.66:
        band = "⚠️ 상승"
    else:
        band = "🟢 안정"
    return f"VIX: *{vix:.2f}* ({band}, 기준 {threshold:.0f})"
