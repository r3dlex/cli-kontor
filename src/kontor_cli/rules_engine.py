"""Unified rules engine — evaluates YAML DSL → Python → NL rules in priority order."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from kontor_cli.rules import nl_rules, python_rules, yaml_dsl

if TYPE_CHECKING:
    from kontor_cli.config import Config
    from kontor_cli.himalaya import Email


logger = logging.getLogger("kontor_cli.rules_engine")


class RulesEngine:
    """Evaluates email classification through three rule sources in priority order."""

    def __init__(self, config: Config, cwd: Path | None = None) -> None:
        self.yaml_rules = yaml_dsl.load_rules_from_dir(config.rules_yaml_dir)
        self.python_ns = python_rules.load_python_rules(config.rules_python_file)
        self.nl_rules = nl_rules.load_nl_rules(config.rules_nl_dir)
        self.cwd = cwd

    def classify(self, email: Email) -> str | None:
        """Classify an email through all three rule sources.

        Priority: YAML DSL > Python module > NL rules (best-effort).
        NL rules return None — they require LLM context.
        """
        # 1. YAML DSL
        yaml_result: str | None = yaml_dsl.evaluate_yaml_rules(
            self.yaml_rules,
            email.from_addr,
            email.subject,
        )
        if yaml_result is not None:
            logger.info(
                "YAML rule matched",
                extra={
                    "email_id": email.id,
                    "rule_source": "yaml_dsl",
                    "folder": yaml_result,
                },
            )
            return yaml_result

        # 2. Python module
        py_result: str | None = python_rules.call_python_rules(self.python_ns, email)
        if py_result is not None:
            logger.info(
                "Python rule matched",
                extra={
                    "email_id": email.id,
                    "rule_source": "python_rules",
                    "folder": py_result,
                },
            )
            return py_result

        # 3. NL rules — no direct match; requires LLM
        if self.nl_rules:
            logger.info(
                "No YAML or Python match; NL rules available for LLM context",
                extra={
                    "email_id": email.id,
                    "rule_source": "nl_rules",
                },
            )
        return None

    def get_nl_context(self) -> str:
        """Return formatted NL rules for LLM prompt injection."""
        return nl_rules.nl_rules_context(self.nl_rules)
