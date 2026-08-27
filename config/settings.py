"""Global configuration and settings management for ThetaGuard."""
from functools import lru_cache
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Alpaca API Credentials
    alpaca_api_key: str = Field(
        default="PKTEST_MOCK_KEY",
        validation_alias="ALPACA_API_KEY",
        description="Alpaca paper trading API key",
    )
    alpaca_secret_key: str = Field(
        default="SKTEST_MOCK_SECRET",
        validation_alias="ALPACA_SECRET_KEY",
        description="Alpaca paper trading secret key",
    )
    alpaca_paper_trade: bool = Field(
        default=True,
        validation_alias="ALPACA_PAPER_TRADE",
        description="Must always be True. Live trading is strictly disabled.",
    )

    # Strategy Constants & Universe Guardrails
    allowed_universe: List[str] = Field(
        default=["SPY", "QQQ"],
        description="Strictly restricted trading universe. Only SPY and QQQ.",
    )
    iv_rank_floor: float = Field(
        default=30.0,
        validation_alias="IV_RANK_FLOOR",
        description="Minimum IV rank required to initiate premium-selling credit spread.",
    )
    min_short_delta: float = Field(
        default=-0.20,
        validation_alias="MIN_SHORT_DELTA",
        description="Lower bound for short put leg delta (e.g., -0.20)",
    )
    max_short_delta: float = Field(
        default=-0.15,
        validation_alias="MAX_SHORT_DELTA",
        description="Upper bound for short put leg delta (e.g., -0.15)",
    )
    spread_width: float = Field(
        default=5.0,
        validation_alias="SPREAD_WIDTH",
        description="Strike width in USD between short put and long put leg.",
    )

    # Sizing & Concentration Constraints
    max_concurrent_spreads: int = Field(
        default=2,
        validation_alias="MAX_CONCURRENT_SPREADS",
        description="Maximum concurrent open spreads across entire portfolio (max 1 SPY, 1 QQQ).",
    )
    max_account_risk_pct: float = Field(
        default=0.05,
        validation_alias="MAX_ACCOUNT_RISK_PCT",
        description="Maximum total collateral / max loss across all open spreads as % of account equity.",
    )
    max_spread_risk_pct: float = Field(
        default=0.02,
        validation_alias="MAX_SPREAD_RISK_PCT",
        description="Maximum collateral / max loss for any single spread as % of account equity.",
    )

    # Exit Rules
    take_profit_pct: float = Field(
        default=0.50,
        validation_alias="TAKE_PROFIT_PCT",
        description="Take-profit target: 50% of maximum credit received.",
    )
    stop_loss_pct: float = Field(
        default=2.00,
        validation_alias="STOP_LOSS_PCT",
        description="Stop-loss target: 200% of maximum credit received.",
    )

    # Polling Heartbeats & Performance Caching
    daemon_interval_seconds: int = Field(
        default=300,
        validation_alias="DAEMON_INTERVAL_SECONDS",
        description="Standard baseline daemon loop polling interval in seconds (5 minutes).",
    )
    event_window_polling_seconds: int = Field(
        default=30,
        validation_alias="EVENT_WINDOW_POLLING_SECONDS",
        description="Tightened high-volatility polling interval (30 seconds) during and around macro blackout windows.",
    )
    options_cache_ttl_seconds: int = Field(
        default=60,
        validation_alias="OPTIONS_CACHE_TTL_SECONDS",
        description="TTL cache lifetime in seconds for options chain market data to prevent rate-limit throttling.",
    )

    # Environment, Safety & Public Deployment
    app_host: str = Field(default="0.0.0.0", validation_alias="APP_HOST")
    app_port: int = Field(default=8000, validation_alias="APP_PORT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    public_read_only_mode: bool = Field(
        default=True,
        validation_alias="PUBLIC_READ_ONLY_MODE",
        description="When True, public web routes cannot trigger orders. Only daemon executes trades.",
    )
    admin_api_key: Optional[str] = Field(
        default="THETAGUARD_ADMIN_SECRET",
        validation_alias="ADMIN_API_KEY",
        description="Secret key required to trigger manual debug cycles when in public mode.",
    )
    mock_alpaca: bool = Field(
        default=False,
        validation_alias="MOCK_ALPACA",
        description="Enable local deterministic mock engine for testing without active network.",
    )

    @field_validator("alpaca_paper_trade")
    @classmethod
    def enforce_paper_trading_only(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "CRITICAL SAFETY VIOLATION: ThetaGuard is strictly configured for Paper Trading. "
                "ALPACA_PAPER_TRADE cannot be set to False."
            )
        return True

    @field_validator("allowed_universe")
    @classmethod
    def enforce_strict_universe(cls, v: List[str]) -> List[str]:
        cleaned = [s.upper().strip() for s in v]
        if set(cleaned) != {"SPY", "QQQ"}:
            raise ValueError(
                f"Universe violation: Only ['SPY', 'QQQ'] are authorized. Received: {v}"
            )
        return cleaned


@lru_cache()
def get_settings() -> Settings:
    """Returns singleton settings instance."""
    return Settings()
