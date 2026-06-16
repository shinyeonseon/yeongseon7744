"""Claude analysis engine.

Forces structured output via a single tool (`submit_recommendation`) so every
response is parseable and schema-valid. One call per candidate keeps retries and
error handling clean. Token usage is accumulated for a soft budget warning.
"""

from __future__ import annotations

import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from tossai.analysis.prompts import (
    RECOMMENDATION_TOOL,
    SYSTEM_PROMPT,
    build_user_message,
)
from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.models import Action, AnalyzedCandidate, Candidate, Recommendation

log = get_logger(__name__)

# Transient API failures worth retrying: timeouts, dropped connections, rate
# limits, and server-side 5xx (InternalServerError). A flaky 500 should not drop
# a candidate/position from the run.
_RETRYABLE = (
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)

# Rough USD per 1M tokens for the soft budget guard (input, output).
_PRICE_PER_MTOK = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (15.0, 75.0),
}


class ClaudeEngine:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None,
                 deep: bool = False):
        self.s = settings
        self.deep = deep
        self.model = settings.claude_model_deep if deep else settings.claude_model
        self._client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def analyze_all(self, candidates: list[Candidate], context=None) -> list[AnalyzedCandidate]:
        out: list[AnalyzedCandidate] = []
        for cand in candidates[: self.s.claude_max_candidates]:
            out.append(self.analyze(cand, context))
        self._budget_check()
        return out

    def analyze(self, candidate: Candidate, context=None) -> AnalyzedCandidate:
        try:
            rec, in_tok, out_tok = self._call(candidate, context)
        except Exception as exc:
            log.warning("Claude analysis failed for %s: %s", candidate.symbol, exc)
            return AnalyzedCandidate(
                candidate=candidate,
                recommendation=Recommendation(
                    action=Action.ANALYSIS_FAILED,
                    confidence=0.0,
                    rationale=f"Analysis failed: {exc}",
                    risks=["analysis_error"],
                ),
            )
        self.total_input_tokens += in_tok
        self.total_output_tokens += out_tok
        return AnalyzedCandidate(
            candidate=candidate, recommendation=rec,
            input_tokens=in_tok, output_tokens=out_tok,
        )

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        reraise=True,
    )
    def _create(self, **kwargs):
        """Single Claude call with transient-failure retry (5xx/timeout/rate-limit)."""
        return self._client.messages.create(**kwargs)

    def _call(self, candidate: Candidate, context=None) -> tuple[Recommendation, int, int]:
        ctx = None
        if context is not None:
            try:
                ctx = context.payload_for(candidate.symbol, candidate.market)
            except Exception as exc:
                log.debug("market context lookup failed for %s: %s", candidate.symbol, exc)
        resp = self._create(
            model=self.model,
            max_tokens=self.s.claude_max_tokens,
            system=SYSTEM_PROMPT,
            tools=[RECOMMENDATION_TOOL],
            tool_choice={"type": "tool", "name": "submit_recommendation"},
            messages=[{"role": "user", "content": build_user_message(candidate, ctx)}],
        )
        rec = _extract_recommendation(resp)
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        return rec, in_tok, out_tok

    def analyze_position(self, position, signals: dict):
        """Advise on a held position (ADD/HOLD/TRIM/SELL). Analysis-only."""
        from tossai.analysis.portfolio_prompts import (
            POSITION_TOOL,
            build_position_message,
        )
        from tossai.analysis.portfolio_prompts import (
            SYSTEM_PROMPT as POS_SYSTEM,
        )
        from tossai.models import AnalyzedPosition, PortfolioAction, PositionAdvice

        try:
            resp = self._create(
                model=self.model,
                max_tokens=self.s.claude_max_tokens,
                system=POS_SYSTEM,
                tools=[POSITION_TOOL],
                tool_choice={"type": "tool", "name": "submit_position_advice"},
                messages=[{"role": "user", "content": build_position_message(position, signals)}],
            )
            advice = None
            for block in getattr(resp, "content", []) or []:
                if getattr(block, "type", None) == "tool_use":
                    advice = PositionAdvice.model_validate(block.input)
                    break
            if advice is None:
                raise ValueError("no submit_position_advice tool_use block")
            usage = getattr(resp, "usage", None)
            in_tok = getattr(usage, "input_tokens", 0) or 0
            out_tok = getattr(usage, "output_tokens", 0) or 0
        except Exception as exc:
            log.warning("position analysis failed for %s: %s", position.symbol, exc)
            return AnalyzedPosition(
                position=position,
                advice=PositionAdvice(
                    action=PortfolioAction.ANALYSIS_FAILED, confidence=0.0,
                    rationale=f"Analysis failed: {exc}", risks=["analysis_error"],
                ),
            )
        self.total_input_tokens += in_tok
        self.total_output_tokens += out_tok
        return AnalyzedPosition(
            position=position, advice=advice, input_tokens=in_tok, output_tokens=out_tok,
        )

    def estimated_cost_usd(self) -> float:
        price_in, price_out = _PRICE_PER_MTOK.get(self.model, (3.0, 15.0))
        return (
            self.total_input_tokens / 1_000_000 * price_in
            + self.total_output_tokens / 1_000_000 * price_out
        )

    def _budget_check(self) -> None:
        budget = self.s.claude_monthly_budget_usd
        if budget > 0 and self.estimated_cost_usd() >= budget * 0.8:
            log.warning(
                "Claude spend this run ~$%.4f is approaching the configured "
                "monthly budget $%.2f (this is a soft warning only).",
                self.estimated_cost_usd(), budget,
            )


def _extract_recommendation(resp: object) -> Recommendation:
    """Pull the forced tool_use block out of the response and validate it."""
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_recommendation":
            return Recommendation.model_validate(block.input)
    raise ValueError("no submit_recommendation tool_use block in Claude response")
