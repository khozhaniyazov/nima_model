# Contributing to NIMA

Thanks for your interest! NIMA is an open-source (Apache-2.0) AI Manim generator. External contributions are welcome — bug reports, feature PRs, docs fixes, tests, all fair game.

This guide covers the workflow the project uses internally so your PR lines up with what reviewers expect.

---

## Quick dev setup

```bash
git clone https://github.com/khozhaniyazov/nima_model.git
cd nima_model
python -m pip install -r requirements.txt
cp .env.example .env              # fill in OPENAI_API_KEY at minimum
```

For lint/format:

```bash
pip install ruff
```

Optional: install pre-commit hooks so checks run before each commit:

```bash
pip install pre-commit
pre-commit install
```

Running tests:

```bash
ruff check .
pytest tests/ -q                  # 352 tests, ~5 s
```

Both must pass before you push.

---

## Workflow

Non-trivial changes flow through a PR. Direct push to `main` is reserved for trivial typo/doc-only fixes.

1. **Branch** with a conventional prefix:
   - `feat/<thing>` — user-visible feature
   - `fix/<thing>` — bugfix
   - `chore/<thing>` — repo hygiene, lint, deps
   - `docs/<thing>` — docs only
   - `refactor/<thing>` — internal restructure, no behavior change
   - `ci/<thing>` — workflow / pipeline
2. **Atomic commits.** One logical change per commit. Use conventional-commit-style messages. Include a `Why:` paragraph for anything non-obvious — future readers need the reason, not just the diff.
3. **Link to an issue** if one exists. Use `Closes #N` in the PR body when the PR fully resolves the issue.
4. **Open a PR** via `gh pr create` (or the GitHub UI). The PR body should cover:
   - **What** — the change, one short paragraph.
   - **Why** — the motivation or bug being fixed.
   - **Testing** — what you ran locally and what passed.
   - **Risk** — anything reviewers should double-check.
5. **Self-review** — read your own diff one more time before handing it off. If something in the diff surprises you, it will surprise the reviewer too.
6. **Squash-merge** after approval: `gh pr merge <n> --squash --delete-branch`.

---

## CI note

The repository does not currently run hosted CI (GitHub Actions). `ruff check .` and `pytest tests/` run locally are the contract — if they pass, the PR is ready for review. If you want to propose re-enabling Actions, open an issue first so the setup can be sorted.

---

## Architecture rules (enforced by review)

- **`app.py` is a thin Flask factory.** Business logic belongs in `algorithms/` and HTTP concerns in `api_routes/`. Don't grow `app.py`.
- **`config.py` is the primary env reader.** Other modules import constants from `config`. New env-driven knobs go in `config.py` first, then get imported where needed. The documented exception is `NIMA_LANGUAGE_LOCK`, which is read at call-time in `algorithms/i18n.py` and `algorithms/streaming_providers.py` so per-request language switches don't require a process restart — only follow that pattern if you need the same runtime-mutable behaviour.
- **Tests under `tests/`.** Dev / reliability scripts under `scripts/`. Design docs under `docs/`. Phase plans under `.planning/phases/NN-name/`.
- **Never commit secrets.** `.env` is gitignored; defaults in `config.py` must be empty for credential-shaped values. If `USE_DATABASE=true`, `DB_CONNECTION_STRING` is mandatory and `config.py` will fail fast at import time.

---

## Streaming-layer refactors

The streaming pipeline (`algorithms/streaming*.py`) is split across multiple modules. If you touch it, keep the following invariants:

- **Leaf modules must not import `algorithms.streaming` at module-load time.** This would create a cycle during streaming.py's own load. Use `from __future__ import annotations` + `TYPE_CHECKING` for type hints.
- **Test monkey-patches of `streaming.<name>`** must keep firing after moves. Every new module that calls a name the test suite monkey-patches routes through a lazy `_s()` helper (`from algorithms import streaming as _streaming; return _streaming`) inside the call site. See `algorithms/streaming_orchestration.py` for the canonical pattern.
- **Back-compat via re-exports.** When you move a symbol, re-export it from `algorithms/streaming.py` so callers using the old import path keep working.

---

## Testing tips

- `pytest tests/` runs the full suite (~5 s).
- One file: `pytest tests/test_streaming_split.py -v`.
- One test by name: `pytest tests/ -k "scene_quality_warning"`.
- Live-backend reliability checks: `python scripts/reliability_streaming.py` (requires the Flask server running).

---

## Reporting bugs / asking for help

Open a [GitHub issue](https://github.com/khozhaniyazov/nima_model/issues) with:

- What you ran and what happened.
- What you expected.
- Environment: Python version, OS, Manim version (`manim --version`), ffmpeg version (`ffmpeg -version`).
- A minimal reproducing prompt or snippet if possible.

For security issues (credentials, arbitrary code exec through prompts, etc.), please do NOT open a public issue — email `saparbayevskii@gmail.com` instead.

---

## Code of conduct

Be respectful. No personal attacks, no discriminatory language, no bad-faith argumentation. If someone's response is unclear, ask for clarification before assuming intent. The maintainers reserve the right to close discussions that derail.
