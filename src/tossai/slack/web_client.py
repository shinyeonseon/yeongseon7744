"""Outbound Slack Web API wrapper.

Wraps ``slack_sdk.WebClient`` for ``chat.postMessage`` and posts to a slash
command's ``response_url`` (a plain webhook) via httpx. Failures are logged and
swallowed so a Slack hiccup never breaks a pipeline run.
"""

from __future__ import annotations

import httpx
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from tossai.logging_setup import get_logger

log = get_logger(__name__)


class SlackClient:
    def __init__(self, bot_token: str, web_client: WebClient | None = None,
                 http: httpx.Client | None = None):
        self._client = web_client or WebClient(token=bot_token)
        self._http = http or httpx.Client(timeout=10.0)

    def post_message(self, channel: str, blocks: list[dict], text: str = "") -> bool:
        """Post a proactive message to a channel. Returns success."""
        if not channel:
            log.warning("post_message skipped: no channel configured")
            return False
        try:
            self._client.chat_postMessage(channel=channel, blocks=blocks, text=text or " ")
            return True
        except SlackApiError as exc:
            log.error("chat.postMessage failed: %s", exc.response.get("error", exc))
            return False

    def respond(self, response_url: str, blocks: list[dict], text: str = "",
                response_type: str = "in_channel") -> bool:
        """Reply to a slash command via its response_url (valid ~30min/5 uses)."""
        payload = {"response_type": response_type, "blocks": blocks, "text": text or " "}
        try:
            resp = self._http.post(response_url, json=payload)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.error("response_url post failed: %s", exc)
            return False
