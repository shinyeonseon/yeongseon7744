"""Pluggable screening strategies.

Each strategy turns OHLCV candles into ranked Candidates and is a drop-in for
``Screener.screen_universe`` (same signature), so the orchestrator is agnostic
to which strategy (or ensemble) runs. Analysis-only — no strategy ever touches
order placement.
"""

from __future__ import annotations

from tossai.screening.strategies.base import (
    BaseStrategy,
    Strategy,
    StrategyResult,
)
from tossai.screening.strategies.buffett_quality import BuffettQualityStrategy
from tossai.screening.strategies.canslim import CanSlimTechnicalStrategy
from tossai.screening.strategies.dual_momentum import DualMomentumStrategy
from tossai.screening.strategies.ensemble import StrategyEnsemble, build_strategy
from tossai.screening.strategies.graham import GrahamValueStrategy
from tossai.screening.strategies.low_volatility import LowVolatilityStrategy
from tossai.screening.strategies.magic_formula import MagicFormulaStrategy
from tossai.screening.strategies.mean_reversion import MeanReversionStrategy
from tossai.screening.strategies.meb_faber import MebFaberTrendStrategy
from tossai.screening.strategies.momentum_quality import MomentumQualityStrategy
from tossai.screening.strategies.piotroski import PiotroskiLiteStrategy
from tossai.screening.strategies.technical_swing import TechnicalSwingStrategy
from tossai.screening.strategies.trend_breakout import TrendBreakoutStrategy

__all__ = [
    "BaseStrategy",
    "Strategy",
    "StrategyResult",
    "CanSlimTechnicalStrategy",
    "DualMomentumStrategy",
    "MeanReversionStrategy",
    "TechnicalSwingStrategy",
    "TrendBreakoutStrategy",
    "MebFaberTrendStrategy",
    "MomentumQualityStrategy",
    "LowVolatilityStrategy",
    "GrahamValueStrategy",
    "MagicFormulaStrategy",
    "BuffettQualityStrategy",
    "PiotroskiLiteStrategy",
    "StrategyEnsemble",
    "build_strategy",
]
