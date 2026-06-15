"""Fundamentals provider protocol, market routing, and per-run caching."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from tossai.config import Settings
from tossai.fundamentals.models import Fundamentals
from tossai.logging_setup import get_logger

log = get_logger(__name__)


@runtime_checkable
class FundamentalsProvider(Protocol):
    def get(self, symbol: str, market: str) -> Fundamentals | None: ...


class CachingProvider:
    """Wraps a provider with a per-run in-memory cache (one fetch per symbol)."""

    def __init__(self, inner: FundamentalsProvider):
        self._inner = inner
        self._cache: dict[tuple[str, str], Fundamentals | None] = {}

    def get(self, symbol: str, market: str) -> Fundamentals | None:
        key = (symbol, market)
        if key not in self._cache:
            try:
                self._cache[key] = self._inner.get(symbol, market)
            except Exception as exc:  # any provider failure → no data, never crash
                log.warning("fundamentals fetch failed for %s [%s]: %s", symbol, market, exc)
                self._cache[key] = None
        return self._cache[key]


class MarketRoutingProvider:
    """Routes to a KRX or US provider by market label; None for unknown markets."""

    def __init__(self, krx: FundamentalsProvider | None, us: FundamentalsProvider | None):
        self._krx = krx
        self._us = us

    def get(self, symbol: str, market: str) -> Fundamentals | None:
        m = (market or "").upper()
        provider = self._krx if m == "KRX" else self._us if m == "US" else None
        if provider is None:
            return None
        return provider.get(symbol, market)


def build_fundamentals_provider(settings: Settings) -> FundamentalsProvider | None:
    """Construct the default routed+cached provider, or None if disabled.

    Providers are constructed lazily and tolerate missing libraries; they only
    fail (return None) at fetch time, so this never raises.
    """
    if not settings.fundamentals_enabled:
        return None
    from tossai.fundamentals.pykrx_provider import PykrxProvider
    from tossai.fundamentals.yfinance_provider import YFinanceProvider

    routed = MarketRoutingProvider(krx=PykrxProvider(), us=YFinanceProvider())
    return CachingProvider(routed)
