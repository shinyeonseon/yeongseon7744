"""Market-context provider: caches macro once per run and per-symbol news/
earnings, with the same fail-soft contract as the fundamentals stack."""

from __future__ import annotations

from collections.abc import Callable

from tossai.config import Settings
from tossai.context import sources
from tossai.context.models import MacroSnapshot, SymbolContext
from tossai.logging_setup import get_logger

log = get_logger(__name__)


class MarketContextProvider:
    def __init__(
        self,
        settings: Settings,
        news_fn: Callable[[str, str, int], list] | None = None,
        earnings_fn: Callable[[str, str], str | None] | None = None,
        macro_fn: Callable[[Settings], MacroSnapshot] | None = None,
    ):
        self.s = settings
        self._news_fn = news_fn or sources.fetch_news
        self._earnings_fn = earnings_fn or sources.fetch_next_earnings
        self._macro_fn = macro_fn or sources.fetch_macro
        self._macro: MacroSnapshot | None = None
        self._sym_cache: dict[tuple[str, str], SymbolContext] = {}

    def macro(self) -> MacroSnapshot:
        if self._macro is None:
            if self.s.context_macro_enabled:
                try:
                    self._macro = self._macro_fn(self.s)
                except Exception as exc:
                    log.warning("macro context fetch failed: %s", exc)
                    self._macro = MacroSnapshot()
            else:
                self._macro = MacroSnapshot()
        return self._macro

    def for_symbol(self, symbol: str, market: str) -> SymbolContext:
        key = (symbol, (market or "").upper())
        if key in self._sym_cache:
            return self._sym_cache[key]
        news = []
        earnings = None
        if self.s.context_news_enabled:
            try:
                news = self._news_fn(symbol, market, self.s.context_news_max)
            except Exception as exc:
                log.debug("news fetch failed for %s: %s", symbol, exc)
        if self.s.context_earnings_enabled:
            try:
                earnings = self._earnings_fn(symbol, market)
            except Exception as exc:
                log.debug("earnings fetch failed for %s: %s", symbol, exc)
        ctx = SymbolContext(symbol=symbol, market=market, news=news, next_earnings=earnings)
        self._sym_cache[key] = ctx
        return ctx

    def payload_for(self, symbol: str, market: str) -> dict:
        """Combined per-symbol payload (symbol context + shared macro) for Claude."""
        out = self.for_symbol(symbol, market).to_payload()
        macro = self.macro()
        if not macro.is_empty():
            out["macro"] = macro.to_payload()
        return out


def build_market_context_provider(settings: Settings) -> MarketContextProvider | None:
    """The default provider, or None when the whole layer is disabled."""
    if not settings.context_enabled:
        return None
    return MarketContextProvider(settings)
