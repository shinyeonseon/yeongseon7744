"""APScheduler wiring: morning/weekly briefings + recurring risk scan.

Jobs run on the same event loop as the Slack server (AsyncIOScheduler) and push
their blocking work to threads so the loop stays responsive. All output is
analysis-only Slack messages.
"""

from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.market.calendar import (
    _HOURS,
    is_holiday,
    markets_for,
    now_in_market,
)
from tossai.risk.evaluators import evaluate_blackswan, evaluate_gap_down
from tossai.risk.sentiment import get_vix
from tossai.risk.state import AlertDeduper
from tossai.scheduler.briefings import (
    generate_morning_briefing,
    generate_weekly_briefing,
)
from tossai.slack import blocks
from tossai.slack.web_client import SlackClient

log = get_logger(__name__)


def _briefing_tz(settings: Settings):
    markets = markets_for(settings.briefing_market.value)
    # Use the first market's timezone (KST for KRX, US-Eastern for US).
    return _HOURS[markets[0]][2]


def _parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def _is_trading_day(settings: Settings) -> bool:
    for market in markets_for(settings.briefing_market.value):
        local = now_in_market(market)
        if local.weekday() < 5 and not is_holiday(market, local):
            return True
    return False


def build_scheduler(settings: Settings, slack_client: SlackClient) -> AsyncIOScheduler:
    tz = _briefing_tz(settings)
    sched = AsyncIOScheduler(timezone=tz)
    deduper = AlertDeduper(settings.reports_dir)

    mh, mm = _parse_hhmm(settings.briefing_morning_time)
    sched.add_job(
        _morning_job, "cron", hour=mh, minute=mm, timezone=tz,
        args=[settings, slack_client], id="morning_briefing",
    )

    wh, wm = _parse_hhmm(settings.briefing_weekly_time)
    sched.add_job(
        _weekly_job, "cron", day_of_week=settings.briefing_weekly_day.lower(),
        hour=wh, minute=wm, timezone=tz,
        args=[settings, slack_client], id="weekly_briefing",
    )

    sched.add_job(
        _risk_job, "interval", minutes=max(1, settings.risk_scan_interval_min),
        args=[settings, slack_client, deduper], id="risk_scan",
    )

    if settings.portfolio_schedule_enabled:
        ph, pm = _parse_hhmm(settings.portfolio_schedule_time)
        sched.add_job(
            _portfolio_job, "cron", day_of_week="mon-fri", hour=ph, minute=pm, timezone=tz,
            args=[settings, slack_client], id="portfolio_advice",
        )
    return sched


async def _morning_job(settings: Settings, slack: SlackClient) -> None:
    if not _is_trading_day(settings):
        log.info("morning briefing skipped (not a trading day)")
        return
    bs = await asyncio.to_thread(generate_morning_briefing, settings)
    await asyncio.to_thread(slack.post_message, settings.slack_channel, bs, "Morning briefing")


async def _weekly_job(settings: Settings, slack: SlackClient) -> None:
    bs = await asyncio.to_thread(generate_weekly_briefing, settings)
    await asyncio.to_thread(slack.post_message, settings.slack_channel, bs, "Weekly briefing")


async def _portfolio_job(settings: Settings, slack: SlackClient) -> None:
    if not _is_trading_day(settings):
        log.info("portfolio advice skipped (not a trading day)")
        return
    report = await asyncio.to_thread(_run_portfolio, settings)
    if report is None or not report.results:
        log.info("portfolio advice: nothing to push")
        return
    bs = blocks.portfolio_blocks(report, settings.alert_min_confidence)
    await asyncio.to_thread(slack.post_message, settings.slack_channel, bs, "Portfolio advice")


def _run_portfolio(settings: Settings):
    """Blocking: analyze held positions, return the PortfolioReport (or None)."""
    from tossai.analysis.claude_engine import ClaudeEngine
    from tossai.portfolio.analyzer import PortfolioAnalyzer
    from tossai.toss.client import TossClient

    try:
        with TossClient(settings) as client:
            engine = ClaudeEngine(settings)
            return PortfolioAnalyzer(settings, client, engine).run()
    except Exception as exc:
        log.warning("portfolio advice run failed: %s", exc)
        return None


async def _risk_job(settings: Settings, slack: SlackClient, deduper: AlertDeduper) -> None:
    alerts = await asyncio.to_thread(_scan_risk, settings)
    for alert in alerts:
        if deduper.should_send(alert):
            await asyncio.to_thread(
                slack.post_message, settings.slack_channel,
                blocks.risk_alert_blocks(alert), "Risk alert",
            )


def _scan_risk(settings: Settings) -> list:
    """Blocking risk scan: VIX blackswan + per-symbol gap-down. Returns alerts."""
    from tossai.market.universe import load_universe
    from tossai.toss.client import TossClient

    found = []
    vix = get_vix(settings)
    bs = evaluate_blackswan(vix, settings.vix_blackswan_threshold)
    if bs:
        found.append(bs)

    if not _is_trading_day(settings):
        return found

    symbols = load_universe(settings.universe_file, settings.briefing_market.value)
    try:
        with TossClient(settings) as client:
            for sym in symbols:
                try:
                    candles = client.get_candles(sym.symbol)
                except Exception as exc:
                    log.debug("risk scan candle fetch failed for %s: %s", sym.symbol, exc)
                    continue
                gd = evaluate_gap_down(sym.symbol, candles, settings.gap_down_pct)
                if gd:
                    found.append(gd)
    except Exception as exc:
        log.warning("risk scan failed: %s", exc)
    return found
