"""Risk-parity / All-Weather (Ray Dalio) inverse-volatility weighting.

A *suggestion-only* overlay: given the final candidate set, propose portfolio
weights inversely proportional to each name's realized volatility (lower vol →
larger weight), normalized to sum to 1. This is analysis output, never an order.
"""

from __future__ import annotations

from tossai.models import Candle
from tossai.screening.screener import candles_to_df


def inverse_vol_weights(
    candle_map: dict[str, list[Candle]], lookback: int = 63
) -> dict[str, float]:
    """Return {symbol: weight} with weight ∝ 1/volatility, summing to 1.0.

    Symbols without enough history are dropped. Returns {} if nothing usable.
    """
    inv: dict[str, float] = {}
    for symbol, candles in candle_map.items():
        if len(candles) < lookback + 1:
            continue
        df = candles_to_df(candles)
        rets = df["close"].pct_change().dropna().iloc[-lookback:]
        vol = float(rets.std()) if len(rets) else 0.0
        if vol <= 0.0:
            continue
        inv[symbol] = 1.0 / vol

    total = sum(inv.values())
    if total <= 0.0:
        return {}
    return {sym: round(w / total, 4) for sym, w in inv.items()}
