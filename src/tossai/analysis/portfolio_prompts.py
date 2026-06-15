"""Position-aware prompt + tool for advising on a held position.

Analysis-only: produces ADD/HOLD/TRIM/SELL advice with reasoning. No orders.
"""

from __future__ import annotations

import json

from tossai.models import Position

SYSTEM_PROMPT = (
    "You are a disciplined portfolio analyst for an automated, analysis-only "
    "tool. You receive ONE position the user already holds — its average cost, "
    "current price, unrealized P&L, quantity — together with deterministic "
    "technical/fundamental signals. Advise whether to ADD (buy more), HOLD, "
    "TRIM (reduce), or SELL (exit), reasoning from cost basis, current P&L, and "
    "the signals.\n\n"
    "Rules:\n"
    "- This is informational analysis, NOT financial advice. No orders are placed.\n"
    "- Weigh the entry (average cost) vs current price and the signals; do not "
    "invent data you were not given.\n"
    "- Beware anchoring: a large gain is not automatically SELL, a loss is not "
    "automatically ADD. Judge forward prospects from the signals.\n"
    "- Always state concrete risks; set confidence honestly.\n"
    "- You MUST respond by calling submit_position_advice exactly once."
)

POSITION_TOOL = {
    "name": "submit_position_advice",
    "description": "Submit the action for this held position.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["ADD", "HOLD", "TRIM", "SELL"],
                "description": "ADD=buy more, HOLD=keep, TRIM=reduce, SELL=exit.",
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "target_price": {"type": ["number", "null"]},
            "rationale": {"type": "string"},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "confidence", "rationale", "risks"],
    },
}


def build_position_message(position: Position, signals: dict) -> str:
    payload = {
        "symbol": position.symbol,
        "market": position.market,
        "name": position.name,
        "quantity": position.quantity,
        "average_cost": position.avg_price,
        "current_price": position.last_price,
        "unrealized_pl_rate": position.pl_rate,  # fraction, 0.2 == +20%
        "market_value": position.market_value,
        "currency": position.currency,
        "signals": signals,
    }
    return (
        "Advise on this held position and call submit_position_advice.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
