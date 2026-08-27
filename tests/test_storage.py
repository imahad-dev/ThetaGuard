"""Tests for StateStore crash recovery and atomic state snapshot persistence."""
from pathlib import Path
from datetime import date, datetime, timezone
import pytest

from src.models.options import OptionContract, OptionType, PutCreditSpread
from src.models.portfolio import ActiveSpread
from src.models.signals import DecisionAction, TradeAuditLog, TradeReasoning, VolatilityRecord
from src.storage.state_store import StateStore


def create_sample_spread():
    short_leg = OptionContract(
        symbol="SPY",
        option_symbol="SPY260831P00550000",
        option_type=OptionType.PUT,
        strike_price=550.0,
        expiration_date=date(2026, 8, 31),
        bid=1.00,
        ask=1.10,
        mid=1.05,
        delta=-0.18,
    )
    long_leg = OptionContract(
        symbol="SPY",
        option_symbol="SPY260831P00545000",
        option_type=OptionType.PUT,
        strike_price=545.0,
        expiration_date=date(2026, 8, 31),
        bid=0.40,
        ask=0.45,
        mid=0.42,
        delta=-0.10,
    )
    return PutCreditSpread.create("SPY", short_leg, long_leg, quantity=1)


def test_state_store_save_and_load(tmp_path: Path):
    """Verifies that StateStore accurately saves and restores active spreads and audit history."""
    store_file = tmp_path / "test_state.json"
    store = StateStore(file_path=store_file)

    spread = create_sample_spread()
    active_spread = ActiveSpread(
        id="trade_test_01",
        underlying="SPY",
        spread=spread,
        status="OPEN",
        entry_credit=0.63,
        tp_order_id="mock_tp_12345",
    )

    audit_log = TradeAuditLog(
        trade_id="audit_test_01",
        action=DecisionAction.OPEN_SPREAD,
        underlying="SPY",
        reasoning=TradeReasoning(
            underlying="SPY",
            action=DecisionAction.OPEN_SPREAD,
            justification="Unit test reasoning justification",
        ),
        spread=spread,
        execution_status="SUBMITTED",
        net_credit_executed=0.63,
    )

    metadata = {"last_cycle_timestamp": "2026-08-28T14:30:00Z", "account_equity": 100123.0}

    vol_record = VolatilityRecord(
        timestamp=datetime.now(timezone.utc),
        spy_vol_rank=42.0,
        qqq_vol_rank=38.5,
        spy_vol=0.142,
        qqq_vol=0.181,
        iv_rank_floor=30.0,
    )

    # Save state
    store.save_state(
        active_spreads=[active_spread],
        execution_history=[audit_log],
        volatility_history=[vol_record],
        metadata=metadata,
    )
    assert store_file.exists()

    # Load state
    loaded_spreads, loaded_history, loaded_vol, loaded_meta = store.load_state()
    assert len(loaded_spreads) == 1
    assert loaded_spreads[0].id == "trade_test_01"
    assert loaded_spreads[0].tp_order_id == "mock_tp_12345"
    assert len(loaded_history) == 1
    assert loaded_history[0].trade_id == "audit_test_01"
    assert len(loaded_vol) == 1
    assert loaded_vol[0].spy_vol_rank == 42.0
    assert loaded_meta["account_equity"] == 100123.0


def test_tp_sl_race_prevention_in_client():
    """Verifies that close_spread_position correctly identifies and cancels resting TP order."""
    from src.clients.alpaca_client import AlpacaOptionsClient
    client = AlpacaOptionsClient()
    client.mock_mode = True
    spread = create_sample_spread()

    receipt = client.close_spread_position(
        spread=spread,
        reason="STOP_LOSS",
        tp_order_id="mock_tp_9999",
    )
    assert receipt["status"] == "CLOSED"
    assert receipt["tp_cancelled"] is True
