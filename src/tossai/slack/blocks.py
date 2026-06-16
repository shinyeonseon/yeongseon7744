"""Block Kit formatters (pure functions, no I/O).

Mirror the content of ``output/report.console_table`` / ``WebhookNotifier`` but
as Slack blocks. Every message ends with the DISCLAIMER context block. These
are the most-tested pieces of the Slack layer.
"""

from __future__ import annotations

import re

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


# A Slack section's text field caps at 3000 chars. Rather than clip a long
# rationale, split it across several section blocks at word/line boundaries.
_SECTION_MAX = 2900


def _chunk(text: str, size: int = _SECTION_MAX) -> list[str]:
    """Split text into <= size pieces, breaking at the last newline/space."""
    text = text or ""
    chunks: list[str] = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        if cut <= 0:
            cut = text.rfind(" ", 0, size)
        if cut <= 0:
            cut = size
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    chunks.append(text)
    return chunks


def _text_sections(text: str) -> list[dict]:
    """One or more section blocks holding the full text (no truncation)."""
    return [_section(c) for c in _chunk(text)]


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _divider() -> dict:
    return {"type": "divider"}


def _conf_bar(conf: float) -> str:
    """Five-segment confidence meter, e.g. 0.72 -> '▰▰▰▰▱ 72%'."""
    filled = max(0, min(5, round(conf * 5)))
    return f"{'▰' * filled}{'▱' * (5 - filled)} {conf:.0%}"


def _bullets(items: list[str], marker: str = "•") -> str:
    return "\n".join(f"{marker} {_slack_mrkdwn(s).strip()}" for s in items if s and s.strip())


def _slack_mrkdwn(text: str) -> str:
    """Convert the Markdown Claude emits to Slack's mrkdwn so it renders cleanly
    (Slack bold is *one* asterisk, so '**x**' would otherwise show literal '**')."""
    text = text or ""
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.S)   # **bold** -> *bold*
    text = re.sub(r"__(.+?)__", r"*\1*", text, flags=re.S)        # __bold__ -> *bold*
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*(.+?)\s*$", r"*\1*", text)  # # Heading -> *Heading*
    text = re.sub(r"(?m)^(\s*)[-*]\s+", r"\1• ", text)           # - item / * item -> • item
    text = re.sub(r"\n{3,}", "\n\n", text)                        # collapse big gaps
    return text.strip()


def _header(text: str) -> dict:
    return {"type": "header", "text": {"type": "plain_text", "text": _truncate(text, 150)}}


def _disclaimer_block() -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": DISCLAIMER}]}


def _recommendation_sections(item: AnalyzedCandidate) -> list[dict]:
    c = item.candidate
    rec = item.recommendation
    emoji = _ACTION_EMOJI.get(rec.action, "•")
    title = c.name and f"{c.name} `{c.symbol}`" or f"`{c.symbol}`"
    lead = f"{emoji} *{title}*  ·  {c.market}  ·  *{_action_ko(rec.action.value)}*"
    if rec.rationale:
        lead += f"\n_{_truncate(_slack_mrkdwn(rec.rationale), 300)}_"
    blocks = [_section(lead)]
    # Visual metric line: confidence meter + the fields we actually have.
    meta = [f"확신도 {_conf_bar(rec.confidence)}"]
    if rec.target_price is not None:
        meta.append(f"🎯 목표가 *{rec.target_price:,.2f}*")
    if c.price is not None:
        meta.append(f"현재가 {c.price:,.2f}")
    if getattr(c, "flagged_by", None):
        meta.append(f"✅ 전략 {len(c.flagged_by)}종 동의")
    blocks.append(_context("  ·  ".join(meta)))
    body = ""
    if rec.key_points:
        body += "*핵심*\n" + _bullets(rec.key_points)
    if rec.risks:
        body += ("\n\n" if body else "") + "*리스크*\n" + _bullets(rec.risks, "⚠️")
    if body:
        blocks.extend(_text_sections(body))
    blocks.append(_divider())
    return blocks


def report_blocks(report: Report, min_confidence: float = 0.0) -> list[dict]:
    """Recommendation signals from a run. Includes all results; the actionable
    count (BUY/SELL ≥ confidence) is summarized at the top."""
    actionable = report.actionable(min_confidence)
    open_txt = "장중" if report.market_open else "장마감"
    blocks: list[dict] = [
        _header("📈 Toss AI — 추천 시그널"),
        _context(
            f"{report.generated_at:%Y-%m-%d %H:%M UTC}  ·  시장 *{report.market}* ({open_txt})  ·  "
            f"유니버스 *{report.universe_size}*  ·  스크리닝 *{report.screened_count}*  ·  "
            f"실행대상 *{len(actionable)}*  ·  분석비용 ~${report.estimated_cost_usd:.4f}"
        ),
    ]
    if getattr(report, "macro", ""):
        blocks.append(_context(f"🌐 {report.macro}"))
    blocks.append(_divider())
    if not report.results:
        blocks.append(_section("_스크리닝을 통과한 종목이 없습니다._"))
    for item in report.results:
        blocks.extend(_recommendation_sections(item))
    blocks.append(_disclaimer_block())
    return blocks


def _portfolio_sections(item) -> list[dict]:
    p, a = item.position, item.advice
    emoji = _PORTFOLIO_EMOJI.get(a.action.value, "•")
    title = p.name and f"{p.name} `{p.symbol}`" or f"`{p.symbol}`"
    lead = f"{emoji} *{title}*  ·  {p.market}  ·  *{_action_ko(a.action.value)}*"
    if a.rationale:
        lead += f"\n_{_truncate(_slack_mrkdwn(a.rationale), 300)}_"
    blocks = [_section(lead)]
    meta = [f"확신도 {_conf_bar(a.confidence)}"]
    if p.pl_rate is not None:
        arrow = "🔺" if p.pl_rate >= 0 else "🔻"
        meta.append(f"손익 {arrow} *{p.pl_rate * 100:+.1f}%*")
    if p.avg_price:
        meta.append(f"평단 {p.avg_price:,.2f}")
    if p.last_price:
        meta.append(f"현재가 {p.last_price:,.2f}")
    blocks.append(_context("  ·  ".join(meta)))
    body = ""
    if a.key_points:
        body += "*핵심*\n" + _bullets(a.key_points)
    if a.risks:
        body += ("\n\n" if body else "") + "*리스크*\n" + _bullets(a.risks, "⚠️")
    if body:
        blocks.extend(_text_sections(body))
    blocks.append(_divider())
    return blocks


def portfolio_blocks(report: PortfolioReport, min_confidence: float = 0.0) -> list[dict]:
    """Held-position advice (ADD/HOLD/TRIM/SELL) as Block Kit — one card per
    position (title · metrics context · Korean rationale · divider)."""
    blocks: list[dict] = [
        _header("💼 보유 포트폴리오 조언"),
        _context(
            f"{report.generated_at:%Y-%m-%d %H:%M UTC}  ·  "
            f"보유종목 *{report.positions_count}*  ·  분석비용 ~${report.estimated_cost_usd:.4f}"
        ),
    ]
    if getattr(report, "macro", ""):
        blocks.append(_context(f"🌐 {report.macro}"))
    shown = [r for r in report.results if r.advice.confidence >= min_confidence]
    if not shown:
        blocks.append(_section("_조회된 보유종목이 없습니다 (TOSS_ACCOUNT_SEQ 확인)._"))
    for item in shown:
        blocks.extend(_portfolio_sections(item))
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
