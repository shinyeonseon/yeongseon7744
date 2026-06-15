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
    toss_base_url: str = "https://openapi.tossinvest.com/v1"
    toss_oauth_url: str = "https://openapi.tossinvest.com/v1/oauth/token"
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

    @field_validator("market", mode="before")
    @classmethod
    def _upper_market(cls, v: object) -> object:
        return v.upper() if isinstance(v, str) else v

    def channels(self) -> list[str]:
        return [c.strip().lower() for c in self.alert_channels.split(",") if c.strip()]

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
            "enable_trading": self.enable_trading,
            "alert_channels": self.channels(),
            "webhook_url_set": bool(self.webhook_url),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
