"""Unit tests for kontor_cli.cli."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from unittest import mock


class TestCliHelp:
    def test_cli_help(self) -> None:
        from click.testing import CliRunner

        from kontor_cli.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "kontor-cli" in result.output


class TestCheckConfig:
    def test_cli_check_config_valid(self, tmp_path: Path) -> None:
        import yaml

        from kontor_cli.config import Config

        cfg_file = tmp_path / "config.yaml"
        yaml.safe_dump(
            {
                "himalaya": {"version": ">=1.0.0"},
                "davmail": {
                    "host": "localhost",
                    "imap_port": 1110,
                    "smtp_port": 1025,
                    "http_proxy_port": 3128,
                },
                "account": {
                    "email": "t@t.com",
                    "display_name": "t",
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
                "logging": {"level": "ERROR", "format": "text"},
            },
            open(cfg_file, "w"),
        )

        with mock.patch.object(Config, "load", return_value=mock.MagicMock()):
            with mock.patch.object(Config, "check_prerequisites"):
                from click.testing import CliRunner

                from kontor_cli.cli import cli

                runner = CliRunner()
                result = runner.invoke(cli, ["check-config"], catch_exceptions=False)
                # Should exit 0 or at least not raise
                assert result.exit_code in (0, None)

    def test_cli_check_config_invalid(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from kontor_cli.cli import cli

        runner = CliRunner()
        result = runner.invoke(
            cli, ["check-config", "--config", str(tmp_path / "missing.yaml")]
        )
        assert result.exit_code == 1
        assert "Config error" in result.output or "not found" in result.output


class TestClassify:
    def test_cli_classify_output_format(self, tmp_path: Path) -> None:
        from datetime import datetime

        import yaml

        from kontor_cli.config import Config
        from kontor_cli.himalaya import Email

        cfg_file = tmp_path / "config.yaml"
        yaml.safe_dump(
            {
                "himalaya": {"version": ">=1.0.0"},
                "davmail": {
                    "host": "localhost",
                    "imap_port": 1110,
                    "smtp_port": 1025,
                    "http_proxy_port": 3128,
                },
                "account": {
                    "email": "t@t.com",
                    "display_name": "t",
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
                "logging": {"level": "WARNING", "format": "json"},
            },
            open(cfg_file, "w"),
        )

        mock_cfg = mock.MagicMock(spec=Config)
        mock_cfg.triage_enabled = True
        mock_cfg.pipeline_archive_months = 6

        mock_email = Email(
            id="42",
            from_addr="alice@example.com",
            subject="Test",
            date=datetime.now(UTC),
            flags={},
            folder="INBOX",
        )

        with mock.patch("kontor_cli.cli.Config.load", return_value=mock_cfg):
            with mock.patch(
                "kontor_cli.himalaya.list_emails", return_value=[mock_email]
            ):
                with mock.patch("kontor_cli.rules_engine.RulesEngine") as mock_re:
                    instance = mock_re.return_value
                    instance.classify.return_value = "4_Info"

                    from click.testing import CliRunner

                    from kontor_cli.cli import cli

                    runner = CliRunner()
                    result = runner.invoke(
                        cli, ["classify", "--email-id", "42"], catch_exceptions=False
                    )
                    assert "4_Info" in result.output or result.exit_code == 0


class TestProcess:
    def test_cli_process_rebuild(self, tmp_path: Path) -> None:
        import yaml

        from kontor_cli.config import Config

        cfg_file = tmp_path / "config.yaml"
        yaml.safe_dump(
            {
                "himalaya": {"version": ">=1.0.0"},
                "davmail": {
                    "host": "localhost",
                    "imap_port": 1110,
                    "smtp_port": 1025,
                    "http_proxy_port": 3128,
                },
                "account": {
                    "email": "t@t.com",
                    "display_name": "t",
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
                "logging": {"level": "WARNING", "format": "json"},
            },
            open(cfg_file, "w"),
        )

        mock_cfg = mock.MagicMock(spec=Config)
        mock_cfg.triage_enabled = True
        mock_cfg.pipeline_archive_months = 6

        with mock.patch("kontor_cli.cli.Config.load", return_value=mock_cfg):
            with mock.patch("kontor_cli.cli.RebuildPipeline") as mock_rebuild:
                instance = mock_rebuild.return_value
                instance.run.return_value = {"phase": "rebuild", "total_processed": 0}

                from click.testing import CliRunner

                from kontor_cli.cli import cli

                runner = CliRunner()
                result = runner.invoke(
                    cli, ["process", "--phase", "rebuild", "--config", str(cfg_file)]
                )
                assert result.exit_code == 0
                assert "rebuild" in result.output


class TestClassifyRecommend:
    def test_classify_recommend_requires_no_llm_api_key(self, tmp_path: Path) -> None:
        """--recommend should work without llm.api_key in config."""
        import json

        import yaml
        from click.testing import CliRunner

        from kontor_cli.cli import cli

        cfg_file = tmp_path / "config.yaml"
        with open(cfg_file, "w") as fh:
            yaml.safe_dump(
                {
                    "himalaya": {"version": ">=1.0.0"},
                    "davmail": {
                        "host": "localhost",
                        "imap_port": 1110,
                        "smtp_port": 1025,
                        "http_proxy_port": 3128,
                    },
                    "account": {
                        "email": "t@t.com",
                        "display_name": "t",
                        "imap_host": "localhost",
                        "imap_port": 1110,
                        "smtp_host": "localhost",
                        "smtp_port": 1025,
                    },
                    # No llm.api_key — this is the key assertion
                    "llm": {
                        "base_url": "https://api.openai.com/v1",
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
                    "logging": {"level": "ERROR", "format": "text"},
                },
                fh,
            )
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()

        runner = CliRunner()
        with mock.patch(
            "kontor_cli.himalaya._run",
            return_value=json.dumps(
                [
                    {
                        "id": "42",
                        "from": {"address": "boss@example.com"},
                        "subject": "Q1 Budget",
                        "date": "2024-03-15T10:00:00Z",
                        "flags": {},
                    }
                ]
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "classify",
                    "--email-id",
                    "42",
                    "--recommend",
                    "--config",
                    str(cfg_file),
                ],
            )

        assert result.exit_code == 0, result.output
        # stdout may contain JSON log lines before the --recommend JSON; parse the last complete JSON block
        import re

        json_blocks = re.findall(r"\{[^{}]*\}", result.output, re.DOTALL)
        # Try to find the recommend JSON (has "email" and "taxonomy" keys)
        data = None
        for block in reversed(json_blocks):
            try:
                parsed = json.loads(block)
                if "email" in parsed and "taxonomy" in parsed:
                    data = parsed
                    break
            except Exception:
                continue
        if data is None:
            data = json.loads(result.output)  # fallback
        assert data["email"]["id"] == "42"
        assert data["email"]["from"] == "boss@example.com"
        assert "rules_based_target" in data
        assert "taxonomy" in data


class TestTriage:
    """Tests for the `triage` candidate-lister CLI command."""

    def _make_candidate(self) -> object:
        from kontor_cli.triage import TriageCandidate

        return TriageCandidate(
            email_id="99",
            from_name="Customer Carol",
            from_addr="customer@external.com",
            subject="Urgent: blocker on go-live",
            body="Please decide before Friday.",
            reason="external customer sender",
            decisive_prior=False,
        )

    def _make_email(self) -> object:
        from datetime import datetime

        from kontor_cli.himalaya import Email

        return Email(
            id="99",
            from_addr="customer@external.com",
            subject="Urgent: blocker on go-live",
            date=datetime(2026, 6, 28, 10, 0, 0, tzinfo=UTC),
            flags={},
            folder="INBOX",
        )

    def test_triage_lists_candidates_with_body(self) -> None:
        from click.testing import CliRunner

        from kontor_cli.cli import cli
        from kontor_cli.config import Config

        mock_cfg = mock.MagicMock(spec=Config)
        mock_cfg.triage_enabled = True
        candidate = self._make_candidate()

        with mock.patch("kontor_cli.cli.Config.load", return_value=mock_cfg):
            with mock.patch("kontor_cli.cli.Triage") as mock_triage_cls:
                instance = mock_triage_cls.return_value
                instance.list_candidates.return_value = [candidate]

                runner = CliRunner()
                result = runner.invoke(cli, ["triage"], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        assert "99" in result.output
        assert "customer@external.com" in result.output
        assert "Urgent: blocker on go-live" in result.output
        assert "external customer sender" in result.output
        assert "Please decide before Friday." in result.output
        instance.list_candidates.assert_called_once()

    def test_triage_never_calls_asana_write(self) -> None:
        from click.testing import CliRunner

        from kontor_cli.cli import cli
        from kontor_cli.config import Config

        mock_cfg = mock.MagicMock(spec=Config)
        mock_cfg.triage_enabled = True

        with mock.patch("kontor_cli.cli.Config.load", return_value=mock_cfg):
            with mock.patch("kontor_cli.cli.Triage") as mock_triage_cls:
                instance = mock_triage_cls.return_value
                instance.list_candidates.return_value = []
                with mock.patch(
                    "kontor_cli.asana_client.AsanaClient.create_task"
                ) as mock_create:
                    runner = CliRunner()
                    result = runner.invoke(cli, ["triage"], catch_exceptions=False)
                    mock_create.assert_not_called()

        assert result.exit_code == 0, result.output

    def test_triage_config_error_exits_1(self) -> None:
        from click.testing import CliRunner

        from kontor_cli.cli import cli
        from kontor_cli.config import ConfigError

        with mock.patch(
            "kontor_cli.cli.Config.load", side_effect=ConfigError("bad config")
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["triage"], catch_exceptions=False)

        assert result.exit_code == 1
        assert "Config error" in result.output


class TestTriageCreate:
    """Tests for the `triage-create` CLI command (agent-driven creation)."""

    def _make_email(self) -> object:
        from datetime import datetime

        from kontor_cli.himalaya import Email

        return Email(
            id="99",
            from_addr="customer@external.com",
            subject="Urgent: blocker on go-live",
            date=datetime(2026, 6, 28, 10, 0, 0, tzinfo=UTC),
            flags={},
            folder="INBOX",
        )

    def _make_decision(self) -> object:
        from kontor_cli.triage import TriageDecision

        return TriageDecision(
            email_id="99",
            qualifies=True,
            reason="agent-supplied",
            category="taking_decision",
            target_date="2026-06-30",
            task_name="[Taking Decision] Urgent: blocker on go-live",
            task_notes="some notes",
            outcome="preview",
        )

    def test_dry_run_previews_with_no_write(self) -> None:
        from click.testing import CliRunner

        from kontor_cli.cli import cli
        from kontor_cli.config import Config

        mock_cfg = mock.MagicMock(spec=Config)
        mock_cfg.triage_enabled = True
        email = self._make_email()
        decision = self._make_decision()

        with mock.patch("kontor_cli.cli.Config.load", return_value=mock_cfg):
            with mock.patch("kontor_cli.cli.list_emails", return_value=[email]):
                with mock.patch("kontor_cli.cli.Triage") as mock_triage_cls:
                    instance = mock_triage_cls.return_value
                    instance.create_task_for.return_value = decision

                    runner = CliRunner()
                    result = runner.invoke(
                        cli,
                        [
                            "triage-create",
                            "--email-id",
                            "99",
                            "--category",
                            "taking_decision",
                        ],
                        catch_exceptions=False,
                    )

        assert result.exit_code == 0, result.output
        assert "preview" in result.output
        assert "[Taking Decision] Urgent: blocker on go-live" in result.output
        assert "2026-06-30" in result.output
        # default is dry-run
        instance.create_task_for.assert_called_once()
        call = instance.create_task_for.call_args
        assert call.kwargs.get("dry_run") is True or call.args[2] is True

    def test_no_dry_run_creates_real_task(self) -> None:
        from click.testing import CliRunner

        from kontor_cli.cli import cli
        from kontor_cli.config import Config

        mock_cfg = mock.MagicMock(spec=Config)
        mock_cfg.triage_enabled = True
        email = self._make_email()
        created = self._make_decision()
        created.outcome = "created"

        with mock.patch("kontor_cli.cli.Config.load", return_value=mock_cfg):
            with mock.patch("kontor_cli.cli.list_emails", return_value=[email]):
                with mock.patch("kontor_cli.cli.Triage") as mock_triage_cls:
                    instance = mock_triage_cls.return_value
                    instance.create_task_for.return_value = created

                    runner = CliRunner()
                    result = runner.invoke(
                        cli,
                        [
                            "triage-create",
                            "--email-id",
                            "99",
                            "--category",
                            "taking_decision",
                            "--no-dry-run",
                        ],
                        catch_exceptions=False,
                    )

        assert result.exit_code == 0, result.output
        assert "created" in result.output
        # the only write path: dry_run must flow through as False
        call = instance.create_task_for.call_args
        passed = call.kwargs.get("dry_run")
        if passed is None:
            passed = call.args[2]
        assert passed is False

    def test_triage_disabled_exits_1(self) -> None:
        from click.testing import CliRunner

        from kontor_cli.cli import cli
        from kontor_cli.config import Config

        mock_cfg = mock.MagicMock(spec=Config)
        mock_cfg.triage_enabled = True
        mock_cfg.triage_enabled = False

        with mock.patch("kontor_cli.cli.Config.load", return_value=mock_cfg):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "triage-create",
                    "--email-id",
                    "99",
                    "--category",
                    "taking_decision",
                ],
            )
        assert result.exit_code == 1
        assert "disabled" in result.output.lower()

    def test_invalid_category_rejected_by_click(self) -> None:
        from click.testing import CliRunner

        from kontor_cli.cli import cli

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "triage-create",
                "--email-id",
                "99",
                "--category",
                "nonsense",
            ],
        )
        # click.Choice rejects → usage error, exit code 2
        assert result.exit_code == 2
        assert "nonsense" in result.output or "invalid" in result.output.lower()

    def test_deadline_parsed_and_passed_through(self) -> None:
        from datetime import date

        from click.testing import CliRunner

        from kontor_cli.cli import cli
        from kontor_cli.config import Config

        mock_cfg = mock.MagicMock(spec=Config)
        mock_cfg.triage_enabled = True
        email = self._make_email()
        decision = self._make_decision()

        with mock.patch("kontor_cli.cli.Config.load", return_value=mock_cfg):
            with mock.patch("kontor_cli.cli.list_emails", return_value=[email]):
                with mock.patch("kontor_cli.cli.Triage") as mock_triage_cls:
                    instance = mock_triage_cls.return_value
                    instance.create_task_for.return_value = decision

                    runner = CliRunner()
                    result = runner.invoke(
                        cli,
                        [
                            "triage-create",
                            "--email-id",
                            "99",
                            "--category",
                            "nudging",
                            "--deadline",
                            "2026-07-15",
                        ],
                        catch_exceptions=False,
                    )

        assert result.exit_code == 0, result.output
        passed_decision = instance.create_task_for.call_args.args[1]
        assert passed_decision.category == "nudging"
        assert passed_decision.deadline == date(2026, 7, 15)

    def test_email_not_found_exits_1(self) -> None:
        from click.testing import CliRunner

        from kontor_cli.cli import cli
        from kontor_cli.config import Config

        mock_cfg = mock.MagicMock(spec=Config)
        mock_cfg.triage_enabled = True

        with mock.patch("kontor_cli.cli.Config.load", return_value=mock_cfg):
            with mock.patch("kontor_cli.cli.list_emails", return_value=[]):
                with mock.patch("kontor_cli.cli.Triage"):
                    runner = CliRunner()
                    result = runner.invoke(
                        cli,
                        [
                            "triage-create",
                            "--email-id",
                            "missing",
                            "--category",
                            "nudging",
                        ],
                        catch_exceptions=False,
                    )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_config_error_exits_1(self) -> None:
        from click.testing import CliRunner

        from kontor_cli.cli import cli
        from kontor_cli.config import ConfigError

        with mock.patch(
            "kontor_cli.cli.Config.load", side_effect=ConfigError("bad config")
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "triage-create",
                    "--email-id",
                    "99",
                    "--category",
                    "nudging",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "Config error" in result.output
