"""himalaya CLI wrapper for kontor-cli.

Uses `himalaya envelope list` (JSON) to enumerate emails, and
`himalaya message copy` to move them. Deletion raises DeleteNotSupportedError.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PAGE_SIZE = 50


class HimalayaError(Exception):
    """Raised when a himalaya command fails."""


class DeleteNotSupportedError(HimalayaError):
    """Raised when delete_email is called — deletion is not permitted."""


@dataclass
class Email:
    """Parsed email from himalaya JSON envelope output."""

    id: str
    from_addr: str
    subject: str
    date: datetime
    flags: dict[str, bool]
    folder: str
    from_name: str = ""

    @classmethod
    def from_json(cls, obj: dict[str, Any], folder: str) -> Email:
        """Parse from a himalaya envelope JSON dict."""
        from_field = obj.get("from", {})
        if isinstance(from_field, dict):
            addr = from_field.get("addr", from_field.get("address", ""))
            name = from_field.get("name", "")
        else:
            addr = str(from_field)
            name = ""
        if not isinstance(addr, str):
            addr = str(addr)
        if not isinstance(name, str):
            name = str(name)
        date_str = obj.get("date", "")
        try:
            date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            date = datetime.now()
        return cls(
            id=str(obj.get("id", "")),
            from_addr=addr,
            from_name=name,
            subject=obj.get("subject", ""),
            date=date,
            flags=obj.get("flags", {}),
            folder=folder,
        )


def _run(args: list[str], cwd: str | Path | None = None) -> str:
    """Run himalaya with the given args, return stdout. Raises HimalayaError on failure."""
    try:
        result = subprocess.run(
            ["himalaya"] + args,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        )
    except FileNotFoundError:
        raise HimalayaError(
            "himalaya not found in PATH. Install: https://github.com/tobiassjosten/himalaya"
        ) from None
    except subprocess.CalledProcessError as exc:
        raise HimalayaError(
            f"himalaya command failed: {exc.stderr.strip() or exc.stdout.strip()}"
        ) from exc
    return result.stdout


def list_emails(folder: str = "INBOX", cwd: str | Path | None = None) -> list[Email]:
    """List all emails in a folder using pagination. Returns list of Email objects."""
    import time

    all_envelopes = []
    page = 1
    while True:
        output = _run(
            [
                "envelope",
                "list",
                "-f",
                folder,
                "-o",
                "json",
                "--page-size",
                str(PAGE_SIZE),
                "--page",
                str(page),
            ],
            cwd=cwd,
        )
        try:
            envelopes = json.loads(output)
        except json.JSONDecodeError as exc:
            raise HimalayaError(f"himalaya returned invalid JSON: {exc}") from exc
        if not isinstance(envelopes, list):
            raise HimalayaError(
                f"himalaya envelope list returned unexpected type: {type(envelopes)}"
            )
        if not envelopes:
            break
        all_envelopes.extend(envelopes)
        if len(envelopes) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.3)  # Rate limit for Exchange
    return [Email.from_json(e, folder) for e in all_envelopes]


def move_email(
    email_id: str, from_folder: str, to_folder: str, cwd: str | Path | None = None
) -> None:
    """Move an email from one folder to another using himalaya message move."""
    _run(["message", "move", to_folder, email_id, "-f", from_folder], cwd=cwd)


def create_folder(folder_name: str, cwd: str | Path | None = None) -> None:
    """Create a new folder."""
    _run(["folder", "add", folder_name], cwd=cwd)


def list_folders(cwd: str | Path | None = None) -> list[str]:
    """List mailbox folders as folder-name strings."""
    output = _run(["folder", "list", "-o", "json"], cwd=cwd)
    try:
        folders = json.loads(output)
    except json.JSONDecodeError as exc:
        raise HimalayaError(f"himalaya returned invalid JSON: {exc}") from exc
    if not isinstance(folders, list):
        raise HimalayaError(
            f"himalaya folder list returned unexpected type: {type(folders)}"
        )

    names: list[str] = []
    for folder in folders:
        if isinstance(folder, dict):
            name = folder.get("name")
        else:
            name = folder
        if not isinstance(name, str):
            raise HimalayaError(
                f"himalaya folder list returned invalid folder entry: {folder!r}"
            )
        names.append(name)
    return names


def delete_folder(folder_name: str, cwd: str | Path | None = None) -> None:
    """Delete an empty folder."""
    _run(["folder", "delete", folder_name], cwd=cwd)


def read_message_body(
    email_id: str, folder: str = "INBOX", cwd: str | Path | None = None
) -> str:
    """Fetch plaintext body read-only (no seen flag) via himalaya v1.2.0."""
    return _run(
        ["message", "read", email_id, "-f", folder, "--no-headers", "--preview"],
        cwd=cwd,
    )


def read_message_id(
    email_id: str, folder: str = "INBOX", cwd: str | Path | None = None
) -> str | None:
    """Fetch the Message-ID header (stable dedup key); None if absent.

    Issues a separate himalaya call with -H (mutually exclusive with --no-headers).
    Parses the 'Message-Id:' line case-insensitively and strips surrounding <...>.
    """
    out = _run(
        ["message", "read", email_id, "-f", folder, "-H", "Message-Id", "--preview"],
        cwd=cwd,
    )
    for line in out.splitlines():
        if line.lower().startswith("message-id:"):
            value = line.split(":", 1)[1].strip()
            return value.strip("<>")
    return None


def delete_email(email_id: str, folder: str, cwd: str | Path | None = None) -> None:
    """Deletion is not supported — raises DeleteNotSupportedError."""
    raise DeleteNotSupportedError(
        "Email deletion is not supported. Emails must be moved to Archive, not deleted."
    )
