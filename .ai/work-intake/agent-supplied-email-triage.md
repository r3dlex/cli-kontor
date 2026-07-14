# Work intake: agent-supplied email triage

Status: in-progress

## Problem

Email-to-Asana triage must be an explicit agent-driven workflow, not an
automatic side effect of mailbox processing. The agent needs the message body,
eligibility reason, canonical placement, decisive-sender hint, and configured
owner in CLI output to make the category decision. Invalid deadlines must be
rejected before mailbox or Asana access.

## Acceptance criteria

- `process` never invokes triage or Asana, even when triage is enabled.
- `triage` is read-only and exposes body, reason, `canonical_folder`,
  `decisive_prior`, and owner context for every candidate.
- `triage-create` defaults to preview; only `--no-dry-run` writes to Asana.
- Invalid `--deadline` values fail cleanly before mailbox access.
- Canonical context uses the Pipeline's inline classifier with no legacy
  wrapper dependency.
- README and the email-to-Asana skill describe the current explicit workflow.
- Unit tests, Ruff, formatting, and mypy are green.
