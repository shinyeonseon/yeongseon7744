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
        f"{emoji} *{c.symbol}* [{c.market}] *{rec.action.value}* "
        f"({rec.confidence:.0%}){target}\n_{_truncate(rec.rationale, 220)}_"
    )


def report_blocks(report: Report, min_confidence: float = 0.0) -> list[dict]:
    """Recommendation signals from a run. Includes all results; the actionable
    count (BUY/SELL ≥ confidence) is summarized at the top."""
    actionable = report.actionable(min_confidence)
    blocks: list[dict] = [
        _header("📈 Toss AI — Recommendations"),
        _section(
            f"*{report.generated_at:%Y-%m-%d %H:%M UTC}*  ·  market `{report.market}` "
            f"(open={report.market_open})\n"
            f"universe *{report.universe_size}*  ·  screened *{report.screened_count}*  ·  "
            f"actionable *{len(actionable)}*  ·  ~${report.estimated_cost_usd:.4f}"
        ),
    ]
    if not report.results:
        blocks.append(_section("_No candidates passed screening._"))
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
        f"{emoji} *{p.symbol}* [{p.market}] *{a.action.value}* "
        f"({a.confidence:.0%}){pl}\n_{_truncate(rationale, 220)}_"
    )


def portfolio_blocks(report: PortfolioReport, min_confidence: float = 0.0) -> list[dict]:
    """Held-position advice (ADD/HOLD/TRIM/SELL) as Block Kit. Shows every
    position; rationale newlines are flattened so each stays one section."""
    blocks: list[dict] = [
        _header("💼 보유 포트폴리오 조언"),
        _section(
            f"*{report.generated_at:%Y-%m-%d %H:%M UTC}*  ·  "
            f"positions *{report.positions_count}*  ·  ~${report.estimated_cost_usd:.4f}"
        ),
    ]
    shown = [r for r in report.results if r.advice.confidence >= min_confidence]
    if not shown:
        blocks.append(_section("_No positions to report (check TOSS_ACCOUNT_SEQ)._"))
    for item in shown:
        blocks.append(_section(_portfolio_line(item)))
    blocks.append({"type": "divider"})
    blocks.append(_disclaimer_block())
    return blocks


def screen_blocks(candidates: list[Candidate]) -> list[dict]:
    blocks: list[dict] = [_header("🔎 Toss AI — Screening")]
    if not candidates:
        blocks.append(_section("_No candidates passed screening._"))
    else:
        lines = [
            f"• *{c.symbol}* [{c.market}]  score *{c.score:.3f}*  price {c.price}"
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
        _header("🌅 Morning Briefing"),
        _section(f"*{date_label}*  ·  market `{market_label}` (open={market_open})\n{vix_text}"),
    ]
    if candidates:
        lines = [
            f"• *{c.symbol}* [{c.market}]  score *{c.score:.3f}*  price {c.price}"
            for c in candidates[:10]
        ]
        blocks.append(_section("*Today's screened watchlist*\n" + "\n".join(lines)))
    else:
        blocks.append(_section("_Nothing notable passed screening today._"))
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
    counts = "  ·  ".join(f"{k} *{v}*" for k, v in action_counts.items()) or "no signals"
    top = ", ".join(f"{s} ({n})" for s, n in top_symbols) or "—"
    conf = f"{avg_confidence:.0%}" if avg_confidence is not None else "—"
    blocks = [
        _header("🗓️ Weekly Briefing"),
        _section(
            f"*{date_label}*  ·  universe *{universe_size}*\n"
            f"Signals this week: {counts}\n"
            f"Most-screened: {top}\n"
            f"Avg confidence: *{conf}*\n{_vix_phrase(vix, vix_threshold)}"
        ),
        _disclaimer_block(),
    ]
    return blocks


def risk_alert_blocks(alert: RiskAlert) -> list[dict]:
    icon = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(alert.severity.value, "⚠️")
    sym = f" · *{alert.symbol}*" if alert.symbol else ""
    return [
        _header(f"{icon} Risk Alert — {alert.kind.value}"),
        _section(f"{alert.message}{sym}"),
        _disclaimer_block(),
    ]


def status_blocks(summary: dict[str, object]) -> list[dict]:
    lines = [f"• `{k}`: {v}" for k, v in summary.items()]
    return [_header("⚙️ Status"), _section("\n".join(lines))]


def help_blocks() -> list[dict]:
    return [
        _header("🤖 Toss AI — Commands"),
        _section(
            "*/recommend* — run full analysis (screening + Claude) and post signals\n"
            "*/screen* — screening only (free, no Claude)\n"
            "*/briefing* — post the morning briefing now\n"
            "*/status* — show configuration/health\n"
            "*/help* — this message"
        ),
        _disclaimer_block(),
    ]


def error_blocks(message: str) -> list[dict]:
    return [_section(f"⚠️ {_truncate(message, 280)}")]


def _vix_phrase(vix: float | None, threshold: float) -> str:
    if vix is None:
        return "VIX: _unavailable_"
    if vix >= threshold:
        band = "🚨 stressed"
    elif vix >= threshold * 0.66:
        band = "⚠️ elevated"
    else:
        band = "🟢 calm"
    return f"VIX: *{vix:.2f}* ({band}, threshold {threshold:.0f})"
