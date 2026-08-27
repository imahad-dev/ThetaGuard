"""Structured JSON and rich console logging for ThetaGuard."""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from rich.console import Console
from rich.logging import RichHandler

console = Console()

class JSONFormatter(logging.Formatter):
    """Outputs log records formatted as compact, structured JSON objects."""
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "trade_data"):
            log_obj["trade_data"] = record.trade_data
        if hasattr(record, "audit"):
            log_obj["audit"] = record.audit
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def setup_logger(name: str = "thetaguard", log_file: str = "logs/thetaguard.log") -> logging.Logger:
    """Configures multi-channel logger with structured JSON file output and Rich console formatting."""
    os.makedirs(os.path.dirname(log_file) if os.path.dirname(log_file) else ".", exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # File Handler (Structured JSON)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(JSONFormatter())
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)

        # Console Handler (Rich colored output)
        console_handler = RichHandler(
            console=console,
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
        )
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

    return logger

log = setup_logger()
