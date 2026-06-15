"""Slack signature verification tests."""

from __future__ import annotations

import hashlib
import hmac

from tossai.slack.signature import verify_slack_signature

SECRET = "8f742231b10e8888abcd99yyyzzz85a5"


def _sign(secret: str, ts: str, body: str) -> str:
    base = f"v0:{ts}:{body}".encode()
    digest = hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return f"v0={digest}"


def test_valid_signature():
    ts = "1700000000"
    body = "command=/help&text="
    sig = _sign(SECRET, ts, body)
    assert verify_slack_signature(SECRET, ts, body, sig, now=1700000010) is True


def test_tampered_body_fails():
    ts = "1700000000"
    body = "command=/help&text="
    sig = _sign(SECRET, ts, body)
    assert verify_slack_signature(SECRET, ts, "command=/recommend", sig, now=1700000010) is False


def test_wrong_secret_fails():
    ts = "1700000000"
    body = "command=/help"
    sig = _sign(SECRET, ts, body)
    assert verify_slack_signature("other-secret", ts, body, sig, now=1700000010) is False


def test_stale_timestamp_fails():
    ts = "1700000000"
    body = "command=/help"
    sig = _sign(SECRET, ts, body)
    # 10 minutes later > 300s skew
    assert verify_slack_signature(SECRET, ts, body, sig, now=1700000000 + 600) is False


def test_missing_headers_fail():
    assert verify_slack_signature(SECRET, None, "b", "v0=x", now=1) is False
    assert verify_slack_signature(SECRET, "1700000000", "b", None, now=1700000000) is False
    assert verify_slack_signature("", "1700000000", "b", "v0=x", now=1700000000) is False


def test_non_numeric_timestamp_fails():
    assert verify_slack_signature(SECRET, "not-a-ts", "b", "v0=x", now=1) is False


def test_bytes_body_accepted():
    ts = "1700000000"
    body = b"command=/status"
    sig = _sign(SECRET, ts, body.decode())
    assert verify_slack_signature(SECRET, ts, body, sig, now=1700000010) is True
