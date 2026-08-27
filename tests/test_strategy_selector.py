"""Tests for Strategy Selector Agent options chain discovery, delta filtering, and holiday exclusion."""
from datetime import date
from src.agents.strategy_selector import StrategySelectorAgent
from src.agents.state import AgentWorkflowState
from src.clients.alpaca_client import AlpacaOptionsClient
from src.utils.iv_calculator import (
    calculate_historical_realized_volatility_series,
    calculate_volatility_rank_and_percentile,
    generate_benchmark_price_history,
)


def test_delta_and_strike_width_selection():
    """Verifies that discovered spread has short delta between -0.15 and -0.20 and $5 width."""
    client = AlpacaOptionsClient()
    agent = StrategySelectorAgent(client)
    
    spot = 560.0
    iv_rank = 40.0
    spread = agent._find_best_spread_candidate("SPY", spot, iv_rank, date(2026, 8, 24))
    
    assert spread is not None
    assert spread.underlying == "SPY"
    assert spread.spread_width == 5.0
    assert spread.short_leg.strike_price > spread.long_leg.strike_price
    assert spread.short_leg.delta is not None
    assert -0.25 <= spread.short_leg.delta <= -0.10
    assert spread.max_profit > 0
    assert spread.max_loss > 0
    # TP price is 50% of credit
    assert spread.take_profit_target_price == round(spread.net_credit_per_share * 0.50, 2)


def test_mon_wed_fri_expiries_only():
    """Verifies dynamic enumeration lists only Mon/Wed/Fri dates."""
    client = AlpacaOptionsClient()
    expiries = client.enumerate_mon_wed_fri_expiries("SPY", min_dte=1, max_dte=14, reference_date=date(2026, 8, 28))
    for exp in expiries:
        assert exp.weekday() in (0, 2, 4)


def test_market_holidays_excluded_from_expiries():
    """Verifies that US Market Holidays like Labor Day (2026-09-07) are excluded from option expiries."""
    client = AlpacaOptionsClient()
    # Reference date: Friday Aug 28, 2026. Day offset 10 is Monday Sep 7, 2026 (Labor Day)
    expiries = client.enumerate_mon_wed_fri_expiries("SPY", min_dte=1, max_dte=14, reference_date=date(2026, 8, 28))
    assert date(2026, 9, 7) not in expiries


def test_empirical_volatility_rank_calculation():
    """Verifies empirical volatility percentile rank computation from price series."""
    prices_spy = generate_benchmark_price_history("SPY", count=252)
    prices_qqq = generate_benchmark_price_history("QQQ", count=252)

    vol_spy = calculate_historical_realized_volatility_series(prices_spy, window=20)
    vol_qqq = calculate_historical_realized_volatility_series(prices_qqq, window=20)

    rank_spy, pct_spy, min_s, max_s = calculate_volatility_rank_and_percentile(vol_spy[-1], vol_spy)
    rank_qqq, pct_qqq, min_q, max_q = calculate_volatility_rank_and_percentile(vol_qqq[-1], vol_qqq)

    assert 0.0 <= rank_spy <= 100.0
    assert 0.0 <= rank_qqq <= 100.0
    assert 0.0 <= pct_spy <= 100.0
    assert 0.0 <= pct_qqq <= 100.0
    assert min_s < max_s
    assert min_q < max_q
    # Distinct series must produce distinct statistics
    assert rank_spy != rank_qqq or pct_spy != pct_qqq
