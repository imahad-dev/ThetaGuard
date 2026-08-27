"""LangGraph StateGraph orchestration pipeline for ThetaGuard."""
from datetime import datetime, timezone
from typing import Dict, Any, Optional

try:
    from langgraph.graph import StateGraph, START, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

from src.agents.event_risk import EventRiskAgent
from src.agents.execution import ExecutionAgent
from src.agents.reporter import ReporterAgent
from src.agents.risk_manager import RiskManagerAgent
from src.agents.state import AgentWorkflowState
from src.agents.strategy_selector import StrategySelectorAgent
from src.clients.alpaca_client import AlpacaOptionsClient
from src.models.signals import VolatilityRecord
from src.storage.state_store import StateStore
from src.utils.logger import log


class ThetaGuardEngine:
    """End-to-end multi-agent orchestration engine using LangGraph with crash recovery."""

    def __init__(
        self,
        alpaca_client: Optional[AlpacaOptionsClient] = None,
        state_store: Optional[StateStore] = None,
    ):
        self.alpaca_client = alpaca_client or AlpacaOptionsClient()
        self.event_risk_agent = EventRiskAgent(self.alpaca_client)
        self.strategy_selector_agent = StrategySelectorAgent(self.alpaca_client)
        self.risk_manager_agent = RiskManagerAgent()
        self.execution_agent = ExecutionAgent(self.alpaca_client)
        self.reporter_agent = ReporterAgent()
        
        # State repository and on-disk snapshot store for crash recovery
        self.state_store = state_store or StateStore()
        loaded_spreads, loaded_history, loaded_vol, _ = self.state_store.load_state()
        self._persisted_active_spreads = loaded_spreads
        self._execution_history = loaded_history
        self._volatility_history = loaded_vol

        if LANGGRAPH_AVAILABLE:
            self.graph = self._build_langgraph()
        else:
            self.graph = None

    def _build_langgraph(self):
        """Constructs the compiled LangGraph workflow graph."""
        builder = StateGraph(AgentWorkflowState)

        # Register Agent Nodes
        builder.add_node("event_risk", self._event_risk_node)
        builder.add_node("strategy_selector", self._strategy_selector_node)
        builder.add_node("risk_manager", self._risk_manager_node)
        builder.add_node("execution", self._execution_node)
        builder.add_node("reporter", self._reporter_node)

        # Define Edges & Flow
        builder.add_edge(START, "event_risk")
        builder.add_edge("event_risk", "strategy_selector")
        builder.add_edge("strategy_selector", "risk_manager")
        builder.add_edge("risk_manager", "execution")
        builder.add_edge("execution", "reporter")
        builder.add_edge("reporter", END)

        return builder.compile()

    def _ensure_state(self, state: Any) -> AgentWorkflowState:
        if isinstance(state, dict):
            return AgentWorkflowState.model_validate(state)
        return state

    def _event_risk_node(self, state: Any) -> Dict[str, Any]:
        s = self._ensure_state(state)
        result = self.event_risk_agent.process(s)
        return result.model_dump()

    def _strategy_selector_node(self, state: Any) -> Dict[str, Any]:
        s = self._ensure_state(state)
        result = self.strategy_selector_agent.process(s)
        return result.model_dump()

    def _risk_manager_node(self, state: Any) -> Dict[str, Any]:
        s = self._ensure_state(state)
        result = self.risk_manager_agent.process(s)
        return result.model_dump()

    def _execution_node(self, state: Any) -> Dict[str, Any]:
        s = self._ensure_state(state)
        result = self.execution_agent.process(s)
        return result.model_dump()

    def _reporter_node(self, state: Any) -> Dict[str, Any]:
        s = self._ensure_state(state)
        result = self.reporter_agent.process(s)
        return result.model_dump()

    def run_cycle(self, override_dt: Optional[datetime] = None) -> AgentWorkflowState:
        """Executes a complete systematic trading cycle across all agents."""
        current_dt = override_dt or datetime.now(timezone.utc)
        log.info(f"========== Starting ThetaGuard Cycle [{current_dt.isoformat()}] ==========")

        # 1. Fetch current account state
        account_state = self.alpaca_client.get_account_state()
        
        # 2. Initialize initial state container
        initial_state = AgentWorkflowState(
            timestamp=current_dt,
            account_state=account_state,
            active_spreads=self._persisted_active_spreads,
        )

        # 3. Execute via LangGraph or Sequential Fallback
        if self.graph:
            try:
                final_output = self.graph.invoke(initial_state)
                final_state = AgentWorkflowState(**final_output)
            except Exception as e:
                log.warning(f"LangGraph execution exception: {e}. Running sequential fallback.")
                final_state = self._run_sequential(initial_state)
        else:
            final_state = self._run_sequential(initial_state)

        # Record cycle volatility reading for regime analytics time series
        spy_vol, spy_rank = self.alpaca_client.get_current_iv_and_rank("SPY")
        qqq_vol, qqq_rank = self.alpaca_client.get_current_iv_and_rank("QQQ")
        vol_record = VolatilityRecord(
            timestamp=final_state.timestamp,
            spy_vol_rank=round(spy_rank, 1),
            qqq_vol_rank=round(qqq_rank, 1),
            spy_vol=round(spy_vol, 4),
            qqq_vol=round(qqq_vol, 4),
            iv_rank_floor=30.0,
        )
        self._volatility_history.append(vol_record)
        # Retain up to 5,000 cycle records (comfortably covers 2+ weeks of 5m/1m intervals)
        if len(self._volatility_history) > 5000:
            self._volatility_history = self._volatility_history[-5000:]

        # Update persisted state with only still-open positions and snapshot to disk
        self._persisted_active_spreads = [s for s in final_state.active_spreads if s.status == "OPEN"]
        self._execution_history.extend(final_state.executed_trades)
        
        self.state_store.save_state(
            active_spreads=self._persisted_active_spreads,
            execution_history=self._execution_history,
            volatility_history=self._volatility_history,
            metadata={
                "last_cycle_timestamp": final_state.timestamp.isoformat(),
                "account_equity": final_state.account_state.equity if final_state.account_state else 100_000.0,
                "workflow_status": final_state.workflow_status,
            },
        )

        log.info(
            f"========== Cycle Complete: {len(final_state.approved_spreads_to_open)} opened, "
            f"{len(final_state.positions_to_close)} closed, Equity: ${final_state.account_state.equity:,.2f} =========="
        )
        return final_state

    def _run_sequential(self, state: AgentWorkflowState) -> AgentWorkflowState:
        """Deterministic sequential execution fallback."""
        s1 = self.event_risk_agent.process(state)
        s2 = self.strategy_selector_agent.process(s1)
        s3 = self.risk_manager_agent.process(s2)
        s4 = self.execution_agent.process(s3)
        s5 = self.reporter_agent.process(s4)
        return s5
