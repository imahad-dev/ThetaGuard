"""Lightweight on-disk crash recovery state store for ThetaGuard.

Survives process restarts and machine reboots during the 6-day hackathon trading window.
Uses atomic file replacement to prevent corruption on sudden shutdowns.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.models.portfolio import ActiveSpread
from src.models.signals import TradeAuditLog, VolatilityRecord
from src.utils.logger import log


class StateStore:
    """Atomic JSON snapshot state store for active positions, execution history, and volatility time series."""

    def __init__(self, file_path: Optional[Path] = None):
        if file_path is None:
            data_dir = Path("data")
            data_dir.mkdir(parents=True, exist_ok=True)
            self.file_path = data_dir / "thetaguard_state.json"
        else:
            self.file_path = Path(file_path)
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def save_state(
        self,
        active_spreads: List[ActiveSpread],
        execution_history: List[TradeAuditLog],
        volatility_history: Optional[List[VolatilityRecord]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Saves current engine state atomically via a temporary file."""
        payload = {
            "version": "1.0",
            "metadata": metadata or {},
            "active_spreads": [s.model_dump(mode="json") for s in active_spreads],
            "execution_history": [t.model_dump(mode="json") for t in execution_history],
            "volatility_history": [v.model_dump(mode="json") for v in (volatility_history or [])],
        }

        temp_path = self.file_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
            # Atomic file rename
            os.replace(temp_path, self.file_path)
            log.debug(
                f"[STATE STORE] Snapshot saved: {len(active_spreads)} active spreads, "
                f"{len(execution_history)} audit records, {len(volatility_history or [])} vol points to {self.file_path}"
            )
        except Exception as e:
            log.error(f"[STATE STORE ERROR] Failed to persist state snapshot: {e}")
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def load_state(
        self,
    ) -> Tuple[List[ActiveSpread], List[TradeAuditLog], List[VolatilityRecord], Dict[str, Any]]:
        """Loads state snapshot from disk on engine startup for crash recovery."""
        if not self.file_path.exists():
            return [], [], [], {}

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            active_spreads = [
                ActiveSpread.model_validate(s) for s in payload.get("active_spreads", [])
            ]
            execution_history = [
                TradeAuditLog.model_validate(t) for t in payload.get("execution_history", [])
            ]
            volatility_history = [
                VolatilityRecord.model_validate(v) for v in payload.get("volatility_history", [])
            ]
            metadata = payload.get("metadata", {})
            log.info(
                f"[STATE STORE] Restored {len(active_spreads)} active positions, "
                f"{len(execution_history)} audit logs, and {len(volatility_history)} vol records from {self.file_path}"
            )
            return active_spreads, execution_history, volatility_history, metadata
        except Exception as e:
            log.warning(f"[STATE STORE WARNING] Could not parse state snapshot ({e}). Starting fresh.")
            return [], [], [], {}

    def clear(self) -> None:
        """Clears the on-disk state file."""
        if self.file_path.exists():
            self.file_path.unlink(missing_ok=True)
