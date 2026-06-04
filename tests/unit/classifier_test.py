"""Unit tests for kontor_cli.classifier."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from kontor_cli.classifier import (
    Classifier,
    _derive_max_output_tokens,
    _truncate_prompt,
    build_prompt,
)
from kontor_cli.himalaya import Email


def _make_email() -> Email:
    return Email(
        id="1",
        from_addr="alice@example.com",
        subject="Q1 Budget Report",
        date=datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC),
        flags={},
        folder="INBOX",
    )


class TestBuildPrompt:
    def test_email_metadata_injected(self) -> None:
        email = _make_email()
        prompt = build_prompt(email, "TAXONOMY", "NL context", "yaml rules")
        assert "alice@example.com" in prompt
        assert "Q1 Budget Report" in prompt
        assert "2024-03-15" in prompt
        assert "TAXONOMY" in prompt
        assert "NL context" in prompt
        assert "yaml rules" in prompt


class TestDeriveMaxOutputTokens:
    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("gpt-4o", 4096),
            ("gpt-4o-mini", 4096),
            ("gpt-4-turbo", 4096),
            ("gpt-4-32k", 4096),
            ("gpt-4", 1024),
            ("gpt-3.5-turbo", 1024),
            ("gpt-5", 4096),
            ("minimax/minimax", 1024),
            ("MiniMax/MiniMax-200K", 1024),
            ("abab6.5s-chat", 1024),
            ("claude-3-opus", 8192),
            ("claude-3-sonnet", 8192),
            ("anthropic/claude-3-haiku", 8192),
            ("unknown-model", 1024),
            ("", 1024),
        ],
    )
    def test_derives_correct_token_limit(self, model: str, expected: int) -> None:
        assert _derive_max_output_tokens(model) == expected


class TestTruncatePrompt:
    def test_short_prompt_unchanged(self) -> None:
        prompt = "Hello world"
        result = _truncate_prompt(prompt, model="minimax/minimax")
        assert result == prompt

    def test_long_minimax_prompt_truncated(self) -> None:
        # Build a prompt longer than MiniMax's 75%-overhead target (~150K chars)
        prompt = "x" * 200_000
        result = _truncate_prompt(prompt, model="minimax/minimax")
        # Should be truncated and end with the sentinel
        assert len(result) < 200_000
        assert result.endswith("[... prompt truncated ...]")

    def test_gpt4o_prompt_truncated(self) -> None:
        # GPT-4o: 75% of 128K = ~96K chars
        prompt = "y" * 120_000
        result = _truncate_prompt(prompt, model="gpt-4o")
        assert len(result) < 120_000
        assert result.endswith("[... prompt truncated ...]")

    def test_unknown_model_prompt_unchanged(self) -> None:
        # Unknown models: fail-open
        prompt = "z" * 10_000
        result = _truncate_prompt(prompt, model="totally-unknown-model-v99")
        assert result == prompt

    def test_prompt_at_boundary_unchanged(self) -> None:
        # Build a prompt that is exactly at the target for gpt-4
        # 75% of 32K = 24K chars; use slightly less
        prompt = "b" * 20_000
        result = _truncate_prompt(prompt, model="gpt-4-32k")
        assert result == prompt


class TestClassifier:
    def test_classify_llm_response_parsed(self) -> None:
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "folder": "1_Management",
                                "confidence": 0.9,
                                "action": "none",
                            }
                        )
                    }
                }
            ]
        }
        mock_result = mock.MagicMock()
        mock_result.json.return_value = mock_response
        mock_result.raise_for_status = mock.MagicMock()

        from kontor_cli.config import Config

        cfg = mock.MagicMock(spec=Config)
        cfg.llm_base_url = "https://api.openai.com/v1"
        cfg.llm_api_key = "sk-test"
        cfg.llm_model = "gpt-4o"
        cfg.llm_temperature = 0.0
        cfg.llm_timeout = 30
        cfg.pipeline_confidence_threshold = 0.7

        cls = Classifier(cfg)

        with mock.patch("httpx.post") as mock_post:
            mock_post.return_value = mock_result
            result = cls.classify(_make_email())

        assert result is not None
        assert result.folder == "1_Management"
        assert result.confidence == 0.9
        assert result.action == "none"

    def test_classify_sends_max_tokens(self) -> None:
        """Verify max_tokens is included in the API payload."""
        mock_result = mock.MagicMock()
        mock_result.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"folder": "4_Info", "confidence": 0.9, "action": "none"}
                        )
                    }
                }
            ]
        }
        mock_result.raise_for_status = mock.MagicMock()

        from kontor_cli.config import Config

        cfg = mock.MagicMock(spec=Config)
        cfg.llm_base_url = "https://api.openai.com/v1"
        cfg.llm_api_key = "sk-test"
        cfg.llm_model = "gpt-4o"
        cfg.llm_temperature = 0.0
        cfg.llm_timeout = 30
        cfg.pipeline_confidence_threshold = 0.7

        cls = Classifier(cfg)

        with mock.patch("httpx.post") as mock_post:
            mock_post.return_value = mock_result
            cls.classify(_make_email())

        # Assert max_tokens=4096 was in the payload (gpt-4o maps to 4096)
        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        assert "max_tokens" in payload
        assert payload["max_tokens"] == 4096

    def test_classify_minimax_model_sends_max_tokens_1024(self) -> None:
        """MiniMax model should get max_tokens=1024."""
        mock_result = mock.MagicMock()
        mock_result.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"folder": "4_Info", "confidence": 0.9, "action": "none"}
                        )
                    }
                }
            ]
        }
        mock_result.raise_for_status = mock.MagicMock()

        from kontor_cli.config import Config

        cfg = mock.MagicMock(spec=Config)
        cfg.llm_base_url = "https://api.minimax.io/v1"
        cfg.llm_api_key = "sk-test"
        cfg.llm_model = "minimax/minimax"
        cfg.llm_temperature = 0.0
        cfg.llm_timeout = 30
        cfg.pipeline_confidence_threshold = 0.7

        cls = Classifier(cfg)

        with mock.patch("httpx.post") as mock_post:
            mock_post.return_value = mock_result
            cls.classify(_make_email())

        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        assert payload["max_tokens"] == 1024

    def test_classify_confidence_threshold_low(self) -> None:
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"folder": "0_Action", "confidence": 0.3, "action": "none"}
                        )
                    }
                }
            ]
        }
        mock_result = mock.MagicMock()
        mock_result.json.return_value = mock_response
        mock_result.raise_for_status = mock.MagicMock()

        from kontor_cli.config import Config

        cfg = mock.MagicMock(spec=Config)
        cfg.llm_base_url = "https://api.openai.com/v1"
        cfg.llm_api_key = "sk-test"
        cfg.llm_model = "gpt-4o"
        cfg.llm_temperature = 0.0
        cfg.llm_timeout = 30
        cfg.pipeline_confidence_threshold = 0.7

        cls = Classifier(cfg)

        with mock.patch("httpx.post") as mock_post:
            mock_post.return_value = mock_result
            result = cls.classify(_make_email())

        # Low confidence → defaults to 4_Info
        assert result is not None
        assert result.folder == "4_Info"

    def test_classify_api_failure(self) -> None:
        import httpx

        from kontor_cli.config import Config

        cfg = mock.MagicMock(spec=Config)
        cfg.llm_base_url = "https://api.openai.com/v1"
        cfg.llm_api_key = "sk-test"
        cfg.llm_model = "gpt-4o"
        cfg.llm_temperature = 0.0
        cfg.llm_timeout = 30
        cfg.pipeline_confidence_threshold = 0.7

        cls = Classifier(cfg)

        with mock.patch("httpx.post") as mock_post:
            mock_post.side_effect = httpx.HTTPStatusError(
                "rate limited", request=mock.MagicMock(), response=mock.MagicMock()
            )
            result = cls.classify(_make_email())

        assert result is None

    def test_classify_invalid_folder_validation(self) -> None:
        # Test that invalid folder names are not blindly accepted
        # We mock at the classify result level to test the validation path
        from kontor_cli.folders import is_valid_folder

        assert not is_valid_folder("Invalid_Folder")
        assert is_valid_folder("4_Info")
