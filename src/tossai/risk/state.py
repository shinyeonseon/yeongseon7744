"""Anti-spam dedupe for risk alerts.

Keyed by ``(kind, symbol, trading_date)`` and persisted to a small JSON file
under ``reports_dir`` so the same alert doesn't repeat within a day and state
survives restarts. No new database dependency.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tossai.logging_setup import get_logger
from tossai.risk.models import RiskAlert

log = get_logger(__name__)


class AlertDeduper:
    def __init__(self, reports_dir: str, filename: str = ".risk_alerts.json"):
        self.path = Path(reports_dir) / filename
        self._seen: set[str] = set()
        self._load()

    def _today(self, now: datetime | None = None) -> str:
        return (now or datetime.now(UTC)).strftime("%Y-%m-%d")

    def should_send(self, alert: RiskAlert, now: datetime | None = None) -> bool:
        """True the first time this alert is seen today; False on repeats.

        Also prunes keys from previous days so the file stays small.
        """
        today = self._today(now)
        # Drop stale keys from earlier days.
        self._seen = {k for k in self._seen if k.endswith(today)}
        key = alert.dedupe_key(today)
        if key in self._seen:
            return False
        self._seen.add(key)
        self._save()
        return True

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self._seen = set(json.loads(self.path.read_text()))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("ignoring unreadable risk-alert cache: %s", exc)
            self._seen = set()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(sorted(self._seen)))
        except OSError as exc:
            log.warning("could not write risk-alert cache: %s", exc)
