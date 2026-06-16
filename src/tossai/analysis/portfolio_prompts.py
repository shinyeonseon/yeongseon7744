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
    "- 'signals' may include 'market_context' (recent news headlines, the next "
    "earnings date, a macro backdrop). Treat it as qualitative reference: flag an "
    "imminent earnings date or major macro event (e.g. FOMC) as a timing risk, but "
    "let the position's P&L and numeric signals drive the call. Often absent — "
    "then ignore it.\n"
    "- Always state concrete risks; set confidence honestly.\n"
    "- LANGUAGE (REQUIRED): write `rationale`, `key_points`, and `risks` in "
    "natural Korean (반드시 한국어로 작성). Keep ticker symbols, action codes, and "
    "numbers as-is. Do NOT answer in English.\n"
    "- BE CONCISE: `rationale` is ONE headline sentence; put the substance in "
    "`key_points` as a few short, scannable bullets (each one line). Do NOT write "
    "long paragraphs.\n"
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
        },
        "required": ["action", "confidence", "rationale", "key_points", "risks"],
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
        "Advise on this held position and call submit_position_advice. "
        "rationale와 risks는 반드시 한국어로 작성하세요.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
