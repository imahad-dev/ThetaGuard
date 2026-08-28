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


def test_expired_spread_settled_via_pure_bookkeeping_without_broker_error():
    """Verifies that expired spreads settle via pure bookkeeping with 0 broker order submissions."""
    from src.models.signals import DecisionAction
    from src.models.portfolio import ActiveSpread

    client = AlpacaOptionsClient()
    agent = ExecutionAgent(client)

    short_leg = OptionContract(
        symbol="SPY",
        option_symbol="SPY260826P00550000",
        option_type=OptionType.PUT,
        strike_price=550.0,
        expiration_date=date(2026, 8, 26),
        bid=1.0, ask=1.1, mid=1.05, delta=-0.18,
    )
    long_leg = OptionContract(
        symbol="SPY",
        option_symbol="SPY260826P00545000",
        option_type=OptionType.PUT,
        strike_price=545.0,
        expiration_date=date(2026, 8, 26),
        bid=0.4, ask=0.5, mid=0.45, delta=-0.08,
    )
    spread = PutCreditSpread.create("SPY", short_leg, long_leg, quantity=1)
    active_spread = ActiveSpread(
        id="thetaguard_spy_exp_test",
        underlying="SPY",
        spread=spread,
        tp_order_id="mock_tp_gtc_1787692514",
        status="OPEN",
        entry_credit=0.60,
    )

    state = AgentWorkflowState(
        account_state=AccountState(
            account_id="TEST", status="ACTIVE", cash=100000, portfolio_value=100000, buying_power=200000,
            equity=100000, last_equity=100000
        ),
        active_spreads=[active_spread],
        positions_to_close=[{
            "spread_item": active_spread,
            "action": DecisionAction.EXPIRED_MAX_PROFIT,
            "reason": "Contract matured at expiration (2026-08-26). Settled for 100% max profit.",
        }],
    )

    result = agent.process(state)
    assert len(result.execution_errors) == 0
    assert active_spread.status == "CLOSED"
    assert active_spread.realized_pl == 50.0
    assert len(result.executed_trades) == 1
    assert result.executed_trades[0].execution_status == "EXPIRED_WORTHLESS"
    assert result.executed_trades[0].realized_pnl == 50.0
