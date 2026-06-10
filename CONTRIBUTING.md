# Contributing

Thanks for considering a contribution.

## Setup
1. Clone: `git clone git@github.com:r3dlex/cli-kontor.git && cd cli-kontor`
2. Install: `uv sync`
3. Copy `config.example.yaml` to `config.yaml` and fill in your credentials (never commit `config.yaml`).
4. Install pre-commit: `uvx pre-commit install`

## Development workflow
- Follow TDD: write a failing test in `tests/unit/`, watch it fail, then make it pass.
- Never delete emails — `delete_email()` raises `DeleteNotSupportedError`. Move to Archive instead.
- No credentials in source. Use `config.yaml` (gitignored) or env vars.

## Tests
```bash
uv run pytest tests/unit/ -v
```

## Lint & typecheck
```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ --ignore-missing-imports
```

mypy runs in strict mode: `strict = true` is set in `pyproject.toml`.

## Pull requests
- One PR per logical change.
- All local CI gates must pass before requesting review.
- Reference any related issue.

<!-- v3-ai-sdlc-init:start -->
## v3
This repo follows the v3 AI-SDLC layout. See `.ai/matrix.json` and `AGENTS.md` for the operating contract. The merge gate requires architect + reviewer + executor agreement.
<!-- v3-ai-sdlc-init:end -->
