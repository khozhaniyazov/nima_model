# Contributing to NIMA

Quick guide for making changes that flow cleanly through CI and review.

## Project layout

- `app.py` — Flask app factory, **thin**. Don't put logic here.
- `algorithms/` — service modules and pipeline stages (generation, render, stream, webhooks, job lifecycle, planning, RAG glue, etc.).
- `api_routes/` — Flask blueprints (one per area: core, batches, media, templates, webhooks, api_keys, lti, payload).
- `config.py` — single source of env reads. All other modules import from here; **don't call `os.getenv`/`os.environ` elsewhere**.
- `tests/` — pytest suites. ~5s to run all of them.
- `scripts/` — dev tools and live-backend reliability harnesses (these are NOT pytest).
- `docs/` — design notes; `.planning/phases/NN-name/` — phase plans.

## Setup

```bash
python -m pip install -r requirements.txt
cp .env.example .env   # fill in OPENAI_API_KEY at minimum
```

For lint/format work also install ruff:

```bash
pip install ruff
```

## Workflow

Every non-trivial change goes through a PR (see also: `feedback_pr_workflow.md` in agent memory). Direct push to `main` is reserved for trivial typo/doc-only fixes.

1. Branch with a conventional prefix:
   - `feat/<thing>` — user-visible feature
   - `fix/<thing>` — bugfix
   - `chore/<thing>` — repo hygiene, lint, deps
   - `docs/<thing>` — docs only
   - `refactor/<thing>` — internal restructure, no behavior change
   - `ci/<thing>` — workflow / pipeline
2. Make atomic commits. One logical change per commit. Use conventional-commit-style messages with a `**Why:**` paragraph for anything non-obvious — future-you needs the reason, not just the diff.
3. Before pushing, run locally:
   ```bash
   ruff check .
   pytest tests/
   ```
   Both must pass.
4. Push and open a PR via `gh pr create` (use `--body-file` for the body — caret-escaping in `cmd.exe` mangles `--body` strings). Title uses the same conventional prefix.
5. Wait for CI to go green. Failures are not optional — investigate via `gh run view --job=<id> --log-failed`.
6. Squash-merge: `gh pr merge <n> --squash --delete-branch`. The squash commit's title becomes the public history entry, so make it good.

## What CI runs

`.github/workflows/test.yml`:

- **Lint** — `ruff check .` (config in `pyproject.toml`).
- **Pytest** — `pytest tests/` against Python 3.11 with `USE_DATABASE=false` and `OPENAI_API_KEY=test`. Heavy live-backend reliability harnesses are NOT in `tests/`; they live in `scripts/` and run manually.
- **Pipeline mode smoke (DRAFT/FAST/FULL)** — `import config` with each pipeline-mode env combination to make sure config bootstrapping doesn't crash.
- **Benchmark** — manual (`workflow_dispatch`); runs `scripts/benchmark.py`.

System deps for `manim` build are installed in CI (`pkg-config`, `libpango1.0-dev`, `libcairo2-dev`, `ffmpeg`).

## Architecture rules (enforced by review)

- **`app.py` is a thin Flask factory.** Logic belongs in `algorithms/` and routes in `api_routes/`.
- **`config.py` is the only env reader.** Other modules import constants from `config`.
- **Tests under `tests/`, dev scripts under `scripts/`, design docs under `docs/`, phase plans under `.planning/phases/NN-name/`.**
- **Never commit secrets.** `.env` is gitignored; defaults in `config.py` must be empty for credential-shaped values.

## Testing tips

- `pytest tests/` runs the full suite (~5s, 197 tests today).
- A single test file: `pytest tests/test_streaming_split.py -v`.
- A single test by name: `pytest tests/ -k "scene_quality_warning"`.
- Live-backend reliability checks: `python scripts/reliability_streaming.py` (requires the Flask server running).

## Reporting bugs / requesting features

Open an issue with:

- A minimal reproducer (prompt + mode if it's a generation issue; payload if it's an API issue).
- Expected vs. actual.
- Relevant log excerpt from `flask.log` or `manim_generator.log` if available.
