<!--
Title: use a conventional prefix:
  feat: | fix: | chore: | docs: | refactor: | ci: | test: | style:
-->

## Why

<!-- What problem does this PR solve? Link an issue if there is one. -->

## What changed

<!-- Bullet the atomic commits or the high-level changes. Keep it short. -->

-
-

## Verification

- [ ] `ruff check .` passes locally
- [ ] `pytest tests/` passes locally (197 tests as of last count)
- [ ] CI is green on this PR

## Risk / blast radius

<!--
Pick one:
- Local-only (e.g., docs, lint config, tests)
- Touches the generation pipeline (algorithms/* / api_routes/*) — what's the rollback story?
- Touches infrastructure (CI, env handling, deps)
-->

## Out of scope (deliberately)

<!-- Optional: list things you noticed but chose not to fix here, with a one-line reason. -->
