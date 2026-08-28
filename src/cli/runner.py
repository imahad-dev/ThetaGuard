"""ThetaGuard CLI Execution Loop: Scheduled and on-demand production runner with structured JSON output."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from typing import Optional, Tuple
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config.calendar_events import get_active_or_upcoming_lockouts, is_time_in_lockout
from config.settings import get_settings
from src.clients.alpaca_client import AlpacaOptionsClient
from src.orchestration.graph import ThetaGuardEngine
from src.utils.logger import log

console = Console()


def print_banner():
    banner_text = """
========================================================================
  THETAGUARD -- Alpaca Options Premium & Portfolio Overlay Agent
  Systematic Defined-Risk Options Architecture (SPY & QQQ Paper Trading)
========================================================================
    """
    console.print(f"[bold cyan]{banner_text}[/bold cyan]")


def run_cycle_command(engine: ThetaGuardEngine, as_json: bool = False):
    """Executes a single end-to-end trading cycle."""
    state = engine.run_cycle()

    if as_json:
        print(state.model_dump_json(indent=2))
        return

    # Render beautiful CLI summary
    console.print(Panel(
        f"[bold green]ThetaGuard Cycle Completed at {state.current_time_et_str}[/bold green]\n"
        f"Status: [cyan]{state.workflow_status}[/cyan] | Macro Lockout: [{'red' if state.is_in_event_lockout else 'green'}]{state.is_in_event_lockout}[/{'red' if state.is_in_event_lockout else 'green'}]",
        title="Cycle Execution Receipt",
        border_style="cyan",
    ))

    # Risk Metrics Table
    if state.risk_snapshot:
        t_risk = Table(title="Portfolio Risk Snapshot", border_style="yellow")
        t_risk.add_column("Account Equity", justify="right", style="green")
        t_risk.add_column("Capital At Risk", justify="right", style="yellow")
        t_risk.add_column("Risk %", justify="right")
        t_risk.add_column("Active Spreads", justify="center", style="cyan")
        t_risk.add_column("Risk Cap %", justify="right")

        snap = state.risk_snapshot
        t_risk.add_row(
            f"${snap.account_equity:,.2f}",
            f"${snap.total_capital_at_risk:,.2f}",
            f"{snap.capital_at_risk_pct * 100:.2f}%",
            f"{snap.active_spread_count}/2 (SPY: {snap.spy_spread_count}, QQQ: {snap.qqq_spread_count})",
            f"{snap.max_risk_cap_pct * 100:.1f}%",
        )
        console.print(t_risk)

    # Executed Trades Table
    if state.executed_trades:
        t_trades = Table(title="Executed Trades in this Cycle", border_style="green")
        t_trades.add_column("Trade ID", style="dim")
        t_trades.add_column("Action", style="bold magenta")
        t_trades.add_column("Underlying", style="bold")
        t_trades.add_column("Strikes (Short / Long)", justify="center")
        t_trades.add_column("Expiry", justify="center")
        t_trades.add_column("Credit / Price", justify="right", style="green")
        t_trades.add_column("Realized PnL", justify="right")

        for tr in state.executed_trades:
            strikes = f"${tr.spread.short_leg.strike_price} / ${tr.spread.long_leg.strike_price}" if tr.spread else "-"
            expiry = str(tr.spread.expiration_date) if tr.spread else "-"
            credit = f"${tr.net_credit_executed:.2f}" if tr.net_credit_executed else "-"
            pnl = f"${tr.realized_pnl:.2f}" if tr.realized_pnl is not None else "-"
            t_trades.add_row(
                tr.trade_id,
                tr.action.value,
                tr.underlying,
                strikes,
                expiry,
                credit,
                pnl,
            )
        console.print(t_trades)

    # Audit Reasoning Panel
    for r in state.reasoning_logs:
        color = "green" if r.action.value == "OPEN_SPREAD" else "yellow"
        console.print(Panel(
            f"[bold {color}]{r.underlying} -> {r.action.value}[/bold {color}]\n"
            f"[white]{r.justification}[/white]",
            title=f"Reasoning Audit: {r.underlying}",
            border_style=color,
        ))


def get_dynamic_polling_interval_seconds(
    current_dt: Optional[datetime] = None, user_override_interval: Optional[int] = None
) -> Tuple[int, str]:
    """
    Contract §7 & Addendum 3 §3:
    Dynamically tightens daemon polling intervals:
    - Baseline: 300 seconds (5 minutes) for low turnover options monitoring.
    - High-Speed Event Window: Tightens to 30 seconds within 2 hours of JOLTS / NFP releases
      to protect positions against rapid gamma expansion and immediately catch 200% stop-loss breaches.
    """
    settings = get_settings()
    now_dt = current_dt or datetime.now(timezone.utc)
    in_lockout, active_event, reason = is_time_in_lockout(now_dt)

    if in_lockout:
        return settings.event_window_polling_seconds, f"HIGH_VOLATILITY (Active Lockout for {active_event.name if active_event else 'Event'} -> 30s Polling)"

    # Check upcoming events within 2 hours
    upcoming = get_active_or_upcoming_lockouts(now_dt, hours_ahead=2.0)
    if upcoming:
        return settings.event_window_polling_seconds, f"HIGH_VOLATILITY (Approaching {upcoming[0]['name']} in {upcoming[0]['hours_until_release']}h -> 30s Polling)"

    baseline = (user_override_interval * 60) if user_override_interval else settings.daemon_interval_seconds
    return baseline, f"NORMAL_RUNWAY ({baseline}s / {baseline // 60}m Polling)"


def run_status_command(client: AlpacaOptionsClient, engine: ThetaGuardEngine):
    """Displays real-time portfolio, risk, and event countdown status."""
    account = client.get_account_state()
    upcoming = get_active_or_upcoming_lockouts(hours_ahead=72.0)
    in_lockout, event, reason = is_time_in_lockout()
    poll_sec, poll_mode = get_dynamic_polling_interval_seconds()

    console.print(Panel(
        f"[bold]Account ID:[/bold] {account.account_id} [{client.data_source}]\n"
        f"[bold]Equity:[/bold] [green]${account.equity:,.2f}[/green]\n"
        f"[bold]Cash:[/bold] ${account.cash:,.2f}\n"
        f"[bold]Buying Power:[/bold] ${account.buying_power:,.2f}\n"
        f"[bold]Stop-Loss Polling Mode:[/bold] [cyan]{poll_mode}[/cyan]\n"
        f"[bold]Macro Lockout Active:[/bold] [{'red' if in_lockout else 'green'}]{in_lockout} ({reason})[/{'red' if in_lockout else 'green'}]",
        title="ThetaGuard Live Account Status",
        border_style="cyan",
    ))

    if upcoming:
        t_events = Table(title="Macro Events & Lockout Horizons", border_style="red")
        t_events.add_column("Event Name", style="bold")
        t_events.add_column("Release Time", style="cyan")
        t_events.add_column("Lockout Window", style="yellow")
        t_events.add_column("Hours to Release", justify="right")
        t_events.add_column("Status", justify="center")

        for ev in upcoming:
            t_events.add_row(
                ev["name"],
                ev["release_time"],
                f"{ev['lockout_start']} -> {ev['lockout_end']}",
                f"{ev['hours_until_release']} hrs",
                "[red]ACTIVE LOCKOUT[/red]" if ev["is_active"] else "[green]UPCOMING[/green]",
            )
        console.print(t_events)


def run_social_command(engine: ThetaGuardEngine):
    """Generates and prints the latest social post draft."""
    state = engine.run_cycle()
    if state.social_draft:
        console.print(Panel(
            state.social_draft.content,
            title="Latest Build-In-Public Social Post Draft (Ready to Review)",
            border_style="magenta",
        ))


def main():
    parser = argparse.ArgumentParser(description="ThetaGuard CLI Runner")
    parser.add_argument("command", nargs="?", default="cycle", choices=["cycle", "status", "social", "daemon", "clear-state"])
    parser.add_argument("--interval", type=int, default=5, help="Daemon baseline interval in minutes (default: 5)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON format for cron parsing")
    parser.add_argument("--dry-run", action="store_true", help="Run in mock/dry-run simulation mode")

    args = parser.parse_args()
    settings = get_settings()

    if not args.json:
        print_banner()

    client = AlpacaOptionsClient()
    engine = ThetaGuardEngine(client)

    if args.command == "clear-state":
        engine.state_store.clear()
        console.print("[bold green]ThetaGuard on-disk state cleared successfully. Fresh slate ready for live kickoff.[/bold green]")
        return

    if args.command == "cycle":
        run_cycle_command(engine, as_json=args.json)
    elif args.command == "status":
        run_status_command(client, engine)
    elif args.command == "social":
        run_social_command(engine)
    elif args.command == "daemon":
        console.print(f"[bold cyan]Starting ThetaGuard Production Daemon with Dynamic SL Polling...[/bold cyan]")
        try:
            while True:
                run_cycle_command(engine, as_json=args.json)
                interval_secs, mode_desc = get_dynamic_polling_interval_seconds(user_override_interval=args.interval)
                if not args.json:
                    console.print(f"[dim]Next heartbeat in {interval_secs}s [{mode_desc}]...[/dim]\n")
                time.sleep(interval_secs)
        except KeyboardInterrupt:
            console.print("\n[yellow]Daemon stopped by user.[/yellow]")


if __name__ == "__main__":
    main()
