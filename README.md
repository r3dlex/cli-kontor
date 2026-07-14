# kontor-cli

[![CI](https://github.com/r3dlex/cli-kontor/actions/workflows/ci.yml/badge.svg)](https://github.com/r3dlex/cli-kontor/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/r3dlex/cli-kontor/branch/main/graph/badge.svg)](https://codecov.io/gh/r3dlex/cli-kontor)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

`kontor-cli` is a local Python CLI that manages a work mailbox through
**himalaya**, **DavMail** (the EWS-to-IMAP bridge), deterministic rules, and an
OpenAI-compatible LLM fallback. It classifies messages and moves them into a
controlled folder taxonomy. It never deletes email.

## Prerequisites

- macOS or Linux with Git
- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [himalaya](https://github.com/pimalaya/himalaya) 1.0 or newer (`brew install himalaya` on macOS)
- [DavMail](https://davmail.sourceforge.net/) running locally; the example
  configuration uses IMAP `localhost:1110`, SMTP `localhost:1025`, and HTTP
  proxy `localhost:3128`
- An OpenAI-compatible API endpoint and key for messages that do not match a
  deterministic rule

## Quick Start

This is the recommended first run. It validates the local tools and connection,
then previews only the inbox without moving messages.

```bash
git clone https://github.com/r3dlex/cli-kontor.git
cd cli-kontor
uv sync --frozen
cp config.example.yaml config.yaml
# Edit config.yaml with your account, DavMail, and LLM settings, then start DavMail.
uv run kontor-cli check-config
uv run kontor-cli dry-run --phase realtime
```

Successful configuration prints:

```text
Config OK — all prerequisites satisfied.
```

The dry run emits JSON log records such as `[DRY-RUN] Would move email ...` and
ends with `Phase 'realtime' complete: {...}`. No mailbox message is moved and no
Asana task is created during a dry run. Even during a process dry run, fallback
classification sends the email's sender, subject, and date to the configured LLM.
Optional triage is separate and agent-driven: `triage` reads candidate bodies
locally and prints them for the agent; it does not call the configured LLM or
write to Asana. Only `triage-create --no-dry-run` can write an Asana task.
Classification can also write local decision logs under `rules/evolved/`. Those
logs include the email ID, subject, and sender. They are gitignored, but treat
these files as sensitive: restrict access, retain them only for an active review
or audit need, and delete them locally when that review or audit need ends.

## Safety Model

- Preview first: `dry-run --phase ...` and `process --phase ... --dry-run` use
  the same mailbox pipeline while suppressing mailbox moves. The process
  commands never invoke triage or Asana.
- Process commands mutate the mailbox by moving messages. They never delete
  messages; `delete_email()` always raises `DeleteNotSupportedError`.
- `classify` evaluates deterministic YAML and Python rules only; it does not
  call the LLM fallback used by `process`. `classify --email-id ...` prints the
  resulting rules-only target (or the `4_Info` default) and does not move the
  message. `triage` is also preview-only.
- `config.yaml` is gitignored. Keep mailbox and API credentials out of commits.
- Re-running a phase is supported. Messages already in their target folder are
  skipped, and realtime only scans the current inbox. Always repeat a dry run
  after changing configuration or rules.

## Operate the Mailbox

After reviewing dry-run output, run the narrowest mutating phase that fits:

```bash
uv run kontor-cli process --phase realtime  # Move classified inbox messages
uv run kontor-cli process --phase rebuild   # Re-evaluate messages in fixed scan folders
uv run kontor-cli process --phase heal      # Repair violations in fixed scan folders
```

Useful read-only or guarded commands:

```bash
uv run kontor-cli classify --email-id <id>  # Print one message's target folder
uv run kontor-cli triage                     # List agent-triage candidates and context
uv run kontor-cli triage-create --email-id <id> --category nudging  # Preview a task
uv run kontor-cli dry-run --phase rebuild   # Preview the broad historical pass
uv run kontor-cli dry-run --phase heal      # Preview invariant repairs
uv run kontor-cli process --phase heal --rules-freeze
```

`rebuild` and `heal` scan only the fixed `SCAN_FOLDERS` list in the pipeline;
they do not discover arbitrary valid taxonomy folders. In particular, a valid
`MGT_`, `PRJ_`, or `EXT_` folder that is absent from that list is not scanned.

`--rules-freeze` writes a timestamped snapshot of evolved-rule metadata before
the heal run. Use it when a reviewed heal run should retain that audit point.

### Agent-driven Asana triage

Enable `triage.enabled`, configure `triage.owner_email`, and provide the Asana
workspace and four category project GIDs shown in `config.example.yaml`.
`triage` is read-only and prints each candidate's body, eligibility reason,
canonical folder, decisive-sender hint, and configured owner. The agent should
create a task only when the message requires that owner's input or action.

`triage-create` defaults to an offline, no-write preview. Pass `--deadline
YYYY-MM-DD` when the message supplies a due date; the dashed form is required,
and malformed or compact dates fail before mailbox access. Pass `--no-dry-run`
only after reviewing the preview. The real-write path validates every configured
Asana project before mailbox access and exits nonzero on validation, dedup-query,
or task-creation API failures. Neither triage command moves or deletes email.

## Update and Rerun

Update the checkout without rewriting local history, synchronize exactly the
locked dependencies, and repeat the safety checks:

```bash
git pull --ff-only
uv sync --frozen
uv run kontor-cli check-config
uv run kontor-cli dry-run --phase realtime
```

Keep local `config.yaml` and evolved-rule logs when updating. If the example
configuration changes, compare it with your local file instead of overwriting
credentials. A rerun re-reads the mailbox and current rules; it does not resume
an old in-memory scan.

## Troubleshooting

- `Config error: Config file not found`: copy `config.example.yaml` to
  `config.yaml`, or pass `--config /path/to/config.yaml` after the command name.
- `himalaya error`: confirm `himalaya --version` works and satisfies
  `himalaya.version` in the config.
- `DavMail error`: start DavMail and confirm the configured host and IMAP port
  are reachable. `check-config` probes the IMAP endpoint.
- No `[DRY-RUN]` records: messages already in the target folder are skipped. The
  final phase summary still reports how many messages were scanned.
- LLM failures: verify `llm.base_url`, `llm.api_key`, and `llm.model`. YAML and
  Python rules run before the LLM fallback.

Run `uv run kontor-cli --help` or `uv run kontor-cli <command> --help` for the
source-backed command reference.

## How Classification Works

Rules are evaluated in this order:

1. YAML DSL in `rules/rules.d/*.yaml`
2. Python rules in `rules/rules.py`
3. Natural-language rule context with the LLM fallback

The resulting classification passes through the folder policy, which applies
the taxonomy and archive age rule before any move.

## Folder Taxonomy

```
INBOX
 ├─ 0_Action           ← Requires your action
 ├─ 1_Management/MGT_<Topic>
 ├─ 2_Projects/PRJ_<Domain>_<Initiative>_<Scope>
 ├─ 3_External/EXT_<Company>_<Topic>
 ├─ 4_Info            ← Newsletters, announcements
 ├─ 9_System          ← CI/CD, security alerts
 └─ Archive/          ← Emails >6 months old (mirrors structure)
```

## Development

```bash
uv sync --frozen
uv run pytest tests/unit/ -v --tb=short
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ --ignore-missing-imports
bash scripts/validate-rules.sh
bash scripts/archgate.sh structural .rules.ts
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the TDD and pull-request workflow,
[CONTEXT.md](./CONTEXT.md) for domain language, and
[docs/adr/0001-email-move-only.md](./docs/adr/0001-email-move-only.md) for the
move-only safety decision.

<!-- v3-ai-sdlc-init:start -->
## AI SDLC v3
This repo follows the v3 AI-SDLC layout. See `.ai/matrix.json`, `.memory/human-override/`, and `docs/architecture/adr/`. Modules at `r3dlex/skills/ai-sdlc-init/modules/`.
<!-- v3-ai-sdlc-init:end -->

<!-- ai-sdlc-init:start -->
## AI-SDLC governance

This repository follows the AI-SDLC methodology. See [AGENTS.md](./AGENTS.md), [RULES.md](./RULES.md), [PLANS.md](./PLANS.md), [.ai/workflows/repo-workflow.md](./.ai/workflows/repo-workflow.md), and [.ai/workflows/repo-workflow.json](./.ai/workflows/repo-workflow.json).
<!-- ai-sdlc-init:end -->
