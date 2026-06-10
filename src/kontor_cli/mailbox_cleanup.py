"""Operational mailbox cleanup helpers for archive project folders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kontor_cli.himalaya import delete_folder, list_emails, list_folders, move_email

ARCHIVE_PROJECT_PREFIX = "Archive/2_Projects/"
ARCHIVE_PREFIX = "Archive/"


@dataclass(frozen=True)
class ArchiveProjectPlan:
    """One archive project folder and its live-folder relationship."""

    archive_folder: str
    live_folder: str
    live_exists: bool


def live_folder_for_archive(archive_folder: str) -> str:
    """Map an Archive/2_Projects/* folder back to its live 2_Projects/* mirror."""
    if not archive_folder.startswith(ARCHIVE_PROJECT_PREFIX):
        raise ValueError(
            f"Expected archive project folder under {ARCHIVE_PROJECT_PREFIX!r}, "
            f"got {archive_folder!r}"
        )
    return archive_folder.removeprefix(ARCHIVE_PREFIX)


def plan_archive_project_cleanup(folder_names: list[str]) -> list[ArchiveProjectPlan]:
    """Plan restore/cleanup actions for Archive/2_Projects/* folders."""
    live_folders = set(folder_names)
    archive_folders = sorted(
        folder for folder in folder_names if folder.startswith(ARCHIVE_PROJECT_PREFIX)
    )
    return [
        ArchiveProjectPlan(
            archive_folder=archive_folder,
            live_folder=live_folder_for_archive(archive_folder),
            live_exists=live_folder_for_archive(archive_folder) in live_folders,
        )
        for archive_folder in archive_folders
    ]


def restore_archive_projects(
    dry_run: bool = False, cwd: Path | None = None
) -> dict[str, Any]:
    """Move archive project emails back to live folders and prune empty orphans."""
    folder_names = list_folders(cwd=cwd)
    plans = plan_archive_project_cleanup(folder_names)

    moved_messages = 0
    deleted_empty_orphans = 0
    skipped_nonempty_orphans = 0
    folder_results: list[dict[str, Any]] = []

    for plan in plans:
        emails = list_emails(plan.archive_folder, cwd=cwd)
        message_count = len(emails)

        if plan.live_exists:
            action = "empty_matching_live"
            if message_count:
                action = "would_move" if dry_run else "moved"
                if not dry_run:
                    for email in emails:
                        move_email(
                            email.id,
                            plan.archive_folder,
                            plan.live_folder,
                            cwd=cwd,
                        )
                moved_messages += message_count
        elif message_count == 0:
            action = "would_delete_empty_orphan" if dry_run else "deleted_empty_orphan"
            if not dry_run:
                delete_folder(plan.archive_folder, cwd=cwd)
            deleted_empty_orphans += 1
        else:
            action = "skipped_nonempty_orphan"
            skipped_nonempty_orphans += 1

        folder_results.append(
            {
                "archive_folder": plan.archive_folder,
                "live_folder": plan.live_folder,
                "live_exists": plan.live_exists,
                "message_count": message_count,
                "action": action,
            }
        )

    return {
        "inbox_exists": "INBOX" in folder_names,
        "archive_root_exists": "Archive/2_Projects" in folder_names,
        "total_archive_project_folders": len(plans),
        "moved_messages": moved_messages,
        "deleted_empty_orphans": deleted_empty_orphans,
        "skipped_nonempty_orphans": skipped_nonempty_orphans,
        "folders": folder_results,
    }
