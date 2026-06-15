"""Slack request signature verification.

Slack signs each request with HMAC-SHA256 over ``v0:{timestamp}:{raw_body}``
using the app's signing secret. We verify with a constant-time compare and
reject stale timestamps (anti-replay). Pure function, no I/O — the first thing
to build and test, and the gate every inbound request must pass.
"""

from __future__ import annotations

import hashlib
import hmac
import time


def verify_slack_signature(
    signing_secret: str,
    timestamp: str | None,
    raw_body: bytes | str,
    signature: str | None,
    *,
    now: float | None = None,
    max_skew_s: int = 300,
) -> bool:
    """Return True iff ``signature`` is a valid Slack signature for the request.

    - ``timestamp``: value of the ``X-Slack-Request-Timestamp`` header.
    - ``raw_body``: the exact request body bytes (must not be re-serialized).
    - ``signature``: value of the ``X-Slack-Signature`` header (``v0=...``).
    """
    if not signing_secret or not timestamp or not signature:
        return False

    # Anti-replay: reject requests with a stale or non-numeric timestamp.
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = now if now is not None else time.time()
    if abs(current - ts) > max_skew_s:
        return False

    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")

    basestring = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    digest = hmac.new(
        signing_secret.encode("utf-8"), basestring, hashlib.sha256
    ).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)
