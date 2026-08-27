"""Event-Risk Agent: Enforces macro blackout calendars, force-exit triggers, and post-print IV verification."""
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from config.calendar_events import (
    CALENDAR_EVENTS,
    MacroEvent,
    is_time_in_lockout,
    ET_TZ,
)
from src.agents.state import AgentWorkflowState
from src.clients.alpaca_client import AlpacaOptionsClient
from src.models.signals import DecisionAction, TradeReasoning
from src.utils.logger import log


class EventRiskAgent:
    """
    Guards portfolio against high-impact macroeconomic event volatility.
    - Prevents opening positions in blackout windows (JOLTS Sep 1, NFP Sep 4).
    - Signals mandatory force-close of open positions before event market opens.
    - Verifies realized post-release IV rank before re-enabling premium harvesting.
    """

    def __init__(self, alpaca_client: Optional[AlpacaOptionsClient] = None):
        self.alpaca_client = alpaca_client or AlpacaOptionsClient()

    def process(self, state: AgentWorkflowState) -> AgentWorkflowState:
        current_dt = state.timestamp
        if current_dt.tzinfo is None:
            current_dt = current_dt.replace(tzinfo=timezone.utc)
        current_et = current_dt.astimezone(ET_TZ)
        state.current_time_et_str = current_et.strftime("%Y-%m-%d %H:%M:%S ET")

        log.info(f"[EVENT-RISK AGENT] Evaluating macro risks at {state.current_time_et_str}")

        in_lockout, event, reason = is_time_in_lockout(current_dt)
        state.is_in_event_lockout = in_lockout
        state.event_lockout_reason = reason

        if in_lockout:
            state.active_macro_event_name = event.name if event else "Build Window Closure"
            log.warning(f"[EVENT-RISK LOCKOUT ACTIVE] {reason}")

            # Check if open positions exist that must be force-closed before market open
            if state.active_spreads:
                state.force_close_all_positions = True
                log.warning(
                    f"[EVENT-RISK FORCE CLOSE] Flagging {len(state.active_spreads)} active spreads for immediate exit."
                )

            # Record reasoning for skipping new entries
            for sym in ["SPY", "QQQ"]:
                state.reasoning_logs.append(
                    TradeReasoning(
                        underlying=sym,
                        action=DecisionAction.SKIP_EVENT_LOCKOUT,
                        justification=(
                            f"Macro lockout active for {state.active_macro_event_name}. "
                            f"Rule Section 4/8 prohibits holding spreads through high-impact risk windows."
                        ),
                    )
                )
            state.next_step = "RISK_MANAGER_EXIT_CHECK"
        else:
            state.active_macro_event_name = None
            state.force_close_all_positions = False
            state.next_step = "STRATEGY_SELECTOR"

        return state

    def verify_post_event_iv_rank(self, underlying: str, current_iv_rank: float) -> Tuple[bool, str]:
        """
        After each macro print, checks realized IV rank post-release before allowing new entries.
        Contract §8: 'do not assume IV is automatically elevated after the data drops; verify it.'
        """
        if current_iv_rank < 30.0:
            return False, (
                f"Post-release IV rank for {underlying} is {current_iv_rank:.1f} (below floor 30.0). "
                f"IV crush confirmed -- skipping premium entry until volatility expands."
            )
        return True, f"Post-release IV rank for {underlying} verified at {current_iv_rank:.1f} >= 30.0. Entry permitted."
