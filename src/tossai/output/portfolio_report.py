"""Portfolio advice report: per-position P&L + ADD/HOLD/TRIM/SELL advice."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from tossai.logging_setup import get_logger
from tossai.models import DISCLAIMER, AnalyzedPosition

log = get_logger(__name__)

_ACTION_EMOJI = {"ADD": "🟢", "HOLD": "⚪", "TRIM": "🟠", "SELL": "🔴", "ANALYSIS_FAILED": "⚠️"}


def _oneline(text: str, n: int = 48) -> str:
    """Collapse newlines/extra whitespace so a rationale stays on one row."""
    flat = " ".join((text or "").split())
    return (flat[: n - 1] + "…") if len(flat) > n else flat


def _fmt_qty(q: float) -> str:
    """Whole shares as integers; fractional holdings keep up to 4 sig figs so a
    small fractional position (Toss supports fractional US shares) isn't shown as 0."""
    return f"{q:.0f}" if q == int(q) else f"{q:.4g}"


class PortfolioReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    positions_count: int = 0
    results: list[AnalyzedPosition] = Field(default_factory=list)
    estimated_cost_usd: float = 0.0
    macro: str = ""  # one-line macro backdrop (indicators + next FOMC), may be empty
    disclaimer: str = DISCLAIMER


def save_report(report: PortfolioReport, reports_dir: str) -> Path:
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.strftime("%Y-%m-%d_%H%M%S")
    path = Path(reports_dir) / f"portfolio_{stamp}.json"
    path.write_text(report.model_dump_json(indent=2))
    log.info("portfolio report written to %s", path)
    return path


def console_table(report: PortfolioReport) -> str:
    lines = [
        f"=== Portfolio advice {report.generated_at:%Y-%m-%d %H:%M UTC} "
        f"({report.positions_count} positions, ~${report.estimated_cost_usd:.4f}) ===",
        f"{'SYMBOL':<8}{'MKT':<5}{'QTY':>6} {'AVG':>11} {'LAST':>11} {'P&L%':>8}  "
        f"{'ACTION':<8}{'CONF':<6}RATIONALE",
        "-" * 92,
    ]
    if not report.results:
        lines.append("(no holdings found — check TOSS_ACCOUNT_SEQ)")
    for r in report.results:
        p, a = r.position, r.advice
        emoji = _ACTION_EMOJI.get(a.action.value, "")
        pl = f"{p.pl_rate * 100:+.1f}" if p.pl_rate is not None else "-"
        rationale = _oneline(a.rationale, 48)
        lines.append(
            f"{p.symbol:<8}{p.market:<5}{_fmt_qty(p.quantity):>6} {p.avg_price:>11.2f} "
            f"{p.last_price:>11.2f} {pl:>8}  {emoji}{a.action.value:<7}{a.confidence:<6.2f}{rationale}"
        )
    lines.append("-" * 92)
    lines.append(DISCLAIMER)
    return "\n".join(lines)
