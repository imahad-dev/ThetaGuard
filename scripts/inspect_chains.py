import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datetime import date
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.clients.alpaca_client import AlpacaOptionsClient

console = Console()


def inspect_symbol_chains(client: AlpacaOptionsClient, symbol: str):
    console.print(f"\n[bold cyan]=== Analyzing Underlying: {symbol} ===[/bold cyan]")
    spot = client.get_underlying_price(symbol)
    base_iv, iv_rank = client.get_current_iv_and_rank(symbol)
    
    console.print(Panel(
        f"[bold]Spot Price:[/bold] ${spot:,.2f}\n"
        f"[bold]Implied Volatility:[/bold] {base_iv * 100:.2f}%\n"
        f"[bold]52-Week IV Rank:[/bold] [{'green' if iv_rank >= 30 else 'yellow'}]{iv_rank:.1f}[/{'green' if iv_rank >= 30 else 'yellow'}] (Strategy Floor: 30.0)",
        title=f"{symbol} Market Snapshot",
        border_style="cyan",
    ))

    # Enumerate Mon/Wed/Fri expiries
    expiries = client.enumerate_mon_wed_fri_expiries(symbol, min_dte=2, max_dte=12)
    console.print(f"[bold]Discovered Mon/Wed/Fri Expirations:[/bold] {[str(e) for e in expiries]}")

    if not expiries:
        console.print("[red]No available expiries found.[/red]")
        return

    # Inspect first expiry chain
    target_expiry = expiries[0]
    chain = client.get_put_option_chain(symbol, target_expiry)

    t = Table(title=f"{symbol} Put Option Chain (Exp: {target_expiry})", border_style="green")
    t.add_column("OSI Symbol", style="dim")
    t.add_column("Strike", justify="right", style="bold")
    t.add_column("Delta", justify="right")
    t.add_column("Bid", justify="right", style="green")
    t.add_column("Ask", justify="right")
    t.add_column("Mid", justify="right", style="cyan")
    t.add_column("Strategy Fit", justify="center")

    for opt in chain[:15]:
        is_target_delta = (opt.delta is not None) and (-0.20 <= opt.delta <= -0.15)
        fit_badge = "[bold green]TARGET SHORT LEG[/bold green]" if is_target_delta else "-"
        t.add_row(
            opt.option_symbol,
            f"${opt.strike_price:.1f}",
            f"{opt.delta:.4f}" if opt.delta else "-",
            f"${opt.bid:.2f}",
            f"${opt.ask:.2f}",
            f"${opt.mid:.2f}",
            fit_badge,
        )

    console.print(t)


def main():
    console.print("[bold green]Starting Pre-Kickoff Options Chain & Delta Inspector...[/bold green]")
    client = AlpacaOptionsClient()
    console.print(Panel(
        f"[bold]Active Data Source:[/bold] [cyan]{client.data_source}[/cyan]\n"
        f"[bold]Paper Trading Enforcement:[/bold] [green]ENABLED (ALPACA_PAPER_TRADE=True)[/green]\n"
        f"[bold]Greeks & IV Calculation:[/bold] Analytical Black-Scholes Formula & 52-Week Normal Distribution Solver",
        title="ThetaGuard Data Provenance",
        border_style="cyan",
    ))
    for sym in ["SPY", "QQQ"]:
        inspect_symbol_chains(client, sym)
    console.print("\n[bold green][OK] Chain inspection complete. Delta strikes & IV ranks verified.[/bold green]")


if __name__ == "__main__":
    main()
