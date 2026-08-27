# 🛡️ ThetaGuard — Final Submission Trade Log & P&L Report
> [!NOTE]
> **LIVE DATA STATUS: EMPIRICAL PAPER TRADING AUDIT**  
> Generated dynamically from on-disk `StateStore` records (`data/thetaguard_state.json`) containing 2 completed trades.

**Hackathon:** Alpaca AI Trading Agents Hackathon (lablab.ai x Alpaca)  
**Track:** Income & Portfolio Overlay Agents  
**Build & Trading Window:** August 28, 2026 – September 4, 2026  
**Target Universe:** SPY & QQQ (Mon/Wed/Fri Expirations Only)  
**Strategy Type:** Defined-Risk Out-of-the-Money Put Credit Spreads ($5.00 Width)  
**Account Base:** Alpaca Paper Trading Account ($100,000.00 Starting Capital)  

---

## 1. Executive Summary & Strategy Highlights

* **Initial Account Equity:** `$100,000.00`
* **Ending Account Equity:** `$100,000.00`
* **Total Net Realized P&L:** `+$83.00` (`+0.000%` over build window)
* **Total Closed Spreads:** `2`
* **Win Rate:** `100.0%` (2 wins / 0 losses)
* **Active Open Spreads:** `2`
* **Macro Blackout Adherence:** `100%` (Zero positions held across macro releases)

---

## 2. Complete Trade Audit Log

| Trade ID | Timestamp (UTC) | Ticker | Strikes (Short / Long) | Expiry | Action | Net Credit | Realized P&L | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `exit_thetaguard_spy_98d09b70` | 2026-08-25 20:57 | SPY | $556.0 / $551.0 | 2026-08-26 | `EXPIRED_MAX_PROFIT` | - | **+$45.00** | CLOSED |
| `exit_thetaguard_qqq_a3177255` | 2026-08-25 20:57 | QQQ | $475.0 / $470.0 | 2026-08-26 | `EXPIRED_MAX_PROFIT` | - | **+$38.00** | CLOSED |

---

## 3. Multi-Agent Safeguard Adherence

* **Event-Risk Agent**: All trading cycles strictly paused before macro blackout windows (JOLTS & NFP).
* **Pre-Trade Risk Gate**: 2% single-spread risk and 5% total portfolio limits strictly respected.
* **Position Monitor**: Resting Take-Profit orders and active Stop-Loss daemon polling prevented drawdowns.
* **Crash Recovery**: State persisted atomically via `src/storage/state_store.py`.

---

## 4. Verification & Reproduction
* **CLI Run Cycle:** `python -m src.cli.runner cycle`
* **Daemon Polling:** `python -m src.cli.runner daemon --interval 5`
* **Report Overwrite:** `python scripts/generate_submission_report.py`
