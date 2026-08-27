"""Tests for full multi-agent orchestration cycle."""
from src.clients.alpaca_client import AlpacaOptionsClient
from src.orchestration.graph import ThetaGuardEngine


def test_full_trading_cycle():
    """Runs full multi-agent cycle and validates outputs."""
    client = AlpacaOptionsClient()
    engine = ThetaGuardEngine(client)
    
    state = engine.run_cycle()
    assert state.workflow_status == "COMPLETED"
    assert state.account_state is not None
    assert state.risk_snapshot is not None
    assert len(state.reasoning_logs) > 0
    assert state.daily_summary is not None
    assert state.social_draft is not None
    assert "@lablabai" in state.social_draft.content
    assert "@AlpacaHQ" in state.social_draft.content
