# Python Language Pack (kontor-cli)

Per `r3dlex/skills/ai-sdlc-init/modules/language-packs.md`, this repo uses the
**Python pack** with the following detection evidence and selected commands.

## Detection evidence

| Signal | File | Match |
| --- | --- | --- |
| `pyproject.toml` | `pyproject.toml` | yes (root) |
| `uv.lock` | `uv.lock` | yes (root) |
| pytest config | `pyproject.toml` `[tool.pytest.ini_options]` | yes (`testpaths = ["tests/unit"]`) |
| ruff | `pyproject.toml` `[tool.ruff]` / `ruff_cache/` in `.gitignore` | yes (lint cache) |
| mypy | `pyproject.toml` `[tool.mypy]` / `.mypy_cache/` in `.gitignore` | yes (typecheck cache) |

## Selected local checks

| Check | Command | Source |
| --- | --- | --- |
| Unit tests | `uv run pytest tests/unit/ -v` | AGENTS.md "Verification" section |
| Lint | `uv run ruff check src/ tests/` | AGENTS.md "Operating Principles" |
| Typecheck | `uv run mypy src/ --ignore-missing-imports` | AGENTS.md "Verification" section |

## CI checks (already present in `.github/workflows/`)

| Job | File | Trigger |
| --- | --- | --- |
| Lint & tests | `ci.yml` | push to main / PR |
| Full test matrix | `tests.yml` | push to main / PR |
| Pre-commit (new) | `ci-prek.yml` | push to main / PR |

## Intentionally skipped

- `dotnet ef migrations script` — not applicable (Python repo)
- `cargo test` / `cargo clippy` — not applicable (Python repo)
- `dotnet format --verify-no-changes` — not applicable
- New dependencies — not added; pack reuses existing `uv` toolchain and
  `pytest` / `ruff` / `mypy` already configured in `pyproject.toml`.

## Toolchain pin

`pyproject.toml` declares `requires-python = ">=3.12"`. The CI uses
`ubuntu-latest` with the system Python; no `global.json`-equivalent is
present (Python toolchain is uv-driven, no version-pin file needed).
