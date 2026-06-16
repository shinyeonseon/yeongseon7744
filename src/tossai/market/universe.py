"""Load the watchlist (universe) of symbols to screen from a YAML file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from tossai.logging_setup import get_logger
from tossai.market.calendar import markets_for

log = get_logger(__name__)


@dataclass(frozen=True)
class Symbol:
    symbol: str
    market: str
    name: str | None = None
    sector: str | None = None


def load_universe(path: str, market_setting: str = "BOTH") -> list[Symbol]:
    """Read symbols from YAML, filtered to the active market(s).

    Expected YAML shape:
        KRX:
          - { symbol: "005930", name: "Samsung Electronics", sector: "Semiconductor" }
          - "000660"
        US:
          - { symbol: "AAPL", name: "Apple", sector: "TechHardware" }

    ``sector`` is optional; it powers the diversification cap (max names per
    sector). Symbols without a sector are never capped (treated as their own bucket).
    """
    p = Path(path)
    if not p.exists():
        log.warning("universe file not found: %s (returning empty list)", path)
        return []

    data = yaml.safe_load(p.read_text()) or {}
    active = set(markets_for(market_setting))
    out: list[Symbol] = []
    for market, entries in data.items():
        if market.upper() not in active:
            continue
        for entry in entries or []:
            if isinstance(entry, str):
                out.append(Symbol(symbol=entry, market=market.upper()))
            elif isinstance(entry, dict) and entry.get("symbol"):
                out.append(
                    Symbol(
                        symbol=str(entry["symbol"]),
                        market=market.upper(),
                        name=entry.get("name"),
                        sector=entry.get("sector"),
                    )
                )
    log.info("loaded %d symbols for markets %s", len(out), sorted(active))
    return out
