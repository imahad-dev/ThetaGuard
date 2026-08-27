"""Tests for Execution Agent hard universe guardrails and paper trading enforcement."""
from datetime import date
from src.agents.execution import ExecutionAgent
from src.agents.state import AgentWorkflowState
from src.clients.alpaca_client import AlpacaOptionsClient
from src.models.options import OptionContract, OptionType, PutCreditSpread
from src.models.portfolio import AccountState


def test_hard_rejection_of_unauthorized_ticker():
    """Verifies that the Execution Agent hard-rejects any ticker other than SPY and QQQ."""
    client = AlpacaOptionsClient()
    agent = ExecutionAgent(client)

    # Attempt to construct spread on AAPL (Must be blocked)
    short_leg = OptionContract(
        symbol="SPY",  # bypass initial model check
        option_symbol="AAPL260831P00220000",
        option_type=OptionType.PUT,
        strike_price=220.0,
        expiration_date=date(2026, 8, 31),
        bid=1.0, ask=1.1, mid=1.05, delta=-0.18,
    )
    long_leg = OptionContract(
        symbol="SPY",
        option_symbol="AAPL260831P00215000",
        option_type=OptionType.PUT,
        strike_price=215.0,
        expiration_date=date(2026, 8, 31),
        bid=0.4, ask=0.5, mid=0.45, delta=-0.08,
    )
    spread = PutCreditSpread.create("SPY", short_leg, long_leg, quantity=1)
    # Manually tamper underlying
    object.__setattr__(spread, "underlying", "AAPL")

    state = AgentWorkflowState(
        account_state=AccountState(
            account_id="TEST", status="ACTIVE", cash=100000, portfolio_value=100000, buying_power=200000,
            equity=100000, last_equity=100000
        ),
        approved_spreads_to_open=[spread],
    )

    result = agent.process(state)
    assert len(result.active_spreads) == 0
    assert len(result.executed_trades) == 1
    assert result.executed_trades[0].execution_status == "REJECTED_UNAUTHORIZED_UNIVERSE"
    assert len(result.execution_errors) > 0
    assert "FATAL SECURITY VIOLATION" in result.execution_errors[0]
