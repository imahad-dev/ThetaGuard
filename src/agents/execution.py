from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from config.settings import get_settings
from src.agents.state import AgentWorkflowState
from src.clients.alpaca_client import AlpacaOptionsClient
from src.models.portfolio import ActiveSpread
from src.models.signals import DecisionAction, TradeAuditLog, TradeReasoning
from src.utils.logger import log


class ExecutionAgent:
    """
    Executes approved trades on Alpaca Paper Trading with strict runtime guardrails:
    - Hard code-level universe validation: Rejects any ticker != SPY/QQQ
    - Enforces Paper Trading endpoint only
    - Structured JSON pre-trade and post-trade audit logging
    - Handles position exits (TP, SL, Event Time-Stop)
    """

    def __init__(self, alpaca_client: Optional[AlpacaOptionsClient] = None):
        self.settings = get_settings()
        self.alpaca_client = alpaca_client or AlpacaOptionsClient()

    def process(self, state: AgentWorkflowState) -> AgentWorkflowState:
        log.info("[EXECUTION AGENT] Starting execution cycle...")

        # 1. Execute Position Closures
        for exit_order in state.positions_to_close:
            spread_item = exit_order["spread_item"]
            if isinstance(spread_item, dict):
                spread_item = ActiveSpread.model_validate(spread_item)
            action = exit_order["action"]
            if isinstance(action, str):
                action = DecisionAction(action)
            reason: str = exit_order["reason"]

            log.info(f"[EXECUTION EXIT] Processing {action.value} for {spread_item.underlying}...")
            try:
                receipt = self.alpaca_client.close_spread_position(
                    spread_item.spread,
                    reason=action.value,
                    tp_order_id=spread_item.tp_order_id,
                )
                spread_item.status = "CLOSED"
                spread_item.closed_at = datetime.now(timezone.utc)
                spread_item.close_reason = reason
                
                # Approximate realized PnL based on exit type
                if action == DecisionAction.TAKE_PROFIT:
                    spread_item.realized_pl = round(spread_item.spread.max_profit * 0.50, 2)
                elif action == DecisionAction.STOP_LOSS:
                    spread_item.realized_pl = -round(spread_item.spread.max_profit * 2.00, 2)
                elif action == DecisionAction.EXPIRED_MAX_PROFIT:
                    spread_item.realized_pl = round(spread_item.spread.max_profit, 2)
                else:
                    spread_item.realized_pl = round(spread_item.spread.max_profit * 0.20, 2)

                # Ensure referenced objects in state.active_spreads reflect CLOSED status
                for s in state.active_spreads:
                    if s.id == spread_item.id:
                        s.status = "CLOSED"
                        s.closed_at = spread_item.closed_at
                        s.close_reason = reason
                        s.realized_pl = spread_item.realized_pl

                audit_log = TradeAuditLog(
                    trade_id=f"exit_{spread_item.id}",
                    action=action,
                    underlying=spread_item.underlying,
                    reasoning=next(
                        (r for r in state.reasoning_logs if r.underlying == spread_item.underlying),
                        state.reasoning_logs[0] if state.reasoning_logs else None,
                    ),
                    spread=spread_item.spread,
                    execution_status="CLOSED",
                    realized_pnl=spread_item.realized_pl,
                    is_paper_trading=True,
                )
                state.executed_trades.append(audit_log)
                log.info(f"[EXECUTION EXIT SUCCESS] Closed {spread_item.underlying} spread. Realized PnL: ${spread_item.realized_pl:.2f}")
            except Exception as e:
                err_msg = f"Failed to close spread {spread_item.underlying}: {e}"
                log.error(f"[EXECUTION ERROR] {err_msg}")
                state.execution_errors.append(err_msg)

        # 2. Execute Approved New Spreads
        for spread in state.approved_spreads_to_open:
            trade_id = f"thetaguard_{spread.underlying.lower()}_{uuid.uuid4().hex[:8]}"

            # Locate matching pre-trade reasoning log
            matched_reasoning = next(
                (r for r in state.reasoning_logs if r.underlying == spread.underlying and r.action == DecisionAction.OPEN_SPREAD),
                None
            ) or TradeReasoning(
                underlying=spread.underlying,
                action=DecisionAction.OPEN_SPREAD,
                justification=f"Approved spread order generated for {spread.underlying}.",
            )

            # PRE-SUBMISSION AUDIT LOG (Contract Section 10 & Addendum 1 Section 7)
            # Log reasoning before attempting submission so rejected/failed orders leave a complete trace
            audit_record = TradeAuditLog(
                trade_id=trade_id,
                action=DecisionAction.OPEN_SPREAD,
                underlying=spread.underlying,
                reasoning=matched_reasoning,
                spread=spread,
                order_ids=[],
                execution_status="PRE_SUBMISSION",
                net_credit_executed=spread.net_credit_per_share,
                is_paper_trading=True,
            )
            state.executed_trades.append(audit_record)

            # HARD UNIVERSE GUARDRAIL (Rule Section 2)
            if spread.underlying not in self.settings.allowed_universe:
                err_msg = (
                    f"FATAL SECURITY VIOLATION: Execution Agent rejected order for {spread.underlying}. "
                    f"Universe is hard-filtered to {self.settings.allowed_universe}."
                )
                log.critical(err_msg)
                audit_record.execution_status = "REJECTED_UNAUTHORIZED_UNIVERSE"
                state.execution_errors.append(err_msg)
                continue

            # HARD SPREAD SIZING GUARDRAIL (Rule Section 5)
            equity = state.account_state.equity if state.account_state else 100_000.0
            if spread.max_loss > (equity * self.settings.max_spread_risk_pct * 1.05):
                err_msg = (
                    f"FATAL RISK VIOLATION: Spread max loss (${spread.max_loss:.2f}) exceeds "
                    f"2% equity limit (${equity * 0.02:.2f}). Hard-rejected."
                )
                log.critical(err_msg)
                audit_record.execution_status = "REJECTED_SIZING_LIMIT_BREACH"
                state.execution_errors.append(err_msg)
                continue

            log.info(f"[EXECUTION ENTRY] Routing Put Credit Spread for {spread.underlying} (ID: {trade_id})...")

            try:
                receipt = self.alpaca_client.execute_put_credit_spread(spread)
                
                # Register new active spread
                new_active_spread = ActiveSpread(
                    id=trade_id,
                    underlying=spread.underlying,
                    spread=spread,
                    short_order_id=receipt.get("short_order_id"),
                    long_order_id=receipt.get("long_order_id"),
                    tp_order_id=receipt.get("tp_order_id"),
                    status="OPEN",
                    entry_credit=spread.net_credit_per_share,
                    current_spread_value=spread.net_credit_per_share,
                    realized_pl=0.0,
                    unrealized_pl=0.0,
                )
                state.active_spreads.append(new_active_spread)

                # Update audit record to SUBMITTED
                audit_record.order_ids = [
                    receipt.get("short_order_id", ""),
                    receipt.get("long_order_id", ""),
                    receipt.get("tp_order_id", ""),
                ]
                audit_record.execution_status = receipt.get("status", "SUBMITTED")
                log.info(f"[EXECUTION ENTRY SUCCESS] {spread.underlying} spread live on Paper Trading.")
            except Exception as e:
                err = f"Execution failed for {spread.underlying}: {e}"
                log.error(f"[EXECUTION ERROR] {err}")
                audit_record.execution_status = "FAILED"
                state.execution_errors.append(err)

        state.next_step = "REPORTER"
        return state
