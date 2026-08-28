"""Contract: scan scope is derived from the folders.py taxonomy registry.

The folder taxonomy is single-homed in folders.py. Rebuild and heal must
scan every concrete folder the registry enumerates; a valid registry folder
absent from the scan scope is a correctness gap (the README used to document
it as a limitation).
"""

from kontor_cli import folders
from kontor_cli.classifier import FOLDER_TAXONOMY
from kontor_cli.folders import (
    LEGACY_SCAN_FOLDERS,
    NON_SCAN_ROOTS,
    TAXONOMY_DESCRIPTIONS,
    VALID_ROOT_PREFIXES,
    VALID_SUB_PREFIXES,
    is_valid_folder,
)
from kontor_cli.pipeline import SCAN_FOLDERS

# Mail-client folders and the Archive mirror are valid folder names but are
# never scan targets.
assert NON_SCAN_ROOTS == frozenset({"Archive", "Drafts", "Sent", "Trash"})


def _registry_scan_targets() -> set[str]:
    """Every concrete valid registry folder a rebuild/heal scan must visit."""
    folders_set = {
        f for f in VALID_ROOT_PREFIXES if f not in NON_SCAN_ROOTS and is_valid_folder(f)
    }
    for root, subs in VALID_SUB_PREFIXES.items():
        if root in NON_SCAN_ROOTS:
            continue
        folders_set.update(
            f"{root}/{sub}"
            for sub in subs
            if not sub.endswith("_") and is_valid_folder(f"{root}/{sub}")
        )
    return folders_set


def test_scan_folders_cover_the_registry() -> None:
    """Every registry scan target appears in the pipeline scan scope."""
    missing = _registry_scan_targets() - set(SCAN_FOLDERS)
    assert not missing, f"registry folders missing from SCAN_FOLDERS: {sorted(missing)}"


def test_pipeline_scan_folders_are_the_derived_scope() -> None:
    """pipeline.SCAN_FOLDERS is the registry's derived scan scope."""
    assert SCAN_FOLDERS == folders.scan_folders()


def test_legacy_folders_are_retained_as_data_next_to_the_registry() -> None:
    """Legacy folders live next to the registry and stay in scan scope."""
    assert set(LEGACY_SCAN_FOLDERS) <= set(SCAN_FOLDERS)
    for folder in LEGACY_SCAN_FOLDERS:
        assert not is_valid_folder(folder), folder


def test_classifier_prompt_is_derived_from_the_registry() -> None:
    """The classifier prompt's taxonomy section is the registry's output."""
    assert FOLDER_TAXONOMY == folders.taxonomy_prompt()


def test_recommend_payload_taxonomy_is_derived_from_the_registry() -> None:
    """The classify --recommend payload derives from the same registry."""
    payload = folders.taxonomy_payload(archive_age_months=6)
    assert set(payload) == set(TAXONOMY_DESCRIPTIONS)
    assert payload["0_Action"] == TAXONOMY_DESCRIPTIONS["0_Action"]
    assert payload["Archive/<same_path>"] == "Emails older than 6 months"


def test_adding_a_registry_folder_propagates(monkeypatch) -> None:
    """A folder added to the registry reaches every derived consumer."""
    subs = tuple(VALID_SUB_PREFIXES["1_Management"]) + ("NewTeam",)
    monkeypatch.setitem(VALID_SUB_PREFIXES, "1_Management", subs)
    monkeypatch.setitem(
        TAXONOMY_DESCRIPTIONS, "1_Management/NewTeam", "New team folder."
    )

    assert "1_Management/NewTeam" in folders.scan_folders()
    assert "1_Management/NewTeam" in folders.taxonomy_prompt()
    assert "1_Management/NewTeam" in folders.taxonomy_payload(archive_age_months=6)
