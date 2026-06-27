"""Unit tests for kontor_cli.folders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kontor_cli.folders import (
    FolderInvariantError,
    FolderPolicy,
    get_archive_path,
    is_valid_folder,
    validate_folder,
)


class TestIsValidFolder:
    def test_valid_root_folders(self) -> None:
        assert is_valid_folder("0_Action")
        assert is_valid_folder("1_Management")
        assert is_valid_folder("2_Projects")
        assert is_valid_folder("3_External")
        assert is_valid_folder("4_Info")
        assert is_valid_folder("9_System")
        assert is_valid_folder("Archive")

    def test_valid_sub_folders(self) -> None:
        assert is_valid_folder("1_Management/MGT_HR")
        assert is_valid_folder("2_Projects/PRJ_Finance_ERP_Global")
        assert is_valid_folder("3_External/EXT_Vendor_Service")
        assert is_valid_folder("Archive/2_Projects")
        assert is_valid_folder("Archive/0_Action")

    def test_live_exchange_subfolders_without_taxonomy_prefix_are_valid(self) -> None:
        assert is_valid_folder("1_Management/AI")
        assert is_valid_folder("2_Projects/Augment")

    def test_invalid_folder_prefix(self) -> None:
        assert not is_valid_folder("5_Other")
        assert not is_valid_folder("Random_Folder")
        assert not is_valid_folder("")
        assert not is_valid_folder(".hidden")


class TestValidateFolder:
    def test_validate_valid(self) -> None:
        validate_folder("2_Projects/PRJ_Finance")  # should not raise

    def test_validate_invalid_raises(self) -> None:
        with pytest.raises(FolderInvariantError):
            validate_folder("5_Other")


class TestArchivePath:
    def test_archive_mirror_path(self) -> None:
        assert get_archive_path("0_Action") == "Archive/0_Action"
        assert get_archive_path("1_Management/MGT_HR") == "Archive/1_Management/MGT_HR"
        assert (
            get_archive_path("Archive/2_Projects") == "Archive/2_Projects"
        )  # no double-wrap


class TestFolderPolicy:
    policy = FolderPolicy(archive_age_months=6)

    def test_recent_classified_email_keeps_its_folder(self) -> None:
        recent = datetime.now(UTC) - timedelta(days=30)
        assert (
            self.policy.target_for(recent, "2_Projects/PRJ_Test")
            == "2_Projects/PRJ_Test"
        )

    def test_unclassified_email_defaults_to_4_info(self) -> None:
        recent = datetime.now(UTC) - timedelta(days=30)
        assert self.policy.target_for(recent, None) == "4_Info"

    def test_old_email_is_archive_enforced(self) -> None:
        old = datetime(2020, 1, 1, tzinfo=UTC)
        assert (
            self.policy.target_for(old, "2_Projects/PRJ_Test")
            == "Archive/2_Projects/PRJ_Test"
        )

    def test_email_already_in_archive_stays(self) -> None:
        old = datetime(2020, 1, 1, tzinfo=UTC)
        assert (
            self.policy.target_for(old, "Archive/2_Projects/PRJ_Test")
            == "Archive/2_Projects/PRJ_Test"
        )

    def test_archive_root_itself_stays(self) -> None:
        old = datetime(2020, 1, 1, tzinfo=UTC)
        assert self.policy.target_for(old, "Archive") == "Archive"

    def test_old_unclassified_email_is_never_archive_enforced(self) -> None:
        # Pinned: archive enforcement only applies to classified emails.
        # An old email without a classification stays in live 4_Info.
        old = datetime(2020, 1, 1, tzinfo=UTC)
        assert self.policy.target_for(old, None) == "4_Info"

    def test_archive_age_months_is_configurable(self) -> None:
        two_months_old = datetime.now(UTC) - timedelta(days=62)
        assert (
            FolderPolicy(archive_age_months=1).target_for(two_months_old, "4_Info")
            == "Archive/4_Info"
        )
        assert (
            FolderPolicy(archive_age_months=6).target_for(two_months_old, "4_Info")
            == "4_Info"
        )

    def test_default_archive_age_is_6_months(self) -> None:
        assert FolderPolicy() == FolderPolicy(archive_age_months=6)
