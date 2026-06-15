"""Market-regime classification from VIX (and optional benchmark trend).

Used to gate/down-weight risk-seeking strategies. Degrades gracefully: when VIX
is unavailable the regime is NEUTRAL and nothing is suppressed.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

import pandas as pd

from tossai.config import Settings
from tossai.screening import indicators as ind


class MarketRegime(str, Enum):
    RISK_ON = "risk_on"
    NEUTRAL = "neutral"
    RISK_OFF = "risk_off"


def classify_regime(
    vix: float | None,
    *,
    neutral_vix: float,
    riskoff_vix: float,
    benchmark_close: pd.Series | None = None,
    benchmark_ma: int = 200,
) -> MarketRegime:
    if vix is None:
        regime = MarketRegime.NEUTRAL
    elif vix >= riskoff_vix:
        regime = MarketRegime.RISK_OFF
    elif vix >= neutral_vix:
        regime = MarketRegime.NEUTRAL
    else:
        regime = MarketRegime.RISK_ON

    # Optional benchmark overlay: a benchmark below its long MA downgrades a step.
    if benchmark_close is not None and len(benchmark_close) >= benchmark_ma:
        ma = ind.sma(benchmark_close, benchmark_ma).iloc[-1]
        if not pd.isna(ma) and float(benchmark_close.iloc[-1]) < float(ma):
            regime = {
                MarketRegime.RISK_ON: MarketRegime.NEUTRAL,
                MarketRegime.NEUTRAL: MarketRegime.RISK_OFF,
                MarketRegime.RISK_OFF: MarketRegime.RISK_OFF,
            }[regime]
    return regime


class RegimeProvider:
    """Fetches VIX once per run and classifies the regime."""

    def __init__(self, settings: Settings, vix_getter: Callable[[Settings], float | None] | None = None):
        self.s = settings
        self._vix_getter = vix_getter
        self._vix: float | None = None
        self._fetched = False

    def get_vix(self) -> float | None:
        if not self._fetched:
            getter = self._vix_getter
            if getter is None:
                from tossai.risk.sentiment import get_vix as getter
            self._vix = getter(self.s)
            self._fetched = True
        return self._vix

    def get_regime(self, benchmark_close: pd.Series | None = None) -> MarketRegime:
        return classify_regime(
            self.get_vix(),
            neutral_vix=self.s.regime_neutral_vix,
            riskoff_vix=self.s.regime_riskoff_vix,
            benchmark_close=benchmark_close,
        )
