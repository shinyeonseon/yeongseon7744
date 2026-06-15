"""Toss client + auth tests with mocked HTTP (no network)."""

from __future__ import annotations

import httpx
import pytest

from tossai.toss.auth import TossAuth, TossAuthError
from tossai.toss.client import TossClient


def _client_with(settings, handler, tmp_path, token_preset=True):
    """Build a TossClient whose auth + API share one MockTransport."""
    transport = httpx.MockTransport(handler)
    api_http = httpx.Client(base_url=settings.toss_base_url, transport=transport)
    auth_http = httpx.Client(transport=transport)
    auth = TossAuth(settings, cache_path=str(tmp_path / "tok.json"), http=auth_http)
    if token_preset:
        auth._token = "t"
        auth._expires_at = 9_999_999_999
    return TossClient(settings, auth=auth, http=api_http), auth


def test_token_fetch_and_cache(settings, tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})

    auth = TossAuth(
        settings,
        cache_path=str(tmp_path / "tok.json"),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert auth.get_token() == "tok-123"
    assert auth.get_token() == "tok-123"  # cached, no new request
    assert calls["n"] == 1


def test_get_candles_parses(settings, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "candles": [
                        # Toss returns newest-first with string values; client sorts asc.
                        {"timestamp": "2026-01-02T00:00:00.000+09:00", "openPrice": "1.5",
                         "highPrice": "2.5", "lowPrice": "1", "closePrice": "2.0",
                         "volume": "200"},
                        {"timestamp": "2026-01-01T00:00:00.000+09:00", "openPrice": "1",
                         "highPrice": "2", "lowPrice": "0.5", "closePrice": "1.5",
                         "volume": "100"},
                    ]
                }
            },
        )

    client, _ = _client_with(settings, handler, tmp_path)
    candles = client.get_candles("005930")
    assert len(candles) == 2
    assert candles[0].close == 1.5  # oldest first after sort
    assert candles[1].volume == 200


def test_get_candles_pages_with_before(settings, tmp_path):
    from datetime import datetime, timedelta

    def _gen(end: datetime, n: int) -> list:
        return [
            {
                "timestamp": (end - timedelta(days=i)).strftime("%Y-%m-%dT00:00:00.000+09:00"),
                "openPrice": "100", "highPrice": "101", "lowPrice": "99",
                "closePrice": "100", "volume": "1000",
            }
            for i in range(n)  # newest-first
        ]

    def handler(request: httpx.Request) -> httpx.Response:
        before = request.url.params.get("before")
        if before is None:
            rows = _gen(datetime(2026, 6, 15), 200)
        else:
            bd = datetime.fromisoformat(before)
            rows = _gen(bd - timedelta(days=1), 200)
        return httpx.Response(200, json={"result": {"candles": rows}})

    client, _ = _client_with(settings, handler, tmp_path)
    candles = client.get_candles("005930", count=300)
    assert len(candles) == 300
    assert candles[0].ts < candles[-1].ts  # chronological
    assert candles[-1].ts.strftime("%Y-%m-%d") == "2026-06-15"  # newest retained


def test_401_triggers_refresh(settings, tmp_path):
    state = {"served_401": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth" in str(request.url):
            return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
        if not state["served_401"]:
            state["served_401"] = True
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"result": [{"symbol": "AAPL", "lastPrice": "42.0"}]})

    client, _ = _client_with(settings, handler, tmp_path)
    quote = client.get_quote("AAPL")
    assert quote.price == 42.0
    assert state["served_401"] is True


def test_auth_error_surfaces_toss_message(settings, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": "invalid_client",
                  "error_description": "Client authentication failed: client_secret"},
        )

    auth = TossAuth(
        settings, cache_path=str(tmp_path / "tok.json"),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(TossAuthError) as exc:
        auth.get_token()
    msg = str(exc.value)
    assert "invalid_client" in msg
    assert "client_secret" in msg


def test_429_raises_after_retries(settings, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate"})

    client, _ = _client_with(settings, handler, tmp_path)
    with pytest.raises(httpx.TransportError):
        client.get_quote("AAPL")
