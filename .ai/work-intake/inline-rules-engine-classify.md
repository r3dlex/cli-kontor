# Work intake: inline RulesEngine pass-through into Pipeline classify

Status: in-progress

## Problem

`src/kontor_cli/rules_engine.py` is a shallow pass-through: `classify()` only sequences the
three rule loaders (YAML → Python → NL) with logging, and `get_nl_context()` forwards one
call. Its interface is as complex as its implementation, so it adds a layer without hiding
anything. The classify sequence belongs in the Pipeline, where the surrounding
orchestration (LLM fallback, folder policy, moves) already lives.

## Acceptance criteria

- `rules_engine.py` deleted; YAML → Python → NL evaluation inlined into the Pipeline,
  calling the loaders in `kontor_cli.rules` directly.
- `kontor-cli classify` CLI command updated to the new call path.
- Test coverage from `tests/unit/rules_engine_test.py` migrated (no assertions lost);
  pipeline tests stub the rules step / loaders directly.
- `uv run pytest tests/unit/ -v`, `uv run ruff check src/ tests/`,
  `uv run ruff format --check src/ tests/`, and
  `uv run mypy src/ --ignore-missing-imports` all pass.
- No behavior change.
