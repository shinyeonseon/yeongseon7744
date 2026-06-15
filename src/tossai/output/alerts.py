"""Pluggable notifiers. Console always; webhook (Slack/Discord) is the v1
push channel; SMTP is available for email. Only actionable, high-confidence
BUY/SELL items are pushed externally — full detail always lands in the report.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

import httpx

from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.output.report import Report, console_table

log = get_logger(__name__)


class Notifier(Protocol):
    def send(self, report: Report) -> None: ...


class ConsoleNotifier:
    def send(self, report: Report) -> None:
        print(console_table(report))


class WebhookNotifier:
    """POST a compact summary to a Slack/Discord incoming webhook."""

    def __init__(self, url: str, min_confidence: float):
        self.url = url
        self.min_confidence = min_confidence

    def send(self, report: Report) -> None:
        items = report.actionable(self.min_confidence)
        if not items:
            log.info("webhook: no actionable items to push")
            return
        lines = [f"*Toss AI* — {len(items)} signal(s) ({report.generated_at:%Y-%m-%d %H:%M UTC})"]
        for r in items:
            rec = r.recommendation
            tgt = f" → {rec.target_price:.2f}" if rec.target_price is not None else ""
            lines.append(
                f"• {r.candidate.symbol} [{r.candidate.market}] "
                f"*{rec.action.value}* ({rec.confidence:.0%}){tgt} — {rec.rationale[:120]}"
            )
        lines.append("_Automated analysis, not financial advice._")
        text = "\n".join(lines)
        # Slack uses {"text": ...}; Discord uses {"content": ...}. Send both keys.
        try:
            resp = httpx.post(self.url, json={"text": text, "content": text}, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("webhook send failed: %s", exc)


class SmtpNotifier:
    def __init__(self, s: Settings):
        self.s = s

    def send(self, report: Report) -> None:
        s = self.s
        items = report.actionable(s.alert_min_confidence)
        if not items:
            return
        msg = EmailMessage()
        msg["Subject"] = f"Toss AI — {len(items)} signal(s)"
        msg["From"] = s.smtp_from or s.smtp_user
        msg["To"] = s.smtp_to
        msg.set_content(console_table(report))
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
                server.starttls()
                if s.smtp_user:
                    server.login(s.smtp_user, s.smtp_password)
                server.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            log.error("smtp send failed: %s", exc)


class SlackNotifier:
    """Posts recommendation signals to Slack via a bot token + Block Kit.

    Only actionable BUY/SELL at/above the confidence threshold are pushed (same
    gate as WebhookNotifier); the full detail always lives in the JSON report.
    """

    def __init__(self, bot_token: str, channel: str, min_confidence: float,
                 client=None):
        self.channel = channel
        self.min_confidence = min_confidence
        if client is None:
            from tossai.slack.web_client import SlackClient

            client = SlackClient(bot_token)
        self._client = client

    def send(self, report: Report) -> None:
        from tossai.slack.blocks import report_blocks

        if not report.actionable(self.min_confidence):
            log.info("slack: no actionable items to push")
            return
        blocks = report_blocks(report, self.min_confidence)
        self._client.post_message(self.channel, blocks, text=console_table(report))


class PortfolioNotifier:
    """Posts held-position advice (ADD/HOLD/TRIM/SELL) to Slack via bot token.

    Mirrors ``SlackNotifier`` but for the portfolio report. Pushes every position
    at/above the confidence gate; full detail always lives in the JSON report.
    """

    def __init__(self, bot_token: str, channel: str, min_confidence: float,
                 client=None):
        self.channel = channel
        self.min_confidence = min_confidence
        if client is None:
            from tossai.slack.web_client import SlackClient

            client = SlackClient(bot_token)
        self._client = client

    def send(self, report) -> None:
        from tossai.output.portfolio_report import console_table as portfolio_console
        from tossai.slack.blocks import portfolio_blocks

        if not report.results:
            log.info("slack: no portfolio positions to push")
            return
        blocks = portfolio_blocks(report, self.min_confidence)
        self._client.post_message(self.channel, blocks, text=portfolio_console(report))


def dispatch_portfolio(settings: Settings, report) -> None:
    """Push the portfolio report to Slack when the slack channel is configured.

    No-op (with a log line) when slack isn't an alert channel or creds are
    missing — keeps the CLI safe to run without Slack set up.
    """
    if "slack" not in settings.channels():
        return
    if not (settings.slack_bot_token and settings.slack_channel):
        log.warning("slack channel enabled but SLACK_BOT_TOKEN/SLACK_CHANNEL missing")
        return
    notifier = PortfolioNotifier(
        settings.slack_bot_token, settings.slack_channel, settings.alert_min_confidence,
    )
    try:
        notifier.send(report)
    except Exception as exc:  # never break the CLI on a Slack hiccup
        log.error("portfolio slack push failed: %s", exc)


def build_notifiers(settings: Settings) -> list[Notifier]:
    notifiers: list[Notifier] = []
    channels = settings.channels()
    if "console" in channels or not channels:
        notifiers.append(ConsoleNotifier())
    if "webhook" in channels:
        if settings.webhook_url:
            notifiers.append(WebhookNotifier(settings.webhook_url, settings.alert_min_confidence))
        else:
            log.warning("webhook channel enabled but WEBHOOK_URL is empty")
    if "smtp" in channels:
        if settings.smtp_host and settings.smtp_to:
            notifiers.append(SmtpNotifier(settings))
        else:
            log.warning("smtp channel enabled but SMTP_HOST/SMTP_TO missing")
    if "slack" in channels:
        if settings.slack_bot_token and settings.slack_channel:
            notifiers.append(
                SlackNotifier(
                    settings.slack_bot_token, settings.slack_channel,
                    settings.alert_min_confidence,
                )
            )
        else:
            log.warning("slack channel enabled but SLACK_BOT_TOKEN/SLACK_CHANNEL missing")
    return notifiers


def dispatch(settings: Settings, report: Report) -> None:
    for notifier in build_notifiers(settings):
        try:
            notifier.send(report)
        except Exception as exc:  # one bad channel must not break the others
            log.error("notifier %s failed: %s", type(notifier).__name__, exc)
