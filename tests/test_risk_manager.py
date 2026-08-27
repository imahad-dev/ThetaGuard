"""Tests for Risk Manager Agent sizing limits and concentration caps."""
from datetime import date
from src.agents.risk_manager import RiskManagerAgent
from src.agents.state import AgentWorkflowState
from src.models.options import OptionContract, OptionType, PutCreditSpread
from src.models.portfolio import AccountState, ActiveSpread


def create_dummy_spread(symbol: str = "SPY", short_strike: float = 550.0) -> PutCreditSpread:
    short_leg = OptionContract(
        symbol=symbol,
        option_symbol=f"{symbol}260831P00550000",
        option_type=OptionType.PUT,
        strike_price=short_strike,
        expiration_date=date(2026, 8, 31),
        bid=1.00,
        ask=1.10,
        mid=1.05,
        delta=-0.18,
    )
    long_leg = OptionContract(
        symbol=symbol,
        option_symbol=f"{symbol}260831P00545000",
        option_type=OptionType.PUT,
        strike_price=short_strike - 5.0,
        expiration_date=date(2026, 8, 31),
        bid=0.40,
        ask=0.45,
        mid=0.42,
        delta=-0.10,
    )
    return PutCreditSpread.create(symbol, short_leg, long_leg, quantity=1)


def test_max_concurrent_spreads_cap():
    """Verifies that attempting to open >2 spreads is rejected."""
    agent = RiskManagerAgent()
    spread_spy = create_dummy_spread("SPY", 550.0)
    spread_qqq = create_dummy_spread("QQQ", 470.0)
    spread_third = create_dummy_spread("SPY", 545.0)

    # 2 spreads already active
    active1 = ActiveSpread(id="1", underlying="SPY", spread=spread_spy, status="OPEN", entry_credit=0.6)
    active2 = ActiveSpread(id="2", underlying="QQQ", spread=spread_qqq, status="OPEN", entry_credit=0.6)

    state = AgentWorkflowState(
        account_state=AccountState(
            account_id="TEST", status="ACTIVE", cash=100000, portfolio_value=100000, buying_power=200000,
            equity=100000, last_equity=100000
        ),
        active_spreads=[active1, active2],
        candidate_spreads=[spread_third],
    )

    result = agent.process(state)
    assert len(result.approved_spreads_to_open) == 0
    assert len(result.rejected_spreads) == 1
    assert "Concentration cap reached" in result.rejected_spreads[0]["reason"]


def test_portfolio_risk_cap_enforcement():
    """Verifies that total risk cannot breach 5% of account equity."""
    agent = RiskManagerAgent()
    spread = create_dummy_spread("SPY", 550.0)
    
    # Account with only $5,000 equity -> $5 width spread max loss is ~$440 (8.8% of equity, exceeds 5% and 2%)
    state = AgentWorkflowState(
        account_state=AccountState(
            account_id="TEST", status="ACTIVE", cash=5000, portfolio_value=5000, buying_power=10000,
            equity=5000, last_equity=5000
        ),
        active_spreads=[],
        candidate_spreads=[spread],
    )

    result = agent.process(state)
    assert len(result.approved_spreads_to_open) == 0
    assert len(result.rejected_spreads) == 1


def test_expiration_settlement_at_market_close():
    """Verifies that PositionMonitor automatically settles expired OTM spreads for 100% max profit."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from src.models.signals import DecisionAction
    
    agent = RiskManagerAgent()
    spread = create_dummy_spread("SPY", 550.0)
    # Spread expires Aug 31, 2026
    active = ActiveSpread(id="exp_01", underlying="SPY", spread=spread, status="OPEN", entry_credit=0.6)

    # State evaluated at Aug 31, 2026 16:05 ET (5 minutes after market close)
    et_tz = ZoneInfo("America/New_York")
    eval_dt = datetime(2026, 8, 31, 16, 5, tzinfo=et_tz).astimezone(timezone.utc)

    state = AgentWorkflowState(
        timestamp=eval_dt,
        account_state=AccountState(
            account_id="TEST", status="ACTIVE", cash=100000, portfolio_value=100000, buying_power=200000,
            equity=100000, last_equity=100000
        ),
        active_spreads=[active],
    )

    result = agent.process(state)
    assert len(result.positions_to_close) == 1
    exit_info = result.positions_to_close[0]
    assert exit_info["action"] == DecisionAction.EXPIRED_MAX_PROFIT
    assert "Settled for 100% max profit" in exit_info["reason"]


def test_dynamic_polling_interval_during_lockout():
    """Verifies dynamic tightening to 30s during high-volatility event windows."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from src.cli.runner import get_dynamic_polling_interval_seconds

    et_tz = ZoneInfo("America/New_York")
    # Sep 4 8:00 ET is 30 mins before NFP release -> must tighten to 30s
    t_nfp_approach = datetime(2026, 9, 4, 8, 0, tzinfo=et_tz).astimezone(timezone.utc)
    poll_sec, mode_desc = get_dynamic_polling_interval_seconds(t_nfp_approach)
    assert poll_sec == 30
    assert "HIGH_VOLATILITY" in mode_desc

    # Sep 2 12:00 ET is outside event windows -> baseline 300s
    t_normal = datetime(2026, 9, 2, 12, 0, tzinfo=et_tz).astimezone(timezone.utc)
    poll_sec_normal, mode_desc_normal = get_dynamic_polling_interval_seconds(t_normal)
    assert poll_sec_normal == 300
    assert "NORMAL_RUNWAY" in mode_desc_normal


def test_options_chain_ttl_caching():
    """Verifies that AlpacaOptionsClient caches chains for 60s to prevent rate-limiting."""
    from src.clients.alpaca_client import AlpacaOptionsClient
    client = AlpacaOptionsClient()

    chain1 = client.get_put_option_chain("SPY", date(2026, 8, 28))
    cache_key = "SPY_2026-08-28"
    assert cache_key in client._chain_cache
    
    # Second immediate query returns cached reference
    chain2 = client.get_put_option_chain("SPY", date(2026, 8, 28))
    assert chain1 is chain2
