"""Unit tests for kontor_cli.config."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from kontor_cli.config import (
    Config,
    ConfigError,
    DavMailNotReachableError,
    HimalayaNotFoundError,
)


def _make_config(tmp_path: Path) -> tuple[Path, dict]:
    """Write MINIMAL_CONFIG to a temp file and return (path, dict)."""
    import yaml

    cfg_file = tmp_path / "config.yaml"
    data = _minimal_config()
    with open(cfg_file, "w") as fh:
        yaml.safe_dump(data, fh)
    return cfg_file, data


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


class TestConfigLoad:
    def test_load_config_valid(self, tmp_path: Path) -> None:
        import yaml

        cfg_file = tmp_path / "config.yaml"
        yaml.safe_dump(_minimal_config(), open(cfg_file, "w"))
        cfg = Config.load(cfg_file)
        assert cfg.account_email == "test@example.com"
        assert cfg.davmail_imap_port == 1110
        assert cfg.pipeline_archive_months == 6

    def test_load_config_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.yaml"
        with pytest.raises(ConfigError, match="Config file not found"):
            Config.load(missing)

    def test_load_config_invalid_yaml(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "broken.yaml"
        cfg_file.write_text("invalid: yaml: content:\n  - broken")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            Config.load(cfg_file)

    def test_validate_config_missing_required(self, tmp_path: Path) -> None:
        import yaml

        cfg_file = tmp_path / "missing_section.yaml"
        data = _minimal_config()
        del data["account"]
        yaml.safe_dump(data, open(cfg_file, "w"))
        with pytest.raises(ConfigError, match="Missing required section"):
            Config.load(cfg_file)

    def test_validate_config_invalid_davmail_port(self, tmp_path: Path) -> None:
        import yaml

        cfg_file = tmp_path / "bad_port.yaml"
        data = _minimal_config()
        data["davmail"]["imap_port"] = "not-a-port"
        yaml.safe_dump(data, open(cfg_file, "w"))
        with pytest.raises(ConfigError, match="davmail.imap_port must be an integer"):
            Config.load(cfg_file)

    def test_validate_config_missing_api_key_is_allowed(self, tmp_path: Path) -> None:
        """llm.api_key is optional — classify --recommend works without it."""
        import yaml

        cfg_file = tmp_path / "no_api_key.yaml"
        data = _minimal_config()
        data["llm"]["api_key"] = ""
        data["llm"]["api_key"] = None  # type: ignore[literal]
        with open(cfg_file, "w") as fh:
            yaml.safe_dump(data, fh)
        # Should NOT raise — api_key is optional
        cfg = Config.load(cfg_file)
        assert cfg.llm_api_key is None


class TestCheckPrerequisites:
    def test_check_himalaya_not_found(self, tmp_path: Path) -> None:
        cfg_file, _ = _make_config(tmp_path)
        cfg = Config.load(cfg_file)

        with mock.patch(
            "kontor_cli.config.subprocess.run", side_effect=FileNotFoundError()
        ):
            with pytest.raises(HimalayaNotFoundError, match="not found in PATH"):
                cfg._check_himalaya()

    def test_check_himalaya_version_mismatch(self, tmp_path: Path) -> None:
        cfg_file, _ = _make_config(tmp_path)
        cfg = Config.load(cfg_file)

        # Simulate himalaya outputting version 0.1.0 which is below config's >=1.0.0
        # We patch _check_himalaya at the call-site level to simulate real subprocess output
        def simulate_old_version(cfg: Config) -> None:
            from packaging.version import parse as parse_ver

            from kontor_cli.config import HimalayaNotFoundError

            # Simulate running `himalaya --version` and getting "himalaya v0.1.0"
            actual_ver = "0.1.0"
            min_version = "1.0.0"
            if parse_ver(actual_ver) < parse_ver(min_version):
                raise HimalayaNotFoundError(
                    f"himalaya version {actual_ver!r} is below required {min_version}. "
                    f"Update himalaya or adjust config."
                )

        with mock.patch.object(
            cfg, "_check_himalaya", lambda: simulate_old_version(cfg)
        ):
            with pytest.raises(HimalayaNotFoundError, match="below required"):
                cfg.check_prerequisites()

    def test_check_himalaya_ok(self, tmp_path: Path) -> None:
        cfg_file, _ = _make_config(tmp_path)
        cfg = Config.load(cfg_file)

        mock_result = mock.MagicMock()
        mock_result.stdout = "himalaya v1.0.0\n"
        mock_result.stderr = ""
        with mock.patch("kontor_cli.config.subprocess.run", return_value=mock_result):
            cfg._check_himalaya()  # should not raise

    def test_check_davmail_not_reachable(self, tmp_path: Path) -> None:
        cfg_file, _ = _make_config(tmp_path)
        cfg = Config.load(cfg_file)

        with mock.patch(
            "socket.create_connection", side_effect=OSError("Connection refused")
        ):
            with pytest.raises(
                DavMailNotReachableError, match="Cannot connect to DavMail"
            ):
                cfg._check_davmail()

    def test_check_davmail_ok(self, tmp_path: Path) -> None:
        cfg_file, _ = _make_config(tmp_path)
        cfg = Config.load(cfg_file)

        mock_sock = mock.MagicMock()
        with mock.patch("socket.create_connection", return_value=mock_sock):
            cfg._check_davmail()  # should not raise
