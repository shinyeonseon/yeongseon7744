"""Command-line interface.

Commands:
  doctor       validate config + connectivity (no orders, near-zero cost)
  screen-only  run screening, skip Claude (free dry-run)
  run-once     one full pipeline pass, then exit (ideal for cron/systemd)
  run-loop     loop on an interval, acting only during market hours
"""

from __future__ import annotations

import time

import typer

from tossai.config import get_settings
from tossai.logging_setup import get_logger, setup_logging

app = typer.Typer(add_completion=False, help="Toss Securities investment AI (analysis-only).")
log = get_logger(__name__)


def _boot(deep: bool = False):
    """Common startup: settings, safety guard, logging. Returns (settings, engine_deep)."""
    settings = get_settings()
    settings.enforce_safety()  # refuses to run if ENABLE_TRADING=true
    setup_logging(settings.log_level, settings.log_file)
    return settings


@app.command()
def doctor() -> None:
    """Check configuration and connectivity without placing orders."""
    settings = _boot()
    log.info("config: %s", settings.redacted_summary())

    ok = True
    # 1. Toss token + one quote call.
    try:
        from tossai.toss.client import TossClient

        with TossClient(settings) as client:
            client.auth.get_token()
            log.info("Toss OAuth token acquired ✓")
            # A single, cheap read to confirm the schema parses.
            sample = "005930" if settings.market.value != "US" else "AAPL"
            quote = client.get_quote(sample)
            log.info("Toss quote(%s) ✓ price=%s", sample, quote.price)
    except Exception as exc:
        ok = False
        log.error("Toss check failed: %s", exc)

    # 2. Anthropic key presence (no paid call here).
    if not settings.anthropic_api_key:
        ok = False
        log.error("ANTHROPIC_API_KEY is not set")
    else:
        log.info("Anthropic API key present ✓")

    if ok:
        log.info("doctor: all checks passed")
    else:
        log.error("doctor: some checks failed (see above)")
        raise typer.Exit(code=1)


@app.command("screen-only")
def screen_only(
    strategy: str = typer.Option(None, "--strategy", help="Override STRATEGY (comma list)."),
) -> None:
    """Run screening only (no Claude, no cost)."""
    settings = _boot()
    if strategy:
        settings.strategy = strategy
    from tossai.pipeline.orchestrator import Orchestrator
    from tossai.toss.client import TossClient

    with TossClient(settings) as client:
        orch = Orchestrator(settings, client)
        candidates = orch.screen_only()
    if not candidates:
        typer.echo("No candidates passed screening.")
        return
    typer.echo(f"{len(candidates)} candidate(s):")
    for c in candidates:
        flagged = ",".join(c.flagged_by) or (c.strategy or "-")
        typer.echo(
            f"  {c.symbol:<8} [{c.market}] score={c.score:.3f} "
            f"bucket={c.bucket or '-'} by={flagged} price={c.price}"
        )


@app.command("run-once")
def run_once(
    force: bool = typer.Option(False, "--force", help="Send alerts even if market is closed."),
    deep: bool = typer.Option(False, "--deep", help="Use the deeper Claude model."),
    strategy: str = typer.Option(None, "--strategy", help="Override STRATEGY (comma list)."),
) -> None:
    """Run one full analysis pass and exit."""
    settings = _boot()
    if strategy:
        settings.strategy = strategy
    from tossai.analysis.claude_engine import ClaudeEngine
    from tossai.pipeline.orchestrator import Orchestrator
    from tossai.toss.client import TossClient

    with TossClient(settings) as client:
        engine = ClaudeEngine(settings, deep=deep)
        orch = Orchestrator(settings, client, engine=engine)
        report = orch.run_once(force=force)
    typer.echo(f"Done. screened={report.screened_count} cost~${report.estimated_cost_usd:.4f}")


@app.command()
def portfolio(
    deep: bool = typer.Option(False, "--deep", help="Use the deeper Claude model."),
    slack: bool = typer.Option(
        True, "--slack/--no-slack",
        help="Push advice to Slack when ALERT_CHANNELS includes 'slack'."),
) -> None:
    """Advise ADD/HOLD/TRIM/SELL on your held Toss positions (no orders)."""
    settings = _boot()
    from tossai.analysis.claude_engine import ClaudeEngine
    from tossai.output import alerts
    from tossai.output import portfolio_report as pr
    from tossai.portfolio.analyzer import PortfolioAnalyzer
    from tossai.toss.client import TossClient

    if not settings.toss_account_seq:
        log.warning("TOSS_ACCOUNT_SEQ is not set — holdings call needs it. "
                    "Find it via `accounts` (accountSeq) and set it in .env.")
    with TossClient(settings) as client:
        engine = ClaudeEngine(settings, deep=deep)
        report = PortfolioAnalyzer(settings, client, engine).run()
    typer.echo(pr.console_table(report))
    pr.save_report(report, settings.reports_dir)
    if slack:
        alerts.dispatch_portfolio(settings, report)


@app.command()
def backtest(
    years: float = typer.Option(3.0, "--years", help="Years of history to fetch."),
    rebalance: int = typer.Option(21, "--rebalance", help="Rebalance every N trading days."),
    top: int = typer.Option(10, "--top", help="Hold the top-N candidates each rebalance."),
    weighting: str = typer.Option(
        None, "--weighting", help="equal | inverse_vol. Default from config."),
    cost_bps: float = typer.Option(
        None, "--cost-bps", help="Trading cost per turnover unit (bps). Default from config."),
    trend_filter: bool = typer.Option(
        None, "--trend-filter/--no-trend-filter",
        help="De-risk holdings below their trailing MA to cash. Default from config."),
    trend_ma: int = typer.Option(
        None, "--trend-ma", help="Trailing MA window for the trend filter. Default from config."),
    vol_target: float = typer.Option(
        None, "--vol-target",
        help="Annualized volatility target (e.g. 0.15); scales exposure to cash. "
             "0 disables. Default from config."),
    vol_lookback: int = typer.Option(
        None, "--vol-lookback", help="Lookback window for realized vol. Default from config."),
    max_per_sector: int = typer.Option(
        None, "--max-per-sector",
        help="Cap held names per sector (needs sector: in universe.yaml). 0=off. "
             "Default from config."),
) -> None:
    """Walk-forward backtest of the strategy ensemble (no Claude, no orders)."""
    settings = _boot()
    from tossai.backtest.engine import walk_forward_backtest
    from tossai.market.universe import load_universe
    from tossai.screening.strategies.ensemble import build_strategy
    from tossai.toss.client import TossClient

    symbols = load_universe(settings.universe_file, settings.market.value)
    sector_map = {s.symbol: s.sector for s in symbols if s.sector}
    strategy = build_strategy(settings)
    count = max(int(years * 252) + 10, getattr(strategy, "required_history", 260) + 10)

    candle_map: dict = {}
    markets: dict = {}
    with TossClient(settings) as client:
        for sym in symbols:
            try:
                candle_map[sym.symbol] = client.get_candles(sym.symbol, count=count)
                markets[sym.symbol] = sym.market
            except Exception as exc:
                log.warning("backtest candle fetch failed for %s: %s", sym.symbol, exc)

    result = walk_forward_backtest(
        candle_map, strategy, markets,
        rebalance_days=rebalance, top_n=top,
        weighting=settings.backtest_weighting if weighting is None else weighting,
        risk_parity_lookback=settings.risk_parity_lookback,
        cost_bps=settings.backtest_cost_bps if cost_bps is None else cost_bps,
        trend_filter=settings.backtest_trend_filter if trend_filter is None else trend_filter,
        trend_ma=settings.backtest_trend_ma if trend_ma is None else trend_ma,
        vol_target=settings.backtest_vol_target if vol_target is None else vol_target,
        vol_lookback=settings.backtest_vol_lookback if vol_lookback is None else vol_lookback,
        sector_map=sector_map,
        max_per_sector=settings.max_per_sector if max_per_sector is None else max_per_sector,
    )
    if sector_map:
        typer.echo(f"(sector cap: ≤{settings.max_per_sector if max_per_sector is None else max_per_sector}"
                   f"/sector, {len(set(sector_map.values()))} sectors labeled)")
    else:
        typer.echo("(no sector labels in universe.yaml — sector cap inactive; add `sector:` to enable)")
    typer.echo(result.summary())


@app.command()
def track(
    horizons: str = typer.Option("5,21,63", "--horizons", help="Forward trading-day horizons."),
    primary: int = typer.Option(21, "--primary", help="Horizon used for per-action/confidence stats."),
    min_confidence: float = typer.Option(
        0.0, "--min-confidence", help="Only score recommendations at/above this confidence."),
) -> None:
    """Score past recommendations against later prices (did they add alpha?)."""
    settings = _boot()
    from tossai.performance import ledger, tracker
    from tossai.toss.client import TossClient

    seeded = ledger.backfill_from_reports(settings.reports_dir)
    if seeded:
        log.info("ledger backfilled %d records from saved reports", seeded)
    records = ledger.load_ledger(settings.reports_dir)
    if not records:
        typer.echo("No recommendations logged yet (run `run-once` a few times first).")
        return

    hs = tuple(int(x) for x in horizons.split(",") if x.strip())
    need = max(hs) + 5
    symbols = sorted({r.symbol for r in records})
    candle_map: dict = {}
    with TossClient(settings) as client:
        for sym in symbols:
            try:
                candle_map[sym] = client.get_candles(sym, count=settings.resolved_candle_count(need))
            except Exception as exc:
                log.warning("track candle fetch failed for %s: %s", sym, exc)

    summary = tracker.evaluate(records, candle_map, horizons=hs,
                               primary_horizon=primary, min_confidence=min_confidence)
    typer.echo(tracker.summary_table(summary))


@app.command("run-loop")
def run_loop(
    deep: bool = typer.Option(False, "--deep", help="Use the deeper Claude model."),
) -> None:
    """Loop forever, running a pass each interval, only while a market is open."""
    settings = _boot()
    from tossai.analysis.claude_engine import ClaudeEngine
    from tossai.market.calendar import any_market_open
    from tossai.pipeline.orchestrator import Orchestrator
    from tossai.toss.client import TossClient

    interval_s = max(settings.loop_interval_min, 1) * 60
    log.info("starting run-loop; interval=%dmin market=%s", settings.loop_interval_min,
             settings.market.value)
    while True:
        if any_market_open(settings.market.value):
            try:
                with TossClient(settings) as client:
                    engine = ClaudeEngine(settings, deep=deep)
                    Orchestrator(settings, client, engine=engine).run_once()
            except Exception as exc:
                log.exception("run-once iteration failed: %s", exc)
        else:
            log.info("market closed; sleeping")
        time.sleep(interval_s)


@app.command()
def serve() -> None:
    """Run the Slack interactive server + briefing/risk scheduler (long-lived)."""
    settings = _boot()  # enforce_safety() + logging, same as every command
    import uvicorn

    from tossai.scheduler.jobs import build_scheduler
    from tossai.slack.server import create_app
    from tossai.slack.web_client import SlackClient

    if not settings.slack_signing_secret or not settings.slack_bot_token:
        log.warning(
            "SLACK_SIGNING_SECRET / SLACK_BOT_TOKEN not set — slash commands and "
            "proactive posts will fail until configured."
        )

    slack_client = SlackClient(settings.slack_bot_token)
    fastapi_app = create_app(settings, slack_client=slack_client)
    scheduler = build_scheduler(settings, slack_client)

    @fastapi_app.on_event("startup")
    async def _start_scheduler() -> None:
        scheduler.start()
        log.info("scheduler started with %d jobs", len(scheduler.get_jobs()))

    @fastapi_app.on_event("shutdown")
    async def _stop_scheduler() -> None:
        scheduler.shutdown(wait=False)

    log.info("serving Slack app on %s:%d", settings.slack_app_host, settings.slack_app_port)
    uvicorn.run(fastapi_app, host=settings.slack_app_host, port=settings.slack_app_port,
                log_level=settings.log_level.lower())


if __name__ == "__main__":
    app()
