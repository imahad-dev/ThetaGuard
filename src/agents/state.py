"""Multi-agent shared state schema for LangGraph orchestration."""
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional
from pydantic import BaseModel, Field
import operator

from src.models.options import PutCreditSpread
from src.models.portfolio import AccountState, ActiveSpread, RiskSnapshot
from src.models.signals import (
    DailyReportSummary,
    DecisionAction,
    SocialPostDraft,
    TradeAuditLog,
    TradeReasoning,
)


class AgentWorkflowState(BaseModel):
    """Immutable state container flowing through the LangGraph multi-agent graph."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Environment & System State
    current_time_et_str: str = ""
    is_simulation: bool = False
    
    # Account & Portfolio Snapshot
    account_state: Optional[AccountState] = None
    risk_snapshot: Optional[RiskSnapshot] = None
    active_spreads: List[ActiveSpread] = Field(default_factory=list)
    
    # Event-Risk Agent Outputs
    is_in_event_lockout: bool = False
    active_macro_event_name: Optional[str] = None
    event_lockout_reason: str = ""
    force_close_all_positions: bool = False
    
    # Strategy Selector Agent Outputs
    evaluated_tickers: List[str] = Field(default_factory=list)
    market_iv_ranks: Dict[str, float] = Field(default_factory=dict)
    candidate_spreads: List[PutCreditSpread] = Field(default_factory=list)
    reasoning_logs: List[TradeReasoning] = Field(default_factory=list)
    
    # Risk Manager Agent Outputs
    approved_spreads_to_open: List[PutCreditSpread] = Field(default_factory=list)
    rejected_spreads: List[Dict[str, Any]] = Field(default_factory=list)
    positions_to_close: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Execution Agent Outputs
    executed_trades: List[TradeAuditLog] = Field(default_factory=list)
    execution_errors: List[str] = Field(default_factory=list)
    
    # Reporter & Build-in-Public Outputs
    daily_summary: Optional[DailyReportSummary] = None
    social_draft: Optional[SocialPostDraft] = None
    
    # Flow Control
    workflow_status: str = "INITIALIZED"
    next_step: str = "EVENT_RISK_CHECK"
