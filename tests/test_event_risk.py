"""Tests for Event-Risk Agent macro blackout lockouts and IV verification."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from config.calendar_events import is_time_in_lockout, ET_TZ
from src.agents.event_risk import EventRiskAgent
from src.agents.state import AgentWorkflowState
from src.clients.alpaca_client import AlpacaOptionsClient


def test_jolts_lockout_window():
    """Verifies lockout triggers on Aug 31 EOD prior to Sep 1 10:00 AM ET JOLTS."""
    # Test during lockout (Aug 31 at 15:50 ET)
    dt_locked = datetime(2026, 8, 31, 15, 50, tzinfo=ET_TZ).astimezone(timezone.utc)
    in_lockout, event, reason = is_time_in_lockout(dt_locked)
    assert in_lockout is True
    assert event is not None
    assert "JOLTS" in event.name

    # Test before lockout (Aug 31 at 14:00 ET)
    dt_clear = datetime(2026, 8, 31, 14, 0, tzinfo=ET_TZ).astimezone(timezone.utc)
    in_lockout_clear, _, _ = is_time_in_lockout(dt_clear)
    assert in_lockout_clear is False


def test_nfp_lockout_window():
    """Verifies lockout triggers on Sep 3 EOD prior to Sep 4 8:30 AM ET NFP."""
    # Test during NFP morning (Sep 4 at 08:30 ET)
    dt_nfp = datetime(2026, 9, 4, 8, 30, tzinfo=ET_TZ).astimezone(timezone.utc)
    in_lockout, event, reason = is_time_in_lockout(dt_nfp)
    assert in_lockout is True
    assert event is not None
    assert "Non-Farm Payrolls" in event.name


def test_post_event_iv_verification():
    """Verifies that post-release IV rank check properly permits or skips entry."""
    client = AlpacaOptionsClient()
    agent = EventRiskAgent(client)
    
    # Below floor 30 -> skip
    allowed_low, _ = agent.verify_post_event_iv_rank("SPY", 22.0)
    assert allowed_low is False

    # Above floor 30 -> allow
    allowed_high, _ = agent.verify_post_event_iv_rank("SPY", 38.5)
    assert allowed_high is True
