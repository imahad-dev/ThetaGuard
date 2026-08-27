"""Strategy Selector Agent: Discovers options chains, filters IV rank, and builds delta-hedged put credit spreads."""
from datetime import date, datetime, timedelta
from typing import Any, List, Optional, Union
from zoneinfo import ZoneInfo

from config.calendar_events import (
    CALENDAR_EVENTS,
    ET_TZ,
    is_expiry_safe_from_blackouts,
)
from config.settings import get_settings
from src.agents.state import AgentWorkflowState
from src.clients.alpaca_client import AlpacaOptionsClient
from src.models.options import OptionContract, PutCreditSpread
from src.models.signals import DecisionAction, TradeReasoning
from src.utils.logger import log


class StrategySelectorAgent:
    """
    Selects defined-risk Put Credit Spreads based on IV rank and delta boundaries:
    - Short Put: -0.15 to -0.20 delta
    - Long Put: $5 strike width below short strike
    - Expiries: Mon/Wed/Fri, PROACTIVELY avoiding macro blackout windows (Sep 1 JOLTS, Sep 4 NFP)
    """

    def __init__(self, alpaca_client: Optional[AlpacaOptionsClient] = None):
        self.settings = get_settings()
        self.alpaca_client = alpaca_client or AlpacaOptionsClient()

    def process(self, state: AgentWorkflowState) -> AgentWorkflowState:
        log.info("[STRATEGY SELECTOR] Scanning SPY and QQQ for options premium opportunities...")
        
        # If event risk agent initiated a blackout or force-close, skip strategy search
        if state.is_in_event_lockout:
            log.info("[STRATEGY SELECTOR] Event lockout active. Skipping entry scans.")
            return state

        state.evaluated_tickers = list(self.settings.allowed_universe)
        state.candidate_spreads = []

        # Find existing active tickers to avoid duplicate spreads on the same ticker
        existing_underlyings = {
            s.underlying for s in state.active_spreads if s.status == "OPEN"
        }

        for symbol in state.evaluated_tickers:
            if symbol in existing_underlyings:
                log.info(f"[STRATEGY SELECTOR] Skipping {symbol}: Existing open spread position found.")
                state.reasoning_logs.append(
                    TradeReasoning(
                        underlying=symbol,
                        action=DecisionAction.SKIP_MAX_POSITION_REACHED,
                        justification=(
                            f"Position on {symbol} is already active. Max concentration rule Section 5 allows "
                            f"at most 1 spread on {symbol}."
                        ),
                    )
                )
                continue

            # Step 1: Pull current spot price and IV rank
            spot_price = self.alpaca_client.get_underlying_price(symbol)
            base_iv, iv_rank = self.alpaca_client.get_current_iv_and_rank(symbol)
            state.market_iv_ranks[symbol] = round(iv_rank, 1)

            # Step 2: Check IV Rank floor
            if iv_rank < self.settings.iv_rank_floor:
                log.info(
                    f"[STRATEGY SELECTOR] Skipping {symbol}: IV Rank ({iv_rank:.1f}) < Floor ({self.settings.iv_rank_floor})"
                )
                state.reasoning_logs.append(
                    TradeReasoning(
                        underlying=symbol,
                        action=DecisionAction.SKIP_LOW_IV,
                        iv_rank=round(iv_rank, 1),
                        iv_rank_floor=self.settings.iv_rank_floor,
                        underlying_price=spot_price,
                        justification=(
                            f"IV Rank for {symbol} is {iv_rank:.1f}, which fails the minimum threshold "
                            f"of {self.settings.iv_rank_floor}. Premium is too cheap to justify downside risk."
                        ),
                    )
                )
                continue

            # Step 3: Select valid Mon/Wed/Fri Expiries that proactively avoid macro events
            candidate_spread = self._find_best_spread_candidate(symbol, spot_price, iv_rank, state.timestamp)
            if candidate_spread:
                state.candidate_spreads.append(candidate_spread)
                log.info(
                    f"[STRATEGY SELECTOR] Generated candidate spread for {symbol}: "
                    f"Exp {candidate_spread.expiration_date} | Short {candidate_spread.short_leg.strike_price} "
                    f"(Delta: {candidate_spread.short_leg.delta}) | Long {candidate_spread.long_leg.strike_price} | "
                    f"Credit: ${candidate_spread.net_credit_per_share:.2f}"
                )
            else:
                log.info(f"[STRATEGY SELECTOR] No blackout-safe spread candidate found for {symbol} at this time.")
                state.reasoning_logs.append(
                    TradeReasoning(
                        underlying=symbol,
                        action=DecisionAction.SKIP_EVENT_LOCKOUT,
                        iv_rank=round(iv_rank, 1),
                        underlying_price=spot_price,
                        justification=(
                            f"Proactive Blackout Filter: No Mon/Wed/Fri expiration matures safely before "
                            f"the next upcoming macro blackout window. Trade entry blocked to prevent forced liquidation."
                        ),
                    )
                )

        state.next_step = "RISK_MANAGER"
        return state

    def _find_best_spread_candidate(
        self, symbol: str, spot_price: float, iv_rank: float, current_dt: Any
    ) -> Optional[PutCreditSpread]:
        """Discovers options chain, identifies Mon/Wed/Fri expiry safe from lockouts, and forms spread."""
        if isinstance(current_dt, datetime):
            ref_date = current_dt.date()
        elif isinstance(current_dt, date):
            ref_date = current_dt
        else:
            ref_date = date.today()

        # Enumerate dynamic Mon/Wed/Fri expiries within 1 to 10 DTE
        available_expiries = self.alpaca_client.enumerate_mon_wed_fri_expiries(
            symbol, min_dte=1, max_dte=10, reference_date=ref_date
        )

        valid_expiry = None
        for exp in available_expiries:
            is_safe, reason = is_expiry_safe_from_blackouts(exp, current_dt)
            if is_safe:
                valid_expiry = exp
                break

        if not valid_expiry:
            # Proactive avoidance: Do NOT fallback to an unsafe expiry!
            return None

        # Pull put chain for this expiration respecting current simulation/live timestamp
        chain = self.alpaca_client.get_put_option_chain(symbol, valid_expiry, current_dt=current_dt)
        if not chain:
            return None

        # Filter short leg: delta between min_short_delta (-0.20) and max_short_delta (-0.15)
        # Delta for puts is negative: e.g. -0.20 <= delta <= -0.15
        short_candidates = [
            c for c in chain
            if c.delta is not None and self.settings.min_short_delta <= c.delta <= self.settings.max_short_delta
        ]

        if not short_candidates:
            # Pick closest strike near -0.17 delta
            short_candidates = sorted(
                chain, key=lambda c: abs((c.delta or -0.5) - (-0.17))
            )

        if not short_candidates:
            return None

        short_leg = short_candidates[0]

        # Target long leg: $5 wide lower strike
        target_long_strike = short_leg.strike_price - self.settings.spread_width
        long_candidates = [c for c in chain if abs(c.strike_price - target_long_strike) < 0.25]

        if not long_candidates:
            # Pick closest strike below short leg
            lower_strikes = [c for c in chain if c.strike_price < short_leg.strike_price]
            if not lower_strikes:
                return None
            long_leg = min(lower_strikes, key=lambda c: abs(c.strike_price - target_long_strike))
        else:
            long_leg = long_candidates[0]

        try:
            spread = PutCreditSpread.create(
                underlying=symbol,
                short_leg=short_leg,
                long_leg=long_leg,
                quantity=1,
            )
            return spread
        except Exception as e:
            log.warning(f"Failed to create spread for {symbol}: {e}")
            return None
