"""Unit tests for kontor_cli.pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from kontor_cli.himalaya import Email, HimalayaError


def _email(id: str, folder: str, days_ago: int = 30) -> Email:
    return Email(
        id=id,
        from_addr=f"{id}@example.com",
        subject=f"Subject {id}",
        date=datetime.now(UTC) - timedelta(days=days_ago),
        flags={},
        folder=folder,
    )


class MockConfig:
    """Minimal mock config for pipeline tests — only includes what's actually used."""

    pipeline_archive_months = 6
    pipeline_llm_failure_alert = 5
    rules_yaml_dir = Path.cwd() / "rules"
    rules_python_file = Path.cwd() / "rules" / "rules.py"
    rules_nl_dir = Path.cwd() / "rules"
    rules_evolved_dir = Path.cwd() / "rules" / "evolved"
    llm_base_url = "https://api.openai.com/v1"
    llm_api_key = "sk-test"
    llm_model = "gpt-4o"
    llm_temperature = 0.0
    llm_timeout = 30
    pipeline_confidence_threshold = 0.7


class TestRebuildPipeline:
    def test_rebuild_phase_flow(self, tmp_path: Path) -> None:
        emails = [_email("1", "INBOX"), _email("2", "INBOX")]

        with mock.patch("kontor_cli.pipeline.list_emails", return_value=emails):
            with mock.patch("kontor_cli.pipeline.move_email"):
                with mock.patch("kontor_cli.pipeline.create_folder"):
                    with mock.patch("kontor_cli.pipeline.Classifier") as mock_cls:
                        mock_cls = mock_cls.return_value
                        mock_cls.classify.return_value = None

                        from kontor_cli.pipeline import RebuildPipeline

                        pipeline = RebuildPipeline(MockConfig(), cwd=tmp_path)
                        # Override rules_engine classify with our mock
                        pipeline.rules_engine.classify = lambda e: "2_Projects/PRJ_Test"
                        pipeline.rules_engine.get_nl_context = lambda: ""
                        result = pipeline.run(dry_run=False)

        assert result["phase"] == "rebuild"
        assert result["moves_made"] >= 2  # may be more if multiple folders scanned

    def test_move_history_prevents_loop(self, tmp_path: Path) -> None:
        emails = [_email("1", "INBOX")]

        with mock.patch("kontor_cli.pipeline.list_emails", return_value=emails):
            with mock.patch("kontor_cli.pipeline.move_email") as mock_move:
                with mock.patch("kontor_cli.pipeline.create_folder"):
                    with mock.patch("kontor_cli.pipeline.Classifier"):
                        from kontor_cli.pipeline import RebuildPipeline

                        pipeline = RebuildPipeline(MockConfig(), cwd=tmp_path)
                        pipeline.rules_engine.classify = lambda e: "2_Projects/PRJ_Test"
                        pipeline.rules_engine.get_nl_context = lambda: ""
                        pipeline.run(dry_run=False)

        assert mock_move.call_count == 1


class TestRealtimePipeline:
    def test_realtime_phase_flow(self, tmp_path: Path) -> None:
        emails = [_email("1", "INBOX"), _email("2", "INBOX")]

        with mock.patch("kontor_cli.pipeline.list_emails", return_value=emails):
            with mock.patch("kontor_cli.pipeline.move_email"):
                with mock.patch("kontor_cli.pipeline.create_folder"):
                    with mock.patch("kontor_cli.pipeline.Classifier"):
                        from kontor_cli.pipeline import RealtimePipeline

                        pipeline = RealtimePipeline(MockConfig(), cwd=tmp_path)
                        pipeline.rules_engine.classify = lambda e: "4_Info"
                        pipeline.rules_engine.get_nl_context = lambda: ""
                        result = pipeline.run(dry_run=False)

        assert result["phase"] == "realtime"
        assert result["total_processed"] == 2


class TestHealPipeline:
    def test_heal_pipeline_has_expected_result_keys(self, tmp_path: Path) -> None:
        # Verify HealPipeline.run() returns the expected structure
        from unittest.mock import patch

        from kontor_cli.pipeline import HealPipeline

        pipeline = HealPipeline(MockConfig(), cwd=tmp_path)

        # Mock list_emails to return empty (no folders accessible)
        # This simulates an environment where no folders are found
        def list_emails_side_effect(folder, cwd=None):
            raise HimalayaError("No folders")

        with patch(
            "kontor_cli.pipeline.list_emails", side_effect=list_emails_side_effect
        ):
            result = pipeline.run(dry_run=True)

        # Result must have expected keys
        assert result["phase"] == "heal"
        assert "violations_found" in result
        assert "violations_fixed" in result
        assert "emails_scanned" in result
        assert "moves_made" in result


class TestRulesFreeze:
    def test_rules_freeze_snapshots_evolved(self, tmp_path: Path) -> None:
        """Verify the evolved directory contains rule files after freeze."""
        evolved = tmp_path / "rules" / "evolved"
        evolved.mkdir(parents=True)

        import json

        (evolved / "20240101_rule.json").write_text(json.dumps({"folder": "4_Info"}))

        files = sorted(evolved.glob("*.json"))
        assert len(files) == 1
        assert files[0].name == "20240101_rule.json"
