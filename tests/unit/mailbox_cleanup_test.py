"""Unit tests for kontor_cli.mailbox_cleanup."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from kontor_cli.himalaya import Email
from kontor_cli.mailbox_cleanup import (
    plan_archive_project_cleanup,
    restore_archive_projects,
)


class TestPlanArchiveProjectCleanup:
    def test_plans_live_matches_and_orphans(self) -> None:
        plans = plan_archive_project_cleanup(
            [
                "INBOX",
                "2_Projects/Augment",
                "2_Projects/Zeppelin",
                "Archive/2_Projects/Augment",
                "Archive/2_Projects/AI",
            ]
        )

        assert [plan.archive_folder for plan in plans] == [
            "Archive/2_Projects/AI",
            "Archive/2_Projects/Augment",
        ]
        assert plans[0].live_folder == "2_Projects/AI"
        assert not plans[0].live_exists
        assert plans[1].live_folder == "2_Projects/Augment"
        assert plans[1].live_exists


class TestRestoreArchiveProjects:
    def test_moves_matching_live_and_deletes_empty_orphans(self) -> None:
        email = Email(
            id="42",
            from_addr="a@example.com",
            subject="Restorable",
            date=datetime(2024, 1, 1, tzinfo=UTC),
            flags={},
            folder="Archive/2_Projects/Augment",
        )

        with (
            mock.patch(
                "kontor_cli.mailbox_cleanup.list_folders",
                return_value=[
                    "INBOX",
                    "2_Projects/Augment",
                    "Archive/2_Projects",
                    "Archive/2_Projects/Augment",
                    "Archive/2_Projects/AI",
                ],
            ),
            mock.patch(
                "kontor_cli.mailbox_cleanup.list_emails",
                side_effect=lambda folder, cwd=None: (
                    [email] if folder == "Archive/2_Projects/Augment" else []
                ),
            ),
            mock.patch("kontor_cli.mailbox_cleanup.move_email") as move,
            mock.patch("kontor_cli.mailbox_cleanup.delete_folder") as delete,
        ):
            report = restore_archive_projects(cwd=Path("/tmp/project"))

        move.assert_called_once_with(
            "42",
            "Archive/2_Projects/Augment",
            "2_Projects/Augment",
            cwd=Path("/tmp/project"),
        )
        delete.assert_called_once_with(
            "Archive/2_Projects/AI", cwd=Path("/tmp/project")
        )
        assert report["inbox_exists"] is True
        assert report["archive_root_exists"] is True
        assert report["moved_messages"] == 1
        assert report["deleted_empty_orphans"] == 1
        assert report["skipped_nonempty_orphans"] == 0

    def test_skips_nonempty_orphan_without_creating_live_folder(self) -> None:
        orphan_email = Email(
            id="99",
            from_addr="a@example.com",
            subject="Orphan",
            date=datetime(2024, 1, 1, tzinfo=UTC),
            flags={},
            folder="Archive/2_Projects/AI",
        )

        with (
            mock.patch(
                "kontor_cli.mailbox_cleanup.list_folders",
                return_value=["INBOX", "Archive/2_Projects/AI"],
            ),
            mock.patch(
                "kontor_cli.mailbox_cleanup.list_emails",
                return_value=[orphan_email],
            ),
            mock.patch("kontor_cli.mailbox_cleanup.move_email") as move,
            mock.patch("kontor_cli.mailbox_cleanup.delete_folder") as delete,
        ):
            report = restore_archive_projects(dry_run=True)

        move.assert_not_called()
        delete.assert_not_called()
        assert report["moved_messages"] == 0
        assert report["deleted_empty_orphans"] == 0
        assert report["skipped_nonempty_orphans"] == 1
        assert report["folders"] == [
            {
                "archive_folder": "Archive/2_Projects/AI",
                "live_folder": "2_Projects/AI",
                "live_exists": False,
                "message_count": 1,
                "action": "skipped_nonempty_orphan",
            }
        ]
