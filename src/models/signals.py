"""Trade signals, audit logs, and agent communication models."""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from src.models.options import PutCreditSpread


class DecisionAction(str, Enum):
    OPEN_SPREAD = "OPEN_SPREAD"
    SKIP_LOW_IV = "SKIP_LOW_IV"
    SKIP_EVENT_LOCKOUT = "SKIP_EVENT_LOCKOUT"
    SKIP_MAX_POSITION_REACHED = "SKIP_MAX_POSITION_REACHED"
    SKIP_RISK_CAP_EXCEEDED = "SKIP_RISK_CAP_EXCEEDED"
    SKIP_NO_VALID_STRIKES = "SKIP_NO_VALID_STRIKES"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TIME_STOP_EVENT = "TIME_STOP_EVENT"
    TIME_STOP_BUILD_WINDOW_END = "TIME_STOP_BUILD_WINDOW_END"
    EXPIRED_MAX_PROFIT = "EXPIRED_MAX_PROFIT"
    HOLD = "HOLD"


class TradeReasoning(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    underlying: str
    action: DecisionAction
    iv_rank: Optional[float] = None
    iv_rank_floor: float = 30.0
    underlying_price: Optional[float] = None
    chosen_expiry: Optional[str] = None
    short_strike: Optional[float] = None
    short_delta: Optional[float] = None
    long_strike: Optional[float] = None
    long_delta: Optional[float] = None
    spread_width: Optional[float] = None
    estimated_net_credit: Optional[float] = None
    max_loss: Optional[float] = None
    account_equity: Optional[float] = None
    capital_at_risk_pct: Optional[float] = None
    justification: str = Field(
        description="Comprehensive audit-ready narrative explaining why this trade was selected or rejected."
    )
    raw_metrics: Dict[str, Any] = Field(default_factory=dict)


class TradeAuditLog(BaseModel):
    trade_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    action: DecisionAction
    underlying: str
    reasoning: TradeReasoning
    spread: Optional[PutCreditSpread] = None
    order_ids: List[str] = Field(default_factory=list)
    execution_status: str = Field(default="PENDING")
    net_credit_executed: Optional[float] = Field(
        default=None, description="Net premium collected or paid per share"
    )
    realized_pnl: Optional[float] = None
    is_paper_trading: bool = True


class SocialPostDraft(BaseModel):
    id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    platform: str = "X / Twitter & LinkedIn"
    tags: List[str] = Field(
        default=["@lablabai", "@AlpacaHQ", "#AlpacaTrading", "#OptionsTrading", "#AIagents", "#ThetaGuard"]
    )
    content: str
    metrics_highlight: Dict[str, Any] = Field(default_factory=dict)
    is_approved: bool = False


class DailyReportSummary(BaseModel):
    date_str: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    account_equity: float
    daily_realized_pl: float
    total_realized_pl: float
    active_spreads_count: int
    trades_opened_today: int
    trades_closed_today: int
    win_rate: float
    current_iv_ranks: Dict[str, float]
    upcoming_macro_events: List[Dict[str, Any]]
    audit_notes: List[str]
    suggested_social_draft: SocialPostDraft


class VolatilityRecord(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    spy_vol_rank: float = Field(description="52-week empirical volatility rank for SPY (0-100)")
    qqq_vol_rank: float = Field(description="52-week empirical volatility rank for QQQ (0-100)")
    spy_vol: float = Field(description="Current 20d annualized realized volatility for SPY")
    qqq_vol: float = Field(description="Current 20d annualized realized volatility for QQQ")
    iv_rank_floor: float = Field(default=30.0, description="Strategy entry threshold")
