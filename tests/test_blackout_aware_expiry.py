"""Tests for Proactive Blackout-Aware Expiry Selection and Safety Guardrails."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient

from config.calendar_events import (
    CALENDAR_EVENTS,
    ET_TZ,
    is_expiry_safe_from_blackouts,
)
from src.agents.execution import ExecutionAgent
from src.agents.state import AgentWorkflowState
from src.agents.strategy_selector import StrategySelectorAgent
from src.api.main import app
from src.clients.alpaca_client import AlpacaOptionsClient
from src.models.options import OptionContract, OptionType, PutCreditSpread


def test_is_expiry_safe_from_blackouts_direct():
    """Direct validation of blackout boundary safety."""
    # Scenario 1: Aug 28 evaluating Aug 28 (today's close 16:00 ET) -> SAFE (before Aug 31 15:45 ET)
    t_aug28 = datetime(2026, 8, 28, 10, 0, tzinfo=ET_TZ)
    safe, msg = is_expiry_safe_from_blackouts(date(2026, 8, 28), t_aug28)
    assert safe is True

    # Scenario 2: Aug 28 evaluating Aug 31 (expires Aug 31 16:00 ET) -> UNSAFE (crosses Aug 31 15:45 ET JOLTS lockout)
    safe, msg = is_expiry_safe_from_blackouts(date(2026, 8, 31), t_aug28)
    assert safe is False
    assert "JOLTS Job Openings lockout start" in msg

    # Scenario 3: Aug 28 evaluating Sep 1 (JOLTS release day) -> UNSAFE
    safe, msg = is_expiry_safe_from_blackouts(date(2026, 9, 1), t_aug28)
    assert safe is False

    # Scenario 4: Sep 1 11:00 ET (after JOLTS) evaluating Wed Sep 2 -> SAFE (matures before Sep 3 15:45 ET NFP lockout)
    t_sep1_post = datetime(2026, 9, 1, 11, 0, tzinfo=ET_TZ)
    safe, msg = is_expiry_safe_from_blackouts(date(2026, 9, 2), t_sep1_post)
    assert safe is True

    # Scenario 5: Sep 2 evaluating Fri Sep 4 -> UNSAFE (crosses Sep 3 15:45 ET NFP lockout and Sep 4 8:30 AM release)
    t_sep2 = datetime(2026, 9, 2, 10, 0, tzinfo=ET_TZ)
    safe, msg = is_expiry_safe_from_blackouts(date(2026, 9, 4), t_sep2)
    assert safe is False
    assert "Non-Farm Payrolls" in msg


def test_strategy_selector_never_picks_blackout_crossing_expiry():
    """
    Contract §4 / Addendum 1 §9 / Addendum 2 #2:
    Assert that StrategySelectorAgent never selects an expiry that lands on or after
    the start of a blackout window (Aug 31 EOD for JOLTS, Sep 3 EOD for NFP).
    """
    client = AlpacaOptionsClient()
    agent = StrategySelectorAgent(client)

    # Test evaluated on Sep 2 (Wed before Sep 4 NFP)
    current_dt = datetime(2026, 9, 2, 10, 30, tzinfo=ET_TZ).astimezone(timezone.utc)
    spread = agent._find_best_spread_candidate("SPY", spot_price=560.0, iv_rank=42.0, current_dt=current_dt)

    if spread is not None:
        # Expiry MUST mature strictly before Sep 3, 15:45 ET
        expiry_dt = datetime(spread.expiration_date.year, spread.expiration_date.month, spread.expiration_date.day, 16, 0, tzinfo=ET_TZ)
        nfp_lockout_start = datetime(2026, 9, 3, 15, 45, tzinfo=ET_TZ)
        assert expiry_dt < nfp_lockout_start, f"Selected expiry {spread.expiration_date} crossed NFP lockout!"


def test_audit_log_written_pre_submission():
    """
    Addendum 1 §7 / Addendum 2 #6:
    Assert that ExecutionAgent writes the full reasoning record BEFORE submitting an order,
    so that even an unauthorized/rejected order leaves an immutable audit trace.
    """
    client = AlpacaOptionsClient()
    exec_agent = ExecutionAgent(client)

    # Create a candidate spread and tamper underlying to test runtime guardrail
    short_opt = OptionContract(
        symbol="SPY", option_symbol="AAPL260904P00220000", option_type=OptionType.PUT,
        strike_price=220.0, expiration_date=date(2026, 9, 4), delta=-0.17, bid=1.20, ask=1.30
    )
    long_opt = OptionContract(
        symbol="SPY", option_symbol="AAPL260904P00215000", option_type=OptionType.PUT,
        strike_price=215.0, expiration_date=date(2026, 9, 4), delta=-0.10, bid=0.40, ask=0.50
    )
    illegal_spread = PutCreditSpread.create(
        underlying="SPY", short_leg=short_opt, long_leg=long_opt, quantity=1
    )
    object.__setattr__(illegal_spread, "underlying", "AAPL")

    state = AgentWorkflowState(
        approved_spreads_to_open=[illegal_spread],
        timestamp=datetime.now(timezone.utc),
    )

    result_state = exec_agent.process(state)

    # Must contain audit log recording the rejection
    assert len(result_state.executed_trades) >= 1
    rejected_audit = result_state.executed_trades[0]
    assert rejected_audit.underlying == "AAPL"
    assert rejected_audit.execution_status == "REJECTED_UNAUTHORIZED_UNIVERSE"
    assert len(result_state.execution_errors) >= 1
    # No active spread position opened
    assert len(result_state.active_spreads) == 0
    assert rejected_audit.execution_status == "REJECTED_UNAUTHORIZED_UNIVERSE"
    assert len(result_state.execution_errors) >= 1


def test_public_read_only_route_protection():
    """
    Addendum 1 §8 / Addendum 2 #6:
    Assert that public web route /api/run-cycle cannot trigger orders without admin auth.
    """
    test_client = TestClient(app)
    
    # 1. Calling /api/run-cycle without auth header in public read-only mode returns 403
    response = test_client.post("/api/run-cycle")
    assert response.status_code == 403
    assert "Public Read-Only Mode Active" in response.json()["detail"]

    # 2. Calling with correct admin secret succeeds
    auth_response = test_client.post("/api/run-cycle", headers={"X-Admin-Key": "THETAGUARD_ADMIN_SECRET"})
    assert auth_response.status_code == 200
    assert auth_response.json()["status"] == "SUCCESS"
