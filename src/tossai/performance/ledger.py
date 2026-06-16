"""Append-only recommendation ledger (JSONL) + backfill from saved reports.

The ledger decouples tracking from report retention: each run appends its
recommendations, and scoring reads them back. ``backfill_from_reports`` seeds the
ledger from any reports already on disk so past runs count too.
"""

from __future__ import annotations

import json
from pathlib import Path

from tossai.logging_setup import get_logger
from tossai.performance.models import RecoRecord

log = get_logger(__name__)

LEDGER_NAME = "recommendations.jsonl"


def _ledger_path(reports_dir: str) -> Path:
    return Path(reports_dir) / LEDGER_NAME


def append_records(records: list[RecoRecord], reports_dir: str) -> int:
    """Append records, skipping ones already present (idempotent by date+symbol+action)."""
    if not records:
        return 0
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    existing = {r.key() for r in load_ledger(reports_dir)}
    new = [r for r in records if r.key() not in existing]
    if not new:
        return 0
    with _ledger_path(reports_dir).open("a", encoding="utf-8") as fh:
        for r in new:
            fh.write(r.model_dump_json() + "\n")
    return len(new)


def append_report(report, reports_dir: str) -> int:
    """Record every result in a run report (BUY/HOLD/SELL) to the ledger."""
    date = report.generated_at.date().isoformat()
    records = [
        RecoRecord(
            date=date, symbol=r.candidate.symbol, market=r.candidate.market,
            action=r.recommendation.action.value, confidence=r.recommendation.confidence,
            price=r.candidate.price,
        )
        for r in report.results
    ]
    return append_records(records, reports_dir)


def load_ledger(reports_dir: str) -> list[RecoRecord]:
    path = _ledger_path(reports_dir)
    if not path.exists():
        return []
    out: list[RecoRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(RecoRecord.model_validate_json(line))
        except Exception as exc:
            log.debug("skipping bad ledger line: %s", exc)
    return out


def backfill_from_reports(reports_dir: str) -> int:
    """Seed the ledger from saved run reports (reports/*.json, not portfolio_*)."""
    d = Path(reports_dir)
    if not d.exists():
        return 0
    records: list[RecoRecord] = []
    for path in sorted(d.glob("*.json")):
        if path.name.startswith("portfolio_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        date = str(data.get("generated_at", ""))[:10]
        if not date:
            continue
        for r in data.get("results", []):
            cand = r.get("candidate", {})
            rec = r.get("recommendation", {})
            sym = cand.get("symbol")
            action = rec.get("action")
            if not sym or not action:
                continue
            records.append(RecoRecord(
                date=date, symbol=sym, market=cand.get("market", ""),
                action=action, confidence=rec.get("confidence", 0.0) or 0.0,
                price=cand.get("price"),
            ))
    return append_records(records, reports_dir)
