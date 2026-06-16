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
            ack_text="🟢 전체 분석 실행 중(스크리닝 + Claude)… 잠시 후 결과를 여기에 올립니다.",
            deferred_kind="recommend", args=args,
        )

    if cmd == "screen":
        return CommandResult(
            ack_text="🔎 유니버스 스크리닝 중… 잠시 후 결과를 올립니다.",
            deferred_kind="screen", args=args,
        )

    if cmd == "briefing":
        return CommandResult(
            ack_text="🌅 브리핑 작성 중… 잠시 후 게시합니다.",
            deferred_kind="briefing", args=args,
        )

    return CommandResult(
        inline_blocks=blocks.error_blocks(f"알 수 없는 명령 `/{cmd}`. `/help`를 입력해 보세요.")
    )
