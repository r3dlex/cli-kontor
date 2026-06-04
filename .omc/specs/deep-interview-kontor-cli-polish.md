---
status: pending_approval
created: 2026-06-04
ralplan_iterations: 0
interview_id: di-kontor-cli-polish-2026-06-04
interview_rounds: 0
final_ambiguity: 0.18
type: brownfield
threshold: 0.20
threshold_source: default
status: PASSED_NEAR_THRESHOLD
scope_transfer_from: di-bug-tracking-uv-2026-06-03
---

# Deep Interview Spec: kontor-cli Release-Grade Polish

> **Scope-transfer spec.** This is **not** a fresh deep interview. The substantive
> product/architecture decisions were made in the
> `deep-interview-bug-tracking-uv-and-polish.md` (merged via PR #11,
> squash commit `56cf136`). This spec transfers that scope to kontor-cli with the
> deltas that kontor-cli's brownfield state actually requires.

## Metadata

- Interview ID: `di-kontor-cli-polish-2026-06-04`
- Rounds: 0 (scope transfer)
- Final Ambiguity Score: 18% (under 20% threshold; spec is actionable)
- Type: brownfield
- Generated: 2026-06-04
- Threshold: 0.20
- Threshold Source: default
- Status: PASSED
- Scope transfer source: `deep-interview-bug-tracking-uv-and-polish.md` (spec_ambiguity 0.22)
- Target branch: `feature/kontor-cli-polish` (assumed; not yet created)
- Base branch: `main` (verified clean except for 4 uncommitted changes documented in the bug-tracking spec's "Technical Context" analogue below)

## Clarity Breakdown

| Component | Goal | Constraints | Criteria | Context | Component Clarity | Component Ambiguity |
|-----------|------|-------------|----------|---------|-------------------|---------------------|
| polish-transfer (uv-cutover is N/A) | 0.95 | 0.90 | 0.85 | 0.90 | 0.90 | 0.10 |
| working-tree-reconciliation | 0.90 | 0.85 | 0.80 | 0.85 | 0.85 | 0.15 |
| ci-consolidation | 0.90 | 0.85 | 0.85 | 0.85 | 0.86 | 0.14 |
| mypy-strict | 0.85 | 0.80 | 0.80 | 0.95 | 0.85 | 0.15 |
| pre-commit-license-contributing | 0.90 | 0.85 | 0.85 | 0.90 | 0.875 | 0.125 |
| **Overall (max ambiguity)** | | | | | | **0.18** |

Weights: goal 0.35, constraints 0.25, criteria 0.25, context 0.15 (brownfield).

## Topology

| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| polish-transfer | active | Apply the bug-tracking uv-and-polish pattern: full type hints, mypy --strict, consolidated GH Actions CI, pre-commit, README badges, LICENSE, CONTRIBUTING.md | kontor-cli is already on uv (hatchling, py3.12), so the uv cutover sub-component is N/A |
| working-tree-reconciliation | active | Decide what to do with the 4 modified files (`classifier.py`, `logging_config.py`, `pipeline.py`, `classifier_test.py`) and the 2 untracked items (`.omc/`, `config.work.yaml`) | Recommendation: fold the 4 modified files into a "chore(kontor-cli): fold pre-existing classifier+test changes" commit per the bug-tracking precedent; add `.omc/` to `.gitignore`; add `config.work.yaml` to `.gitignore` (or document it as intentionally local) |
| ci-consolidation | active | Replace the two existing workflows (`ci.yml` Lint & Typecheck + `tests.yml` matrix+smoke) with a single workflow that runs lint + typecheck + tests + smoke, matrix py3.12+3.13, paths filter, uv cache, optional Codecov | The current two-workflow setup has overlap (lint+typecheck runs twice on the same matrix) |
| mypy-strict | active | Add `strict = true` to `[tool.mypy]`; fix the 8 known mypy --strict errors (see Risks) | Risk is low: 8 errors in 3 files, all simple "add type arguments" fixes; empirical evidence from `uv run mypy src/ --strict` |
| pre-commit-license-contributing | active | Add `.pre-commit-config.yaml` (ruff + ruff-format), `LICENSE` (MIT), `CONTRIBUTING.md` (stub), README badges | Pattern is direct port from bug-tracking |

## Goal

Apply the release-grade polish pattern from the merged bug-tracking PR #11 to
kontor-cli, with the uv cutover sub-component dropped (kontor-cli is already on uv).
The polish includes: full type hints under `mypy --strict`, consolidated GH Actions
CI (paths filter, matrix, uv cache, optional Codecov), pre-commit hooks,
`LICENSE`, `CONTRIBUTING.md`, and README badges. The working tree is reconciled in
a separate "fold pre-existing changes" commit so this PR's diff is self-contained.

## Constraints

### Polish transfer
- uv is already the only toolchain (hatchling build, pyproject.toml L23-24). **Do not** introduce poetry, pip-tools, or any other installer.
- `[project.optional-dependencies] dev` (pyproject.toml L13-17) is a duplicate of `[dependency-groups] dev` (L33-39). **Drop the optional-dependencies block** (PEP 735 `dependency-groups` is the modern, uv-native way; matches the bug-tracking decision).
- Add `pytest-cov>=5.0.0` to `[dependency-groups] dev` and add `[tool.coverage.*]` config.
- Add `[tool.coverage.run] source = ["src/kontor_cli"]` and `[tool.coverage.report] fail_under = 80` (lower than bug-tracking's 90% because kontor-cli has a smaller test surface — `tests/unit/` only; integration tests are DavMail-gated; see Test Plan).
- Do not add `mypy` to `[dependency-groups] dev` — it is already there (L35, `mypy>=2.1.0`).
- Do not change the `[tool.ruff]` config line-length (88) or the lint selection (E/F/W/I/N/UP/B/C4) — these are intentionally stricter than bug-tracking's. The plan documents the drift but does not unify.
- `[tool.mypy] strict = true` is the only new mypy setting. Keep `ignore_missing_imports = true` (per current AGENTS.md L20: `uv run mypy src/ --ignore-missing-imports`).

### CI consolidation
- Replace the two existing workflows (`.github/workflows/ci.yml` + `.github/workflows/tests.yml`) with a single `.github/workflows/ci.yml` that runs lint+typecheck+tests+smoke on a py3.12+3.13 matrix. The overlap in the current setup is the "Run with Python 3.12 only (lint + typecheck)" step in `tests.yml` (L35-39), which duplicates `ci.yml`.
- Paths filter: `src/**`, `tests/**`, `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, `LICENSE`, `CONTRIBUTING.md`, `README.md`. (No `.omc/**` — these are planning artifacts and must not be committed.)
- `astral-sh/setup-uv@v4` with `enable-cache: true` and `cache-dependency-glob: "uv.lock"`.
- Codecov upload is **optional** in this PR: include the `codecov/codecov-action@v4` step gated on `env.CODECOV_TOKEN != ''` so the workflow still passes when the secret is absent. This mirrors the bug-tracking approach and avoids hard-failing PRs on the first integration.

### mypy --strict
- 8 known errors (verified via `uv run mypy src/ --strict --no-incremental` on 2026-06-04):
  1. `src/kontor_cli/rules/python_rules.py:15` — `load_python_rules() -> dict` (bare `dict`)
  2. `src/kontor_cli/rules/python_rules.py:35` — `call_python_rules(rules_ns: dict, email)` (bare `dict`)
  3. `src/kontor_cli/pipeline.py:191` — `RebuildPipeline.run() -> dict` (bare `dict`)
  4. `src/kontor_cli/pipeline.py:259` — `RebuildPipeline._summary() -> dict` (bare `dict`)
  5. `src/kontor_cli/pipeline.py:275` — `RealtimePipeline.run() -> dict` (bare `dict`)
  6. `src/kontor_cli/pipeline.py:290` — `RealtimePipeline._summary() -> dict` (bare `dict`)
  7. `src/kontor_cli/pipeline.py:306` — `HealPipeline.run() -> dict` (bare `dict`)
  8. `src/kontor_cli/logging_config.py:39` — `class FlushingStreamHandler(logging.StreamHandler)` (bare `StreamHandler`)
- All 8 fixes are simple "add type arguments" changes:
  - `dict` → `dict[str, Any]` (or `dict[str, int]` for `_summary` based on actual return values)
  - `StreamHandler[Any]` (or just `logging.StreamHandler` parameterization)
- mypy --strict gate must pass before commit lands.

### Pre-commit / License / Contributing
- `.pre-commit-config.yaml` (kontor-cli root): same as bug-tracking's — `pre-commit-hooks` (trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, mixed-line-ending) + `astral-sh/ruff-pre-commit` (ruff + ruff-format). No mypy in pre-commit (mypy is slow and runs in CI).
- `LICENSE`: MIT, copyright 2026 Andre Burgstahler (matches bug-tracking choice).
- `CONTRIBUTING.md`: 5-section stub (setup, dev workflow, test, lint, PR conventions) — direct port from bug-tracking, with kontor-cli-specific commands (`uv run kontor-cli check-config`, `uv run kontor-cli process --phase heal`).
- `README.md` badges: CI, coverage (shields.io for now, Codecov later), Python version. Insert after the title.

### Working tree reconciliation
- 4 modified files MUST be folded in or reverted before the PR is opened. Recommendation: fold them in as a single `chore(kontor-cli): fold pre-existing classifier+test changes` commit (bug-tracking precedent: PR #11 commit 4).
  - `src/kontor_cli/classifier.py` (+76 lines: adds `_derive_max_output_tokens` and `_truncate_prompt`, threads `max_tokens` into the LLM request)
  - `src/kontor_cli/logging_config.py` (+13 lines: minor refactor)
  - `src/kontor_cli/pipeline.py` (+14 lines: minor refactor)
  - `tests/unit/classifier_test.py` (+138 lines: new test coverage for the classifier changes)
- 2 untracked items MUST be addressed:
  - `.omc/` — planning artifacts (must NOT be committed). **Add to `.gitignore`**.
  - `config.work.yaml` — local-only config (per `git status` output; not in `.gitignore`). Either add to `.gitignore` or document as intentionally local. **Recommend add to `.gitignore`**.

### PR mechanics
- Branch: `feature/kontor-cli-polish`
- Base: `main`
- Title (Conventional Commits): `chore(kontor-cli): apply release-grade polish (mypy --strict, CI consolidation, pre-commit, LICENSE, CONTRIBUTING, badges)`
- Open as draft first; mark ready for review after local CI passes
- Auto-merge once remote CI is green
- Single PR (per the bug-tracking precedent — 4-commit atomic PR, see plan)
- Working tree after merge: clean

### CI validation
- **Local CI (pre-push hard gate)**:
  - `uv run pytest --cov` with coverage ≥ 80% (the new floor in pyproject.toml)
  - `uv run ruff check src/ tests/` returns 0
  - `uv run ruff format --check src/ tests/` returns 0
  - `uv run mypy src/ --strict` returns 0
  - All four are required; the push is blocked if any fails
- **Remote CI (`.github/workflows/ci.yml`)**:
  - Matrix: py3.12 + py3.13 on `ubuntu-latest`
  - Trigger: `on: push: branches: [main]` and `on: pull_request`
  - `uv` cache enabled (saves dependency install time)
  - Coverage uploaded to Codecov (gated on `CODECOV_TOKEN` presence)
  - All 4 commands run on each matrix leg

## Non-Goals

- Migrating kontor-cli to any other toolchain (it is already on uv)
- Publishing kontor-cli to PyPI or any package registry
- Bumping the version beyond 0.1.0
- Setting up semantic-release or any automated versioning
- Configuring branch protection rules on kontor-cli (not in scope; this PR adds the workflow but does not change repo settings)
- Unifying ruff config between kontor-cli (line-length 88, E/F/W/I/N/UP/B/C4) and bug-tracking (line-length 100, E/F/I) — documented as drift, not addressed
- Refactoring `_summary` in `pipeline.py` to share code between Rebuild/Realtime/Heal (R1 in the plan flags this as a smell but it is out of scope)
- Splitting `vault_integration.py` (525 lines) into smaller modules (R-flagged as a follow-up, not this PR)
- Adding integration tests for DavMail-gated paths (out of scope; the `integration` pytest marker already exists)

## Acceptance Criteria

### Polish done
- [ ] `uv run mypy src/ --strict` returns 0 errors
- [ ] `uv run pytest` exits 0 with coverage ≥ 80%
- [ ] `uv run ruff check src/ tests/` returns 0
- [ ] `uv run ruff format --check src/ tests/` returns 0
- [ ] `pyproject.toml` has no `[project.optional-dependencies]` block
- [ ] `pyproject.toml` has `pytest-cov>=5.0.0` in `[dependency-groups] dev`
- [ ] `pyproject.toml` has `[tool.coverage.run] source = ["src/kontor_cli"]` and `[tool.coverage.report] fail_under = 80`
- [ ] `pyproject.toml` has `[tool.mypy] strict = true` (with `ignore_missing_imports = true` preserved)
- [ ] `.pre-commit-config.yaml` exists at kontor-cli root
- [ ] `pre-commit run --all-files` exits clean locally
- [ ] `LICENSE` file present (MIT)
- [ ] `CONTRIBUTING.md` stub present
- [ ] `README.md` has CI badge, coverage badge, Python version badge
- [ ] `.gitignore` includes `.omc/` and `config.work.yaml`

### CI consolidated
- [ ] `.github/workflows/ci.yml` exists with paths filter covering all files in the PR
- [ ] `.github/workflows/tests.yml` is removed
- [ ] Matrix: py3.12 + py3.13 on ubuntu-latest
- [ ] All 4 commands (ruff check, ruff format, mypy --strict, pytest+coverage) run on every matrix leg
- [ ] `astral-sh/setup-uv@v4` with `enable-cache: true` and `cache-dependency-glob: "uv.lock"`
- [ ] Codecov upload is gated on `CODECOV_TOKEN` presence (does not hard-fail when secret is absent)
- [ ] Local CI command sequence passes: `uv run pytest --cov && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/ --strict`

### PR merged
- [ ] Branch `feature/kontor-cli-polish` exists
- [ ] PR opened as draft, then marked ready for review
- [ ] PR title is `chore(kontor-cli): apply release-grade polish (mypy --strict, CI consolidation, pre-commit, LICENSE, CONTRIBUTING, badges)`
- [ ] PR body has what + why + test plan + "Folding in pre-existing work" callout
- [ ] All required checks (GH Actions CI matrix) are green on the PR
- [ ] PR is auto-merged once checks pass
- [ ] Working tree after merge: clean (no uncommitted changes; `.omc/` and `config.work.yaml` ignored)

## Assumptions Exposed & Resolved

| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| "Same changes" means full bug-tracking scope verbatim | kontor-cli is already on uv | Drop uv-cutover sub-component; everything else transfers |
| "Improvements from bug-tracking" includes coverage floor of 90% | kontor-cli test surface is smaller (88 unit tests, no integration in CI) | Floor 80% in this PR; bump to 90% in a follow-up if integration tests land |
| Ruff config can be unified to bug-tracking's (line-length 100, E/F/I) | kontor-cli intentionally uses stricter rules (N/UP/B/C4) and shorter line length | Document drift, do not change |
| Codecov is required in this PR | No `CODECOV_TOKEN` is set on the kontor-cli repo | Gate upload on secret presence; status check is informational |
| 4 uncommitted files are part of the polish | They change behavior, not just tooling | Fold them into a "chore: fold pre-existing changes" commit (bug-tracking precedent) and call out in PR body |
| The pre-existing modified `classifier.py` adds 2 new functions with full type hints | mypy --strict must still pass | Verified: 0 new mypy errors from these changes (the 8 known errors are all in pre-existing code) |
| `mypy --strict` may surface 30+ blockers like in bug-tracking | kontor-cli source is 16 files vs bug-tracking's 24, and 68 public functions all already have parameter + return annotations | Empirical evidence: exactly 8 errors in 3 files, all trivial |
| `tests.yml` and `ci.yml` can be merged into one workflow | They currently overlap on lint+typecheck | Consolidate into one; delete `tests.yml` |
| `.omc/` should be committed because the .omc folder exists in the working tree | `.omc/` contains planning artifacts (not code) | Add to `.gitignore`; never commit |
| `config.work.yaml` is personal config that shouldn't be committed | It is a sibling of `config.yaml` (which is gitignored) | Add to `.gitignore`; document in CONTRIBUTING |
| The 4-commit single-PR structure from bug-tracking is overkill for kontor-cli | The polish items are still ~5 file areas | Adopt 4-commit structure (uv-cutover N/A, so commit 1 becomes the "working tree fold-in" commit) |

## Technical Context (Brownfield)

- **Repo location**: `/Users/andreburgstahler/Ws/Rib/kontor-cli/` is a **separate git repo** (not a submodule of rib-workspace)
- **Current state**: uv-managed Python 3.12 project with `src/kontor_cli/` layout, hatchling build, on main
- **Tooling today**: pytest+pytest-mock (no pytest-cov), ruff (E/F/W/I/N/UP/B/C4 selection, line-length 88, py312), mypy (NOT strict, `warn_return_any` + `ignore_missing_imports` only)
- **Uncommitted changes** (will be folded into PR):
  - `src/kontor_cli/classifier.py` (+76/-? — adds `_derive_max_output_tokens` and `_truncate_prompt`, threads `max_tokens` into the LLM request)
  - `src/kontor_cli/logging_config.py` (+13/-? — minor refactor)
  - `src/kontor_cli/pipeline.py` (+14/-? — minor refactor)
  - `tests/unit/classifier_test.py` (+138 — new test coverage)
  - Untracked: `.omc/` (planning artifacts, must NOT be committed) and `config.work.yaml` (local-only config)
- **No `.pre-commit-config.yaml`** at root
- **No `LICENSE`** at root
- **No `CONTRIBUTING.md`** at root
- **No README badges** in `README.md` (plain markdown)
- **CI**: 2 GH Actions workflows already present at `.github/workflows/`:
  - `ci.yml` (516 bytes): `Lint & Typecheck` job, ruff check + ruff format check + mypy (with `--ignore-missing-imports`), only on ubuntu-latest, no matrix, no paths filter, no Codecov
  - `tests.yml` (1256 bytes): `Tests` matrix (3.12 + 3.13) + `smoke` CLI invocation, no Codecov, no paths filter, only ubuntu-latest, no uv cache dependency-glob
- **Source**: 16 .py files in `src/kontor_cli/` (vs bug-tracking's 24). All 68 public functions have parameter and return annotations. `mypy --strict` surfaces exactly 8 errors in 3 files (verified 2026-06-04).
- **Tests**: 88 unit tests in `tests/unit/` all pass. No integration tests in CI (DavMail-required tests are gated by `integration` marker).
- **Other**:
  - `AGENTS.md` and `CLAUDE.md` both exist at root
  - `pyproject.toml` says `version = "0.1.0"`
  - `requires-python = ">=3.12"`
  - `[tool.ruff]` line-length 88, py312, selects E/F/W/I/N/UP/B/C4, ignores E501/B028
  - User feedback memory: "check target branch state before impl" — when this plan transitions to execution, the lead must `git fetch origin main` first, since a parallel PR may have merged

## Ontology (Key Entities)

| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| pyproject.toml | config | [project], [build-system], [tool.*] | Declares deps, build backend, tools |
| uv.lock | lockfile | resolved versions | Already present, generated by `uv lock` |
| .github/workflows/ci.yml | CI config | jobs, matrix, triggers, paths | Replaces both existing workflows |
| .pre-commit-config.yaml | lint config | repos, hooks | Runs on commit and CI |
| LICENSE | file | MIT, 2026, Andre Burgstahler | At root |
| CONTRIBUTING.md | doc | 5-section stub | At root |
| README.md | doc | badges, install, usage, dev | At root; updated |
| .gitignore | file | includes `.omc/`, `config.work.yaml` | At root; updated |
| src/kontor_cli/*.py | source code | modules, classes, functions | Imports from each other, called by CLI entry points |
| tests/unit/*.py | test code | test functions | Imports from src/kontor_cli/ |
| feature/kontor-cli-polish | git branch | — | Source for the PR |
| main | git branch | — | Target of the PR |
| kontor-cli | git remote | URL, branch | `git@github.com:r3dlex/kontor-cli.git` |

## Ontology Convergence

N/A — scope transfer from a fully-converged spec (bug-tracking R12: 100% stability).
No new entities introduced by this spec.

## Interview Transcript

N/A — scope transfer. The substantive Q&A is in
`deep-interview-bug-tracking-uv-and-polish.md` (Rounds 0-15). This spec documents
only the deltas required by kontor-cli's brownfield state.

### Delta Round 1 — uv cutover
**Q:** Does kontor-cli need the uv cutover sub-component from the bug-tracking spec?
**A:** No — already on uv (hatchling, py3.12). Drop the sub-component.

### Delta Round 2 — Coverage floor
**Q:** What coverage floor for `fail_under`?
**A:** 80% (lower than bug-tracking's 90% because kontor-cli has only 88 unit tests and DavMail-gated integration tests are excluded from CI; documented as a follow-up to raise to 90% if integration tests land).

### Delta Round 3 — Working tree
**Q:** Fold, revert, or leave the 4 modified files alone?
**A:** Fold into a "chore(kontor-cli): fold pre-existing changes" commit (bug-tracking precedent). Add `.omc/` and `config.work.yaml` to `.gitignore`.

### Delta Round 4 — CI workflow count
**Q:** Keep `ci.yml` and `tests.yml` separate, or consolidate?
**A:** Consolidate into one `ci.yml` (the current setup has redundant lint+typecheck runs — `tests.yml` L35-39 runs them on the matrix in addition to `ci.yml`).

### Delta Round 5 — Codecov
**Q:** Required or optional?
**A:** Optional (gated on `CODECOV_TOKEN`). The kontor-cli repo doesn't have a Codecov integration yet, and this PR shouldn't hard-fail because of it.

### Delta Round 6 — Ruff config
**Q:** Unify with bug-tracking (line-length 100, E/F/I)?
**A:** No — kontor-cli's stricter rules (N/UP/B/C4) and shorter line length are intentional. Document as drift.

## How to Apply This Spec

1. `cd /Users/andreburgstahler/Ws/Rib/kontor-cli`
2. `git fetch origin main` (per "check target branch state" memory)
3. `git checkout -b feature/kontor-cli-polish`
4. Commit in logical chunks:
   - (1) Fold pre-existing working-tree changes
   - (2) mypy --strict + type-argument fixes
   - (3) Polish files (CI/pre-commit/LICENSE/CONTRIBUTING/README badges/.gitignore/pyproject deps)
   - (4) CI consolidation (delete `tests.yml`, expand `ci.yml`)
5. Open PR as draft, run local CI, mark ready, let remote CI go green
6. Auto-merge once green
