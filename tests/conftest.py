"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from helpers import make_candles, make_uptrend
from tossai.config import Settings
from tossai.models import Candle


@pytest.fixture
def settings() -> Settings:
    return Settings(
        toss_app_key="test-key",
        toss_app_secret="test-secret",
        anthropic_api_key="test-anthropic",
        market="KRX",
        reports_dir="./.test_reports",
        log_file="",
        claude_max_candidates=3,
        sma_fast=5,
        sma_slow=10,
        rsi_period=5,
        volume_ratio_min=1.0,
    )


@pytest.fixture
def uptrend_candles() -> list[Candle]:
    """A realistic uptrend with pullbacks + a recent volume spike — passes."""
    return make_uptrend(n=40)


@pytest.fixture
def flat_candles() -> list[Candle]:
    """Flat/no-momentum series — should fail screening."""
    closes = [100.0] * 40
    return make_candles(closes)
