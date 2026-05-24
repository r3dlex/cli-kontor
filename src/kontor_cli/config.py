"""Configuration loader and validator for kontor-cli."""

from __future__ import annotations

import re
import socket
import subprocess
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""


class HimalayaNotFoundError(ConfigError):
    """Raised when himalaya is not installed or not in PATH."""


class DavMailNotReachableError(ConfigError):
    """Raised when DavMail ports are not reachable."""


class Config:
    """Validated configuration object."""

    def __init__(self, data: dict[str, Any], config_dir: Path | None = None) -> None:
        self.himalaya_version: str = data["himalaya"]["version"]
        self.davmail_host: str = data["davmail"]["host"]
        self.davmail_imap_port: int = data["davmail"]["imap_port"]
        self.davmail_smtp_port: int = data["davmail"]["smtp_port"]
        self.davmail_http_proxy_port: int = data["davmail"]["http_proxy_port"]
        self.account_email: str = data["account"]["email"]
        self.account_display_name: str = data["account"]["display_name"]
        self.account_imap_host: str = data["account"]["imap_host"]
        self.account_imap_port: int = data["account"]["imap_port"]
        self.account_smtp_host: str = data["account"]["smtp_host"]
        self.account_smtp_port: int = data["account"]["smtp_port"]
        self.llm_base_url: str = data["llm"]["base_url"]
        self.llm_api_key: str | None = data["llm"].get("api_key") or None
        self.llm_model: str = data["llm"]["model"]
        self.llm_temperature: float = data["llm"]["temperature"]
        self.llm_timeout: int = data["llm"]["timeout"]
        # Resolve relative paths against the config file directory
        config_dir = config_dir or Path.cwd()
        self.rules_yaml_dir: Path = config_dir / data["rules"]["yaml_dir"]
        self.rules_python_file: Path = config_dir / data["rules"]["python_rules_file"]
        self.rules_nl_dir: Path = config_dir / data["rules"]["nl_rules_dir"]
        self.rules_evolved_dir: Path = config_dir / data["rules"]["evolved_dir"]
        self.pipeline_archive_months: int = data["pipeline"]["archive_age_months"]
        self.pipeline_confidence_threshold: float = data["pipeline"][
            "confidence_threshold"
        ]
        self.pipeline_llm_failure_alert: int = data["pipeline"][
            "llm_failure_alert_threshold"
        ]
        self.log_level: str = data["logging"]["level"]
        self.log_format: str = data["logging"]["format"]

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        """Load and validate configuration from a YAML file."""
        if path is None:
            path = Path.cwd() / "config.yaml"
        path = Path(path)

        if not path.exists():
            raise ConfigError(
                f"Config file not found: {path}. Copy config.example.yaml to config.yaml and fill in your values."
            )

        try:
            with open(path) as fh:
                data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

        cls._validate_required(data, path)
        config_dir = path.parent if path.parent else None
        return cls(data, config_dir=config_dir)

    @classmethod
    def _validate_required(cls, data: dict[str, Any], path: Path) -> None:
        required_sections = [
            "himalaya",
            "davmail",
            "account",
            "llm",
            "rules",
            "pipeline",
            "logging",
        ]
        for section in required_sections:
            if section not in data:
                raise ConfigError(f"Missing required section '{section}' in {path}")

        if not isinstance(data["davmail"].get("imap_port"), int):
            raise ConfigError("davmail.imap_port must be an integer")
        if not isinstance(data["davmail"].get("smtp_port"), int):
            raise ConfigError("davmail.smtp_port must be an integer")

    def check_prerequisites(self) -> None:
        """Run startup checks: himalaya, himalaya version, DavMail connectivity."""
        self._check_himalaya()
        self._check_davmail()

    def _check_himalaya(self) -> None:
        """Verify himalaya is in PATH and version matches requirement."""
        try:
            result = subprocess.run(
                ["himalaya", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError:
            raise HimalayaNotFoundError(
                "himalaya not found in PATH. Install it: https://github.com/tobiassjosten/himalaya"
            ) from None
        except subprocess.CalledProcessError as exc:
            raise HimalayaNotFoundError(
                f"himalaya --version failed: {exc.stderr}"
            ) from exc

        version_line = result.stdout.splitlines()[0] if result.stdout else ""
        # Extract version number from output (e.g. "himalaya v1.0.0" or "himalaya 1.0.0")
        match = re.search(r"(\d+(?:\.\d+)+)", version_line)
        if match:
            actual_ver = match.group(1)
        else:
            actual_ver = version_line.strip()

        if self.himalaya_version.startswith(">="):
            from packaging.version import InvalidVersion
            from packaging.version import parse as parse_ver

            min_version = self.himalaya_version[2:]
            try:
                actual_parsed = parse_ver(actual_ver)
                min_parsed = parse_ver(min_version)
            except InvalidVersion:
                raise HimalayaNotFoundError(
                    f"Cannot verify himalaya version: output {version_line!r} "
                    f"does not contain a parseable version number. "
                    f"Install a standard himalaya release or set himalaya.version "
                    f"to a known-good value in config."
                ) from None
            if actual_parsed < min_parsed:
                raise HimalayaNotFoundError(
                    f"himalaya version {actual_ver!r} is below required {min_version}. "
                    f"Update himalaya or adjust config."
                )

    def _check_davmail(self) -> None:
        """Verify DavMail IMAP port is reachable."""
        try:
            sock = socket.create_connection(
                (self.davmail_host, self.davmail_imap_port),
                timeout=5,
            )
            sock.close()
        except OSError as exc:
            raise DavMailNotReachableError(
                f"Cannot connect to DavMail at {self.davmail_host}:{self.davmail_imap_port}. "
                f"Ensure DavMail is running. Error: {exc}"
            ) from exc
