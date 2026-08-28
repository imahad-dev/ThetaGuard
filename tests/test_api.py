"""Tests for FastAPI REST API endpoints and dashboard data contracts."""
import pytest
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_api_status_endpoint():
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert "account_id" in data
    assert data["is_paper_trading"] is True
    assert data["equity"] > 0
    assert "is_in_macro_lockout" in data


def test_api_risk_endpoint():
    res = client.get("/api/risk")
    assert res.status_code == 200
    data = res.json()
    assert data["max_risk_cap_pct"] == 5.0
    assert "capital_at_risk_pct" in data
    assert "active_spread_count" in data


def test_api_candidates_endpoint():
    res = client.get("/api/candidates")
    assert res.status_code == 200
    candidates = res.json()
    assert isinstance(candidates, list)
    for c in candidates:
        assert c["underlying"] in ("SPY", "QQQ")
        assert c["spread_width"] == 5.0
        assert "short_leg" in c
        assert "long_leg" in c


def test_api_macro_calendar_endpoint():
    res = client.get("/api/macro-calendar")
    assert res.status_code == 200
    events = res.json()
    assert len(events) >= 1
    event_names = [e["name"] for e in events]
    assert any("JOLTS" in name or "Payrolls" in name for name in event_names)


def test_api_run_cycle_and_trades_endpoint():
    res_cycle = client.post("/api/run-cycle", headers={"X-Admin-Key": "THETAGUARD_ADMIN_SECRET"})
    assert res_cycle.status_code == 200
    cycle_data = res_cycle.json()
    assert cycle_data["status"] == "SUCCESS"
    assert "cycle_timestamp" in cycle_data

    res_trades = client.get("/api/trades")
    assert res_trades.status_code == 200
    trades = res_trades.json()
    assert isinstance(trades, list)


def test_api_social_drafts_endpoint():
    res = client.get("/api/social-drafts")
    assert res.status_code == 200
    data = res.json()
    assert "latest_draft" in data
    assert "@lablabai" in data["latest_draft"]["content"]
    assert "@AlpacaHQ" in data["latest_draft"]["content"]


def test_api_volatility_history_endpoint():
    res = client.get("/api/volatility-history")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "spy_vol_rank" in data[0]
    assert "qqq_vol_rank" in data[0]
    assert data[0]["iv_rank_floor"] == 30.0

    # Test limit parameter
    res_limit = client.get("/api/volatility-history?limit=1")
    assert res_limit.status_code == 200
    data_limit = res_limit.json()
    assert len(data_limit) == 1

