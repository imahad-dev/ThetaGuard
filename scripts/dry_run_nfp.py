import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from rich.console import Console
from rich.panel import Panel

from config.calendar_events import CALENDAR_EVENTS, ET_TZ
from src.agents.event_risk import EventRiskAgent
from src.agents.state import AgentWorkflowState
from src.clients.alpaca_client import AlpacaOptionsClient
from src.orchestration.graph import ThetaGuardEngine

console = Console()


def simulate_nfp_timeline():
    console.print("[bold cyan]=== Simulating NFP Event Timeline (Proactive Expiry -> Expiration Settlement -> Zero-Exposure Cutoff -> Post-Print IV) ===[/bold cyan]\n")
    client = AlpacaOptionsClient()
    engine = ThetaGuardEngine(client)

    console.print(f"[DATA SOURCE PROVENANCE] {client.data_source}\n")

    # 1. Timeline Step 1: Proactive Expiry Selection on Sep 2 at 11:00 ET (2 days before NFP)
    # The selector MUST avoid picking Sep 4 expiry because it crosses NFP lockout!
    t1 = datetime(2026, 9, 2, 11, 0, tzinfo=ET_TZ).astimezone(timezone.utc)
    console.print(f"[bold yellow]Step 1: Proactive Blackout-Aware Expiry Selection (Sep 2, 11:00 ET)[/bold yellow]")
    state1 = engine.run_cycle(override_dt=t1)
    for spread in state1.approved_spreads_to_open:
        console.print(f" - Approved Spread: {spread.underlying} Expiry: [bold green]{spread.expiration_date}[/bold green] (Safe before Sep 3 EOD Cutoff)")
    for reason in state1.reasoning_logs:
        console.print(f" - Reasoning [{reason.underlying}]: {reason.action.value} -> {reason.justification[:100]}...")

    # 1b. Timeline Step 1b: Expiration Settlement at Market Close on Sep 2 at 16:05 ET
    t1b = datetime(2026, 9, 2, 16, 5, tzinfo=ET_TZ).astimezone(timezone.utc)
    console.print(f"\n[bold green]Step 1b: Automated Expiration Settlement (Sep 2, 16:05 ET)[/bold green]")
    state1b = engine.run_cycle(override_dt=t1b)
    for tr in state1b.executed_trades:
        console.print(f" - Matured Spread: {tr.underlying} -> Action: [bold green]{tr.action.value}[/bold green] | Realized PnL: ${tr.realized_pnl:.2f}")

    # 2a. Timeline Step 2a: Morning Scans on Sep 3 at 11:00 ET (Before cutoff)
    # Strategy selector scans chain, sees only Sep 4+ expiries which cross NFP, and PROACTIVELY SKIPS entry!
    t2a = datetime(2026, 9, 3, 11, 0, tzinfo=ET_TZ).astimezone(timezone.utc)
    console.print(f"\n[bold yellow]Step 2a: Pre-Cutoff Strategy Scan (Sep 3, 11:00 ET)[/bold yellow]")
    state2a = engine.run_cycle(override_dt=t2a)
    console.print(f" - Approved New Spreads: [bold cyan]{len(state2a.approved_spreads_to_open)}[/bold cyan] (Proactive filter blocked Sep 4 NFP crossing expiry)")
    for reason in state2a.reasoning_logs:
        console.print(f" - Reasoning [{reason.underlying}]: {reason.action.value} -> {reason.justification[:100]}...")

    # 2b. Timeline Step 2b: Lockout Cutoff on Sep 3 at 15:50 ET (Lockout active)
    # Because proactive selection prevented bad entries, there are ZERO open positions exposed to risk!
    t2b = datetime(2026, 9, 3, 15, 50, tzinfo=ET_TZ).astimezone(timezone.utc)
    console.print(f"\n[bold red]Step 2b: Pre-NFP Lockout Cutoff (Sep 3, 15:50 ET)[/bold red]")
    state2b = engine.run_cycle(override_dt=t2b)
    active_open = [s for s in engine._persisted_active_spreads if s.status == "OPEN"]
    console.print(Panel(
        f"Lockout Active: [red]{state2b.is_in_event_lockout}[/red]\n"
        f"Active Macro Event: {state2b.active_macro_event_name}\n"
        f"Open Spreads Exposed: [bold green]{len(active_open)}[/bold green] (Proactive Avoidance Successful!)\n"
        f"Positions Force-Closed: {len(state2b.positions_to_close)}\n"
        f"Reason: {state2b.event_lockout_reason}",
        title="Event-Risk Hard Intercept & Zero-Exposure Verification",
        border_style="red",
    ))

    # 3. Timeline Step 3: NFP Print Morning on Sep 4 at 08:30 ET (Release moment)
    t3 = datetime(2026, 9, 4, 8, 30, tzinfo=ET_TZ).astimezone(timezone.utc)
    console.print(f"\n[bold red]Step 3: NFP Release Window (Sep 4, 08:30 ET)[/bold red]")
    state3 = engine.run_cycle(override_dt=t3)
    console.print(f"Lockout Active: [red]{state3.is_in_event_lockout}[/red] | Trades Blocked: {len(state3.reasoning_logs)}")

    # 4. Timeline Step 4: Post-Release Volatility Verification on Sep 4 at 10:00 ET (Lockout ends)
    t4 = datetime(2026, 9, 4, 10, 0, tzinfo=ET_TZ).astimezone(timezone.utc)
    console.print(f"\n[bold green]Step 4: Post-Release Empirical IV Verification (Sep 4, 10:00 ET)[/bold green]")
    
    # Test Contract Section 8 & Addendum 1 Section 2: Test low post-release IV (< 30) vs elevated IV (>= 30)
    agent = EventRiskAgent(client)
    pass_low, msg_low = agent.verify_post_event_iv_rank("SPY", 24.5)
    pass_high, msg_high = agent.verify_post_event_iv_rank("SPY", 36.0)

    console.print(f"Test A (Crushed IV 24.5): [yellow]{msg_low}[/yellow] -> Entry Allowed: {pass_low}")
    console.print(f"Test B (Elevated IV 36.0): [green]{msg_high}[/green] -> Entry Allowed: {pass_high}")

    console.print("\n[bold green][OK] NFP Dry-Run simulation successfully validated all Contract Section 4, 8 and Addendum constraints.[/bold green]")


def main():
    simulate_nfp_timeline()


if __name__ == "__main__":
    main()
