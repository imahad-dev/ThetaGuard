"""Risk Manager Agent: Enforces pre-trade risk gates, concentration limits, and active position monitoring."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from config.settings import get_settings
from src.agents.state import AgentWorkflowState
from src.models.options import PutCreditSpread
from src.models.portfolio import ActiveSpread, RiskSnapshot
from src.models.signals import DecisionAction, TradeReasoning
from src.utils.logger import log

ET_TZ = ZoneInfo("America/New_York")


class PreTradeRiskGate:
    """
    Evaluates new candidate spreads against hard portfolio constraints:
    - Max 2 concurrent open spreads total (at most 1 on SPY, 1 on QQQ)
    - Total portfolio capital at risk <= 5.0% of account equity
    - Max loss per individual spread <= 2.0% of account equity
    - Hard rejection if cap breached (no silent resizing)
    """

    def __init__(self):
        self.settings = get_settings()

    def evaluate_candidates(
        self,
        candidates: List[PutCreditSpread],
        active_spreads: List[ActiveSpread],
        equity: float,
        market_iv_ranks: Dict[str, float],
    ) -> tuple[List[PutCreditSpread], List[Dict[str, Any]], List[TradeReasoning], RiskSnapshot]:
        open_spreads = [s for s in active_spreads if s.status == "OPEN"]
        current_active_risk = sum(s.spread.max_loss for s in open_spreads)
        current_risk_pct = (current_active_risk / equity) if equity > 0 else 0.0

        spy_count = sum(1 for s in open_spreads if s.underlying == "SPY")
        qqq_count = sum(1 for s in open_spreads if s.underlying == "QQQ")
        total_count = len(open_spreads)

        risk_snapshot = RiskSnapshot(
            account_equity=equity,
            total_capital_at_risk=round(current_active_risk, 2),
            capital_at_risk_pct=round(current_risk_pct, 4),
            active_spread_count=total_count,
            spy_spread_count=spy_count,
            qqq_spread_count=qqq_count,
            max_risk_cap_pct=self.settings.max_account_risk_pct,
            is_risk_cap_breached=current_risk_pct > self.settings.max_account_risk_pct,
            risk_summary=(
                f"Portfolio Risk: ${current_active_risk:,.2f} ({current_risk_pct * 100:.2f}% of equity). "
                f"Active spreads: {total_count}/{self.settings.max_concurrent_spreads} (SPY: {spy_count}, QQQ: {qqq_count})."
            ),
        )

        approved_spreads: List[PutCreditSpread] = []
        rejected_spreads: List[Dict[str, Any]] = []
        reasoning_logs: List[TradeReasoning] = []

        for candidate in candidates:
            underlying = candidate.underlying
            candidate_risk = candidate.max_loss
            projected_total_risk = current_active_risk + candidate_risk
            projected_risk_pct = projected_total_risk / equity if equity > 0 else 1.0

            # Rule A: Concentration Limit (Max 1 per ticker, Max 2 total)
            ticker_count = spy_count if underlying == "SPY" else qqq_count
            if total_count >= self.settings.max_concurrent_spreads or ticker_count >= 1:
                reason = (
                    f"Concentration cap reached. Active spreads: {total_count}/"
                    f"{self.settings.max_concurrent_spreads} (Active {underlying}: {ticker_count}/1). "
                    f"Contract Section 5 strictly forbids >1 spread per symbol."
                )
                log.warning(f"[RISK REJECTION] {underlying}: {reason}")
                rejected_spreads.append({"spread": candidate, "reason": reason})
                reasoning_logs.append(
                    TradeReasoning(
                        underlying=underlying,
                        action=DecisionAction.SKIP_MAX_POSITION_REACHED,
                        account_equity=equity,
                        justification=reason,
                    )
                )
                continue

            # Rule B: Single Spread Risk Cap (<= 2% equity)
            spread_risk_pct = candidate_risk / equity if equity > 0 else 1.0
            if spread_risk_pct > self.settings.max_spread_risk_pct:
                reason = (
                    f"Single spread max loss (${candidate_risk:.2f}, {spread_risk_pct * 100:.2f}%) "
                    f"breaches single spread cap of {self.settings.max_spread_risk_pct * 100:.1f}% equity."
                )
                log.warning(f"[RISK REJECTION] {underlying}: {reason}")
                rejected_spreads.append({"spread": candidate, "reason": reason})
                reasoning_logs.append(
                    TradeReasoning(
                        underlying=underlying,
                        action=DecisionAction.SKIP_RISK_CAP_EXCEEDED,
                        account_equity=equity,
                        capital_at_risk_pct=spread_risk_pct,
                        justification=reason,
                    )
                )
                continue

            # Rule C: Total Portfolio Risk Cap (<= 5% equity)
            if projected_risk_pct > self.settings.max_account_risk_pct:
                reason = (
                    f"Projected total risk (${projected_total_risk:.2f}, {projected_risk_pct * 100:.2f}%) "
                    f"breaches portfolio cap of {self.settings.max_account_risk_pct * 100:.1f}% equity. "
                    f"Contract Section 5: Reject and log, do NOT resize silently."
                )
                log.warning(f"[RISK REJECTION] {underlying}: {reason}")
                rejected_spreads.append({"spread": candidate, "reason": reason})
                reasoning_logs.append(
                    TradeReasoning(
                        underlying=underlying,
                        action=DecisionAction.SKIP_RISK_CAP_EXCEEDED,
                        account_equity=equity,
                        capital_at_risk_pct=projected_risk_pct,
                        justification=reason,
                    )
                )
                continue

            # Approved! Formulate pre-submission audit reasoning
            log.info(
                f"[RISK APPROVAL] {underlying} Put Credit Spread APPROVED. "
                f"Risk: ${candidate_risk:.2f} ({spread_risk_pct * 100:.2f}% eq). "
                f"Projected total portfolio risk: {projected_risk_pct * 100:.2f}%"
            )
            approved_spreads.append(candidate)
            current_active_risk += candidate_risk
            total_count += 1
            if underlying == "SPY":
                spy_count += 1
            else:
                qqq_count += 1

            reasoning_logs.append(
                TradeReasoning(
                    underlying=underlying,
                    action=DecisionAction.OPEN_SPREAD,
                    iv_rank=market_iv_ranks.get(underlying, 35.0),
                    iv_rank_floor=self.settings.iv_rank_floor,
                    underlying_price=candidate.short_leg.bid,
                    chosen_expiry=str(candidate.expiration_date),
                    short_strike=candidate.short_leg.strike_price,
                    short_delta=candidate.short_leg.delta,
                    long_strike=candidate.long_leg.strike_price,
                    long_delta=candidate.long_leg.delta,
                    spread_width=candidate.spread_width,
                    estimated_net_credit=candidate.net_credit_per_share,
                    max_loss=candidate.max_loss,
                    account_equity=equity,
                    capital_at_risk_pct=spread_risk_pct,
                    justification=(
                        f"Targeted {underlying} Put Credit Spread meets all Section 3-6 criteria: "
                        f"IV Rank ({market_iv_ranks.get(underlying, 35.0):.1f} >= {self.settings.iv_rank_floor}), "
                        f"Short Leg Delta {candidate.short_leg.delta} is inside target [-0.20, -0.15], "
                        f"${candidate.spread_width:.1f} width limits max loss to ${candidate.max_loss:.2f} "
                        f"({spread_risk_pct * 100:.2f}% equity), safely under the 2% spread & 5% portfolio limits. "
                        f"Take-Profit: 50% max credit (${candidate.take_profit_target_price:.2f}) resting GTC limit. "
                        f"Stop-Loss: 200% credit loss (${candidate.stop_loss_trigger_price:.2f}) active daemon polling monitor."
                    ),
                )
            )

        return approved_spreads, rejected_spreads, reasoning_logs, risk_snapshot


class PositionMonitor:
    """
    Active Order & Position Monitoring Engine:
    - Expiration Settlement: Automatically settles matured contracts at 16:00 ET on expiration date.
    - Take-Profit (50% max credit): Resting GTC limit buy order placed immediately upon fill.
    - Stop-Loss (200% credit loss): Active polling check on every daemon heartbeat cycle.
    - Time-Stop: Emergency force-closure before macro event blackout cutoffs (Sep 1 JOLTS, Sep 4 NFP).
    """

    def evaluate_active_exits(
        self,
        active_spreads: List[ActiveSpread],
        is_lockout: bool,
        lockout_reason: str,
        force_close_all: bool,
        current_dt: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        positions_to_close = []
        eval_dt = current_dt or datetime.now(timezone.utc)
        if eval_dt.tzinfo is None:
            eval_dt = eval_dt.replace(tzinfo=timezone.utc)
        current_et = eval_dt.astimezone(ET_TZ)

        for spread_item in active_spreads:
            if spread_item.status != "OPEN":
                continue

            spread = spread_item.spread

            # Exit Trigger 0: Expiration Settlement at market close (16:00 ET) on expiration date
            expiry_dt_1600_et = datetime(
                spread.expiration_date.year,
                spread.expiration_date.month,
                spread.expiration_date.day,
                16,
                0,
                tzinfo=ET_TZ,
            )
            if current_et >= expiry_dt_1600_et:
                log.info(
                    f"[EXPIRATION SETTLEMENT] {spread.underlying} spread (Exp: {spread.expiration_date}) reached maturity. "
                    f"Settling contract for 100% max profit (${spread.max_profit:.2f})."
                )
                positions_to_close.append({
                    "spread_item": spread_item,
                    "action": DecisionAction.EXPIRED_MAX_PROFIT,
                    "reason": f"Contract matured at expiration ({spread.expiration_date}). Settled for 100% max profit.",
                })
                continue

            # Exit Trigger 1: Emergency Macro Event Time-Stop (Contract §4/§7 hard rule)
            if force_close_all or is_lockout:
                log.warning(
                    f"[EXIT TRIGGER] Time-Stop: Force-closing {spread.underlying} spread prior to macro blackout."
                )
                positions_to_close.append({
                    "spread_item": spread_item,
                    "action": DecisionAction.TIME_STOP_EVENT,
                    "reason": f"Macro blackout lockout: {lockout_reason}",
                })
                continue

            # Exit Trigger 2: Take-Profit (50% of credit received)
            if spread_item.current_spread_value <= spread.take_profit_target_price and spread_item.current_spread_value > 0:
                log.info(
                    f"[EXIT TRIGGER] Take-Profit hit for {spread.underlying} "
                    f"(Current debit: ${spread_item.current_spread_value:.2f} <= Target: ${spread.take_profit_target_price:.2f})"
                )
                positions_to_close.append({
                    "spread_item": spread_item,
                    "action": DecisionAction.TAKE_PROFIT,
                    "reason": f"Take-Profit target achieved: Closed at 50% max credit (${spread.take_profit_target_price:.2f}).",
                })
                continue

            # Exit Trigger 3: Active Daemon Polling Stop-Loss (200% of credit received)
            if spread_item.current_spread_value >= spread.stop_loss_trigger_price:
                log.warning(
                    f"[EXIT TRIGGER] Stop-Loss hit for {spread.underlying} "
                    f"(Current debit: ${spread_item.current_spread_value:.2f} >= SL Trigger: ${spread.stop_loss_trigger_price:.2f})"
                )
                positions_to_close.append({
                    "spread_item": spread_item,
                    "action": DecisionAction.STOP_LOSS,
                    "reason": f"Stop-Loss triggered: Current spread debit reached ${spread_item.current_spread_value:.2f} (200% loss).",
                })
                continue

        return positions_to_close


class RiskManagerAgent:
    """
    Risk Manager Agent Facade: Coordinates PreTradeRiskGate and PositionMonitor.
    """

    def __init__(self):
        self.settings = get_settings()
        self.risk_gate = PreTradeRiskGate()
        self.position_monitor = PositionMonitor()

    def process(self, state: AgentWorkflowState) -> AgentWorkflowState:
        equity = state.account_state.equity if state.account_state else 100_000.0
        log.info(f"[RISK MANAGER] Evaluating risk state on Account Equity ${equity:,.2f}...")

        # 1. Evaluate Exits on Active Positions via PositionMonitor
        state.positions_to_close = self.position_monitor.evaluate_active_exits(
            active_spreads=state.active_spreads,
            is_lockout=state.is_in_event_lockout,
            lockout_reason=state.event_lockout_reason,
            force_close_all=state.force_close_all_positions,
            current_dt=state.timestamp,
        )

        # 2. Evaluate New Candidate Spreads via PreTradeRiskGate
        (
            approved,
            rejected,
            reasoning,
            risk_snap,
        ) = self.risk_gate.evaluate_candidates(
            candidates=state.candidate_spreads,
            active_spreads=state.active_spreads,
            equity=equity,
            market_iv_ranks=state.market_iv_ranks,
        )

        state.approved_spreads_to_open = approved
        state.rejected_spreads = rejected
        state.reasoning_logs.extend(reasoning)
        state.risk_snapshot = risk_snap
        log.info(f"[RISK SNAPSHOT] {risk_snap.risk_summary}")

        state.next_step = "EXECUTION"
        return state
