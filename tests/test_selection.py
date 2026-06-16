"""Sector diversification cap (pure selection logic)."""

from __future__ import annotations

from tossai.models import Candidate
from tossai.screening.selection import diversify_by_sector


def _cands(*symbols: str) -> list[Candidate]:
    # pre-sorted best-first; score descending
    return [Candidate(symbol=s, market="US", price=1.0, score=1.0 - i * 0.01)
            for i, s in enumerate(symbols)]


SECTORS = {"NVDA": "Semi", "AVGO": "Semi", "MU": "Semi", "JPM": "Fin", "XOM": "Energy"}


def test_no_cap_returns_top_n():
    c = _cands("NVDA", "AVGO", "MU", "JPM")
    out = diversify_by_sector(c, SECTORS, top_n=3, max_per_sector=0)
    assert [x.symbol for x in out] == ["NVDA", "AVGO", "MU"]


def test_cap_limits_per_sector_and_backfills():
    c = _cands("NVDA", "AVGO", "MU", "JPM", "XOM")  # 3 semis first
    out = diversify_by_sector(c, SECTORS, top_n=3, max_per_sector=2)
    # only 2 semis allowed, so the 3rd slot goes to the next non-semi by rank
    assert [x.symbol for x in out] == ["NVDA", "AVGO", "JPM"]


def test_unknown_sector_is_its_own_bucket():
    c = _cands("AAA", "BBB", "CCC")  # none in SECTORS
    out = diversify_by_sector(c, SECTORS, top_n=3, max_per_sector=1)
    assert [x.symbol for x in out] == ["AAA", "BBB", "CCC"]  # never capped


def test_cap_can_underfill_when_universe_too_concentrated():
    c = _cands("NVDA", "AVGO", "MU")  # all Semi
    out = diversify_by_sector(c, SECTORS, top_n=5, max_per_sector=2)
    assert [x.symbol for x in out] == ["NVDA", "AVGO"]  # only 2 fit the cap
