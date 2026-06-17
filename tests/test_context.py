"""Market-context layer: sources parsing, provider caching/gating, wiring."""

from __future__ import annotations

from datetime import date

import httpx

from tossai.context import sources
from tossai.context.models import MacroSnapshot, NewsItem, SymbolContext
from tossai.context.provider import MarketContextProvider


def test_next_fomc_dday():
    out = sources.next_fomc(today=date(2026, 6, 15))
    assert out == "FOMC 2026-06-17 (D-2)"


def test_next_fomc_rolls_to_following_meeting():
    out = sources.next_fomc(today=date(2026, 6, 18))  # day after the Jun meeting
    assert out.startswith("FOMC 2026-07-29")


def test_parse_news_old_and_new_shapes():
    raw = [
        {"title": "삼성 신고가", "publisher": "Reuters", "providerPublishTime": 1_750_000_000},
        {"content": {"title": "실적 호조", "provider": {"displayName": "Bloomberg"},
                     "pubDate": "2026-06-10T09:00:00Z"}},
    ]
    items = sources._parse_yf_news(raw, limit=5)
    assert [i.title for i in items] == ["삼성 신고가", "실적 호조"]
    assert items[1].publisher == "Bloomberg" and items[1].published == "2026-06-10"


def test_parse_earnings_date_variants():
    assert sources._parse_earnings_date({"Earnings Date": [date(2026, 6, 20)]}) == "2026-06-20"
    assert sources._parse_earnings_date({"Earnings Date": date(2026, 7, 1)}) == "2026-07-01"
    assert sources._parse_earnings_date({}) is None
    assert sources._parse_earnings_date(None) is None


def test_fetch_macro_without_key_still_has_fomc(settings):
    settings.fred_api_key = ""
    # No key + a mock client that returns no F&G → indicators stay empty (offline).
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})))
    snap = sources.fetch_macro(settings, http=client, today=date(2026, 6, 15))
    assert snap.indicators == {}
    assert snap.upcoming and snap.upcoming[0].startswith("FOMC")


def test_fetch_fear_greed_parses(settings):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"fear_and_greed": {"score": 25.4, "rating": "extreme fear"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert sources.fetch_fear_greed(settings, http=client) == (25.4, "극단적공포")


def test_fetch_macro_adds_spreads_and_fear_greed(settings):
    settings.fred_api_key = "k"

    def handler(req: httpx.Request) -> httpx.Response:
        if "fearandgreed" in str(req.url):
            return httpx.Response(200, json={"fear_and_greed": {"score": 72.0, "rating": "greed"}})
        series = req.url.params.get("series_id")
        val = {"T10Y2Y": "-0.18", "BAMLH0A0HYM2": "3.25"}.get(series, "4.0")
        return httpx.Response(200, json={"observations": [{"value": val}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    snap = sources.fetch_macro(settings, http=client, today=date(2026, 6, 15))
    assert snap.indicators["10Y-2Y"] == "-0.18%p"      # inverted shows the minus
    assert snap.indicators["HY스프레드"] == "+3.25%p"
    assert snap.indicators["공포탐욕"] == "72(탐욕)"


def test_fetch_macro_with_fred(settings):
    settings.fred_api_key = "k"

    def handler(req: httpx.Request) -> httpx.Response:
        series = req.url.params.get("series_id")
        if series == "CPIAUCSL":  # 13 obs, newest first; +5% YoY
            obs = [{"value": str(105 - i)} for i in range(13)]
        else:
            obs = [{"value": "4.0"}]
        return httpx.Response(200, json={"observations": obs})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    snap = sources.fetch_macro(settings, http=client, today=date(2026, 6, 15))
    assert snap.indicators["실업률"] == "4.00%"
    assert "CPI(YoY)" in snap.indicators
    assert snap.upcoming[0].startswith("FOMC")


def test_provider_caches_and_merges_macro(settings):
    calls = {"news": 0, "earnings": 0, "macro": 0}

    def news_fn(sym, market, limit):
        calls["news"] += 1
        return [NewsItem(title="호재", published="2026-06-10")]

    def earnings_fn(sym, market):
        calls["earnings"] += 1
        return "2026-06-20"

    def macro_fn(s):
        calls["macro"] += 1
        return MacroSnapshot(indicators={"실업률": "4.0%"}, upcoming=["FOMC 2026-06-17 (D-2)"])

    p = MarketContextProvider(settings, news_fn=news_fn, earnings_fn=earnings_fn, macro_fn=macro_fn)
    payload = p.payload_for("MU", "US")
    p.payload_for("MU", "US")  # cached — fetchers must not run again
    assert payload["recent_news"] == ["2026-06-10 호재"]
    assert payload["next_earnings_date"] == "2026-06-20"
    assert payload["macro"]["indicators"]["실업률"] == "4.0%"
    assert calls == {"news": 1, "earnings": 1, "macro": 1}


def test_provider_gating_disables_sources(settings):
    settings.context_news_enabled = False
    settings.context_earnings_enabled = False
    settings.context_macro_enabled = False

    def boom(*a, **k):
        raise AssertionError("must not be called when disabled")

    p = MarketContextProvider(settings, news_fn=boom, earnings_fn=boom, macro_fn=boom)
    assert p.payload_for("MU", "US") == {}
    assert p.macro().is_empty()


def test_symbol_context_payload_empty_when_no_data():
    ctx = SymbolContext(symbol="X", market="US")
    assert ctx.to_payload() == {} and ctx.is_empty()
