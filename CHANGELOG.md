# Changelog

## Unreleased

## [0.1.0] — 2026-05-11 — First public release

First publicly-visible release of NIMA. The repository moved from private to public and was placed under Apache-2.0. No behavioural changes from the preceding private builds; this tag marks the visibility + licensing milestone.

### Added
- `LICENSE` — Apache License 2.0.
- `NOTICE` — third-party attribution for vendored `training/3b1b/videos` (CC BY-NC-SA 4.0, git submodule) and the `skills/` bundles.
- `SECURITY.md` — vulnerability reporting policy (private email).
- `.github/ISSUE_TEMPLATE/` — structured bug-report and feature-request forms.
- `.gitmodules` — `training/3b1b/videos` registered as a proper submodule of `https://github.com/3b1b/videos` (pinned at `27ec045`). Not populated by default on fresh clones.

### Changed
- `readme.md` rewritten for a public audience: quickstart, feature list, architecture overview, configuration table, known limitations, license.
- `CONTRIBUTING.md` rewritten in external-contributor voice; internal workflow invariants (branch prefixes, atomic commits, streaming-layer `_s()` rule) preserved.
- Streaming pipeline refactor from issue #11 (with follow-up #59) concluded: `algorithms/streaming.py` shrunk from ~5,953 LoC to 1,041 LoC across seven focused modules (`streaming`, `streaming_orchestration`, `streaming_providers`, `streaming_prompts`, `streaming_render`, `streaming_validation`, `streaming_fallbacks`). Landed across PRs #16, #57, #58, #60, #61, #62.
- `STREAM_PROVIDER_TOTAL_TIMEOUT` default raised from 90s to 120s. With `gpt-5.4` on `zjuapi.com` and 2200-token caps, per-scene generation routinely lands at 40–90s; the previous 90s default tripped `_partial_scene_content_is_usable` on later scenes even when the provider was healthy. Operators on faster providers can override via env. Closes #9.
- `_render_short_final_fallback` now reuses scenes that are already marked `_generation_source == "deterministic_short_fallback"` and have a valid prior MP4 on disk, instead of re-rendering them. Reduces wall-clock when the per-scene fallback already produced output that the job-level retry would regenerate identically. Closes #10.

### Fixed
- Standard / course / lecture modes no longer raise `RuntimeError` on a final-QA aesthetic flag after an otherwise-successful render. They now ship the video with `partial=true` and a `final_quality_reason` on the payload. Hard-integrity failures (mostly-blank frames, OCR overlap ≥ 0.5) still raise. Closes #19 (PR #23).
- Layout-gate-classified first-attempt failures now trigger the surgical-retry addendum from PR #7 before falling through to the deterministic fallback. Previously `scene_retries=1` in speed modes meant the in-loop retry never fired, and every layout-classified failure was silently rescued by the deterministic renderer at full LLM cost. Closes #20 (PR #24).
- LTI 1.3 blueprint feature-flagged off by default (`NIMA_LTI_ENABLED=false`) in PR #55 — all six `/api/lti/*` routes 503 until the flag is explicitly enabled. Real JWKS fetch + `iss`/`aud`/`exp`/nonce signature verification remains unimplemented; the feature flag closes the exposure surface while a proper implementation is designed. Closes #43.

### Removed
- `.github/workflows/test.yml` — hosted CI was left dead due to the repository's Actions billing being intentionally off. Local `ruff check .` + `pytest tests/` is now the documented contract; pre-commit hooks run the same checks.

## 2026-03-10

### Added
- Static overlap/scene-hygiene checks (`algorithms/overlap_detector.py`) to flag:
  - repeated placements at the same position without cleanup
  - object accumulation (lots of Create/Write/FadeIn without FadeOut)
  - missing section cleanup between comment-delimited sections
  - long construct() complexity without lifecycle helpers
  - stale `.copy()` usage where originals are not removed
- Deterministic plan scaffolding (v1): `algorithms/plan/*` (compiler + schema).

### Changed
- Upgraded injected layout helpers (`LAYOUT_HELPERS`) with explicit section lifecycle tools.
- Tightened generation/review rules to enforce scene hygiene (fadeouts between steps).
- Wired overlap detection into `app.py` generation pipeline with a one-pass auto-fix loop.

### Fixed
- Overlap detector now catches chained constructor placements like `MathTex(...).move_to(ORIGIN)`.

- Added unified LLM call routing: chat models use `chat.completions`, codex uses `responses` API.
- Updated request analysis + generation/review/fix/polish/eval paths to use the unified router.
