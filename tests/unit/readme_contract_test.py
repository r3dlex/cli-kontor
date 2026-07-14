"""Regression contracts for README safety and command-scope claims."""

from pathlib import Path

ROOT = Path(__file__).parents[2]
README = (ROOT / "README.md").read_text()
README_TEXT = " ".join(README.split())


def test_readme_distinguishes_classify_from_process_llm_fallback() -> None:
    assert (
        "`classify` evaluates deterministic YAML and Python rules only" in README_TEXT
    )
    assert "does not call the LLM fallback" in README_TEXT


def test_readme_limits_rebuild_and_heal_to_fixed_scan_folders() -> None:
    assert "`rebuild` and `heal` scan only the fixed `SCAN_FOLDERS` list" in README_TEXT
    assert "do not discover arbitrary valid taxonomy folders" in README_TEXT


def test_evolved_decision_logs_are_ignored_and_documented_as_sensitive() -> None:
    ignored_paths = (ROOT / ".gitignore").read_text().splitlines()

    assert "rules/evolved/" in ignored_paths
    assert "email ID, subject, and sender" in README_TEXT
    assert "treat these files as sensitive" in README_TEXT
    assert "delete them locally when that review or audit need ends" in README_TEXT


def test_readme_discloses_process_llm_metadata_and_local_triage_bodies() -> None:
    assert "Even during a process dry run" in README_TEXT
    assert (
        "fallback classification sends the email's sender, subject, and date to the "
        "configured LLM" in README_TEXT
    )
    assert "`triage` reads candidate bodies locally" in README_TEXT
    assert "it does not call the configured LLM or write to Asana" in README_TEXT
    assert "Only `triage-create --no-dry-run` can write an Asana task" in README_TEXT
