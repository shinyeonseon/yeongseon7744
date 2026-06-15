"""Build, persist, and pretty-print run reports."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from tossai.logging_setup import get_logger
from tossai.models import DISCLAIMER, AnalyzedCandidate

log = get_logger(__name__)


class Report(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    market: str
    market_open: bool
    universe_size: int
    screened_count: int
    results: list[AnalyzedCandidate] = Field(default_factory=list)
    estimated_cost_usd: float = 0.0
    disclaimer: str = DISCLAIMER

    def actionable(self, min_confidence: float) -> list[AnalyzedCandidate]:
        return [
            r for r in self.results
            if r.recommendation.action.value in {"BUY", "SELL"}
            and r.recommendation.confidence >= min_confidence
        ]


def save_report(report: Report, reports_dir: str) -> Path:
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.strftime("%Y-%m-%d_%H%M%S")
    path = Path(reports_dir) / f"{stamp}.json"
    path.write_text(report.model_dump_json(indent=2))
    log.info("report written to %s", path)
    return path


def console_table(report: Report) -> str:
    lines = [
        f"=== Toss AI report {report.generated_at:%Y-%m-%d %H:%M UTC} "
        f"(market={report.market}, open={report.market_open}) ===",
        f"universe={report.universe_size} screened={report.screened_count} "
        f"~cost=${report.estimated_cost_usd:.4f}",
        f"{'SYMBOL':<10}{'MKT':<5}{'ACTION':<8}{'CONF':<6}{'TARGET':<12}RATIONALE",
        "-" * 78,
    ]
    if not report.results:
        lines.append("(no candidates passed screening)")
    for r in report.results:
        rec = r.recommendation
        target = f"{rec.target_price:.2f}" if rec.target_price is not None else "-"
        rationale = (rec.rationale[:40] + "…") if len(rec.rationale) > 41 else rec.rationale
        lines.append(
            f"{r.candidate.symbol:<10}{r.candidate.market:<5}{rec.action.value:<8}"
            f"{rec.confidence:<6.2f}{target:<12}{rationale}"
        )
    lines.append("-" * 78)
    lines.append(DISCLAIMER)
    return "\n".join(lines)
