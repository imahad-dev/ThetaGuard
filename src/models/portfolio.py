"""Portfolio, position, and account state models."""
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from src.models.options import PutCreditSpread


class PositionInfo(BaseModel):
    symbol: str = Field(description="Option contract or equity symbol")
    quantity: float
    market_value: float
    cost_basis: float
    unrealized_pl: float
    unrealized_plpc: float
    current_price: float
    side: str = Field(description="'long' or 'short'")


class ActiveSpread(BaseModel):
    id: str = Field(description="Unique internal ID for tracking the spread")
    underlying: str = Field(description="SPY or QQQ")
    spread: PutCreditSpread
    short_order_id: Optional[str] = None
    long_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    status: str = Field(default="OPEN", description="OPEN, CLOSED, EXPIRED, FORCED_EXIT")
    entry_credit: float
    current_spread_value: float = Field(default=0.0)
    realized_pl: float = Field(default=0.0)
    unrealized_pl: float = Field(default=0.0)
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    close_reason: Optional[str] = None


class AccountState(BaseModel):
    account_id: str
    status: str
    currency: str = "USD"
    cash: float
    portfolio_value: float
    buying_power: float
    equity: float
    last_equity: float
    initial_margin: float = 0.0
    maintenance_margin: float = 0.0
    daytrade_count: int = 0
    positions: List[PositionInfo] = Field(default_factory=list)
    active_spreads: List[ActiveSpread] = Field(default_factory=list)


class RiskSnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    account_equity: float
    total_capital_at_risk: float
    capital_at_risk_pct: float
    active_spread_count: int
    spy_spread_count: int
    qqq_spread_count: int
    max_risk_cap_pct: float = 0.05
    is_risk_cap_breached: bool = False
    risk_summary: str
