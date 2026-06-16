"""FastAPI app for inbound Slack slash commands.

Flow per request:
  1. read raw body (needed verbatim for HMAC)
  2. verify Slack signature (reject 401 on failure/stale)
  3. parse form payload, dedupe Slack retries
  4. dispatch: fast commands answer inline; heavy commands ack immediately and
     run off the event loop, posting results to response_url.
"""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.slack import runner
from tossai.slack.commands import dispatch_command
from tossai.slack.signature import verify_slack_signature
from tossai.slack.web_client import SlackClient

log = get_logger(__name__)


def create_app(settings: Settings, slack_client: SlackClient | None = None) -> FastAPI:
    app = FastAPI(title="tossai-slack", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.slack = slack_client or SlackClient(settings.slack_bot_token)
    app.state.semaphore = asyncio.Semaphore(max(1, settings.slack_max_concurrent_runs))
    app.state.tasks = set()
    app.state.seen_triggers = set()  # idempotency for Slack retries

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/slack/commands")
    async def slash_commands(request: Request) -> Response:
        raw = await request.body()
        ts = request.headers.get("X-Slack-Request-Timestamp")
        sig = request.headers.get("X-Slack-Signature")
        if not verify_slack_signature(settings.slack_signing_secret, ts, raw, sig):
            return JSONResponse({"error": "invalid signature"}, status_code=401)

        # Parse the urlencoded body directly (avoids a python-multipart dep and
        # reuses the raw bytes already read for signature verification).
        payload = {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
        command = payload.get("command", "")
        response_url = payload.get("response_url", "")
        trigger_id = payload.get("trigger_id", "")

        # Idempotency: Slack retries timed-out requests with the same trigger_id.
        if trigger_id and trigger_id in app.state.seen_triggers:
            return JSONResponse({"response_type": "ephemeral", "text": "(already processing)"})
        if trigger_id:
            app.state.seen_triggers.add(trigger_id)

        result = dispatch_command(command, payload, settings)

        if result.inline_blocks is not None:
            return JSONResponse(
                {"response_type": result.response_type, "blocks": result.inline_blocks}
            )

        # Deferred: schedule heavy work, ack immediately.
        if result.deferred_kind and response_url:
            task = asyncio.create_task(
                _run_deferred(app, response_url, result.deferred_kind, result.args, result.meta)
            )
            app.state.tasks.add(task)
            task.add_done_callback(app.state.tasks.discard)

        return JSONResponse(
            {"response_type": "ephemeral", "text": result.ack_text or "처리 중…"}
        )

    return app


async def _run_deferred(
    app: FastAPI, response_url: str, kind: str, args: list[str], meta: dict | None = None,
) -> None:
    settings: Settings = app.state.settings
    async with app.state.semaphore:
        await asyncio.to_thread(
            runner.run_and_respond, settings, app.state.slack, response_url, kind, args, meta
        )
