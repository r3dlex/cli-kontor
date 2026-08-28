"""Folder taxonomy registry and the folder policy for kontor-cli.

The taxonomy registry is the single home of the folder taxonomy: the valid
folder names (is_valid_folder), the scan scope for the rebuild and heal
phases (scan_folders), and the taxonomy payload the classifier prompt and
the classify --recommend output are built from. The folder policy is the
single place that decides where an email lands: taxonomy default for
unclassified emails, and age-based archive enforcement (the operational arm
of ADR-0001 move-only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from dateutil.relativedelta import relativedelta


class FolderInvariantError(ValueError):
    """Raised when a folder name violates the taxonomy."""


# Live taxonomy roots: the folders the classifier may name as a target and
# the pipeline scans. The Archive mirror and the mail-client folders are
# valid folder names but are never scan targets.
TAXONOMY_ROOTS: tuple[str, ...] = (
    "0_Action",
    "1_Management",
    "2_Projects",
    "3_External",
    "4_Info",
    "9_System",
)

# Valid root-level folder prefixes: the taxonomy roots, the Archive mirror
# root, and the mail-client folders the validator must tolerate.
VALID_ROOT_PREFIXES = TAXONOMY_ROOTS + ("Archive", "Drafts", "Sent", "Trash")

# Valid sub-prefixes by parent
VALID_SUB_PREFIXES: dict[str, tuple[str, ...]] = {
    "1_Management": ("MGT_", "AI", "HR", "Leadership", "1on1"),
    "2_Projects": (
        "PRJ_",
        "Augment",
        "AzureSigning",
        "BoQ",
        "Budimex",
        "China",
        "Development",
        "Eiffage",
        "India",
        "Internal",
        "International",
        "Releases",
        "Sales",
        "Sales_BoQ_Estimate_Procurement",
        "Security",
        "Trivium",
        "Vinci",
        "Willemen",
    ),
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

# Roots that are valid folder names but are never scan targets: the Archive
# mirror and the mail-client folders.
NON_SCAN_ROOTS: frozenset[str] = frozenset({"Archive", "Drafts", "Sent", "Trash"})

# Legacy folders: mailbox folders that still hold unprocessed email but that
# the taxonomy validator rejects — they predate the registry (root level) or
# its naming patterns (pre-EXT_ external folders, pre-taxonomy project
# folders). Retained explicitly as data next to the registry so the derived
# scan scope keeps visiting them until the mailbox migration completes.
LEGACY_SCAN_FOLDERS: tuple[str, ...] = (
    # Root-level folders that predate the taxonomy.
    "Projects",
    "Executive",
    "Admin",
    "Finance",
    "HR",
    "Releases",
    "Security",
    "Travel",
    "Newsletters",
    "Logs",
    "Review",
    "Communication",
    # Pre-taxonomy subfolders of live roots.
    "2_Projects/RIB-4.0/AI",
    "2_Projects/Finance",
    "2_Projects/Infrastructure",
    "3_External/Trivium",
    "3_External/Miro",
    "3_External/GitHub",
    "3_External/Mitarbeiterangebote",
    "3_External/Reportlinker",
    "3_External/CoachHub",
    "3_External/Viseo",
    "3_External/HeroDevs",
    "3_External/Microsoft",
)

# Canonical description per taxonomy entry. This table is the single home of
# the classifier prompt's taxonomy section and the classify --recommend
# taxonomy payload; both are derived from it instead of restating the
# taxonomy by hand.
TAXONOMY_DESCRIPTIONS: dict[str, str] = {
    "0_Action": "Requires immediate action from you. Not a storage folder.",
    "1_Management/MGT_<Topic>": (
        "Management topics: reporting, HR, legal, compliance, meetings, 1:1s."
    ),
    "2_Projects/PRJ_<Domain>_<Initiative>_<Scope>": (
        "Project work: specs, status updates, reviews, kickoffs."
    ),
    "3_External/EXT_<Company>_<Topic>": "External parties: vendors, partners, clients.",
    "4_Info": "Informational only. Newsletters, announcements, system notifications.",
    "9_System": "System emails: password resets, security alerts, CI/CD pipelines, infra.",
    "Archive/<same_path>": (
        "Emails older than 6 months, or already-processed emails from any folder."
    ),
}


def taxonomy_folders() -> tuple[str, ...]:
    """Enumerate the concrete folders the taxonomy registry knows.

    Every taxonomy root plus every concrete subfolder named in
    VALID_SUB_PREFIXES. Prefix families (entries ending in "_", e.g. MGT_)
    name a family of folders rather than one folder, so they are validator
    patterns only and cannot be enumerated. The Archive mirror and the
    mail-client folders are valid folder names but are not scan targets.
    """
    folders = list(TAXONOMY_ROOTS)
    for root, subs in VALID_SUB_PREFIXES.items():
        if root in NON_SCAN_ROOTS:
            continue
        folders.extend(
            f"{root}/{sub}"
            for sub in subs
            if not sub.endswith("_") and is_valid_folder(f"{root}/{sub}")
        )
    return tuple(folders)


def scan_folders() -> tuple[str, ...]:
    """Return the rebuild/heal scan scope, derived from the registry.

    INBOX plus every concrete taxonomy folder the registry enumerates plus
    the retained legacy folders. The Archive mirror and the mail-client
    folders (Drafts, Sent, Trash) are valid folder names but are never
    scanned.
    """
    return ("INBOX",) + taxonomy_folders() + LEGACY_SCAN_FOLDERS


def taxonomy_prompt() -> str:
    """Build the classifier prompt's taxonomy section from the registry."""
    entries = [f"- **{name}** — {desc}" for name, desc in TAXONOMY_DESCRIPTIONS.items()]
    return "\n".join(
        [
            "## Email Folder Taxonomy",
            "",
            "Emails MUST be placed in exactly one of these folders:",
            "",
            *entries,
            "",
            "Folder naming rules:",
            '- Sub-folders use "/" (e.g., "2_Projects/PRJ_Finance_ERP_Global")',
            '- Archive mirrors the exact structure (e.g., "Archive/2_Projects/PRJ_Finance_ERP_Global")',
            "- Never create folders outside this taxonomy.",
        ]
    )


def taxonomy_payload(archive_age_months: int) -> dict[str, str]:
    """Build the classify --recommend taxonomy payload from the registry.

    The Archive entry reflects the configured archive age (the folder policy
    default is 6 months).
    """
    payload = dict(TAXONOMY_DESCRIPTIONS)
    payload["Archive/<same_path>"] = f"Emails older than {archive_age_months} months"
    return payload


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

    # Check sub-folder names. Entries ending in "_" are treated as prefixes
    # (e.g. "MGT_" matches "MGT_HR"); all other entries are exact-match only
    # (e.g. "AI" must not match "AIrport"). Under Archive the child is itself a
    # nested taxonomy path (e.g. "2_Projects/PRJ_Test"), so match its first
    # segment exactly against the known taxonomy roots.
    if child:
        valid_subs = VALID_SUB_PREFIXES.get(parent, ())
        match_target = child.split("/", 1)[0] if parent == ARCHIVE_ROOT else child
        child_valid: bool = any(
            match_target.startswith(s) if s.endswith("_") else match_target == s
            for s in valid_subs
        )
        if not child_valid:
            return False
    return True


def validate_folder(folder_name: str) -> None:
    """Raise FolderInvariantError if folder_name violates taxonomy."""
    if not is_valid_folder(folder_name):
        raise FolderInvariantError(
            f"Invalid folder name: {folder_name!r}. Must follow the taxonomy "
            f"(e.g. 1_Management/MGT_*, 2_Projects/PRJ_*, 3_External/EXT_*, "
            f"0_Action, 4_Info, 9_System, Archive/*) or be one of the known "
            f"live folder names (e.g. 1_Management/AI, 2_Projects/Augment)."
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
