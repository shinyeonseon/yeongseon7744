"""Toss fundamentals — future hook.

If/when the Toss Open API exposes fundamental metrics, implement ``get`` here
using ``TossClient`` and route to it preferentially (single source for KRX+US).
Until then it returns None so callers fall back / skip.
"""

from __future__ import annotations

from tossai.fundamentals.models import Fundamentals


class TossFundamentalsProvider:
    def get(self, symbol: str, market: str) -> Fundamentals | None:
        # TODO(schema): populate from the Toss fundamentals endpoint once its
        # spec is confirmed. No data available yet.
        return None
