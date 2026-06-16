"""KRX fundamentals via pykrx (lazy-imported, fail-soft).

pykrx scrapes KRX/Naver and exposes PER/PBR/EPS/BPS/DIV through
``stock.get_market_fundamental``. Note the data is reported with a lag (after
KRX processes annual reports), so treat it as slow-moving. ROE is approximated
as EPS/BPS when both are present.
"""

from __future__ import annotations

import contextlib
import io
import logging
from datetime import datetime, timedelta

from tossai.fundamentals.models import Fundamentals
from tossai.logging_setup import get_logger

log = get_logger(__name__)


@contextlib.contextmanager
def _quiet():
    """Silence pykrx's noisy prints + its buggy internal logging during a call."""
    buf = io.StringIO()
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            yield
    finally:
        logging.disable(logging.NOTSET)


class PykrxProvider:
    def get(self, symbol: str, market: str) -> Fundamentals | None:
        try:
            with _quiet():  # pykrx prints a KRX-login warning on import w/o creds
                from pykrx import stock
        except ImportError:
            log.debug("pykrx not installed; KRX fundamentals unavailable")
            return None

        # Look back a few days to land on the latest available trading day.
        end = datetime.now()
        start = end - timedelta(days=10)
        fmt = "%Y%m%d"
        try:
            with _quiet():
                df = stock.get_market_fundamental(
                    start.strftime(fmt), end.strftime(fmt), symbol, freq="d"
                )
        except Exception as exc:
            log.debug("pykrx fundamental fetch failed for %s: %s", symbol, exc)
            return None
        if df is None or len(df) == 0:
            return None

        row = df.iloc[-1]
        per = _f(row.get("PER"))
        pbr = _f(row.get("PBR"))
        eps = _f(row.get("EPS"))
        bps = _f(row.get("BPS"))
        div = _f(row.get("DIV"))
        roe = (eps / bps) if (eps is not None and bps not in (None, 0)) else None
        return Fundamentals(
            symbol=symbol, market=market, per=per, pbr=pbr, eps=eps, bps=bps,
            roe=roe, dividend_yield=(div / 100.0) if div is not None else None,
        )


def _f(value: object) -> float | None:
    """Coerce to float; None for missing/NaN."""
    try:
        if value is None:
            return None
        f = float(value)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None
