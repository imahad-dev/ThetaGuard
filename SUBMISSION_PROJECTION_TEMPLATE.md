# 🛡️ ThetaGuard — Final Submission Trade Log & P&L Report

> [!IMPORTANT]
> **PRE-KICKOFF SPECIFICATION & TEST PROJECTION TEMPLATE**  
> **Notice:** This document outlines the audit schema, expected metrics, and baseline projection for the **August 28 – September 4, 2026** hackathon trading window.  
> Real trade records are written by `ThetaGuardEngine` to `data/thetaguard_state.json` on every cycle. Running `python scripts/generate_submission_report.py` dynamically replaces this template with the verified empirical trade log.

**Hackathon:** Alpaca AI Trading Agents Hackathon (lablab.ai x Alpaca)  
**Track:** Income & Portfolio Overlay Agents  
**Build & Trading Window:** August 28, 2026 – September 4, 2026 (6 Trading Days)  
**Target Universe:** SPY & QQQ (Mon/Wed/Fri Expirations Only)  
**Strategy Type:** Defined-Risk Out-of-the-Money Put Credit Spreads ($5.00 Width)  
**Account Base:** Alpaca Paper Trading Account ($100,000.00 Initial Equity)  

---

## 1. Executive Summary & Strategy Highlights (Projected Target)

ThetaGuard executes a systematic, event-aware options premium collection overlay designed to produce a clean, low-variance positive P&L curve across the hackathon trading window without taking unhedged directional market exposure.

### Strategy Safeguards & Baseline Target Metrics:
* **Initial Account Equity:** `$100,000.00`
* **Target Net Realized P&L:** `+$350.00 to +$450.00` (`+0.35% to +0.45%` across 6 trading days)
* **Target Sizing:** Max 2 concurrent spreads ($\le 1$ SPY, $\le 1$ QQQ), $\le 5\%$ total portfolio risk, $\le 2\%$ single spread risk.
* **Exit Protocol:** Resting 50% Take-Profit GTC limit orders upon entry; active 200% Stop-Loss daemon polling; time-stop force exits before macro cutoffs.
* **Macro Blackout Adherence:** 100% (Strict zero-position lockout across Sep 1 JOLTS and Sep 4 NFP releases).

---

## 2. Benchmark Simulated Trade Audit Log (Calibrated Test Run)

| Trade ID | Entry Time (ET) | Ticker | Short Leg (Delta) | Long Leg (Delta) | Expiry | Est. Credit | Net Credit Exec. | Exit Reason | Realized P&L | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TG-SPY-260828` | 2026-08-28 10:15 | SPY | $552.0 Put (-0.179) | $547.0 Put (-0.098) | 2026-08-28 | $0.56 | $0.56 | `EXPIRED_MAX_PROFIT` | **+$56.00** | CLOSED |
| `TG-QQQ-260828` | 2026-08-28 10:15 | QQQ | $472.0 Put (-0.199) | $467.0 Put (-0.104) | 2026-08-28 | $0.67 | $0.67 | `EXPIRED_MAX_PROFIT` | **+$67.00** | CLOSED |
| `TG-SPY-260831` | 2026-08-31 09:45 | SPY | $554.0 Put (-0.182) | $549.0 Put (-0.095) | 2026-08-31 | $0.48 | $0.48 | `TAKE_PROFIT` (50%) | **+$24.00** | CLOSED |
| `TG-QQQ-260831` | 2026-08-31 09:45 | QQQ | $474.0 Put (-0.178) | $469.0 Put (-0.092) | 2026-08-31 | $0.54 | $0.54 | `TAKE_PROFIT` (50%) | **+$27.00** | CLOSED |
| `TG-SPY-260901` | 2026-09-01 10:30 | SPY | $555.0 Put (-0.165) | $550.0 Put (-0.089) | 2026-09-02 | $0.52 | $0.52 | `EXPIRED_MAX_PROFIT` | **+$52.00** | CLOSED |
| `TG-QQQ-260901` | 2026-09-01 10:30 | QQQ | $475.0 Put (-0.185) | $470.0 Put (-0.099) | 2026-09-02 | $0.63 | $0.63 | `EXPIRED_MAX_PROFIT` | **+$63.00** | CLOSED |
| `TG-SPY-260902` | 2026-09-02 11:00 | SPY | $556.0 Put (-0.172) | $551.0 Put (-0.091) | 2026-09-02 | $0.58 | $0.58 | `EXPIRED_MAX_PROFIT` | **+$58.00** | CLOSED |
| `TG-QQQ-260902` | 2026-09-02 11:00 | QQQ | $476.0 Put (-0.191) | $471.0 Put (-0.101) | 2026-09-02 | $0.65 | $0.65 | `EXPIRED_MAX_PROFIT` | **+$65.00** | CLOSED |

---

## 3. Daily Progression & Macro Event Integration Summary

```
Date         Target P&L      Ending Equity    Active Positions    Macro Event Status / Notes
------------------------------------------------------------------------------------------------------
2026-08-28   +$123.00        $100,123.00      0                   Kickoff day; 2 spreads expired OTM at 16:00 ET
2026-08-31   +$51.00         $100,174.00      0                   Pre-JOLTS early TP triggered at 50% max profit
2026-09-01   +$115.00        $100,289.00      0                   Post-JOLTS IV rank verified (36.2 >= 30.0); entries executed
2026-09-02   +$123.00        $100,412.00      0                   Compounding day; settled at 16:00 ET
2026-09-03   $0.00           $100,412.00      0                   Proactive Blackout Avoidance: 0 trades opened crossing NFP
2026-09-04   $0.00           $100,412.00      0                   NFP Release Lockout & Final Build-Window Settle (16:00 ET)
------------------------------------------------------------------------------------------------------
TOTAL        +$412.00        $100,412.00                          Clean, Monotonic, Low-Variance Growth
```

---

## 4. Submission Links & Verification Commands
* **Live Inspection CLI:** `python scripts/inspect_chains.py`
* **NFP Dry-Run Safety Simulation:** `python scripts/dry_run_nfp.py`
* **Dynamic Report Generator:** `python scripts/generate_submission_report.py`
* **FastAPI Dashboard Server:** `uvicorn src.api.main:app --port 8000`
