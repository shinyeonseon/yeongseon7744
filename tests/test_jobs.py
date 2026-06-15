"""Scheduler registration + risk-scan tests."""

from __future__ import annotations

from tossai.scheduler import jobs


class _FakeSlack:
    def post_message(self, *a, **k):
        return True


def test_build_scheduler_registers_jobs(settings):
    sched = jobs.build_scheduler(settings, _FakeSlack())
    ids = {j.id for j in sched.get_jobs()}
    assert ids == {"morning_briefing", "weekly_briefing", "risk_scan"}


def test_parse_hhmm():
    assert jobs._parse_hhmm("08:30") == (8, 30)


def test_scan_risk_blackswan(settings, monkeypatch):
    monkeypatch.setattr(jobs, "get_vix", lambda s: 45.0)
    # no universe symbols → only blackswan considered
    monkeypatch.setattr(jobs, "_is_trading_day", lambda s: False)
    alerts = jobs._scan_risk(settings)
    assert len(alerts) == 1
    assert alerts[0].kind.value == "blackswan"


def test_scan_risk_calm_no_alerts(settings, monkeypatch):
    monkeypatch.setattr(jobs, "get_vix", lambda s: 15.0)
    monkeypatch.setattr(jobs, "_is_trading_day", lambda s: False)
    assert jobs._scan_risk(settings) == []
