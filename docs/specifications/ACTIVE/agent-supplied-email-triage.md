# Specification: agent-supplied email triage

## A — Safety boundary

Mailbox processing and email-to-Asana triage are separate workflows. The
`process` command may classify and move mail according to its phase, but it must
never instantiate triage or write to Asana. Triage is entered only through the
explicit `triage` and `triage-create` commands and never moves or deletes mail.

## B — Agent decision context

`triage` applies the deterministic recall gate and prints each qualifying
candidate's id, sender, subject, body, eligibility reason, canonical folder,
decisive-sender hint, and configured `triage.owner_email`. The owner is
operational context: the agent creates a task only when the message requires
that owner's personal decision, review, approval, answer, or other action.

Canonical placement is advisory and comes from `Pipeline.classify_with_rules`.
If deterministic classification is unavailable or has no match, the command
prints `canonical_folder=-` and continues.

## C — Explicit creation

The agent supplies one of the four category slugs and an optional ISO deadline
to `triage-create`. The command defaults to a no-write preview. A real,
idempotent Asana write requires `--no-dry-run`. Deadlines must use the exact
dashed `YYYY-MM-DD` form; malformed and compact values are CLI usage errors and
are rejected before mailbox access, without a traceback. Preview makes no Asana
calls. Before a real write, the command validates every configured project;
validation, dedup-query, and create API failures exit nonzero.

## Acceptance criteria

- Candidate output exposes body, reason, `canonical_folder`,
  `decisive_prior`, and owner context.
- Owner context matches the configured `triage.owner_email`.
- `triage` performs no Asana write or mailbox mutation.
- `process` performs no triage or Asana action.
- Invalid or compact deadlines exit cleanly before listing mail.
- `triage-create` remains preview-by-default and the real write path remains
  explicit.
- Preview stays offline; real writes validate every configured Asana project
  before mailbox access and never report API failures as `skipped_error`.
- Source and tests contain no imports or calls to the removed classifier
  wrapper; triage uses the Pipeline's inline classifier.
- README, config example, and email-to-Asana skill agree with this behavior.
- Unit tests, Ruff check, Ruff format check, and mypy pass.

## Sliced goal

Single slice: forward-port the explicit agent-supplied triage workflow onto the
current inline Pipeline classifier architecture.
