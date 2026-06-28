# AGENTS.md — kontor-cli

## Role & Intent

`kontor-cli` is a Python CLI tool that autonomously manages a work email mailbox using himalaya + DavMail + an LLM classifier. The agent operating here should follow TDD, keep changes surgical, and never delete emails.

## Operating Principles

1. **TDD-first** — write failing tests before fixing
2. **Move never delete** — `delete_email()` raises `DeleteNotSupportedError`; never bypass
3. **No credentials in git** — `config.yaml` is gitignored; use `config.example.yaml` as template
4. **Fail fast** — startup checks for himalaya, DavMail connectivity
5. **Autonomous only** — LLM decides without user prompt; log everything

## Execution Protocol

- Run `uv sync` after dependency changes
- Run `uv run pytest tests/unit/ -v` after every change
- Run `uv run ruff check src/ tests/` for lint
- Run `uv run mypy src/ --ignore-missing-imports` for typecheck
- All unit tests must pass before committing

## Verification

```bash
uv run pytest tests/unit/ -v --tb=short   # must be green
uv run ruff check src/ tests/             # 0 errors
uv run mypy src/ --ignore-missing-imports # 0 errors
```

<!-- v3-ai-sdlc-init:start -->
## AI SDLC v3
This repo follows the v3 AI-SDLC layout. See `.ai/matrix.json`, `.memory/human-override/`, and `docs/architecture/adr/`. Modules at `r3dlex/skills/ai-sdlc-init/modules/`.
<!-- v3-ai-sdlc-init:end -->

<!-- ai-sdlc-init:start -->
## AI-SDLC v3 governance

AI-SDLC source of truth:
- Human workflow: [.ai/workflows/repo-workflow.md](./.ai/workflows/repo-workflow.md)
- Machine workflow: [.ai/workflows/repo-workflow.json](./.ai/workflows/repo-workflow.json)
- Topology matrix: [.ai/matrix.json](./.ai/matrix.json)
- Traceability index: [.ai/traceability/index.md](./.ai/traceability/index.md)

Hosted branch and policy changes are checklist-only unless explicitly confirmed. PR merge requires architect, reviewer, and executor agreement, resolved comments, local validation, and green hosted CI.
<!-- ai-sdlc-init:end -->
