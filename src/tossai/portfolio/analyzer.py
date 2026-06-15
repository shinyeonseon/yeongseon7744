"""Analyze held positions: gather a signal snapshot per holding, then ask Claude
for ADD/HOLD/TRIM/SELL advice. No orders are ever placed.
"""

from __future__ import annotations

import pandas as pd

from tossai.analysis.claude_engine import ClaudeEngine
from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.models import Candle, Position
from tossai.output.portfolio_report import PortfolioReport
from tossai.screening import indicators as ind
from tossai.screening.screener import candles_to_df

log = get_logger(__name__)


class PortfolioAnalyzer:
    def __init__(self, settings: Settings, client, engine: ClaudeEngine | None = None):
        self.s = settings
        self.client = client
        self.engine = engine

    def run(self) -> PortfolioReport:
        try:
            positions = self.client.get_holdings()
        except Exception as exc:
            log.error("holdings fetch failed: %s", exc)
            positions = []
        # Skip fully-closed positions (0 shares) — nothing to advise, saves a call.
        positions = [p for p in positions if p.quantity > 0]

        engine = self.engine or ClaudeEngine(self.s)
        results = []
        count = self.s.resolved_candle_count(260)
        for pos in positions:
            try:
                candles = self.client.get_candles(pos.symbol, count=count)
            except Exception as exc:
                log.warning("candle fetch failed for %s: %s", pos.symbol, exc)
                candles = []
            signals = _position_signals(candles, pos)
            results.append(engine.analyze_position(pos, signals))

        return PortfolioReport(
            positions_count=len(positions),
            results=results,
            estimated_cost_usd=round(engine.estimated_cost_usd(), 6),
        )


def _position_signals(candles: list[Candle], pos: Position) -> dict:
    """Compact technical snapshot for Claude — reuses indicators.py."""
    out: dict = {}
    if pos.avg_price:
        out["vs_avg_cost_pct"] = round((pos.last_price / pos.avg_price - 1) * 100, 2)
    if len(candles) < 30:
        out["note"] = "insufficient price history"
        return out

    df = candles_to_df(candles)
    close = df["close"]
    last = float(close.iloc[-1])
    out["price"] = round(last, 4)

    rsi_v = ind.rsi(close, 14).iloc[-1]
    if pd.notna(rsi_v):
        out["rsi"] = round(float(rsi_v), 2)
    for name, n in (("return_3m", 63), ("return_12m", 252)):
        r = ind.total_return(close, n)
        if r is not None:
            out[name] = round(r, 4)
    if len(close) >= 200:
        ma200 = float(ind.sma(close, 200).iloc[-1])
        out["above_ma200"] = last > ma200
        out["sma200"] = round(ma200, 4)
    rp = ind.range_position(close, min(252, len(close))).iloc[-1]
    if pd.notna(rp):
        out["range_position_52w"] = round(float(rp), 3)
    return out
