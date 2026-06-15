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
    "momentum/trend.\n"
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
                "description": "Concise reasoning grounded in the provided signals.",
            },
            "risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Concrete risks to this view.",
            },
            "time_horizon": {
                "type": "string",
                "description": "e.g. 'days', 'weeks', '1-3 months'.",
            },
        },
        "required": ["action", "confidence", "rationale", "risks"],
    },
}


def build_user_message(candidate: Candidate) -> str:
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
    return (
        "Analyze this single candidate and call submit_recommendation.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
