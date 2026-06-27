"""Unit tests for kontor_cli.rules_engine."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import yaml

from kontor_cli.himalaya import Email
from kontor_cli.rules import nl_rules, python_rules, yaml_dsl
from kontor_cli.rules_engine import RulesEngine


def _email(from_addr: str = "alice@example.com", subject: str = "Test") -> Email:
    return Email(
        id="1",
        from_addr=from_addr,
        subject=subject,
        date=datetime.now(UTC),
        flags={},
        folder="INBOX",
    )


class TestYamlDsl:
    def test_yaml_dsl_match(self, tmp_path: Path) -> None:
        rules = [
            {"from": "alice@example.com", "folder": "2_Projects/PRJ_Test"},
        ]
        yaml_file = tmp_path / "rules.yaml"
        with open(yaml_file, "w") as fh:
            yaml.safe_dump(rules, fh)
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        result = yaml_dsl.evaluate_yaml_rules(loaded, "alice@example.com", "Test")
        assert result == "2_Projects/PRJ_Test"

    def test_yaml_dsl_no_match(self, tmp_path: Path) -> None:
        rules = [
            {"from": "alice@example.com", "folder": "2_Projects/PRJ_Test"},
        ]
        yaml_file = tmp_path / "rules.yaml"
        with open(yaml_file, "w") as fh:
            yaml.safe_dump(rules, fh)
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        result = yaml_dsl.evaluate_yaml_rules(loaded, "bob@example.com", "Test")
        assert result is None


class TestPythonRules:
    def test_python_rules_match(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.py"
        rules_file.write_text(
            "def classify(email):\n"
            "    if 'budget' in email.subject.lower():\n"
            "        return '1_Management/MGT_Finance'\n"
        )
        ns = python_rules.load_python_rules(rules_file)
        email = _email(subject="Monthly Budget Report")
        result = python_rules.call_python_rules(ns, email)
        assert result == "1_Management/MGT_Finance"

    def test_python_rules_no_match(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.py"
        rules_file.write_text(
            "def classify(email):\n"
            "    if 'budget' in email.subject.lower():\n"
            "        return '1_Management/MGT_Finance'\n"
        )
        ns = python_rules.load_python_rules(rules_file)
        email = _email(subject="Hello World")
        result = python_rules.call_python_rules(ns, email)
        assert result is None


class TestNlRules:
    def test_nl_rules_format_loaded(self, tmp_path: Path) -> None:
        nl_file = tmp_path / "guidelines.rules.txt"
        nl_file.write_text(
            "All invoices from accounting@ go to Finance.\n---\nPR emails go to 3_External."
        )
        loaded = nl_rules.load_nl_rules(tmp_path)
        assert len(loaded) == 2
        assert "invoices" in loaded[0]

    def test_nl_rules_context(self) -> None:
        ctx = nl_rules.nl_rules_context(["Rule 1", "Rule 2"])
        assert "Rule 1" in ctx
        assert "Rule 2" in ctx
        assert ctx.startswith("- Rule 1")


class TestRulesEngine:
    def test_rules_priority_order(self, tmp_path: Path) -> None:
        """YAML DSL should take priority over Python module."""
        # YAML DSL rule
        yaml_file = tmp_path / "rules.yaml"
        with open(yaml_file, "w") as fh:
            yaml.safe_dump([{"from": "alice@example.com", "folder": "YAML_Folder"}], fh)
        # Python rule (should not fire because YAML matched first)
        rules_file = tmp_path / "rules.py"
        rules_file.write_text("def classify(email):\n    return 'Python_Folder'\n")
        nl_file = tmp_path / "guidelines.rules.txt"
        nl_file.write_text("NL rule")

        cfg = mock.MagicMock()
        cfg.rules_yaml_dir = tmp_path
        cfg.rules_python_file = rules_file
        cfg.rules_nl_dir = tmp_path

        engine = RulesEngine(cfg, cwd=tmp_path)
        result = engine.classify(_email())
        # YAML matched first
        assert result == "YAML_Folder"


# ---------------------------------------------------------------------------
# Regression tests for folder-improvements-2026-06-03.md (G003)
# These lock the four observed gaps. They should FAIL against the current
# 00-global.yaml + rules.py and PASS after the proposed fixes are applied.
# ---------------------------------------------------------------------------


class TestGap1CalendarResponsePattern:
    """Gap 1: calendar-response pattern (Accepted:/Declined:/Tentative:/
    New Time Proposed:/Angenommen:/Abgelehnt:) should route to 1_Management/1on1
    even when the body has project keywords. Requires explicit priority-95
    pattern rule that fires before the generic 1:1 subject regex."""

    def test_accepted_1on1_routes_to_1on1(self, tmp_path: Path) -> None:
        rules = [
            {
                "pattern": "^(Accepted|Declined|Tentative|New Time Proposed|Cancelled):",
                "folder": "1_Management/1on1",
                "priority": 95,
            },
            {
                "from": ".*rib-software\\.com",
                "subject": ".*1:1.*|1on1|one-on-one|one on one|Sync on.*",
                "folder": "1_Management/1on1",
                "priority": 89,
            },
        ]
        yaml_file = tmp_path / "rules.yaml"
        with open(yaml_file, "w") as fh:
            yaml.safe_dump(rules, fh)
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        result = yaml_dsl.evaluate_yaml_rules(
            loaded, "any.sender@rib-software.com", "Accepted: 1:1 Andre X"
        )
        assert result == "1_Management/1on1"

    def test_declined_german_routes_to_1on1(self, tmp_path: Path) -> None:
        # Use 'subject' (not 'pattern') so the ^ anchor matches the subject
        # alone. yaml_dsl.py's pattern field concatenates from_addr + ' ' +
        # subject before applying the regex, so ^ would never match.
        rules = [
            {
                "subject": "^(Angenommen|Abgelehnt|Zugesagt|Unsicher):",
                "folder": "1_Management/1on1",
                "priority": 95,
            },
        ]
        yaml_file = tmp_path / "rules.yaml"
        with open(yaml_file, "w") as fh:
            yaml.safe_dump(rules, fh)
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        result = yaml_dsl.evaluate_yaml_rules(
            loaded,
            "stefan.stelzer@rib-software.com",
            "Abgelehnt: Weekly Sync on Track 1",
        )
        assert result == "1_Management/1on1"


class TestGap2ExternalSaaAtOneOnOne:
    """Gap 2: SAA-domain senders (g.heissenberger@saa.at) should land in
    1_Management/1on1 when their subject indicates a 1:1 calendar response."""

    def test_saa_at_accepted_1on1(self, tmp_path: Path) -> None:
        rules = [
            {
                "from": ".*@saa\\.at",
                "subject": ".*Accepted:.*|.*Declined:.*|.*Tentative:.*|.*1:1.*|one on one.*",
                "folder": "1_Management/1on1",
                "priority": 75,
            },
        ]
        yaml_file = tmp_path / "rules.yaml"
        with open(yaml_file, "w") as fh:
            yaml.safe_dump(rules, fh)
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        result = yaml_dsl.evaluate_yaml_rules(
            loaded,
            "g.heissenberger@saa.at",
            "Accepted: One on One: Georg Heißenberger",
        )
        assert result == "1_Management/1on1"

    def test_saa_at_falls_to_4_info_without_rule(self, tmp_path: Path) -> None:
        """Without the SAA rule, g.heissenberger@saa.at falls through to
        4_Info. This documents the pre-fix behaviour so we can detect
        regressions where the rule is accidentally removed."""
        rules = [
            {
                "from": ".*rib-software\\.com",
                "subject": ".*1:1.*",
                "folder": "1_Management/1on1",
                "priority": 89,
            },
        ]
        yaml_file = tmp_path / "rules.yaml"
        with open(yaml_file, "w") as fh:
            yaml.safe_dump(rules, fh)
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        result = yaml_dsl.evaluate_yaml_rules(
            loaded, "g.heissenberger@saa.at", "Accepted: One on One: Georg"
        )
        assert result is None


class TestGap3AiSubjectRoute:
    """Gap 3: AI and Augment subjects from rib-software.com should route
    only to live Exchange folders so inbox-zero processing can move them."""

    def test_augment_routes_to_live_augment_folder(self, tmp_path: Path) -> None:
        rules = [
            {
                "from": ".*rib-software\\.com",
                "subject": ".*[Aa]ugment.*",
                "folder": "2_Projects/Augment",
                "priority": 69,
            },
            {
                "from": ".*rib-software\\.com",
                "subject": ".*[Cc]opilot.*|Anthropic.*|OpenAI.*",
                "folder": "1_Management/AI",
                "priority": 68,
            },
        ]
        yaml_file = tmp_path / "rules.yaml"
        with open(yaml_file, "w") as fh:
            yaml.safe_dump(rules, fh)
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        result = yaml_dsl.evaluate_yaml_rules(
            loaded,
            "mikhail.golyshev@rib-software.com",
            "Augment License",
        )
        assert result == "2_Projects/Augment"

    def test_ai_tooling_routes_to_live_management_ai_folder(
        self, tmp_path: Path
    ) -> None:
        rules = [
            {
                "from": ".*rib-software\\.com",
                "subject": ".*[Cc]opilot.*|Anthropic.*|OpenAI.*",
                "folder": "1_Management/AI",
                "priority": 68,
            },
        ]
        yaml_file = tmp_path / "rules.yaml"
        with open(yaml_file, "w") as fh:
            yaml.safe_dump(rules, fh)
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        result = yaml_dsl.evaluate_yaml_rules(
            loaded,
            "mikhail.golyshev@rib-software.com",
            "Copilot rollout and OpenAI notes",
        )
        assert result == "1_Management/AI"

    def test_repository_rules_route_ai_subjects_to_live_exchange_folders(self) -> None:
        """Pinned from live mailbox: rules must not target missing 2_Projects/AI."""
        live_folders = {
            "1_Management/AI",
            "2_Projects/Augment",
            "2_Projects/Internal",
            "2_Projects/Releases",
        }
        rules = yaml_dsl.load_rules_from_dir(Path("rules"))

        augment_result = yaml_dsl.evaluate_yaml_rules(
            rules,
            "mangesh.khandave@rib-software.com",
            "Augment License",
        )
        ai_result = yaml_dsl.evaluate_yaml_rules(
            rules,
            "mikhail.golyshev@rib-software.com",
            "Copilot rollout and OpenAI notes",
        )

        assert augment_result == "2_Projects/Augment"
        assert ai_result == "1_Management/AI"
        assert augment_result in live_folders
        assert ai_result in live_folders


class TestGap4SalesRename:
    """Gap 4: Sales/BoQ/Estimate/Procurement subjects should route to the
    renamed 2_Projects/Sales_BoQ_Estimate_Procurement folder."""

    def test_boq_routes_to_renamed_sales_folder(self, tmp_path: Path) -> None:
        rules = [
            {
                "from": ".*rib-software\\.com",
                "subject": ".*[Ss]ales.*[Cc]ommitment.*|[Bb]oQ.*|[Pp]urchase.*[Oo]rder.*",
                "folder": "2_Projects/Sales_BoQ_Estimate_Procurement",
                "priority": 90,
            },
        ]
        yaml_file = tmp_path / "rules.yaml"
        with open(yaml_file, "w") as fh:
            yaml.safe_dump(rules, fh)
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        result = yaml_dsl.evaluate_yaml_rules(
            loaded,
            "julien.seroi@rib-software.com",
            "Comittment on CS-3581 BoQ review",
        )
        assert result == "2_Projects/Sales_BoQ_Estimate_Procurement"


# ---------------------------------------------------------------------------
# Regression tests for PR #5 consensus findings.
# These lock the AI/Augment priority and the Eiffage/Budimex targets against
# the real ruleset in rules/, plus the rules.py imperative fallback. They
# FAIL before the PR #5 fixes and PASS after.
# ---------------------------------------------------------------------------


class TestPr5RealRulesetPriority:
    """The real ruleset must route AI/Augment subjects above the generic
    priority-76 estimate rule, and route Eiffage/Budimex to their own
    folders."""

    def test_estimate_ai_routes_to_management_ai_not_internal(self) -> None:
        rules = yaml_dsl.load_rules_from_dir(Path("rules"))
        result = yaml_dsl.evaluate_yaml_rules(
            rules,
            "mikhail.golyshev@rib-software.com",
            "estimate ai for RIB-4.0",
        )
        assert result == "1_Management/AI"

    def test_plain_estimate_still_routes_to_internal(self) -> None:
        rules = yaml_dsl.load_rules_from_dir(Path("rules"))
        result = yaml_dsl.evaluate_yaml_rules(
            rules,
            "mikhail.golyshev@rib-software.com",
            "estimate review for costing",
        )
        assert result == "2_Projects/Internal"

    def test_eiffage_routes_to_eiffage(self) -> None:
        rules = yaml_dsl.load_rules_from_dir(Path("rules"))
        result = yaml_dsl.evaluate_yaml_rules(
            rules,
            "anna.kowalska@rib-software.com",
            "Eiffage rollout update",
        )
        assert result == "2_Projects/Eiffage"

    def test_budimex_routes_to_budimex(self) -> None:
        rules = yaml_dsl.load_rules_from_dir(Path("rules"))
        result = yaml_dsl.evaluate_yaml_rules(
            rules,
            "anna.kowalska@rib-software.com",
            "Budimex Ratisbona milestone",
        )
        assert result == "2_Projects/Budimex"


class TestPr5PythonClassifyFallback:
    """The rules.py imperative fallback must match 'ai' on a word boundary
    (not substrings like 'maintenance'), keep augment before ai, and not
    misfire on bare 'estimate'."""

    def _classify(self, subject: str) -> str | None:
        ns = python_rules.load_python_rules(Path("rules/rules.py"))
        return python_rules.call_python_rules(
            ns, _email(from_addr="user@rib-software.com", subject=subject)
        )

    def test_augment_and_ai_routes_to_augment(self) -> None:
        assert self._classify("Augment AI rollout") == "2_Projects/Augment"

    def test_ai_guild_routes_to_management_ai(self) -> None:
        assert self._classify("AI Guild kickoff") == "1_Management/AI"

    def test_maintenance_window_does_not_route_to_ai(self) -> None:
        assert self._classify("Maintenance window scheduled") != "1_Management/AI"

    def test_customer_complaint_does_not_route_to_ai(self) -> None:
        assert self._classify("Customer complaint follow-up") != "1_Management/AI"
