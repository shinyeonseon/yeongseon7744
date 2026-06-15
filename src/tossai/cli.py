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
