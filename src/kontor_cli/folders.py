"""Folder taxonomy model and the folder policy for kontor-cli.

The folder policy is the single place that decides where an email lands:
taxonomy default for unclassified emails, and age-based archive enforcement
(the operational arm of ADR-0001 move-only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dateutil.relativedelta import relativedelta


class FolderInvariantError(ValueError):
    """Raised when a folder name violates the taxonomy."""


# Valid root-level folder prefixes
VALID_ROOT_PREFIXES = (
    "0_Action",
    "1_Management",
    "2_Projects",
    "3_External",
    "4_Info",
    "9_System",
    "Archive",
    "Drafts",
    "Sent",
    "Trash",
)

# Valid sub-prefixes by parent
VALID_SUB_PREFIXES: dict[str, tuple[str, ...]] = {
    "1_Management": ("MGT_",),
    "2_Projects": ("PRJ_",),
    "3_External": ("EXT_",),
    "Archive": (
        "0_Action",
        "1_Management",
        "2_Projects",
        "3_External",
        "4_Info",
        "9_System",
    ),
}

ARCHIVE_ROOT = "Archive"


def is_valid_folder(folder_name: str) -> bool:
    """Return True if folder_name conforms to the taxonomy rules."""
    if not folder_name or folder_name.startswith("."):
        return False
    if "/" in folder_name:
        parts = folder_name.split("/", 1)
        parent, child = parts[0], parts[1]
    else:
        parent, child = folder_name, ""

    # Root folder must have valid prefix
    root_valid: bool = any(parent.startswith(p) for p in VALID_ROOT_PREFIXES)
    if not root_valid:
        return False

    # Check sub-folder prefixes
    if child:
        valid_subs = VALID_SUB_PREFIXES.get(parent, ())
        child_valid: bool = any(child.startswith(s) for s in valid_subs)
        if not child_valid:
            return False
    return True


def validate_folder(folder_name: str) -> None:
    """Raise FolderInvariantError if folder_name violates taxonomy."""
    if not is_valid_folder(folder_name):
        raise FolderInvariantError(
            f"Invalid folder name: {folder_name!r}. "
            f"Must follow taxonomy: 0_Action, 1_Management/MGT_*, "
            f"2_Projects/PRJ_*, 3_External/EXT_*, 4_Info, 9_System, Archive/*"
        )


def get_archive_path(folder: str) -> str:
    """Return the Archive mirror path for a given folder."""
    if folder.startswith(ARCHIVE_ROOT + "/"):
        return folder  # already in archive
    return f"{ARCHIVE_ROOT}/{folder}"


@dataclass(frozen=True, slots=True)
class FolderPolicy:
    """The folder decision: where does an email land, given its classification.

    Owns the taxonomy default (unclassified emails land in 4_Info, and are
    never archive-enforced) and archive enforcement (classified emails older
    than archive_age_months are redirected to their Archive mirror path).
    """

    archive_age_months: int = 6

    def target_for(self, email_date: datetime, classified_folder: str | None) -> str:
        """Return the final target folder for an email."""
        if classified_folder is None:
            return "4_Info"

        if (
            classified_folder.startswith(ARCHIVE_ROOT + "/")
            or classified_folder == ARCHIVE_ROOT
        ):
            return classified_folder

        threshold = datetime.now(email_date.tzinfo) - relativedelta(
            months=self.archive_age_months
        )
        if email_date < threshold:
            return get_archive_path(classified_folder)

        return classified_folder
