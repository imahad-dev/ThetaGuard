"""Tests for settings validation and safety constraints."""
import pytest
from pydantic import ValidationError
from config.settings import Settings


def test_paper_trading_cannot_be_disabled():
    """Verifies that ALPACA_PAPER_TRADE=False raises a critical validation error."""
    with pytest.raises(ValidationError):
        Settings(alpaca_paper_trade=False)


def test_universe_strictly_spy_and_qqq():
    """Verifies that attempting to configure unauthorized symbols is rejected."""
    with pytest.raises(ValidationError):
        Settings(allowed_universe=["AAPL", "TSLA"])

    valid = Settings(allowed_universe=["SPY", "QQQ"])
    assert "SPY" in valid.allowed_universe
    assert "QQQ" in valid.allowed_universe
