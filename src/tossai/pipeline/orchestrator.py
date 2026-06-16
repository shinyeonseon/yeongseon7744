"""Ties the pipeline together: market data → screen → Claude → report/alerts.

There is deliberately NO order-placement path here. The flow only reads market
data and produces recommendations.
"""

from __future__ import annotations

from tossai.analysis.claude_engine import ClaudeEngine
from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.market.calendar import any_market_open, markets_for
from tossai.market.universe import Symbol, load_universe
from tossai.models import Candidate, Candle
from tossai.output import alerts
from tossai.output.report import Report, save_report
from tossai.screening.strategies.ensemble import build_strategy
from tossai.toss.client import TossClient

log = get_logger(__name__)


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        client: TossClient,
        engine: ClaudeEngine | None = None,
        screener=None,
    ):
        self.s = settings
        self.client = client
        self.engine = engine
        # ``screener`` may be any object exposing ``screen_universe`` +
        # ``required_history`` (a single Screener/Strategy or a StrategyEnsemble).
        self.screener = screener or build_strategy(settings)

    def _fetch_candles(self, symbols: list[Symbol]) -> tuple[dict[str, list[Candle]], dict[str, str]]:
        candle_map: dict[str, list[Candle]] = {}
        markets: dict[str, str] = {}
        count = self.s.resolved_candle_count(getattr(self.screener, "required_history", 0))
        for sym in symbols:
            try:
                candles = self.client.get_candles(sym.symbol, count=count)
            except Exception as exc:
                log.warning("candle fetch failed for %s: %s", sym.symbol, exc)
                continue
            candle_map[sym.symbol] = candles
            markets[sym.symbol] = sym.market
        return candle_map, markets

    def screen_only(self) -> list[Candidate]:
        """Run market-data fetch + screening, no Claude. Free dry-run."""
        symbols = load_universe(self.s.universe_file, self.s.market.value)
        candle_map, markets = self._fetch_candles(symbols)
        candidates = self.screener.screen_universe(candle_map, markets)
        log.info("screening produced %d candidate(s)", len(candidates))
        return candidates

    def run_once(self, force: bool = False) -> Report:
        market_open = any_market_open(self.s.market.value)
        symbols = load_universe(self.s.universe_file, self.s.market.value)
        candle_map, markets = self._fetch_candles(symbols)
        candidates = self.screener.screen_universe(candle_map, markets)
        # Diversification cap: don't let one sector dominate the analyzed set.
        if self.s.max_per_sector > 0:
            from tossai.screening.selection import diversify_by_sector

            sector_map = {s.symbol: s.sector for s in symbols if s.sector}
            if sector_map:
                candidates = diversify_by_sector(
                    candidates, sector_map, len(candidates), self.s.max_per_sector)

        engine = self.engine or ClaudeEngine(self.s)
        from tossai.context.provider import build_market_context_provider

        context = build_market_context_provider(self.s)
        analyzed = engine.analyze_all(candidates, context) if candidates else []
        macro = context.macro() if context else None

        # Risk-parity / All-Weather suggestion: inverse-vol weights over the
        # screened set (analysis only — never an order).
        from tossai.screening.allocation import inverse_vol_weights

        cand_candles = {c.symbol: candle_map[c.symbol] for c in candidates if c.symbol in candle_map}
        suggested_weights = inverse_vol_weights(cand_candles, self.s.risk_parity_lookback)

        report = Report(
            market=self.s.market.value,
            market_open=market_open,
            universe_size=len(symbols),
            screened_count=len(candidates),
            results=analyzed,
            estimated_cost_usd=round(engine.estimated_cost_usd(), 6),
            suggested_weights=suggested_weights,
            macro=(macro.as_line() if macro and not macro.is_empty() else ""),
        )
        save_report(report, self.s.reports_dir)
        # Append this run's recommendations to the performance ledger (for `track`).
        try:
            from tossai.performance.ledger import append_report

            append_report(report, self.s.reports_dir)
        except Exception as exc:
            log.debug("ledger append failed: %s", exc)

        # Suppress external pushes when the market is closed unless forced.
        if market_open or force:
            alerts.dispatch(self.s, report)
        else:
            log.info("market closed for %s; external alerts suppressed (use --force)",
                     markets_for(self.s.market.value))
            alerts.ConsoleNotifier().send(report)
        return report
