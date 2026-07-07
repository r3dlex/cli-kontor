# Specification: inline RulesEngine pass-through into Pipeline classify

## A — Current friction

`src/kontor_cli/rules_engine.py` is a shallow pass-through module. `RulesEngine.classify()`
merely sequences the three rule loaders (YAML DSL → Python → NL) with logging glue, and
`get_nl_context()` is a one-line forward to `nl_rules.nl_rules_context()`. The interface is
as complex as the implementation: every caller must already know the three rule formats,
their priority order, and the LLM fallback. The module fails the deletion test in the good
direction — deleting it concentrates the classify sequence in the Pipeline, where the real
orchestration (rules → LLM fallback → folder policy → move) already lives.

## B — Target shape

- The Pipeline loads the three rule sources in `__init__` (calling the loaders in
  `kontor_cli.rules` directly) and evaluates them in priority order in a single
  `classify_with_rules()` step; `rules_engine.py` is deleted.
- NL context for the LLM prompt comes straight from `nl_rules.nl_rules_context()` on the
  Pipeline's loaded NL rules — no intermediary object.
- The `classify` CLI command uses the Pipeline for the same sequence instead of
  constructing a private RulesEngine.

## Acceptance criteria

- All unit tests green (`uv run pytest tests/unit/ -v`); rules_engine test coverage is
  migrated, not dropped — loaders are mocked/stubbed directly.
- `uv run ruff check`, `uv run ruff format --check`, and
  `uv run mypy src/ --ignore-missing-imports` are clean.
- No behavior change: identical classification priority (YAML > Python > NL/LLM),
  identical log messages, identical CLI output.

## Sliced goal

Single slice: this PR (inline + delete + test migration). No follow-up slices.
