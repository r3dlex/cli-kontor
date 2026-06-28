"""Asana API client for task lookup and creation."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AsanaError(Exception):
    """Raised on Asana API errors (HTTP or network)."""


class AsanaClient:
    BASE = "https://app.asana.com/api/1.0"

    def __init__(
        self,
        pat: str,
        workspace_gid: str,
        project_gids: dict[str, str],
        timeout: int = 30,
    ) -> None:
        self._pat = pat
        self.workspace_gid = workspace_gid
        self.project_gids = project_gids
        self.timeout = timeout

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._pat}"}

    def validate_projects(self) -> None:
        """GET BASE/projects/<gid> for each project_gid value.

        Raises AsanaError naming any missing or inaccessible project.
        Never POSTs — never creates a project.
        """
        for label, gid in self.project_gids.items():
            url = f"{self.BASE}/projects/{gid}"
            try:
                response = httpx.get(
                    url,
                    headers=self._auth_headers(),
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise AsanaError(
                    f"Project {gid!r} ({label}) is missing or inaccessible: "
                    f"HTTP {exc.response.status_code}"
                ) from exc
            except httpx.RequestError as exc:
                raise AsanaError(
                    f"Network error validating project {gid!r} ({label}): {exc}"
                ) from exc

    def find_task_by_marker(self, project_gid: str, marker: str) -> bool:
        """Search tasks in project for marker substring in notes, with pagination.

        Returns True if `marker` appears in any task's notes field.
        """
        url = f"{self.BASE}/projects/{project_gid}/tasks"
        params: dict[str, str] = {"opt_fields": "notes"}

        while True:
            try:
                response = httpx.get(
                    url,
                    headers=self._auth_headers(),
                    params=params,
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise AsanaError(
                    f"Failed to fetch tasks for project {project_gid!r}: "
                    f"HTTP {exc.response.status_code}"
                ) from exc
            except httpx.RequestError as exc:
                raise AsanaError(
                    f"Network error fetching tasks for project {project_gid!r}: {exc}"
                ) from exc

            data = response.json()
            for task in data.get("data", []):
                notes: str = task.get("notes", "")
                if marker in notes:
                    return True

            next_page = data.get("next_page")
            if not next_page:
                break
            # Follow pagination offset
            params = {"opt_fields": "notes", "offset": next_page["offset"]}

        return False

    def create_task(
        self,
        project_gid: str,
        name: str,
        notes: str,
        due_on: str,
    ) -> dict[str, Any]:
        """POST a new task to Asana.

        Args:
            project_gid: GID of the project to add the task to.
            name: Task title.
            notes: Task body / description.
            due_on: ISO date string 'YYYY-MM-DD'.

        Returns:
            The created task dict (contents of response['data']).

        Raises:
            AsanaError: On HTTP or network errors.
        """
        url = f"{self.BASE}/tasks"
        payload: dict[str, Any] = {
            "data": {
                "name": name,
                "notes": notes,
                "due_on": due_on,
                "projects": [project_gid],
                "workspace": self.workspace_gid,
            }
        }
        try:
            response = httpx.post(
                url,
                headers=self._auth_headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AsanaError(
                f"Failed to create task in project {project_gid!r}: "
                f"HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise AsanaError(
                f"Network error creating task in project {project_gid!r}: {exc}"
            ) from exc

        result: dict[str, Any] = response.json()["data"]
        return result
