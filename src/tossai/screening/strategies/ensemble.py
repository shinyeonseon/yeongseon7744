"""Strategy ensemble + factory.

Runs several strategies, merges their candidates by symbol, and exposes the same
``screen_universe`` signature as a single strategy so the orchestrator stays
agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tossai.config import Settings
from tossai.logging_setup import get_logger
from tossai.models import Candidate, Candle
from tossai.screening.regime import MarketRegime, RegimeProvider
from tossai.screening.strategies.base import BaseStrategy, StrategyResult
from tossai.screening.strategies.buffett_quality import BuffettQualityStrategy
from tossai.screening.strategies.canslim import CanSlimTechnicalStrategy
from tossai.screening.strategies.dual_momentum import DualMomentumStrategy
from tossai.screening.strategies.graham import GrahamValueStrategy
from tossai.screening.strategies.low_volatility import LowVolatilityStrategy
from tossai.screening.strategies.magic_formula import MagicFormulaStrategy
from tossai.screening.strategies.mean_reversion import MeanReversionStrategy
from tossai.screening.strategies.meb_faber import MebFaberTrendStrategy
from tossai.screening.strategies.momentum_quality import MomentumQualityStrategy
from tossai.screening.strategies.piotroski import PiotroskiLiteStrategy
from tossai.screening.strategies.relative_strength import RelativeStrengthStrategy
from tossai.screening.strategies.technical_swing import TechnicalSwingStrategy
from tossai.screening.strategies.trend_breakout import TrendBreakoutStrategy

log = get_logger(__name__)

REGISTRY: dict[str, type[BaseStrategy]] = {
    # Price-based
    "technical_swing": TechnicalSwingStrategy,
    "dual_momentum": DualMomentumStrategy,
    "canslim": CanSlimTechnicalStrategy,
    "mean_reversion": MeanReversionStrategy,
    "trend_breakout": TrendBreakoutStrategy,
    "meb_faber": MebFaberTrendStrategy,
    "momentum_quality": MomentumQualityStrategy,
    "low_volatility": LowVolatilityStrategy,
    "relative_strength": RelativeStrengthStrategy,
    # Fundamental (need a fundamentals provider; skip gracefully without one)
    "graham": GrahamValueStrategy,
    "magic_formula": MagicFormulaStrategy,
    "buffett_quality": BuffettQualityStrategy,
    "piotroski": PiotroskiLiteStrategy,
}

# Buckets that are risk-seeking and get down-weighted in a RISK_OFF regime.
_RISK_BUCKETS = {"long"}


@dataclass
class _Merged:
    result: StrategyResult
    score: float
    signals: dict
    flagged_by: list[str] = field(default_factory=list)
    buckets: set[str] = field(default_factory=set)


class StrategyEnsemble:
    def __init__(self, strategies: list[BaseStrategy], settings: Settings,
                 regime_provider: RegimeProvider | None = None,
                 fundamentals_provider=None):
        self.strategies = strategies
        self.s = settings
        self.regime = regime_provider or RegimeProvider(settings)
        self._fundamentals = fundamentals_provider
        self._fundamentals_built = fundamentals_provider is not None
        self.required_history = max((st.required_history for st in strategies), default=0)

    def _get_fundamentals(self):
        """Lazily build the fundamentals provider once (only if a strategy needs it)."""
        if not self._fundamentals_built:
            from tossai.fundamentals.provider import build_fundamentals_provider

            self._fundamentals = build_fundamentals_provider(self.s)
            self._fundamentals_built = True
        return self._fundamentals

    def screen_universe(
        self, candle_map: dict[str, list[Candle]], markets: dict[str, str] | None = None
    ) -> list[Candidate]:
        markets = markets or {}
        vix = self.regime.get_vix()
        regime = self.regime.get_regime()

        merged: dict[str, _Merged] = {}
        for strat in self.strategies:
            if hasattr(strat, "set_vix"):
                strat.set_vix(vix)  # CAN SLIM market-direction gate
            if hasattr(strat, "set_fundamentals_provider"):
                strat.set_fundamentals_provider(self._get_fundamentals())
            for res in strat.evaluate_all(candle_map, markets):
                weight = self.s.regime_riskoff_weight if (
                    regime == MarketRegime.RISK_OFF and res.bucket in _RISK_BUCKETS
                ) else 1.0
                eff_score = res.score * weight
                self._merge(merged, res, eff_score)

        # Rank by score, then by how many strategies independently agree — broad
        # consensus breaks the common saturation tie (many names at max score).
        ranked = sorted(merged.values(), key=lambda m: (m.score, len(m.flagged_by)), reverse=True)
        top = ranked[: self.s.claude_max_candidates]
        return [self._to_candidate(m, markets.get(m.result.symbol, "KRX")) for m in top]

    def _merge(self, merged: dict[str, _Merged], res: StrategyResult, eff_score: float) -> None:
        existing = merged.get(res.symbol)
        ns_signals = {f"{res.strategy}.{k}": v for k, v in res.signals.items()}
        if existing is None:
            merged[res.symbol] = _Merged(
                result=res, score=eff_score, signals=dict(ns_signals),
                flagged_by=[res.strategy], buckets={res.bucket},
            )
            return
        existing.signals.update(ns_signals)
        existing.flagged_by.append(res.strategy)
        existing.buckets.add(res.bucket)
        if eff_score > existing.score:
            existing.score = eff_score
            existing.result = res  # keep best contributor's price/bucket

    def _to_candidate(self, m: _Merged, market: str) -> Candidate:
        r = m.result
        return Candidate(
            symbol=r.symbol, market=market, price=r.price or 0.0,
            score=round(m.score, 4), signals=m.signals, atr=r.atr,
            strategy=r.strategy, bucket=r.bucket,
            flagged_by=sorted(m.flagged_by),
        )


def build_strategy(settings: Settings, regime_provider: RegimeProvider | None = None):
    """Return a single strategy or an ensemble, both exposing ``screen_universe``."""
    names = settings.strategies()
    strategies: list[BaseStrategy] = []
    for name in names:
        cls = REGISTRY.get(name)
        if cls is None:
            log.warning("unknown strategy '%s' (skipped)", name)
            continue
        strategies.append(cls(settings))

    if not strategies:
        log.warning("no valid strategies configured; falling back to technical_swing")
        strategies = [TechnicalSwingStrategy(settings)]

    if len(strategies) == 1:
        only = strategies[0]
        # A lone CAN SLIM (VIX gate) or fundamental strategy (provider) still
        # needs the ensemble to inject its dependency.
        if hasattr(only, "set_vix") or hasattr(only, "set_fundamentals_provider"):
            return StrategyEnsemble(strategies, settings, regime_provider)
        return only

    return StrategyEnsemble(strategies, settings, regime_provider)
