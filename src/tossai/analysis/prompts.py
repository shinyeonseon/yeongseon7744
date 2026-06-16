"""Prompt templates and the structured-output tool schema for Claude."""

from __future__ import annotations

import json

from tossai.models import Candidate

SYSTEM_PROMPT = (
    "You are a disciplined equity analyst supporting an automated, "
    "analysis-only research tool. You receive a single stock candidate together "
    "with deterministic technical signals that were already computed upstream. "
    "Your job is to weigh those signals and produce ONE structured "
    "recommendation.\n\n"
    "Rules:\n"
    "- This is informational analysis, NOT financial advice. Never advise "
    "leverage or guarantee outcomes.\n"
    "- Reason from the numeric signals provided; do not invent data you were "
    "not given.\n"
    "- Always state concrete risks.\n"
    "- Set confidence honestly: low when signals conflict or history is thin.\n"
    "- A target_price should be consistent with the latest price and ATR; use "
    "null if you cannot justify one.\n"
    "- A candidate may be flagged by multiple strategies (see 'flagged_by'); "
    "treat agreement across strategies as corroborating, but still reason from "
    "the numeric signals and do not assume more history than provided. Buckets: "
    "'swing' = shorter-term technical setup, 'long' = longer-horizon "
    "momentum/trend, 'value' = fundamental value/quality (Graham, Magic Formula, "
    "Buffett, Piotroski).\n"
    "- Signal keys are namespaced by strategy (e.g. 'graham.per', "
    "'buffett_quality.roe', 'magic_formula.earnings_yield'). Fundamental data may "
    "be absent for some markets/symbols; if so, simply rely on what is present.\n"
    "- 'market_context' may include recent news headlines, the next earnings date, "
    "and a macro backdrop (indicators, upcoming events like FOMC). Treat it as "
    "qualitative reference only: let the numeric signals drive the call, flag an "
    "imminent earnings date or major macro event as a risk/timing note, and never "
    "over-trust a single headline. It is often absent — then ignore it.\n"
    "- LANGUAGE (REQUIRED): write `rationale`, `key_points`, and `risks` in "
    "natural Korean (반드시 한국어로 작성). Keep ticker symbols, action codes, and "
    "numbers as-is. Do NOT answer in English.\n"
    "- BE CONCISE: `rationale` is ONE headline sentence; put the substance in "
    "`key_points` as a few short, scannable bullets (each one line). Do NOT write "
    "long paragraphs.\n"
    "- You MUST respond by calling the submit_recommendation tool exactly once."
)

# The single tool that forces parseable, schema-valid output.
RECOMMENDATION_TOOL = {
    "name": "submit_recommendation",
    "description": "Submit the final structured recommendation for this candidate.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["BUY", "HOLD", "SELL"],
                "description": "The recommended action.",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidence in the recommendation, 0.0–1.0.",
            },
            "target_price": {
                "type": ["number", "null"],
                "description": "Price target consistent with price+ATR, or null.",
            },
            "rationale": {
                "type": "string",
                "description": "한 줄 핵심 요약(120자 이내, 한국어). 줄글 금지.",
            },
            "key_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "가장 중요한 근거 2~4개. 각 항목은 한 줄(90자 이내) 한국어 "
                               "불릿. '라벨: 내용' 형태로 간결하게. 문단 쓰지 말 것.",
            },
            "risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "구체적 리스크 1~3개. 각 항목 한 줄(70자 이내) 한국어.",
            },
            "time_horizon": {
                "type": "string",
                "description": "e.g. 'days', 'weeks', '1-3 months'.",
            },
        },
        "required": ["action", "confidence", "rationale", "key_points", "risks"],
    },
}


def build_user_message(candidate: Candidate, context: dict | None = None) -> str:
    """Pass signals as structured JSON, not free prose, so Claude reasons over
    the actual numbers the screener computed."""
    payload = {
        "symbol": candidate.symbol,
        "market": candidate.market,
        "name": candidate.name,
        "latest_price": candidate.price,
        "screen_score": candidate.score,
        "strategy": candidate.strategy,
        "bucket": candidate.bucket,
        "flagged_by": candidate.flagged_by,
        "atr": candidate.atr,
        "technical_signals": candidate.signals,
    }
    if context:
        payload["market_context"] = context
    return (
        "Analyze this single candidate and call submit_recommendation. "
        "rationale와 risks는 반드시 한국어로 작성하세요.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
