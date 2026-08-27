from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from config.calendar_events import get_active_or_upcoming_lockouts, is_time_in_lockout
from config.settings import get_settings
from src.clients.alpaca_client import AlpacaOptionsClient
from src.models.options import PutCreditSpread
from src.models.portfolio import AccountState, RiskSnapshot
from src.models.signals import DailyReportSummary, SocialPostDraft, TradeAuditLog, VolatilityRecord
from src.orchestration.graph import ThetaGuardEngine

router = APIRouter(prefix="/api")

# Singleton dependencies — single shared execution core
client = AlpacaOptionsClient()
engine = ThetaGuardEngine(client)


@router.get("/status")
def get_system_status() -> Dict[str, Any]:
    """Returns overview of account equity, cash, active spreads, and macro lockout."""
    account = client.get_account_state()
    in_lockout, event, reason = is_time_in_lockout()
    active_spreads = [s for s in engine._persisted_active_spreads if s.status == "OPEN"]
    total_risk = sum(s.spread.max_loss for s in active_spreads)
    settings = get_settings()
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_id": account.account_id,
        "is_paper_trading": True,
        "public_read_only_mode": settings.public_read_only_mode,
        "data_source": client.data_source,
        "equity": account.equity,
        "cash": account.cash,
        "buying_power": account.buying_power,
        "active_spreads_count": len(active_spreads),
        "max_concurrent_spreads": 2,
        "total_capital_at_risk": round(total_risk, 2),
        "risk_pct_of_equity": round((total_risk / account.equity * 100) if account.equity > 0 else 0.0, 2),
        "is_in_macro_lockout": in_lockout,
        "active_macro_event": event.name if event else None,
        "lockout_reason": reason,
    }


@router.get("/risk")
def get_risk_snapshot() -> Dict[str, Any]:
    """Returns comprehensive portfolio risk metrics."""
    account = client.get_account_state()
    active_spreads = [s for s in engine._persisted_active_spreads if s.status == "OPEN"]
    total_risk = sum(s.spread.max_loss for s in active_spreads)
    risk_pct = (total_risk / account.equity) if account.equity > 0 else 0.0

    return {
        "account_equity": account.equity,
        "total_capital_at_risk": round(total_risk, 2),
        "capital_at_risk_pct": round(risk_pct * 100, 2),
        "max_risk_cap_pct": 5.0,
        "max_spread_risk_cap_pct": 2.0,
        "active_spread_count": len(active_spreads),
        "spy_count": sum(1 for s in active_spreads if s.underlying == "SPY"),
        "qqq_count": sum(1 for s in active_spreads if s.underlying == "QQQ"),
        "is_cap_breached": risk_pct > 0.05,
    }


@router.get("/candidates")
def get_spread_candidates() -> List[Dict[str, Any]]:
    """Evaluates and returns real-time Put Credit Spread candidates for SPY and QQQ."""
    candidates = []
    for sym in ["SPY", "QQQ"]:
        spot = client.get_underlying_price(sym)
        base_iv, iv_rank = client.get_current_iv_and_rank(sym)
        spread = engine.strategy_selector_agent._find_best_spread_candidate(
            sym, spot, iv_rank, datetime.now(timezone.utc)
        )
        if spread:
            candidates.append({
                "underlying": spread.underlying,
                "spot_price": spot,
                "iv_rank": round(iv_rank, 1),
                "iv_rank_floor": get_settings().iv_rank_floor,
                "is_iv_eligible": iv_rank >= get_settings().iv_rank_floor,
                "expiration_date": str(spread.expiration_date),
                "short_leg": {
                    "strike": spread.short_leg.strike_price,
                    "delta": spread.short_leg.delta,
                    "bid": spread.short_leg.bid,
                },
                "long_leg": {
                    "strike": spread.long_leg.strike_price,
                    "delta": spread.long_leg.delta,
                    "ask": spread.long_leg.ask,
                },
                "spread_width": spread.spread_width,
                "net_credit": spread.net_credit_per_share,
                "max_profit": spread.max_profit,
                "max_loss": spread.max_loss,
                "take_profit_price": spread.take_profit_target_price,
                "stop_loss_price": spread.stop_loss_trigger_price,
            })
    return candidates


@router.post("/run-cycle")
def trigger_trading_cycle(x_admin_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """
    Manually triggers an end-to-end multi-agent systematic trading cycle.
    Strictly protected in Public Read-Only Mode to prevent unauthorized order placement.
    """
    settings = get_settings()
    if settings.public_read_only_mode and x_admin_key != settings.admin_api_key:
        raise HTTPException(
            status_code=403,
            detail="Public Read-Only Mode Active: Manual trade triggering is disabled for public dashboard viewers.",
        )

    state = engine.run_cycle()
    return {
        "status": "SUCCESS",
        "cycle_timestamp": state.timestamp.isoformat(),
        "is_in_lockout": state.is_in_event_lockout,
        "approved_opened": len(state.approved_spreads_to_open),
        "closed_positions": len(state.positions_to_close),
        "executed_trades_count": len(state.executed_trades),
        "reasoning_logs_count": len(state.reasoning_logs),
        "daily_summary": state.daily_summary.model_dump() if state.daily_summary else None,
        "social_draft": state.social_draft.model_dump() if state.social_draft else None,
    }


@router.get("/positions")
def get_active_positions() -> List[Dict[str, Any]]:
    """Returns list of active defined-risk spreads."""
    return [
        {
            "id": s.id,
            "underlying": s.underlying,
            "status": s.status,
            "expiration": str(s.spread.expiration_date),
            "short_strike": s.spread.short_leg.strike_price,
            "short_delta": s.spread.short_leg.delta,
            "long_strike": s.spread.long_leg.strike_price,
            "entry_credit": s.entry_credit,
            "max_profit": s.spread.max_profit,
            "max_loss": s.spread.max_loss,
            "take_profit_target": s.spread.take_profit_target_price,
            "stop_loss_target": s.spread.stop_loss_trigger_price,
            "opened_at": s.opened_at.isoformat(),
        }
        for s in engine._persisted_active_spreads
    ]


@router.get("/trades")
def get_trade_audit_logs() -> List[Dict[str, Any]]:
    """Returns chronological audit trail of all executed trades and reasons."""
    return [t.model_dump() for t in engine._execution_history]


@router.get("/macro-calendar")
def get_macro_calendar() -> List[Dict[str, Any]]:
    """Returns macro lockout schedule (JOLTS Sep 1, NFP Sep 4)."""
    return get_active_or_upcoming_lockouts(hours_ahead=None)


@router.get("/social-drafts")
def get_social_drafts() -> Dict[str, Any]:
    """Returns latest drafted Build-In-Public post for social review."""
    state = engine.run_cycle()
    return {
        "latest_draft": state.social_draft.model_dump() if state.social_draft else None,
        "daily_summary": state.daily_summary.model_dump() if state.daily_summary else None,
    }


@router.get("/volatility-history")
def get_volatility_history(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Returns chronological time series of SPY and QQQ volatility ranks vs entry threshold (30.0).
    
    Args:
        limit: Optional integer to return only the most recent N points (e.g. 100 for live dashboard).
               If None or <= 0, returns the full persistent week-long dataset.
    """
    if not engine._volatility_history:
        spy_vol, spy_rank = engine.alpaca_client.get_current_iv_and_rank("SPY")
        qqq_vol, qqq_rank = engine.alpaca_client.get_current_iv_and_rank("QQQ")
        record = VolatilityRecord(
            timestamp=datetime.now(timezone.utc),
            spy_vol_rank=round(spy_rank, 1),
            qqq_vol_rank=round(qqq_rank, 1),
            spy_vol=round(spy_vol, 4),
            qqq_vol=round(qqq_vol, 4),
            iv_rank_floor=30.0,
        )
        return [record.model_dump()]

    records = engine._volatility_history
    if limit and limit > 0:
        records = records[-limit:]
    return [v.model_dump() for v in records]

