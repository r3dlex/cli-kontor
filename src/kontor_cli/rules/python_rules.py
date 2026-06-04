"""Python module rule loader for kontor-cli."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kontor_cli.himalaya import Email

__all__ = ["load_python_rules", "call_python_rules"]


def load_python_rules(rules_file: Path) -> dict[str, Any]:
    """Load a Python rules module dynamically and return its namespace dict."""
    if not rules_file.exists():
        return {}

    spec = importlib.util.spec_from_file_location("kontor_rules", rules_file)
    if spec is None or spec.loader is None:
        return {}

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        # If rules.py has errors, log and continue
        return {"classify": None}

    return {k: getattr(module, k, None) for k in dir(module)}


def call_python_rules(
    rules_ns: dict[str, Any],
    email: Email,
) -> str | None:
    """Call any `classify(email) -> str | None` function found in the rules module."""
    classify_fn = rules_ns.get("classify")
    if classify_fn is None or not callable(classify_fn):
        return None
    try:
        result = classify_fn(email)
        return str(result) if result else None
    except Exception:
        return None
