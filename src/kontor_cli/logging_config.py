"""Structured logging configuration for kontor-cli."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """Format log records as structured JSON to stdout."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "email_id"):
            payload["email_id"] = record.email_id
        if hasattr(record, "folder"):
            payload["folder"] = record.folder
        if hasattr(record, "rule_source"):
            payload["rule_source"] = record.rule_source
        if hasattr(record, "llm_action"):
            payload["llm_action"] = record.llm_action
        if hasattr(record, "moves_made"):
            payload["moves_made"] = record.moves_made
        if hasattr(record, "phase"):
            payload["phase"] = record.phase
        return json.dumps(payload) + "\n"


class FlushingStreamHandler(logging.StreamHandler[Any]):
    """StreamHandler that flushes after every emit."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def configure_logging(level: str = "INFO", format_type: str = "json") -> None:
    """Configure root logger with structured output."""
    root = logging.getLogger("kontor_cli")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = FlushingStreamHandler(sys.stdout)
    if format_type == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.addHandler(handler)
    root.propagate = False
