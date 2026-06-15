"""Application configuration via pydantic-settings.

All secrets come from the environment / .env file. Never log raw secret values —
use ``redacted_summary()`` which only reports presence booleans.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Market(str, Enum):
    KRX = "KRX"
    US = "US"
    BOTH = "BOTH"


class TradingEnabledError(RuntimeError):
    """Raised at startup if ENABLE_TRADING is true. v1 is analysis-only."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Toss Securities Open API ----
    toss_app_key: str = ""
    toss_app_secret: str = ""
    toss_account_seq: str = ""
    toss_base_url: str = "https://openapi.tossinvest.com"
    toss_oauth_url: str = "https://openapi.tossinvest.com/oauth2/token"
    toss_timeout_s: float = 10.0
    toss_max_retries: int = 3

    # ---- Anthropic / Claude ----
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    claude_model_deep: str = "claude-opus-4-8"
    claude_max_tokens: int = 2000
    claude_max_candidates: int = 8
    claude_monthly_budget_usd: float = 20.0

    # ---- Screening knobs ----
    rsi_period: int = 14
    sma_fast: int = 20
    sma_slow: int = 60
    rsi_overbought: float = 70.0
    volume_ratio_min: float = 1.2
    screen_min_score: float = 0.0

    # ---- Strategies (ensemble) ----
    strategy: str = (
        "technical_swing,dual_momentum,canslim,mean_reversion,trend_breakout,"
        "meb_faber,momentum_quality,low_volatility,"
        "graham,magic_formula,buffett_quality,piotroski"
    )
    candle_count: int = 0  # 0 = auto (required_history + buffer); pages past 200/call.
    # Toss /api/v1/candles returns at most 200 bars/call; the client pages with the
    # `before` cursor to assemble longer history, so full-length lookbacks are fine.
    toss_candle_max: int = 200
    trend_ma: int = 200
    # Dual momentum
    dm_lookback_days: int = 252
    dm_skip_days: int = 0
    dm_abs_threshold: float = 0.0
    dm_require_trend: bool = True
    dm_score_cap: float = 0.5
    # CAN SLIM (technical subset)
    canslim_high_proximity_pct: float = 0.15
    canslim_rs_lookback: int = 252
    canslim_rs_min: float = 0.70
    canslim_vol_ratio_min: float = 1.5
    canslim_max_vix: float = 25.0
    # Mean reversion
    mean_rev_ma: int = 200
    mean_rev_rsi_low: float = 35.0
    mean_rev_support_lookback: int = 20
    mean_rev_support_pos: float = 0.25
    # Trend breakout
    breakout_lookback: int = 252
    breakout_vol_window: int = 20
    breakout_vol_ratio_min: float = 1.5
    # Market regime (VIX based)
    regime_neutral_vix: float = 20.0
    regime_riskoff_vix: float = 28.0
    regime_riskoff_weight: float = 0.5

    # ---- Investment-master strategies (price-based) ----
    # Meb Faber GTAA trend timing (10-month / ~200d SMA).
    meb_faber_ma: int = 200
    # Momentum quality (12-1 momentum + frog-in-the-pan smoothness).
    momq_lookback: int = 252
    momq_skip: int = 21
    momq_score_cap: float = 0.5
    # Low-volatility factor.
    lowvol_lookback: int = 126
    lowvol_vol_cap: float = 0.03  # daily-return std where score → 0
    # Risk-parity / All-Weather inverse-vol weighting overlay (suggestion only).
    risk_parity_lookback: int = 63
    # Backtest trading cost charged on rebalance turnover (basis points per unit
    # traded; a blended commission + tax + slippage estimate).
    backtest_cost_bps: float = 10.0
    # Move a held symbol's weight to cash while it trades below its trailing MA
    # (``trend_ma``) — cuts drawdown by de-risking trend breaks. On by default.
    backtest_trend_filter: bool = True
    # Risk management (drawdown control). Default weighting is inverse-vol (shrinks
    # the most explosive names); a volatility target scales total exposure down to
    # cash when the portfolio's own realized vol exceeds backtest_vol_target.
    backtest_weighting: str = "inverse_vol"  # equal | inverse_vol
    backtest_vol_target: float = 0.15  # annualized; 0 disables vol targeting
    backtest_vol_lookback: int = 20

    # ---- Investment-master strategies (fundamental) ----
    # Need a fundamentals source (pykrx for KRX, yfinance for US). Lazy-imported;
    # when unavailable a strategy skips gracefully (never crashes the run).
    fundamentals_enabled: bool = True
    graham_max_pe: float = 15.0
    graham_max_pb: float = 1.5
    buffett_min_roe: float = 0.15
    buffett_max_pe: float = 25.0
    piotroski_min_score: int = 5

    # ---- Runtime ----
    market: Market = Market.BOTH
    loop_interval_min: int = 30
    reports_dir: str = "./reports"
    log_level: str = "INFO"
    log_file: str = "./logs/tossai.log"
    universe_file: str = "./config/universe.yaml"

    # ---- Safety ----
    enable_trading: bool = False

    # ---- Alerts ----
    alert_channels: str = "console"
    alert_min_confidence: float = 0.6
    webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""

    # ---- Slack ----
    slack_enabled: bool = False
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_channel: str = ""
    slack_app_host: str = "127.0.0.1"
    slack_app_port: int = 8080
    slack_max_concurrent_runs: int = 2

    # ---- Scheduler / briefings ----
    briefing_market: Market = Market.KRX
    briefing_morning_time: str = "08:30"  # local market tz, HH:MM
    briefing_weekly_day: str = "mon"
    briefing_weekly_time: str = "08:00"
    # Portfolio advice can be pushed to Slack on a schedule (serve). Opt-in because
    # it calls Claude (costs money); run-once recommendations push regardless.
    portfolio_schedule_enabled: bool = False
    portfolio_schedule_time: str = "15:40"  # local market tz, HH:MM (after close)

    # ---- Risk ----
    risk_scan_interval_min: int = 15
    vix_blackswan_threshold: float = 30.0
    gap_down_pct: float = 5.0
    vix_source_url: str = "https://stooq.com/q/l/?s=^vix&f=sd2t2ohlcv&e=csv"

    @field_validator("market", "briefing_market", mode="before")
    @classmethod
    def _upper_market(cls, v: object) -> object:
        return v.upper() if isinstance(v, str) else v

    def channels(self) -> list[str]:
        return [c.strip().lower() for c in self.alert_channels.split(",") if c.strip()]

    def strategies(self) -> list[str]:
        return [s.strip().lower() for s in self.strategy.split(",") if s.strip()]

    def resolved_candle_count(self, required_history: int) -> int:
        """How many candles to fetch: enough for the heaviest active strategy
        (plus warm-up buffer). The client pages past the 200/call cap."""
        return max(self.candle_count, required_history + 40)

    def enforce_safety(self) -> None:
        """Hard guard: v1 must never trade. Call once at startup."""
        if self.enable_trading:
            raise TradingEnabledError(
                "ENABLE_TRADING=true is not allowed in v1 (analysis-only). "
                "Set ENABLE_TRADING=false."
            )

    def redacted_summary(self) -> dict[str, object]:
        """Safe-to-log view: secrets reduced to presence booleans."""
        return {
            "toss_app_key_set": bool(self.toss_app_key),
            "toss_app_secret_set": bool(self.toss_app_secret),
            "toss_account_seq_set": bool(self.toss_account_seq),
            "anthropic_api_key_set": bool(self.anthropic_api_key),
            "toss_base_url": self.toss_base_url,
            "claude_model": self.claude_model,
            "market": self.market.value,
            "strategies": self.strategies(),
            "candle_count": self.candle_count,
            "enable_trading": self.enable_trading,
            "alert_channels": self.channels(),
            "webhook_url_set": bool(self.webhook_url),
            "slack_enabled": self.slack_enabled,
            "slack_bot_token_set": bool(self.slack_bot_token),
            "slack_signing_secret_set": bool(self.slack_signing_secret),
            "slack_channel_set": bool(self.slack_channel),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
