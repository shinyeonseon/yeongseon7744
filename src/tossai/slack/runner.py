"""Deferred (heavy) work for slash commands.

The pipeline is synchronous (Toss + Claude). These functions are called from the
server inside ``asyncio.to_thread`` so the event loop stays responsive, then the
result is posted back to the slash command's response_url.

Analysis-only: only read/screen/analyze flows are reachable here.
"""

from __future__ import annotations

from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.slack import blocks
from tossai.slack.web_client import SlackClient

log = get_logger(__name__)

# Per-(channel, user) conversation memory for 박부장, for the serve process lifetime.
_CONV = None


def _conversation_store():
    global _CONV
    if _CONV is None:
        from tossai.agent.advisor import ConversationStore
        _CONV = ConversationStore()
    return _CONV


def execute_kind(
    settings: Settings, kind: str, args: list[str] | None = None, meta: dict | None = None,
) -> list[dict]:
    """Run the work for a deferred command kind and return Slack blocks."""
    if kind == "advisor":
        from tossai.agent.advisor import Advisor

        meta = meta or {}
        question = meta.get("text") or " ".join(args or [])
        key = f"{meta.get('channel_id', '')}:{meta.get('user_id', '')}"
        store = _conversation_store()
        text, history = Advisor(settings).answer(question, store.get(key))
        store.set(key, history)
        return blocks.advisor_blocks(text)

    if kind == "screen":
        from tossai.pipeline.orchestrator import Orchestrator
        from tossai.toss.client import TossClient

        with TossClient(settings) as client:
            candidates = Orchestrator(settings, client).screen_only()
        return blocks.screen_blocks(candidates)

    if kind == "recommend":
        from tossai.analysis.claude_engine import ClaudeEngine
        from tossai.pipeline.orchestrator import Orchestrator
        from tossai.toss.client import TossClient

        with TossClient(settings) as client:
            engine = ClaudeEngine(settings)
            report = Orchestrator(settings, client, engine=engine).run_once(force=True)
        return blocks.report_blocks(report, settings.alert_min_confidence)

    if kind == "briefing":
        from tossai.scheduler.briefings import generate_morning_briefing

        return generate_morning_briefing(settings)

    return blocks.error_blocks(f"알 수 없는 작업 종류: {kind}")


def run_and_respond(
    settings: Settings, slack_client: SlackClient, response_url: str,
    kind: str, args: list[str] | None = None, meta: dict | None = None,
) -> None:
    """Execute a deferred command and post the result to response_url.

    Never raises: failures are reported back to the user as an error message.
    """
    try:
        result_blocks = execute_kind(settings, kind, args, meta)
    except Exception as exc:  # noqa: BLE001 - report any failure to the user
        log.exception("deferred %s failed: %s", kind, exc)
        result_blocks = blocks.error_blocks(f"`/{kind}` failed: {exc}")
    slack_client.respond(response_url, result_blocks, response_type="in_channel")
