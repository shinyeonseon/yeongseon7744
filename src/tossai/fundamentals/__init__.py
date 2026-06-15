"""Fundamental-data layer for value/quality strategies.

All external data sources (pykrx for KRX, yfinance for US) are lazy-imported and
fail soft: when a source is missing or errors, ``get`` returns ``None`` and the
consuming strategy skips that symbol. Nothing here places orders.
"""

from __future__ import annotations

from tossai.fundamentals.models import Fundamentals
from tossai.fundamentals.provider import (
    FundamentalsProvider,
    MarketRoutingProvider,
    build_fundamentals_provider,
)

__all__ = [
    "Fundamentals",
    "FundamentalsProvider",
    "MarketRoutingProvider",
    "build_fundamentals_provider",
]
