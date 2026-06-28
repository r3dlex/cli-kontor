"""CLI entry point for kontor-cli."""

from __future__ import annotations

import logging
import sys
from datetime import UTC, date
from pathlib import Path
from typing import Any

import click

from kontor_cli.config import (
    Config,
    ConfigError,
    DavMailNotReachableError,
    HimalayaNotFoundError,
)
from kontor_cli.himalaya import list_emails
from kontor_cli.logging_config import configure_logging
from kontor_cli.mailbox_cleanup import restore_archive_projects
from kontor_cli.pipeline import (
    HealPipeline,
    Pipeline,
    RealtimePipeline,
    RebuildPipeline,
)
from kontor_cli.rules import nl_rules
from kontor_cli.triage import CategoryDecision, Triage

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

    pipeline = Pipeline(cfg)
    result = pipeline.classify_with_rules(email)
    nl_context = nl_rules.nl_rules_context(pipeline.nl_rules)

    from kontor_cli.folders import FolderPolicy

    target = FolderPolicy(cfg.pipeline_archive_months).target_for(email.date, result)

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
                "Archive/<same_path>": (
                    f"Emails older than {cfg.pipeline_archive_months} months"
                ),
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

    result: dict[str, Any]
    if phase == "rebuild":
        result = RebuildPipeline(cfg, cwd=root).run(dry_run=dry_run)
    elif phase == "realtime":
        result = RealtimePipeline(cfg, cwd=root).run(dry_run=dry_run)
    elif phase == "heal":
        if rules_freeze:
            _rules_freeze(cfg, root)
        result = HealPipeline(cfg, cwd=root).run(dry_run=dry_run)
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


@cli.command("cleanup-archive-projects")
@click.option(
    "--dry-run", is_flag=True, help="Show what would be done without making changes"
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, path_type=Path),
    default=None,
)
def cleanup_archive_projects(dry_run: bool, config_path: Path | None) -> None:
    """Restore Archive/2_Projects/* mail into live folders and prune empty orphans."""
    try:
        Config.load(config_path)
    except ConfigError as exc:
        click.echo(f"Config error: {exc}", err=True)
        sys.exit(1)

    root = (config_path or Path.cwd() / "config.yaml").parent
    report = restore_archive_projects(dry_run=dry_run, cwd=root)
    click.echo(report)


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


@cli.command("triage")
@click.option("--folder", default="INBOX", help="Source folder (default: INBOX)")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, path_type=Path),
    default=None,
)
def triage_cmd(folder: str, config_path: Path | None) -> None:
    """List qualifying emails for the agent to classify (read-only).

    Surfaces each email that passes the deterministic eligibility gate, along
    with its fetched body, so the agent can read it and pick one of the four
    management-action categories. Creation is the job of ``triage-create``.
    No Asana writes; no mailbox mutation.
    """
    try:
        cfg = Config.load(config_path)
    except ConfigError as exc:
        click.echo(f"Config error: {exc}", err=True)
        sys.exit(1)

    if not cfg.triage_enabled:
        click.echo("Triage is disabled (set triage.enabled: true).", err=True)
        sys.exit(1)

    root = (config_path or Path.cwd() / "config.yaml").parent
    triage = Triage(cfg, cwd=root)

    for candidate in triage.list_candidates(folder):
        sender = f"{candidate.from_name} <{candidate.from_addr}>".strip()
        click.echo(
            f"{candidate.email_id}  from={sender}  subject={candidate.subject}"
            f"  reason={candidate.reason}"
        )
        click.echo(f"  body:\n{candidate.body}\n")


@cli.command("triage-create")
@click.option("--email-id", required=True, help="Email ID from `triage` output")
@click.option(
    "--category",
    required=True,
    type=click.Choice(
        [
            "information_gathering",
            "nudging",
            "being_the_example",
            "taking_decision",
        ]
    ),
    help="Agent-supplied management-action category",
)
@click.option(
    "--deadline",
    default=None,
    help="Optional ISO date (YYYY-MM-DD); falls back to the email date",
)
@click.option("--folder", default="INBOX", help="Source folder (default: INBOX)")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, path_type=Path),
    default=None,
)
@click.option(
    "--dry-run/--no-dry-run",
    default=True,
    help="Preview without writing to Asana (default); --no-dry-run creates the task",
)
def triage_create_cmd(
    email_id: str,
    category: str,
    deadline: str | None,
    folder: str,
    config_path: Path | None,
    dry_run: bool,
) -> None:
    """Create an Asana task for one agent-classified email.

    Looks up the email by id, builds the agent-supplied ``CategoryDecision``,
    and orchestrates an idempotent Asana task. Defaults to a dry-run preview;
    pass ``--no-dry-run`` to perform the real create.
    """
    try:
        cfg = Config.load(config_path)
    except ConfigError as exc:
        click.echo(f"Config error: {exc}", err=True)
        sys.exit(1)

    if not cfg.triage_enabled:
        click.echo("Triage is disabled (set triage.enabled: true).", err=True)
        sys.exit(1)

    root = (config_path or Path.cwd() / "config.yaml").parent
    emails = list_emails(folder, cwd=root)
    email = next((e for e in emails if e.id == email_id), None)
    if email is None:
        click.echo(f"Email {email_id} not found in {folder}.", err=True)
        sys.exit(1)

    parsed_deadline = date.fromisoformat(deadline) if deadline else None
    decision = CategoryDecision(
        category=category,
        deadline=parsed_deadline,
        rationale="agent-supplied",
    )

    triage = Triage(cfg, cwd=root)
    result = triage.create_task_for(email, decision, dry_run=dry_run)
    click.echo(
        f"outcome={result.outcome}  task={result.task_name or '-'}"
        f"  due={result.target_date or '-'}"
    )


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


@cli.command("md-to-docx")
@click.argument(
    "md_files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path)
)
@click.option(
    "--output-dir",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to write .docx files into (default: same dir as each input file).",
)
def md_to_docx_cmd(md_files: tuple[Path, ...], output_dir: Path | None) -> None:
    """Convert CS-intake Markdown templates to .docx files.

    Accepts one or more .md file paths. Each file is converted to a .docx
    placed next to the source file (or in OUTPUT_DIR when given).

    Source provenance: r3dlex/rib-workspace scripts/md_to_docx.py @ 3e3d082
    """
    from kontor_cli.md_to_docx import convert  # noqa: PLC0415

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    for md_file in md_files:
        md_file = Path(md_file)
        if output_dir is not None:
            docx_path = output_dir / md_file.with_suffix(".docx").name
        else:
            docx_path = md_file.with_suffix(".docx")
        try:
            out = convert(md_file, docx_path)
            click.echo(f"wrote {out}")
        except Exception as exc:  # noqa: BLE001
            click.echo(f"error converting {md_file}: {exc}", err=True)
            sys.exit(1)


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
