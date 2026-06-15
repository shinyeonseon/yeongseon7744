"""Slash-command dispatch.

Pure mapping from a command to a plan: either inline blocks (fast commands) or
a deferred ``kind`` the server runs off the event loop and posts to response_url.
Keeping this server-agnostic makes it unit-testable without a web framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tossai.config import Settings
from tossai.slack import blocks

# Deferred kinds the runner knows how to execute.
DEFERRED_KINDS = {"recommend", "screen", "briefing"}


@dataclass
class CommandResult:
    # Immediate response: either inline blocks (fast) or an ack for deferred work.
    inline_blocks: list[dict] | None = None
    ack_text: str | None = None
    deferred_kind: str | None = None
    response_type: str = "ephemeral"
    args: list[str] = field(default_factory=list)


def dispatch_command(name: str, payload: dict, settings: Settings) -> CommandResult:
    cmd = (name or "").lstrip("/").strip().lower()
    args = (payload.get("text") or "").split()

    if cmd in ("help", ""):
        return CommandResult(inline_blocks=blocks.help_blocks())

    if cmd == "status":
        return CommandResult(inline_blocks=blocks.status_blocks(settings.redacted_summary()))

    if cmd == "recommend":
        return CommandResult(
            ack_text="🟢 Running full analysis (screening + Claude)… results will post here shortly.",
            deferred_kind="recommend", args=args,
        )

    if cmd == "screen":
        return CommandResult(
            ack_text="🔎 Screening the universe… results shortly.",
            deferred_kind="screen", args=args,
        )

    if cmd == "briefing":
        return CommandResult(
            ack_text="🌅 Building the briefing… posting shortly.",
            deferred_kind="briefing", args=args,
        )

    return CommandResult(
        inline_blocks=blocks.error_blocks(f"Unknown command `/{cmd}`. Try `/help`.")
    )
