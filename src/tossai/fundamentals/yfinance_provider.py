"""US fundamentals via yfinance (lazy-imported, fail-soft).

yfinance's ``.info`` is convenient but flaky; every access is guarded and any
failure yields ``None`` so the value/quality strategies simply skip the symbol.
"""

from __future__ import annotations

from tossai.fundamentals.models import Fundamentals
from tossai.logging_setup import get_logger

log = get_logger(__name__)


class YFinanceProvider:
    def get(self, symbol: str, market: str) -> Fundamentals | None:
        try:
            import yfinance as yf
        except ImportError:
            log.debug("yfinance not installed; US fundamentals unavailable")
            return None

        try:
            info = yf.Ticker(symbol).info or {}
        except Exception as exc:
            log.debug("yfinance fetch failed for %s: %s", symbol, exc)
            return None
        if not info:
            return None

        return Fundamentals(
            symbol=symbol,
            market=market,
            per=_f(info.get("trailingPE")),
            pbr=_f(info.get("priceToBook")),
            eps=_f(info.get("trailingEps")),
            bps=_f(info.get("bookValue")),
            roe=_f(info.get("returnOnEquity")),
            dividend_yield=_f(info.get("dividendYield")),
            market_cap=_f(info.get("marketCap")),
            debt_to_equity=_f(info.get("debtToEquity")),
        )


def _f(value: object) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None
