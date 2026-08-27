"""ThetaGuard Alpaca MCP Server: Reasoning & Dev Layer for Claude / Antigravity conversational inspection."""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from mcp.server.fastmcp import FastMCP
    mcp_app = FastMCP("thetaguard-alpaca-mcp")
except Exception:
    # Fallback lightweight mock wrapper if fastmcp is not installed
    class MockFastMCP:
        def __init__(self, name: str):
            self.name = name
            self.tools = {}
        def tool(self):
            def decorator(func):
                self.tools[func.__name__] = func
                return func
            return decorator
    mcp_app = MockFastMCP("thetaguard-alpaca-mcp")

from config.calendar_events import get_active_or_upcoming_lockouts, is_time_in_lockout
from config.settings import get_settings
from src.clients.alpaca_client import AlpacaOptionsClient
from src.orchestration.graph import ThetaGuardEngine

client = AlpacaOptionsClient()
engine = ThetaGuardEngine(client)


@mcp_app.tool()
def get_market_state(symbol: str = "SPY") -> str:
    """
    Fetches real-time market data, spot price, IV, and 52-week IV rank for SPY or QQQ.
    Verifies if current IV rank meets the strategy threshold (>= 30).
    """
    sym = symbol.upper()
    if sym not in ("SPY", "QQQ"):
        return json.dumps({"error": f"Invalid universe. Only SPY and QQQ allowed. Got: {symbol}"})
    
    price = client.get_underlying_price(sym)
    base_iv, iv_rank = client.get_current_iv_and_rank(sym)
    floor = get_settings().iv_rank_floor
    is_eligible = iv_rank >= floor

    return json.dumps({
        "symbol": sym,
        "spot_price": price,
        "implied_volatility": round(base_iv * 100, 2),
        "iv_rank": round(iv_rank, 1),
        "iv_rank_floor": floor,
        "is_eligible_for_premium_entry": is_eligible,
        "status": "APPROVED" if is_eligible else "SKIPPED_LOW_IV",
    }, indent=2)


@mcp_app.tool()
def audit_active_risk() -> str:
    """
    Audits current paper account equity, active open spreads, and total capital at risk against the 5% limit.
    """
    account = client.get_account_state()
    active_spreads = [s for s in engine._persisted_active_spreads if s.status == "OPEN"]
    total_risk = sum(s.spread.max_loss for s in active_spreads)
    risk_pct = (total_risk / account.equity) if account.equity > 0 else 0.0

    return json.dumps({
        "account_id": account.account_id,
        "account_equity": account.equity,
        "cash": account.cash,
        "active_spreads_count": len(active_spreads),
        "max_concurrent_spreads_allowed": 2,
        "total_capital_at_risk": total_risk,
        "risk_percentage_of_equity": round(risk_pct * 100, 2),
        "max_risk_cap_allowed_pct": 5.0,
        "is_risk_cap_breached": risk_pct > 0.05,
        "active_positions": [
            {
                "underlying": s.underlying,
                "expiry": str(s.spread.expiration_date),
                "short_strike": s.spread.short_leg.strike_price,
                "long_strike": s.spread.long_leg.strike_price,
                "credit_collected": s.spread.net_credit_per_share,
                "max_loss": s.spread.max_loss,
            }
            for s in active_spreads
        ],
    }, indent=2)


@mcp_app.tool()
def evaluate_spread_candidate(symbol: str = "SPY") -> str:
    """
    Calculates the optimal Put Credit Spread for SPY or QQQ:
    - Short Put: -0.15 to -0.20 delta
    - Long Put: $5 strike width below short strike
    - Mon/Wed/Fri Expirations
    - Defined max profit, max loss, take profit (50%), stop loss (200%)
    """
    sym = symbol.upper()
    if sym not in ("SPY", "QQQ"):
        return json.dumps({"error": f"Invalid universe. Only SPY and QQQ allowed. Got: {symbol}"})

    spot = client.get_underlying_price(sym)
    _, iv_rank = client.get_current_iv_and_rank(sym)
    spread = engine.strategy_selector_agent._find_best_spread_candidate(
        sym, spot, iv_rank, datetime.now(timezone.utc)
    )

    if not spread:
        return json.dumps({"status": "NO_SPREAD_FOUND", "message": f"No valid spread candidate found for {sym}"})

    return json.dumps({
        "underlying": spread.underlying,
        "expiration_date": str(spread.expiration_date),
        "short_leg": {
            "symbol": spread.short_leg.option_symbol,
            "strike": spread.short_leg.strike_price,
            "delta": spread.short_leg.delta,
            "bid": spread.short_leg.bid,
        },
        "long_leg": {
            "symbol": spread.long_leg.option_symbol,
            "strike": spread.long_leg.strike_price,
            "delta": spread.long_leg.delta,
            "ask": spread.long_leg.ask,
        },
        "spread_width": spread.spread_width,
        "net_credit_per_share": spread.net_credit_per_share,
        "max_profit_per_contract": spread.max_profit,
        "max_loss_per_contract": spread.max_loss,
        "take_profit_target_price": spread.take_profit_target_price,
        "stop_loss_trigger_price": spread.stop_loss_trigger_price,
    }, indent=2)


@mcp_app.tool()
def check_macro_lockout(iso_datetime_str: Optional[str] = None) -> str:
    """
    Checks if a given timestamp (or current time) falls in a macro event blackout (JOLTS Sep 1, NFP Sep 4).
    """
    dt = datetime.fromisoformat(iso_datetime_str) if iso_datetime_str else datetime.now(timezone.utc)
    in_lockout, event, reason = is_time_in_lockout(dt)
    upcoming = get_active_or_upcoming_lockouts(dt, hours_ahead=48.0)

    return json.dumps({
        "evaluated_timestamp": dt.isoformat(),
        "is_in_lockout": in_lockout,
        "active_event": event.name if event else None,
        "reason": reason,
        "upcoming_macro_events": upcoming,
    }, indent=2)


@mcp_app.tool()
def run_trading_cycle() -> str:
    """
    Executes a full systematic trading cycle across all ThetaGuard agents.
    Returns the complete cycle state, trades executed, and daily summary.
    """
    state = engine.run_cycle()
    return json.dumps({
        "timestamp": state.timestamp.isoformat(),
        "workflow_status": state.workflow_status,
        "is_in_lockout": state.is_in_event_lockout,
        "executed_trades_count": len(state.executed_trades),
        "reasoning_logs_count": len(state.reasoning_logs),
        "active_spreads_count": len([s for s in state.active_spreads if s.status == "OPEN"]),
        "account_equity": state.account_state.equity if state.account_state else 100_000.0,
    }, indent=2)


if __name__ == "__main__":
    if hasattr(mcp_app, "run"):
        mcp_app.run()
