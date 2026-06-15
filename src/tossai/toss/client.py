"""Thin REST client for the Toss Open API.

Read-only surface only: quotes, candles, account, balances. All Toss-specific
endpoint paths and response shapes are isolated here + in ``schemas.py`` behind
``TODO(schema)`` markers so confirming them against the live API touches one
place. Order endpoints are intentionally absent (see ``orders.py``).
"""

from __future__ import annotations

import time

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.models import Candle
from tossai.toss.auth import TossAuth, _explain_auth_error
from tossai.toss.schemas import CandleRaw, QuoteResponse

log = get_logger(__name__)


class TossClient:
    def __init__(self, settings: Settings, auth: TossAuth | None = None,
                 http: httpx.Client | None = None):
        self.s = settings
        self.auth = auth or TossAuth(settings)
        self._http = http or httpx.Client(
            base_url=settings.toss_base_url, timeout=settings.toss_timeout_s
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> TossClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- request plumbing ----
    def _headers(self, account_scoped: bool = False, force_refresh: bool = False) -> dict[str, str]:
        headers = self.auth.auth_header(force_refresh=force_refresh)
        headers["Content-Type"] = "application/json"
        if account_scoped and self.s.toss_account_seq:
            # TODO(schema): confirm exact account header name.
            headers["X-Tossinvest-Account"] = self.s.toss_account_seq
        return headers

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _get(self, path: str, params: dict | None = None, account_scoped: bool = False) -> dict:
        resp = self._http.get(path, params=params, headers=self._headers(account_scoped))
        if resp.status_code == 401:
            # Token may have expired mid-flight; refresh once and retry.
            log.info("401 from Toss; refreshing token and retrying %s", path)
            resp = self._http.get(
                path, params=params,
                headers=self._headers(account_scoped, force_refresh=True),
            )
        if resp.status_code == 429:
            # Surface as a transport-style error so tenacity backs off.
            raise httpx.TransportError(f"rate limited (429) on {path}")
        if resp.status_code >= 400:
            raise RuntimeError(f"Toss API error on {path} — {_explain_auth_error(resp)}")
        return resp.json()

    # ---- public, read-only endpoints (Toss Open API) ----
    def get_quote(self, symbol: str) -> QuoteResponse:
        # GET /api/v1/prices?symbols=005930 -> {"result":[{"lastPrice": "...", ...}]}
        data = self._get("/api/v1/prices", params={"symbols": symbol})
        obj = _first_obj(_unwrap_list(data, keys=("result", "prices", "items", "data"))) or {}
        last = obj.get("lastPrice")
        return QuoteResponse(
            symbol=obj.get("symbol", symbol),
            price=float(last) if last not in (None, "") else None,
        )

    _PER_CALL = 200  # Toss caps count at 200 bars per request

    def get_candles(self, symbol: str, interval: str = "1d", count: int = 200) -> list[Candle]:
        """Fetch up to ``count`` daily/minute bars, paging past the 200/call cap.

        GET /api/v1/candles -> {"result":{"candles":[{"timestamp","openPrice",...}]}}
        Toss returns newest-first; older pages are fetched with the ``before``
        cursor (the oldest bar's full ISO timestamp). Returns chronological order.
        """
        want = max(1, int(count))
        collected: dict = {}  # ts -> Candle (dedupe across page boundaries)
        before: str | None = None
        max_pages = want // self._PER_CALL + 2
        for _ in range(max_pages):
            params = {"symbol": symbol, "interval": interval, "count": self._PER_CALL}
            if before is not None:
                params["before"] = before
            rows = self._candle_rows(self._get("/api/v1/candles", params=params))
            if not rows:
                break
            for row in rows:
                try:
                    c = CandleRaw.model_validate(row).to_candle()
                    collected[c.ts] = c
                except Exception as exc:  # tolerate a single malformed bar
                    log.debug("skip malformed candle for %s: %s", symbol, exc)
            if len(collected) >= want or len(rows) < self._PER_CALL:
                break
            before = rows[-1].get("timestamp")  # oldest bar (newest-first) → page back
            if not before:
                break
            time.sleep(0.25)  # stay under the chart rate limit (5/s)
        candles = sorted(collected.values(), key=lambda c: c.ts)
        return candles[-want:]

    @staticmethod
    def _candle_rows(data: object) -> list:
        if isinstance(data, dict) and isinstance(data.get("result"), dict):
            return data["result"].get("candles", []) or []
        return _unwrap_list(data, keys=("candles", "items", "data"))

    def get_accounts(self) -> list:
        """GET /api/v1/accounts -> [Account]. Returns raw AccountRaw list."""
        from tossai.toss.schemas import AccountRaw

        data = self._get("/api/v1/accounts")
        rows = _unwrap_list(data, keys=("result", "accounts", "items", "data"))
        out = []
        for row in rows:
            try:
                out.append(AccountRaw.model_validate(row))
            except Exception as exc:
                log.debug("skip malformed account: %s", exc)
        return out

    def get_holdings(self) -> list:
        """GET /api/v1/holdings (account-scoped) -> list[Position]."""
        from tossai.toss.schemas import HoldingItemRaw

        data = self._get("/api/v1/holdings", account_scoped=True)
        items = []
        if isinstance(data, dict) and isinstance(data.get("result"), dict):
            items = data["result"].get("items", []) or []
        positions = []
        for row in items:
            try:
                positions.append(HoldingItemRaw.model_validate(row).to_position())
            except Exception as exc:
                log.debug("skip malformed holding: %s", exc)
        return positions

    def get_balances(self) -> dict:
        """Raw holdings payload (account-scoped: Bearer + X-Tossinvest-Account)."""
        return self._get("/api/v1/holdings", account_scoped=True)


def _unwrap_list(data: object, keys: tuple[str, ...]) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            if isinstance(data.get(k), list):
                return data[k]
    return []


def _first_obj(rows: list) -> dict | None:
    for row in rows:
        if isinstance(row, dict):
            return row
    return None
