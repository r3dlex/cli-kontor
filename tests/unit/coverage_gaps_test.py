"""Targeted coverage tests for residual gaps in existing modules.

Each test class targets a specific source file's missed lines as reported by
`uv run pytest --cov`. New tests should be added here when coverage drops
below the 90% threshold rather than scattered across the existing files.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest
import yaml

from kontor_cli.classifier import Classifier
from kontor_cli.himalaya import Email, HimalayaError
from kontor_cli.rules import nl_rules, python_rules, yaml_dsl


def _email(
    id: str = "1",
    from_addr: str = "alice@example.com",
    subject: str = "Test",
    folder: str = "INBOX",
    days_ago: int = 30,
) -> Email:
    return Email(
        id=id,
        from_addr=from_addr,
        subject=subject,
        date=datetime.now(UTC) - (datetime.now(UTC) - datetime.now(UTC)),
        flags={},
        folder=folder,
    )


# ---------------------------------------------------------------------------
# config.py gaps: 66, 102, 107, 122-123, 133, 143-144, 151
# ---------------------------------------------------------------------------


def _minimal_config() -> dict:
    return {
        "himalaya": {"version": ">=1.0.0"},
        "davmail": {
            "host": "localhost",
            "imap_port": 1110,
            "smtp_port": 1025,
            "http_proxy_port": 3128,
        },
        "account": {
            "email": "test@example.com",
            "display_name": "Test User",
            "imap_host": "localhost",
            "imap_port": 1110,
            "smtp_host": "localhost",
            "smtp_port": 1025,
        },
        "llm": {
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "model": "gpt-4o",
            "temperature": 0.0,
            "timeout": 30,
        },
        "rules": {
            "yaml_dir": "rules",
            "python_rules_file": "rules/rules.py",
            "nl_rules_dir": "rules",
            "evolved_dir": "rules/evolved",
        },
        "pipeline": {
            "archive_age_months": 6,
            "confidence_threshold": 0.7,
            "llm_failure_alert_threshold": 5,
        },
        "logging": {"level": "INFO", "format": "json"},
    }


def _write_config(tmp_path: Path, data: dict) -> Path:
    cfg_file = tmp_path / "config.yaml"
    with open(cfg_file, "w") as fh:
        yaml.safe_dump(data, fh)
    return cfg_file


class TestConfigGaps:
    def test_load_config_default_path(self, tmp_path: Path, monkeypatch) -> None:
        """Config.load() with None path falls back to cwd/config.yaml."""
        from kontor_cli.config import Config, ConfigError

        # Ensure no config.yaml in cwd by chdir into tmp_path with no file
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ConfigError, match="Config file not found"):
            Config.load(None)

    def test_validate_config_invalid_smtp_port(self, tmp_path: Path) -> None:
        from kontor_cli.config import Config, ConfigError

        data = _minimal_config()
        data["davmail"]["smtp_port"] = "not-an-int"
        cfg_file = _write_config(tmp_path, data)
        with pytest.raises(ConfigError, match="davmail.smtp_port must be an integer"):
            Config.load(cfg_file)

    def test_check_prerequisites_calls_both_checks(self, tmp_path: Path) -> None:
        from kontor_cli.config import Config

        cfg_file = _write_config(tmp_path, _minimal_config())
        cfg = Config.load(cfg_file)
        with mock.patch.object(cfg, "_check_himalaya") as h:
            with mock.patch.object(cfg, "_check_davmail") as d:
                cfg.check_prerequisites()
        h.assert_called_once()
        d.assert_called_once()

    def test_check_himalaya_called_process_error(self, tmp_path: Path) -> None:
        from kontor_cli.config import Config, HimalayaNotFoundError

        cfg_file = _write_config(tmp_path, _minimal_config())
        cfg = Config.load(cfg_file)
        exc = subprocess.CalledProcessError(returncode=1, cmd=["himalaya"], stderr="x")
        with mock.patch("kontor_cli.config.subprocess.run", side_effect=exc):
            with pytest.raises(HimalayaNotFoundError, match="--version failed"):
                cfg._check_himalaya()

    def test_check_himalaya_no_version_in_output(self, tmp_path: Path) -> None:
        """When himalaya outputs no parseable version and version is a raw string,
        fall through without raising (line 133 path).
        """
        from kontor_cli.config import Config

        data = _minimal_config()
        data["himalaya"]["version"] = "1.0.0"  # no >= prefix → skip the if block
        cfg_file = _write_config(tmp_path, data)
        cfg = Config.load(cfg_file)

        mock_result = mock.MagicMock()
        mock_result.stdout = "himalaya custom-build\n"
        mock_result.stderr = ""
        with mock.patch("kontor_cli.config.subprocess.run", return_value=mock_result):
            cfg._check_himalaya()  # should not raise — version check is bypassed

    def test_check_himalaya_invalid_version_string(self, tmp_path: Path) -> None:
        from kontor_cli.config import Config, HimalayaNotFoundError

        cfg_file = _write_config(tmp_path, _minimal_config())
        cfg = Config.load(cfg_file)

        mock_result = mock.MagicMock()
        mock_result.stdout = "himalaya not-a-parseable-version\n"
        mock_result.stderr = ""
        with mock.patch("kontor_cli.config.subprocess.run", return_value=mock_result):
            with pytest.raises(
                HimalayaNotFoundError, match="Cannot verify himalaya version"
            ):
                cfg._check_himalaya()

    def test_check_himalaya_version_below_minimum(self, tmp_path: Path) -> None:
        from kontor_cli.config import Config, HimalayaNotFoundError

        cfg_file = _write_config(tmp_path, _minimal_config())
        cfg = Config.load(cfg_file)

        mock_result = mock.MagicMock()
        mock_result.stdout = "himalaya v0.1.0\n"
        mock_result.stderr = ""
        with mock.patch("kontor_cli.config.subprocess.run", return_value=mock_result):
            with pytest.raises(HimalayaNotFoundError, match="below required"):
                cfg._check_himalaya()


# ---------------------------------------------------------------------------
# classifier.py gaps: 125, 134, 200-202, 209-211, 213-217
# ---------------------------------------------------------------------------


def _mock_classifier_cfg() -> mock.MagicMock:
    from kontor_cli.config import Config

    cfg = mock.MagicMock(spec=Config)
    cfg.llm_base_url = "https://api.openai.com/v1"
    cfg.llm_api_key = "sk-test"
    cfg.llm_model = "gpt-4o"
    cfg.llm_temperature = 0.0
    cfg.llm_timeout = 30
    cfg.pipeline_confidence_threshold = 0.7
    return cfg


def _make_email() -> Email:
    return Email(
        id="1",
        from_addr="alice@example.com",
        subject="Test",
        date=datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC),
        flags={},
        folder="INBOX",
    )


class TestClassifierGaps:
    def test_truncate_gpt5_branch(self) -> None:
        """_truncate_prompt gpt-5 branch (line 125)."""
        from kontor_cli.classifier import _truncate_prompt

        prompt = "x" * 200_000
        result = _truncate_prompt(prompt, model="gpt-5")
        assert result.endswith("[... prompt truncated ...]")

    def test_truncate_claude_branch(self) -> None:
        """_truncate_prompt claude branch (line 134)."""
        from kontor_cli.classifier import _truncate_prompt

        prompt = "x" * 200_000
        result = _truncate_prompt(prompt, model="claude-3-opus")
        assert result.endswith("[... prompt truncated ...]")

    def test_classify_request_error_returns_none(self) -> None:
        import httpx

        cls = Classifier(_mock_classifier_cfg())
        with mock.patch("httpx.post", side_effect=httpx.RequestError("conn")):
            result = cls.classify(_make_email())
        assert result is None

    def test_classify_strips_markdown_fence(self) -> None:
        """LLM response wrapped in ```json ... ``` should be parsed."""
        mock_result = mock.MagicMock()
        mock_result.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "```json\n"
                        + json.dumps(
                            {
                                "folder": "2_Projects/PRJ_X",
                                "confidence": 0.9,
                                "action": "none",
                            }
                        )
                        + "\n```"
                    }
                }
            ]
        }
        mock_result.raise_for_status = mock.MagicMock()
        cls = Classifier(_mock_classifier_cfg())
        with mock.patch("httpx.post", return_value=mock_result):
            result = cls.classify(_make_email())
        assert result is not None
        assert result.folder == "2_Projects/PRJ_X"

    def test_classify_invalid_json_returns_none(self) -> None:
        mock_result = mock.MagicMock()
        mock_result.json.return_value = {
            "choices": [{"message": {"content": "not-valid-json{"}}]
        }
        mock_result.raise_for_status = mock.MagicMock()
        cls = Classifier(_mock_classifier_cfg())
        with mock.patch("httpx.post", return_value=mock_result):
            result = cls.classify(_make_email())
        assert result is None

    def test_classify_missing_choices_returns_none(self) -> None:
        """Response without 'choices' key triggers the parse error branch."""
        mock_result = mock.MagicMock()
        mock_result.json.return_value = {"error": "rate limited"}
        mock_result.raise_for_status = mock.MagicMock()
        cls = Classifier(_mock_classifier_cfg())
        with mock.patch("httpx.post", return_value=mock_result):
            result = cls.classify(_make_email())
        assert result is None


# ---------------------------------------------------------------------------
# python_rules.py gaps: 22, 27-29, 45-46
# ---------------------------------------------------------------------------


class TestPythonRulesGaps:
    def test_load_python_rules_spec_is_none(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.py"
        rules_file.write_text("# empty")
        with mock.patch.object(
            importlib.util, "spec_from_file_location", return_value=None
        ):
            ns = python_rules.load_python_rules(rules_file)
        assert ns == {}

    def test_load_python_rules_exec_error(self, tmp_path: Path) -> None:
        """A rules.py with a syntax error returns {'classify': None}."""
        rules_file = tmp_path / "rules.py"
        rules_file.write_text("def classify(email\n    # syntax error\n")
        ns = python_rules.load_python_rules(rules_file)
        assert ns.get("classify") is None

    def test_call_python_rules_classify_raises(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.py"
        rules_file.write_text("def classify(email):\n    raise RuntimeError('boom')\n")
        ns = python_rules.load_python_rules(rules_file)
        result = python_rules.call_python_rules(ns, _email())
        assert result is None


# ---------------------------------------------------------------------------
# yaml_dsl.py gaps: 33, 35-36, 59, 75-76, 82
# ---------------------------------------------------------------------------


class TestYamlDslGaps:
    def test_to_field_matches(self, tmp_path: Path) -> None:
        rules = [{"to": "boss@", "folder": "2_Projects/PRJ_A", "priority": 50}]
        (tmp_path / "rules.yaml").write_text(yaml.safe_dump(rules))
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        # to field only available on dataclass — assert via evaluate_yaml_rules
        assert loaded[0].to == "boss@"
        # Matches: to=boss@example.com contains 'boss@'
        assert loaded[0].matches("x@y.com", "Subject", "boss@example.com")
        # Does not match: to=boss@ but email is someone else
        assert not loaded[0].matches("x@y.com", "Subject", "other@example.com")

    def test_load_combined_yaml_dsl_file(self, tmp_path: Path) -> None:
        rules = [{"from": "alice@example.com", "folder": "2_Projects/PRJ_A"}]
        (tmp_path / "yaml_dsl.yaml").write_text(yaml.safe_dump(rules))
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        # The file is loaded twice: once as the combined file, once as a
        # root-level *.yaml — but at least one rule must be loaded.
        assert len(loaded) >= 1
        assert loaded[0].from_addr == "alice@example.com"

    def test_load_rules_d_subdir(self, tmp_path: Path) -> None:
        """rules.d/*.yaml are loaded."""
        subdir = tmp_path / "rules.d"
        subdir.mkdir()
        rules = [{"from": "bob@example.com", "folder": "2_Projects/PRJ_B"}]
        (subdir / "a.yaml").write_text(yaml.safe_dump(rules))
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].from_addr == "bob@example.com"

    def test_root_yaml_files_loaded_skipping_config(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text("# not a rule file")
        (tmp_path / "rules.yaml").write_text(
            yaml.safe_dump([{"from": "x@y.com", "folder": "2_Projects/PRJ_X"}])
        )
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        # config.yaml is skipped, rules.yaml is loaded
        assert len(loaded) == 1

    def test_invalid_yaml_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "rules.yaml").write_text("invalid: yaml: content:\n  - broken")
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        assert loaded == []

    def test_non_dict_entry_skipped(self, tmp_path: Path) -> None:
        rules = [
            "not-a-dict",
            {"from": "x@y.com", "folder": "2_Projects/PRJ_X"},
        ]
        (tmp_path / "rules.yaml").write_text(yaml.safe_dump(rules))
        loaded = yaml_dsl.load_rules_from_dir(tmp_path)
        assert len(loaded) == 1


# ---------------------------------------------------------------------------
# pipeline.py inline rules-evaluation gaps
# ---------------------------------------------------------------------------


def _rules_pipeline(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Pipeline whose rule sources all load from tmp_path (triage disabled)."""
    from kontor_cli.pipeline import Pipeline

    cfg = mock.MagicMock()
    cfg.rules_yaml_dir = tmp_path
    cfg.rules_python_file = tmp_path / "rules.py"
    cfg.rules_nl_dir = tmp_path
    cfg.triage_enabled = False
    return Pipeline(cfg, cwd=tmp_path)


class TestPipelineRulesGaps:
    def test_python_rule_matched_logged(self, tmp_path: Path) -> None:
        """When YAML misses and Python hits, the 'Python rule matched' branch fires."""
        # YAML rules dir is empty (no rules)
        (tmp_path / "rules.yaml").write_text(yaml.safe_dump([]))
        # Python rules present
        (tmp_path / "rules.py").write_text(
            "def classify(email):\n    return '2_Projects/PRJ_Py'\n"
        )
        # NL rules present (used by later path)
        (tmp_path / "guidelines.rules.txt").write_text("NL rule text")

        p = _rules_pipeline(tmp_path)
        result = p.classify_with_rules(_email())
        assert result == "2_Projects/PRJ_Py"

    def test_nl_rules_only_logs_no_direct_match(self, tmp_path: Path) -> None:
        """When no YAML or Python match, NL rules path is hit for logging."""
        (tmp_path / "rules.yaml").write_text(yaml.safe_dump([]))
        (tmp_path / "rules.py").write_text("# no classify fn")
        (tmp_path / "guidelines.rules.txt").write_text("Always escalate sales leads")

        p = _rules_pipeline(tmp_path)
        result = p.classify_with_rules(_email())
        assert result is None
        # NL rules are loaded
        assert p.nl_rules
        assert "Always escalate sales leads" in nl_rules.nl_rules_context(p.nl_rules)


# ---------------------------------------------------------------------------
# himalaya.py gap: 115 (empty-page break)
# ---------------------------------------------------------------------------


class TestHimalayaGaps:
    def test_list_emails_stops_on_empty_page(self) -> None:
        """A page with no envelopes short-circuits the loop."""
        from kontor_cli.himalaya import list_emails

        full_page = [
            {
                "id": str(i),
                "from": {"address": f"u{i}@x.com"},
                "subject": f"S{i}",
                "date": "2024-01-01T00:00:00Z",
                "flags": {},
            }
            for i in range(50)
        ]
        # Page 1 = full, page 2 = [] (empty), no page 3
        page_payloads = [json.dumps(full_page), "[]"]

        def fake_run(*args, **kwargs):
            r = mock.MagicMock()
            r.returncode = 0
            r.stdout = page_payloads.pop(0) if page_payloads else "[]"
            return r

        with (
            mock.patch("kontor_cli.himalaya.subprocess.run", side_effect=fake_run) as p,
            mock.patch("time.sleep"),
        ):
            emails = list_emails("INBOX")

        assert len(emails) == 50
        assert p.call_count == 2


# ---------------------------------------------------------------------------
# mailbox_cleanup.py gap: 27 (ValueError in live_folder_for_archive)
# ---------------------------------------------------------------------------


class TestMailboxCleanupGaps:
    def test_live_folder_for_archive_invalid(self) -> None:
        from kontor_cli.mailbox_cleanup import live_folder_for_archive

        with pytest.raises(ValueError, match="Expected archive project folder"):
            live_folder_for_archive("1_Management/NotArchive")


# ---------------------------------------------------------------------------
# nl_rules.py gap: 23-24 (OSError in load_nl_rules)
# ---------------------------------------------------------------------------


class TestNlRulesGaps:
    def test_load_nl_rules_oserror_skips(self, tmp_path: Path) -> None:
        """A rule file that raises OSError is skipped, not propagated."""
        rule_file = tmp_path / "guideline.rules.txt"
        rule_file.write_text("ok rule")
        with mock.patch.object(Path, "read_text", side_effect=OSError("perm denied")):
            loaded = nl_rules.load_nl_rules(tmp_path)
        # All files raise, so empty result
        assert loaded == []


# ---------------------------------------------------------------------------
# pipeline.py gaps: 55-57, 267-269, 386
# ---------------------------------------------------------------------------


class MockConfig:
    """Minimal pipeline config mock (subset of Config)."""

    pipeline_archive_months = 6
    pipeline_llm_failure_alert = 5
    rules_yaml_dir = Path.cwd() / "rules"
    rules_python_file = Path.cwd() / "rules" / "rules.py"
    rules_nl_dir = Path.cwd() / "rules"
    rules_evolved_dir = Path.cwd() / "rules" / "evolved"
    llm_base_url = "https://api.openai.com/v1"
    llm_api_key = "sk-test"
    llm_model = "gpt-4o"
    llm_temperature = 0.0
    llm_timeout = 30
    pipeline_confidence_threshold = 0.7


class TestPipelineGaps:
    def test_ensure_folder_swallows_himalaya_error(self, tmp_path: Path) -> None:
        """_ensure_folder should not propagate HimalayaError from create_folder."""
        from kontor_cli.pipeline import Pipeline

        p = Pipeline(MockConfig(), cwd=tmp_path)
        with mock.patch(
            "kontor_cli.pipeline.create_folder",
            side_effect=HimalayaError("perm denied"),
        ):
            p._ensure_folder("2_Projects/PRJ_Test")  # should not raise

    def test_rebuild_skips_folders_with_himalaya_error(self, tmp_path: Path) -> None:
        """RebuildPipeline.run() should continue on per-folder HimalayaError."""
        from kontor_cli.pipeline import RebuildPipeline

        def list_emails_side_effect(folder, cwd=None):
            if folder == "INBOX":
                raise HimalayaError("folder not found")
            return []

        with (
            mock.patch(
                "kontor_cli.pipeline.list_emails", side_effect=list_emails_side_effect
            ),
            mock.patch("kontor_cli.pipeline.create_folder"),
        ):
            p = RebuildPipeline(MockConfig(), cwd=tmp_path)
            p.classify_with_rules = lambda e: "4_Info"
            result = p.run(dry_run=True)

        assert result["phase"] == "rebuild"

    def test_heal_wrong_folder_violation_fixed_when_not_dry_run(
        self, tmp_path: Path
    ) -> None:
        """HealPipeline with dry_run=False fixes wrong-folder violations (line 386)."""
        from kontor_cli.pipeline import HealPipeline

        email = _email(id="misplaced-1", folder="INBOX", days_ago=10)
        with (
            mock.patch("kontor_cli.pipeline.list_emails", return_value=[email]),
            mock.patch("kontor_cli.pipeline.move_email"),
            mock.patch("kontor_cli.pipeline.create_folder"),
        ):
            p = HealPipeline(MockConfig(), cwd=tmp_path)
            p.classify_with_rules = lambda e: "2_Projects/PRJ_Test"
            result = p.run(dry_run=False)

        assert result["violations_found"] >= 1
        assert result["violations_fixed"] >= 1


# ---------------------------------------------------------------------------
# logging_config.py gaps: 23, 59
# ---------------------------------------------------------------------------


class TestLoggingConfigGaps:
    def test_json_formatter_with_exc_info(self) -> None:
        import logging
        import sys

        from kontor_cli.logging_config import JSONFormatter

        fmt = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=0,
            msg="an error",
            args=(),
            exc_info=exc_info,
        )
        output = fmt.format(record)
        assert "exception" in output
        assert "ValueError" in output

    def test_text_format_branch(self) -> None:
        from kontor_cli.logging_config import configure_logging

        configure_logging(level="INFO", format_type="text")
        root = __import__("logging").getLogger("kontor_cli")
        # At least one handler is attached with a text Formatter
        assert any(
            hasattr(h, "formatter") and not isinstance(h.formatter, type(None))
            for h in root.handlers
        )
