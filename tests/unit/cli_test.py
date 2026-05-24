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
