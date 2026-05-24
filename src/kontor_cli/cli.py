"""CLI entry point for kontor-cli."""

from __future__ import annotations

import logging
import sys
from datetime import UTC
from pathlib import Path

import click

from kontor_cli.config import (
    Config,
    ConfigError,
    DavMailNotReachableError,
    HimalayaNotFoundError,
)
from kontor_cli.logging_config import configure_logging
from kontor_cli.pipeline import HealPipeline, RealtimePipeline, RebuildPipeline

logger = logging.getLogger("kontor_cli")


@click.group()
@click.option(
    "--log-level",
    default="INFO",
    type=str,
    help="Log level: DEBUG, INFO, WARNING, ERROR",
)
@click.option(
    "--log-format",
    default="json",
    type=click.Choice(["json", "text"]),
    help="Log format",
)
@click.pass_context
def cli(ctx: click.Context, log_level: str, log_format: str) -> None:
    """kontor-cli — Autonomous email management via himalaya + DavMail + LLM."""
    configure_logging(level=log_level, format_type=log_format)
    ctx.ensure_object(dict)


@cli.command("check-config")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, path_type=Path),
    default=None,
    help="Path to config.yaml (default: ./config.yaml)",
)
def check_config(config_path: Path | None) -> None:
    """Validate config.yaml and run startup checks (himalaya, DavMail)."""
    try:
        cfg = Config.load(config_path)
        cfg.check_prerequisites()
        click.echo("Config OK — all prerequisites satisfied.")
        sys.exit(0)
    except ConfigError as exc:
        click.echo(f"Config error: {exc}", err=True)
        sys.exit(1)
    except HimalayaNotFoundError as exc:
        click.echo(f"himalaya error: {exc}", err=True)
        sys.exit(1)
    except DavMailNotReachableError as exc:
        click.echo(f"DavMail error: {exc}", err=True)
        sys.exit(1)


@cli.command("classify")
@click.option("--email-id", required=True, help="Email ID from himalaya envelope list")
@click.option("--folder", default="INBOX", help="Source folder (default: INBOX)")
@click.option(
    "--recommend",
    is_flag=True,
    help="Output full classification recommendation as JSON for LLM review (no API key required)",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, path_type=Path),
    default=None,
)
def classify(
    email_id: str, folder: str, recommend: bool, config_path: Path | None
) -> None:
    """Print the target folder for a given email ID (dry run — no changes)."""
    try:
        cfg = Config.load(config_path)
    except ConfigError as exc:
        click.echo(f"Config error: {exc}", err=True)
        sys.exit(1)

    from kontor_cli.himalaya import HimalayaError, list_emails

    try:
        emails = list_emails(folder)
    except HimalayaError as exc:
        click.echo(f"himalaya error: {exc}", err=True)
        sys.exit(1)

    email = next((e for e in emails if e.id == email_id), None)
    if email is None:
        click.echo(f"Email {email_id} not found in {folder}.", err=True)
        sys.exit(1)

    from kontor_cli.rules_engine import RulesEngine

    engine = RulesEngine(cfg)
    result = engine.classify(email)
    nl_context = engine.get_nl_context()

    from kontor_cli.folders import get_target_for_email

    target = get_target_for_email(
        email.date,
        result,
        archive_age_months=cfg.pipeline_archive_months,
    )

    if recommend:
        import json

        payload = {
            "email": {
                "id": email.id,
                "from": email.from_addr,
                "subject": email.subject,
                "date": email.date.isoformat(),
                "flags": email.flags,
                "folder": email.folder,
            },
            "rules_based_target": target,
            "rules_match": result is not None,
            "nl_context": nl_context,
            "archive_age_months": cfg.pipeline_archive_months,
            "taxonomy": {
                "0_Action": "Requires immediate action from you",
                "1_Management/MGT_<Topic>": "Management topics: reporting, HR, legal, compliance",
                "2_Projects/PRJ_<Domain>_<Initiative>_<Scope>": "Project work: specs, status updates, reviews",
                "3_External/EXT_<Company>_<Topic>": "External parties: vendors, partners, clients",
                "4_Info": "Informational only: newsletters, announcements",
                "9_System": "System emails: CI/CD, security alerts, infra",
                "Archive/<same_path>": "Emails >6 months old",
            },
        }
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(target)


@cli.command("process")
@click.option(
    "--phase",
    "phase",
    required=True,
    type=click.Choice(["rebuild", "realtime", "heal"]),
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would be done without making changes"
)
@click.option(
    "--rules-freeze", is_flag=True, help="Snapshot evolved rules before running heal"
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, path_type=Path),
    default=None,
)
def process(
    phase: str,
    dry_run: bool,
    rules_freeze: bool,
    config_path: Path | None,
) -> None:
    """Run a pipeline phase: rebuild, realtime, or heal."""
    try:
        cfg = Config.load(config_path)
    except ConfigError as exc:
        click.echo(f"Config error: {exc}", err=True)
        sys.exit(1)

    # Determine project root (where config.yaml lives)
    root = (config_path or Path.cwd() / "config.yaml").parent

    if phase == "rebuild":
        pipeline = RebuildPipeline(cfg, cwd=root)
        result = pipeline.run(dry_run=dry_run)
    elif phase == "realtime":
        pipeline = RealtimePipeline(cfg, cwd=root)
        result = pipeline.run(dry_run=dry_run)
    elif phase == "heal":
        if rules_freeze:
            _rules_freeze(cfg, root)
        pipeline = HealPipeline(cfg, cwd=root)
        result = pipeline.run(dry_run=dry_run)
    else:
        click.echo(f"Unknown phase: {phase}", err=True)
        sys.exit(1)

    click.echo(f"Phase '{phase}' complete: {result}")


@cli.command("dry-run")
@click.option(
    "--phase", required=True, type=click.Choice(["rebuild", "realtime", "heal"])
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, path_type=Path),
    default=None,
)
def dry_run(phase: str, config_path: Path | None) -> None:
    """Show what would be done without making changes. Alias for process --phase X --dry-run."""
    ctx = click.get_current_context()
    ctx.invoke(
        process, phase=phase, dry_run=True, rules_freeze=False, config_path=config_path
    )


@cli.command("rules-freeze")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, path_type=Path),
    default=None,
)
def rules_freeze_cmd(config_path: Path | None) -> None:
    """Snapshot the current evolved rules state before a heal run."""
    try:
        cfg = Config.load(config_path)
    except ConfigError as exc:
        click.echo(f"Config error: {exc}", err=True)
        sys.exit(1)
    root = (config_path or Path.cwd() / "config.yaml").parent
    _rules_freeze(cfg, root)


def _rules_freeze(cfg: Config, root: Path) -> None:
    """Write a frozen snapshot of the evolved rules directory."""
    import json
    from datetime import datetime

    evolved_dir = Path(cfg.rules_evolved_dir)
    if not evolved_dir.exists():
        click.echo("No evolved rules to freeze.")
        return

    files = sorted(evolved_dir.glob("*.json"))
    snapshot = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "files": [{"name": f.name, "size": f.stat().st_size} for f in files],
    }

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    snapshot_file = evolved_dir / f"snapshot_{timestamp}.json"
    try:
        with open(snapshot_file, "w") as fh:
            json.dump(snapshot, fh, indent=2)
        click.echo(
            f"Frozen snapshot written: {snapshot_file.name} ({len(files)} rule files)"
        )
    except OSError as exc:
        click.echo(f"Failed to write snapshot: {exc}", err=True)
        sys.exit(1)


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
