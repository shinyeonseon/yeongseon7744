"""Candidate selection helpers — diversification on top of strategy ranking.

Keeping these pure (no I/O) so both the live pipeline and the backtest can share
the same sector-cap logic and it stays deterministically testable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def diversify_by_sector(
    candidates: Sequence,
    sector_of: Mapping[str, str | None] | None,
    top_n: int,
    max_per_sector: int = 0,
) -> list:
    """Pick up to ``top_n`` highest-ranked candidates, capping how many may share
    a sector (the screening's correlated-cluster drawdown control).

    ``candidates`` are assumed already sorted best-first. ``sector_of`` maps a
    symbol to its sector label; a missing/None sector is treated as a unique
    bucket (never capped). ``max_per_sector <= 0`` disables the cap.
    """
    if max_per_sector <= 0:
        return list(candidates[:top_n])
    sector_of = sector_of or {}
    picked: list = []
    counts: dict[str, int] = {}
    for c in candidates:
        sector = sector_of.get(c.symbol)
        key = sector if sector else f"__solo__{c.symbol}"  # unknown = own bucket
        if counts.get(key, 0) >= max_per_sector:
            continue
        picked.append(c)
        counts[key] = counts.get(key, 0) + 1
        if len(picked) >= top_n:
            break
    return picked
