"""Unit tests for AsanaClient."""

from __future__ import annotations

from unittest import mock

import httpx
import pytest

from kontor_cli.asana_client import AsanaClient, AsanaError

PAT = "test-pat-token"
WORKSPACE_GID = "ws-123"
PROJECT_GIDS = {"bugs": "proj-bugs-456", "features": "proj-features-789"}


def _make_client() -> AsanaClient:
    return AsanaClient(
        pat=PAT,
        workspace_gid=WORKSPACE_GID,
        project_gids=PROJECT_GIDS,
        timeout=10,
    )


def _mock_response(json_data: object, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = mock.MagicMock()
    resp.status_code = status_code
    return resp


# ---------------------------------------------------------------------------
# validate_projects
# ---------------------------------------------------------------------------


def test_validate_projects_all_exist_passes() -> None:
    client = _make_client()
    ok = _mock_response({"data": {"gid": "proj-bugs-456", "name": "Bugs"}})

    with mock.patch("httpx.get", return_value=ok) as mock_get:
        client.validate_projects()  # should not raise

    # Called once per project gid
    assert mock_get.call_count == len(PROJECT_GIDS)


def test_validate_projects_missing_gid_raises_asana_error() -> None:
    client = _make_client()

    status_err = httpx.HTTPStatusError(
        "404",
        request=mock.MagicMock(),
        response=mock.MagicMock(status_code=404),
    )
    err_resp = _mock_response({}, status_code=404)
    err_resp.raise_for_status.side_effect = status_err

    with mock.patch("httpx.get", return_value=err_resp):
        with pytest.raises(AsanaError, match="proj-"):
            client.validate_projects()


def test_validate_projects_invalid_pat_raises_asana_error() -> None:
    client = _make_client()
    status_err = httpx.HTTPStatusError(
        "401",
        request=mock.MagicMock(),
        response=mock.MagicMock(status_code=401),
    )
    err_resp = _mock_response({}, status_code=401)
    err_resp.raise_for_status.side_effect = status_err

    with mock.patch("httpx.get", return_value=err_resp):
        with pytest.raises(AsanaError, match="HTTP 401"):
            client.validate_projects()


def test_validate_projects_fails_on_later_configured_gid() -> None:
    client = _make_client()
    ok = _mock_response({"data": {"gid": "proj-bugs-456"}})
    status_err = httpx.HTTPStatusError(
        "404",
        request=mock.MagicMock(),
        response=mock.MagicMock(status_code=404),
    )
    missing = _mock_response({}, status_code=404)
    missing.raise_for_status.side_effect = status_err

    with mock.patch("httpx.get", side_effect=[ok, missing]) as mock_get:
        with pytest.raises(AsanaError, match="proj-features-789"):
            client.validate_projects()

    assert mock_get.call_count == 2


def test_validate_never_posts_to_projects_endpoint() -> None:
    """validate_projects must never POST (i.e., never create a project)."""
    client = _make_client()
    ok = _mock_response({"data": {"gid": "proj-bugs-456", "name": "Bugs"}})

    with mock.patch("httpx.get", return_value=ok):
        with mock.patch("httpx.post") as mock_post:
            client.validate_projects()

    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# find_task_by_marker
# ---------------------------------------------------------------------------


def test_find_task_by_marker_found_returns_true() -> None:
    client = _make_client()
    marker = "TICKET-42"
    page = _mock_response(
        {
            "data": [
                {"gid": "t1", "notes": f"Some notes with {marker} embedded"},
            ],
            "next_page": None,
        }
    )

    with mock.patch("httpx.get", return_value=page):
        found = client.find_task_by_marker("proj-bugs-456", marker)

    assert found is True


def test_find_task_by_marker_not_found_returns_false() -> None:
    client = _make_client()
    page = _mock_response(
        {
            "data": [
                {"gid": "t1", "notes": "Unrelated task"},
            ],
            "next_page": None,
        }
    )

    with mock.patch("httpx.get", return_value=page):
        found = client.find_task_by_marker("proj-bugs-456", "TICKET-99")

    assert found is False


def test_find_task_by_marker_paginates() -> None:
    """First page has a next_page offset; marker appears only on second page."""
    client = _make_client()
    marker = "TICKET-77"

    page1 = _mock_response(
        {
            "data": [{"gid": "t1", "notes": "nothing here"}],
            "next_page": {"offset": "eyJsaW1pdCI6MjV9"},
        }
    )
    page2 = _mock_response(
        {
            "data": [{"gid": "t2", "notes": f"contains {marker} here"}],
            "next_page": None,
        }
    )

    with mock.patch("httpx.get", side_effect=[page1, page2]):
        found = client.find_task_by_marker("proj-bugs-456", marker)

    assert found is True


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------


def test_create_task_posts_expected_payload() -> None:
    client = _make_client()
    project_gid = "proj-bugs-456"
    name = "Bug: something broke"
    notes = "Details about the bug"
    due_on = "2026-07-15"

    created = {"gid": "task-new-999", "name": name}
    resp = _mock_response({"data": created})

    with mock.patch("httpx.post", return_value=resp) as mock_post:
        result = client.create_task(project_gid, name, notes, due_on)

    assert result == created

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    data = payload["data"]
    assert data["name"] == name
    assert data["notes"] == notes
    assert data["due_on"] == due_on
    assert project_gid in data["projects"]
    assert data["workspace"] == WORKSPACE_GID


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_asana_http_error_raises_asana_error() -> None:
    client = _make_client()

    status_err = httpx.HTTPStatusError(
        "403 Forbidden",
        request=mock.MagicMock(),
        response=mock.MagicMock(status_code=403),
    )
    err_resp = _mock_response({}, status_code=403)
    err_resp.raise_for_status.side_effect = status_err

    with mock.patch("httpx.get", return_value=err_resp):
        with pytest.raises(AsanaError):
            client.find_task_by_marker("proj-bugs-456", "TICKET-1")


def test_asana_request_error_raises_asana_error() -> None:
    client = _make_client()

    with mock.patch(
        "httpx.get",
        side_effect=httpx.RequestError("connection refused", request=mock.MagicMock()),
    ):
        with pytest.raises(AsanaError):
            client.find_task_by_marker("proj-bugs-456", "TICKET-1")
