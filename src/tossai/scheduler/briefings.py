"""Briefing content generation (Block Kit, analysis-only, Claude-free).

Morning: macro one-liner + VIX + held-portfolio P/L (with latest advice) +
today's screened watchlist snapshot.
Weekly: aggregate of the past week's saved reports + VIX.
Both reuse the existing Screener/Orchestrator, calendar, and report files.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.market.calendar import any_market_open, markets_for
from tossai.risk.sentiment import get_vix
from tossai.slack import blocks

log = get_logger(__name__)


def _screen(settings: Settings):
    from tossai.pipeline.orchestrator import Orchestrator
    from tossai.toss.client import TossClient

    with TossClient(settings) as client:
        return Orchestrator(settings, client).screen_only()


def _latest_advice_actions(reports_dir: str) -> dict[str, str]:
    """{symbol: action} from the newest portfolio report, for annotating holdings."""
    d = Path(reports_dir)
    files = sorted(d.glob("portfolio_*.json")) if d.exists() else []
    if not files:
        return {}
    try:
        data = json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, str] = {}
    for r in data.get("results", []):
        sym = r.get("position", {}).get("symbol")
        act = r.get("advice", {}).get("action")
        if sym and act:
            out[sym] = act
    return out


def _holdings_summary(settings: Settings) -> dict | None:
    """Value-weighted P/L + per-position lines (with latest advice), or None.

    Fail-soft: returns None when no account is set, holdings can't be fetched,
    or there are no open positions — the briefing then just omits the section.
    """
    if not settings.toss_account_seq:
        return None
    from tossai.toss.client import TossClient

    try:
        with TossClient(settings) as client:
            positions = [p for p in client.get_holdings() if p.quantity > 0]
    except Exception as exc:
        log.warning("briefing holdings fetch failed: %s", exc)
        return None
    if not positions:
        return None

    actions = _latest_advice_actions(settings.reports_dir)
    icon = {"TRIM": "⚠️", "SELL": "🚨", "ADD": "🟢"}
    positions.sort(key=lambda p: p.market_value, reverse=True)
    lines, tot_mv, tot_w = [], 0.0, 0.0
    for p in positions:
        pl = p.pl_rate
        if pl is not None:
            tot_mv += p.market_value
            tot_w += p.market_value * pl
        act = actions.get(p.symbol, "")
        tag = f" {icon.get(act, '')}{act}".rstrip() if act else ""
        pl_s = f"{pl * 100:+.0f}%" if pl is not None else "—"
        lines.append(f"{p.symbol} {pl_s}{tag}")
    avg_pl = tot_w / tot_mv if tot_mv else None
    return {"count": len(positions), "avg_pl": avg_pl, "lines": lines}


def generate_morning_briefing(settings: Settings) -> list[dict]:
    market_label = "+".join(markets_for(settings.briefing_market.value))
    market_open = any_market_open(settings.briefing_market.value)
    vix = get_vix(settings)
    macro_line = ""
    try:
        from tossai.context.provider import MarketContextProvider
        macro_line = MarketContextProvider(settings).macro().as_line()
    except Exception as exc:  # macro is a nice-to-have, never block the briefing
        log.warning("morning briefing macro fetch failed: %s", exc)
    holdings = _holdings_summary(settings)
    try:
        candidates = _screen(settings)
    except Exception as exc:  # never let a data hiccup kill the briefing
        log.warning("morning briefing screening failed: %s", exc)
        candidates = []
    return blocks.morning_briefing_blocks(
        market_label, market_open, vix, settings.vix_blackswan_threshold,
        candidates, datetime.now(UTC).strftime("%Y-%m-%d"),
        macro_line=macro_line, holdings=holdings,
    )


def generate_weekly_briefing(settings: Settings, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    reports = _load_recent_reports(settings.reports_dir, since=now - timedelta(days=7))

    action_counter: Counter[str] = Counter()
    symbol_counter: Counter[str] = Counter()
    confidences: list[float] = []
    for rep in reports:
        for item in rep.get("results", []):
            rec = item.get("recommendation", {})
            action = rec.get("action")
            if action:
                action_counter[action] += 1
            symbol = item.get("candidate", {}).get("symbol")
            if symbol:
                symbol_counter[symbol] += 1
            conf = rec.get("confidence")
            if isinstance(conf, (int, float)):
                confidences.append(float(conf))

    avg_conf = sum(confidences) / len(confidences) if confidences else None
    universe_size = max((r.get("universe_size", 0) for r in reports), default=0)

    return blocks.weekly_briefing_blocks(
        now.strftime("%Y-%m-%d"),
        universe_size,
        dict(action_counter),
        symbol_counter.most_common(5),
        avg_conf,
        get_vix(settings),
        settings.vix_blackswan_threshold,
    )


def _load_recent_reports(reports_dir: str, since: datetime) -> list[dict]:
    out: list[dict] = []
    d = Path(reports_dir)
    if not d.exists():
        return out
    for path in d.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        gen = data.get("generated_at")
        if gen:
            try:
                ts = datetime.fromisoformat(str(gen).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < since:
                    continue
            except ValueError:
                pass
        out.append(data)
    return out
