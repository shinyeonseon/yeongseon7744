"""OAuth2 token management for the Toss Open API.

Tokens are cached on disk (``.token_cache.json``, gitignored) so short-lived
``run-once`` invocations don't re-authenticate every time. The manager refreshes
proactively before expiry and can be forced to refresh reactively on a 401.

TODO(schema): confirm the token request/response shape against live docs. The
client_credentials grant with appKey/appSecret is the assumed flow.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx

from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.toss.schemas import TokenResponse

log = get_logger(__name__)

# Refresh this many seconds before the token actually expires.
_EXPIRY_SKEW_S = 60


class TossAuthError(RuntimeError):
    """Token request failed; message carries the Toss error code/description."""


def _explain_auth_error(resp: httpx.Response) -> str:
    """Build a human-readable reason from a Toss error response body.

    Toss returns OAuth errors as {"error","error_description"} and API errors as
    {"error":{"code","message"}}. Fall back to a short raw snippet.
    """
    try:
        data = resp.json()
    except (ValueError, TypeError):
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
    err = data.get("error")
    if isinstance(err, dict):
        return f"HTTP {resp.status_code}: {err.get('code')} — {err.get('message')}"
    desc = data.get("error_description") or data.get("message")
    return f"HTTP {resp.status_code}: {err} — {desc}"



class TossAuth:
    def __init__(
        self,
        settings: Settings,
        cache_path: str = ".token_cache.json",
        http: httpx.Client | None = None,
    ):
        self.s = settings
        self.cache_path = Path(cache_path)
        self._http = http or httpx.Client(timeout=settings.toss_timeout_s)
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._load_cache()

    # ---- public API ----
    def get_token(self, force_refresh: bool = False) -> str:
        with self._lock:
            if force_refresh or self._is_expired():
                self._refresh()
            assert self._token is not None
            return self._token

    def auth_header(self, force_refresh: bool = False) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_token(force_refresh=force_refresh)}"}

    # ---- internals ----
    def _is_expired(self) -> bool:
        return self._token is None or time.time() >= (self._expires_at - _EXPIRY_SKEW_S)

    def _refresh(self) -> None:
        if not self.s.toss_app_key or not self.s.toss_app_secret:
            raise RuntimeError("TOSS_APP_KEY / TOSS_APP_SECRET are not configured.")
        log.info("requesting new Toss OAuth token")
        # OAuth 2.0 Client Credentials Grant — application/x-www-form-urlencoded
        # with client_id/client_secret in the body (per Toss Open API docs).
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.s.toss_app_key,
            "client_secret": self.s.toss_app_secret,
        }
        resp = self._http.post(
            self.s.toss_oauth_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code >= 400:
            reason = _explain_auth_error(resp)
            log.error("Toss token request failed: %s", reason)
            raise TossAuthError(f"Toss token request failed — {reason}")
        token = TokenResponse.model_validate(resp.json())
        self._token = token.access_token
        self._expires_at = time.time() + token.expires_in
        self._save_cache()

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text())
            self._token = data.get("access_token")
            self._expires_at = float(data.get("expires_at", 0.0))
            if self._is_expired():
                self._token = None
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            log.warning("ignoring unreadable token cache: %s", exc)
            self._token = None

    def _save_cache(self) -> None:
        try:
            self.cache_path.write_text(
                json.dumps({"access_token": self._token, "expires_at": self._expires_at})
            )
            self.cache_path.chmod(0o600)
        except OSError as exc:
            log.warning("could not write token cache: %s", exc)
