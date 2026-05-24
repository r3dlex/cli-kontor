"""Unit tests for kontor_cli.himalaya."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from kontor_cli.himalaya import (
    DeleteNotSupportedError,
    Email,
    HimalayaError,
    create_folder,
    delete_email,
    list_emails,
    move_email,
)

SAMPLE_ENVELOPES = [
    {
        "id": "1",
        "from": {"address": "alice@example.com", "name": "Alice"},
        "subject": "Hello",
        "date": "2024-01-01T10:00:00Z",
        "flags": {},
    },
    {
        "id": "2",
        "from": {"address": "bob@example.com", "name": "Bob"},
        "subject": "World",
        "date": "2024-01-02T11:00:00Z",
        "flags": {"seen": True},
    },
]


class TestEmailFromJson:
    def test_email_from_json_basic(self) -> None:
        env = {
            "id": "42",
            "from": {"address": "x@y.com"},
            "subject": "Test",
            "date": "2024-06-15T09:00:00Z",
            "flags": {"seen": True},
        }
        email = Email.from_json(env, "INBOX")
        assert email.id == "42"
        assert email.from_addr == "x@y.com"
        assert email.subject == "Test"
        assert email.flags == {"seen": True}
        assert email.folder == "INBOX"

    def test_email_from_json_supports_addr_field(self) -> None:
        env = {
            "id": "43",
            "from": {"addr": "alt@example.com"},
            "subject": "Alt",
            "date": "2024-06-15T09:00:00Z",
            "flags": {},
        }
        email = Email.from_json(env, "INBOX")
        assert email.from_addr == "alt@example.com"


class TestListEmails:
    def test_list_emails_parsed(self) -> None:
        mock_result = mock.MagicMock()
        mock_result.stdout = json.dumps(SAMPLE_ENVELOPES)
        mock_result.returncode = 0

        with mock.patch(
            "kontor_cli.himalaya.subprocess.run", return_value=mock_result
        ) as p:
            emails = list_emails("INBOX")
            p.assert_called_once()
            assert len(emails) == 2
            assert emails[0].id == "1"
            assert emails[0].from_addr == "alice@example.com"
            assert emails[1].id == "2"

    def test_list_emails_invalid_json(self) -> None:
        mock_result = mock.MagicMock()
        mock_result.stdout = "not json"
        mock_result.returncode = 0

        with mock.patch("kontor_cli.himalaya.subprocess.run", return_value=mock_result):
            with pytest.raises(HimalayaError, match="invalid JSON"):
                list_emails("INBOX")

    def test_list_emails_non_list_response(self) -> None:
        mock_result = mock.MagicMock()
        mock_result.stdout = json.dumps({"error": "oops"})
        mock_result.returncode = 0

        with mock.patch("kontor_cli.himalaya.subprocess.run", return_value=mock_result):
            with pytest.raises(HimalayaError, match="unexpected type"):
                list_emails("INBOX")

    def test_himalaya_not_found(self) -> None:
        with mock.patch(
            "kontor_cli.himalaya.subprocess.run", side_effect=FileNotFoundError()
        ):
            with pytest.raises(HimalayaError, match="not found in PATH"):
                list_emails("INBOX")

    def test_list_emails_paginates_until_short_page(self) -> None:
        full_page = [
            {
                "id": str(i),
                "from": {"address": f"user{i}@example.com"},
                "subject": f"Message {i}",
                "date": "2024-01-01T10:00:00Z",
                "flags": {},
            }
            for i in range(50)
        ]
        final_page = [
            {
                "id": "50",
                "from": {"address": "last@example.com"},
                "subject": "Last",
                "date": "2024-01-02T10:00:00Z",
                "flags": {},
            }
        ]
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        page_payloads = [json.dumps(full_page), json.dumps(final_page)]

        def fake_run(*args: object, **kwargs: object) -> mock.MagicMock:
            current = mock.MagicMock()
            current.returncode = 0
            current.stdout = page_payloads.pop(0) if page_payloads else "[]"
            return current

        with (
            mock.patch("kontor_cli.himalaya.subprocess.run", side_effect=fake_run) as p,
            mock.patch("time.sleep"),
        ):
            emails = list_emails("INBOX")

        assert len(emails) == 51
        assert emails[-1].id == "50"
        assert p.call_count == 2
        first_args = p.call_args_list[0].args[0]
        second_args = p.call_args_list[1].args[0]
        assert first_args[-1] == "1"
        assert second_args[-1] == "2"


class TestMoveEmail:
    def test_move_email_command(self) -> None:
        mock_result = mock.MagicMock()
        mock_result.returncode = 0

        with mock.patch(
            "kontor_cli.himalaya.subprocess.run", return_value=mock_result
        ) as p:
            move_email("42", "INBOX", "Archive/INBOX")
            p.assert_called_once()
            args = p.call_args[0][0]
            assert args == [
                "himalaya",
                "message",
                "copy",
                "Archive/INBOX",
                "42",
                "-f",
                "INBOX",
            ]


class TestCreateFolder:
    def test_create_folder_command(self) -> None:
        mock_result = mock.MagicMock()
        mock_result.returncode = 0

        with mock.patch(
            "kontor_cli.himalaya.subprocess.run", return_value=mock_result
        ) as p:
            create_folder("2_Projects/PRJ_Test")
            p.assert_called_once()
            args = p.call_args[0][0]
            assert args == ["himalaya", "folder", "add", "2_Projects/PRJ_Test"]


class TestDeleteEmail:
    def test_delete_email_raises(self) -> None:
        with pytest.raises(DeleteNotSupportedError, match="not supported"):
            delete_email("42", "INBOX")
