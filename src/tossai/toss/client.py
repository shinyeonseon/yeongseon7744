"""Thin REST client for the Toss Open API.

Read-only surface only: quotes, candles, account, balances. All Toss-specific
endpoint paths and response shapes are isolated here + in ``schemas.py`` behind
``TODO(schema)`` markers so confirming them against the live API touches one
place. Order endpoints are intentionally absent (see ``orders.py``).
"""

from __future__ import annotations

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

    def get_candles(self, symbol: str, interval: str = "1d", count: int = 200) -> list[Candle]:
        # GET /api/v1/candles -> {"result":{"candles":[{"timestamp","openPrice",...}]}}
        # interval ∈ {"1d","1m"}. Toss caps count at 200/call and returns
        # newest-first; we clamp and sort chronologically.
        count = max(1, min(int(count), 200))
        data = self._get(
            "/api/v1/candles",
            params={"symbol": symbol, "interval": interval, "count": count},
        )
        rows = []
        if isinstance(data, dict) and isinstance(data.get("result"), dict):
            rows = data["result"].get("candles", [])
        if not rows:
            rows = _unwrap_list(data, keys=("candles", "items", "data"))
        candles: list[Candle] = []
        for row in rows:
            try:
                candles.append(CandleRaw.model_validate(row).to_candle())
            except Exception as exc:  # tolerate a single malformed bar
                log.debug("skip malformed candle for %s: %s", symbol, exc)
        candles.sort(key=lambda c: c.ts)  # oldest -> newest
        return candles

    def get_balances(self) -> dict:
        """Holdings (account-scoped: Bearer + X-Tossinvest-Account)."""
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
