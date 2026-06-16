"""Slash-command dispatch tests."""

from __future__ import annotations

from tossai.slack.commands import dispatch_command


def test_help_inline(settings):
    r = dispatch_command("/help", {}, settings)
    assert r.inline_blocks is not None
    assert r.deferred_kind is None


def test_empty_is_help(settings):
    r = dispatch_command("", {}, settings)
    assert r.inline_blocks is not None


def test_status_inline_uses_redacted(settings):
    r = dispatch_command("/status", {}, settings)
    text = "".join(str(b) for b in r.inline_blocks)
    # presence booleans, never raw secrets
    assert "slack_bot_token_set" in text
    assert settings.toss_app_secret not in text


def test_recommend_is_deferred(settings):
    r = dispatch_command("/recommend", {}, settings)
    assert r.deferred_kind == "recommend"
    assert r.ack_text and r.inline_blocks is None


def test_screen_and_briefing_deferred(settings):
    assert dispatch_command("/screen", {}, settings).deferred_kind == "screen"
    assert dispatch_command("/briefing", {}, settings).deferred_kind == "briefing"


def test_unknown_command(settings):
    r = dispatch_command("/nope", {}, settings)
    assert r.inline_blocks is not None
    assert "알 수 없는 명령" in "".join(str(b) for b in r.inline_blocks)


def test_args_parsed(settings):
    r = dispatch_command("/screen", {"text": "KRX foo"}, settings)
    assert r.args == ["KRX", "foo"]
