"""박부장 — a conversational investment-desk persona over the user's own data.

A Claude tool-use agent: it answers questions by calling read-only tools
(holdings + advice, latest picks, realized performance, live quotes) and
reasoning over the results. Analysis-only — it never places an order. Multi-turn
history can be passed in/out so the same conversation continues across calls.
"""

from __future__ import annotations

import time

import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from tossai.agent.tools import ADVISOR_TOOLS, AdvisorContext, run_tool
from tossai.analysis.claude_engine import _RETRYABLE
from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.models import DISCLAIMER

log = get_logger(__name__)

PERSONA = (
    "당신은 '박부장'입니다. 한국 증권사의 베테랑 투자부장으로, 사용자의 실제 포트폴리오와 후보·성과 "
    "데이터를 꿰뚫고 있는 노련한 자문역입니다.\n"
    "원칙:\n"
    "- 항상 한국어로, 간결하고 직설적으로 답합니다. 군더더기 없이 핵심부터.\n"
    "- 추측하지 말고 도구로 실제 데이터를 확인한 뒤 근거를 들어 말합니다. "
    "보유/후보/성과/시세 질문은 물론, 시장 현황·분위기 질문이면 market_overview, "
    "특정 종목 이슈·뉴스 질문이면 news 도구를 먼저 부르세요.\n"
    "- 기회와 함께 리스크를 반드시 짚습니다. 확신도가 낮으면 낮다고 솔직히 말합니다.\n"
    "- 분석·의견만 제공합니다. 주문을 실행하거나 매매를 지시·대행하지 않습니다.\n"
    "- 데이터가 없으면 없다고 말하고, 무엇을 실행하면 채워지는지 안내합니다.\n"
    f"필요시 다음을 상기시키세요: {DISCLAIMER}"
)

MAX_STEPS = 6  # tool-use rounds before forcing a final answer


class Advisor:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None):
        self.s = settings
        self.model = settings.claude_model
        self._client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        reraise=True,
    )
    def _create(self, **kwargs):
        return self._client.messages.create(**kwargs)

    def answer(self, message: str, history: list[dict] | None = None) -> tuple[str, list[dict]]:
        """Answer one user turn. Returns (text, updated_history).

        `history` is a list of Anthropic message dicts (role + content blocks);
        pass the returned list back in to continue the conversation.
        """
        messages = list(history or [])
        messages.append({"role": "user", "content": message})
        ctx = AdvisorContext(self.s)
        try:
            for _ in range(MAX_STEPS):
                resp = self._create(
                    model=self.model,
                    max_tokens=self.s.claude_max_tokens,
                    system=PERSONA,
                    tools=ADVISOR_TOOLS,
                    messages=messages,
                )
                content = [_block_dict(b) for b in resp.content]
                messages.append({"role": "assistant", "content": content})

                if resp.stop_reason != "tool_use":
                    return _text_of(content), messages

                results = []
                for block in content:
                    if block.get("type") == "tool_use":
                        out = run_tool(block["name"], block.get("input") or {}, ctx)
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": out,
                        })
                messages.append({"role": "user", "content": results})

            return "정리할 시간이 더 필요합니다. 질문을 좁혀 다시 물어봐 주세요.", messages
        finally:
            ctx.close()


def _block_dict(block) -> dict:
    """Normalize an Anthropic content block (SDK object or dict) to a dict."""
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return {"type": getattr(block, "type", "text"), "text": getattr(block, "text", "")}


def _text_of(content: list[dict]) -> str:
    parts = [b.get("text", "") for b in content if b.get("type") == "text"]
    return "\n".join(p for p in parts if p).strip() or "(응답이 비어 있습니다)"


class ConversationStore:
    """In-process, per-key conversation memory with size + TTL caps.

    Keyed by (channel, user) for Slack so concurrent users don't cross streams.
    Lives only as long as the serve process — fine for short back-and-forth.
    """

    def __init__(self, max_turns: int = 12, ttl_sec: int = 3600):
        self.max_turns = max_turns
        self.ttl_sec = ttl_sec
        self._store: dict[str, tuple[float, list[dict]]] = {}

    def get(self, key: str) -> list[dict]:
        item = self._store.get(key)
        if not item:
            return []
        stamp, history = item
        if time.time() - stamp > self.ttl_sec:
            self._store.pop(key, None)
            return []
        return history

    def set(self, key: str, history: list[dict]) -> None:
        self._store[key] = (time.time(), history[-self.max_turns:])

    def reset(self, key: str) -> None:
        self._store.pop(key, None)
