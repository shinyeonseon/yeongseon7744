"""FastAPI Slack server tests (signature, ack, deferral)."""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi.testclient import TestClient

from tossai.slack import server as server_mod
from tossai.slack.server import create_app

SECRET = "test-signing-secret"


def _sign(secret, ts, body):
    base = f"v0:{ts}:{body}".encode()
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def _client(settings, monkeypatch, captured=None):
    settings.slack_signing_secret = SECRET
    settings.slack_bot_token = "xoxb-x"

    class _FakeSlack:
        def respond(self, *a, **k):
            if captured is not None:
                captured.append((a, k))
            return True

        def post_message(self, *a, **k):
            return True

    app = create_app(settings, slack_client=_FakeSlack())
    return TestClient(app)


def test_healthz(settings, monkeypatch):
    c = _client(settings, monkeypatch)
    assert c.get("/healthz").json()["status"] == "ok"


def test_unsigned_rejected(settings, monkeypatch):
    c = _client(settings, monkeypatch)
    r = c.post("/slack/commands", data={"command": "/help"})
    assert r.status_code == 401


def test_help_inline(settings, monkeypatch):
    c = _client(settings, monkeypatch)
    ts = str(int(time.time()))
    body = "command=%2Fhelp&text="
    sig = _sign(SECRET, ts, body)
    r = c.post(
        "/slack/commands", content=body,
        headers={
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    assert r.status_code == 200
    assert r.json()["blocks"]  # inline help


def test_recommend_defers(settings, monkeypatch):
    # Make deferred work a no-op so the test doesn't hit the network.
    called = {}

    def fake_run_and_respond(s, client, url, kind, args, meta=None):
        called["kind"] = kind

    monkeypatch.setattr(server_mod.runner, "run_and_respond", fake_run_and_respond)

    c = _client(settings, monkeypatch)
    ts = str(int(time.time()))
    body = "command=%2Frecommend&text=&response_url=https%3A%2F%2Fhooks.slack.com%2Fx&trigger_id=t1"
    sig = _sign(SECRET, ts, body)
    r = c.post(
        "/slack/commands", content=body,
        headers={
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    assert r.status_code == 200
    assert r.json()["response_type"] == "ephemeral"  # immediate ack
    # background task ran (TestClient runs the loop to completion on the request)
    assert called.get("kind") == "recommend"


def test_stale_timestamp_rejected(settings, monkeypatch):
    c = _client(settings, monkeypatch)
    ts = str(int(time.time()) - 10000)
    body = "command=%2Fhelp"
    sig = _sign(SECRET, ts, body)
    r = c.post(
        "/slack/commands", content=body,
        headers={
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    assert r.status_code == 401
