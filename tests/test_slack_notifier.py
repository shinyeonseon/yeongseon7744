"""SlackNotifier + build_notifiers wiring tests."""

from __future__ import annotations

import dataclasses

from tossai.models import Action, AnalyzedCandidate, Candidate, Recommendation
from tossai.output.alerts import SlackNotifier, build_notifiers
from tossai.output.report import Report


class _FakeSlackClient:
    def __init__(self):
        self.posts = []

    def post_message(self, channel, blocks, text=""):
        self.posts.append((channel, blocks, text))
        return True


def _report(action=Action.BUY, conf=0.8):
    cand = Candidate(symbol="005930", market="KRX", price=70000.0, score=0.8)
    rec = Recommendation(action=action, confidence=conf, rationale="x", risks=[])
    return Report(market="KRX", market_open=True, universe_size=1, screened_count=1,
                  results=[AnalyzedCandidate(candidate=cand, recommendation=rec)])


def test_slack_notifier_posts_actionable():
    fake = _FakeSlackClient()
    SlackNotifier("xoxb-x", "C123", 0.6, client=fake).send(_report(Action.BUY, 0.8))
    assert len(fake.posts) == 1
    assert fake.posts[0][0] == "C123"


def test_slack_notifier_skips_non_actionable():
    fake = _FakeSlackClient()
    SlackNotifier("xoxb-x", "C123", 0.6, client=fake).send(_report(Action.HOLD, 0.9))
    assert fake.posts == []


def test_slack_notifier_skips_low_confidence():
    fake = _FakeSlackClient()
    SlackNotifier("xoxb-x", "C123", 0.6, client=fake).send(_report(Action.BUY, 0.4))
    assert fake.posts == []


def test_build_notifiers_includes_slack_when_configured(settings):
    s = dataclasses.replace if False else settings  # settings is a pydantic model
    s.alert_channels = "console,slack"
    s.slack_bot_token = "xoxb-x"
    s.slack_channel = "C123"
    notifiers = build_notifiers(s)
    assert any(type(n).__name__ == "SlackNotifier" for n in notifiers)


def test_build_notifiers_warns_when_slack_unconfigured(settings):
    settings.alert_channels = "slack"
    settings.slack_bot_token = ""
    settings.slack_channel = ""
    notifiers = build_notifiers(settings)
    assert not any(type(n).__name__ == "SlackNotifier" for n in notifiers)
