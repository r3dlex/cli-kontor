# kontor-cli

Autonomous email management CLI for a work mailbox using **himalaya** + **DavMail** + **LLM classifier**.

## Key Files

| File | Purpose |
|------|---------|
| `src/kontor_cli/cli.py` | click CLI entry point |
| `src/kontor_cli/config.py` | YAML config loader + startup checks |
| `src/kontor_cli/himalaya.py` | himalaya CLI wrapper |
| `src/kontor_cli/folders.py` | Folder taxonomy + archive enforcement |
| `src/kontor_cli/classifier.py` | OpenAI-compatible LLM classifier |
| `src/kontor_cli/pipeline.py` | Rebuild / Realtime / Heal pipelines |
| `src/kontor_cli/rules_engine.py` | Unified rules evaluation |
| `src/kontor_cli/rules/` | YAML DSL, Python, NL rule loaders |

## Commands

```bash
uv run kontor-cli check-config
uv run kontor-cli classify --email-id <id>
uv run kontor-cli process --phase (rebuild|realtime|heal)
uv run kontor-cli dry-run --phase rebuild
uv run kontor-cli rules-freeze
```

## Running Tests

```bash
uv sync
uv run pytest tests/unit/ -v
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ --ignore-missing-imports
```

## Constraints

- Emails must **never be deleted** — only moved to Archive
- `config.yaml` is gitignored — use `config.example.yaml` as template
- No credentials in source code — all secrets via config or env
