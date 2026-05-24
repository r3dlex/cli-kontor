"""himalaya CLI wrapper for kontor-cli.

Uses `himalaya envelope list` (JSON) to enumerate emails, and
`himalaya message copy` to move them. Deletion raises DeleteNotSupportedError.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any


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

    @classmethod
    def from_json(cls, obj: dict[str, Any], folder: str) -> Email:
        """Parse from a himalaya envelope JSON dict."""
        from_field = obj.get("from", {})
        if isinstance(from_field, dict):
            raw_addr = from_field.get("addr", from_field.get("address", ""))
            addr = str(raw_addr or "")
        else:
            addr = str(from_field)
        date_str = obj.get("date", "")
        try:
            date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            date = datetime.now()
        return cls(
            id=str(obj.get("id", "")),
            from_addr=addr,
            subject=obj.get("subject", ""),
            date=date,
            flags=obj.get("flags", {}),
            folder=folder,
        )


def _run(args: list[str], cwd: str | None = None) -> str:
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


def list_emails(folder: str = "INBOX", cwd: str | None = None) -> list[Email]:
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
                "50",
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
        if len(envelopes) < 50:
            break
        page += 1
        time.sleep(0.3)  # Rate limit for Exchange
    return [Email.from_json(e, folder) for e in all_envelopes]


def move_email(
    email_id: str, from_folder: str, to_folder: str, cwd: str | None = None
) -> None:
    """Move an email from one folder to another using himalaya message copy."""
    _run(["message", "copy", to_folder, email_id, "-f", from_folder], cwd=cwd)


def create_folder(folder_name: str, cwd: str | None = None) -> None:
    """Create a new folder."""
    _run(["folder", "add", folder_name], cwd=cwd)


def delete_email(email_id: str, folder: str, cwd: str | None = None) -> None:
    """Deletion is not supported — raises DeleteNotSupportedError."""
    raise DeleteNotSupportedError(
        "Email deletion is not supported. Emails must be moved to Archive, not deleted."
    )
