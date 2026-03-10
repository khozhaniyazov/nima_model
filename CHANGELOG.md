# Changelog

## Unreleased

## 2026-03-10

### Added
- Static overlap/scene-hygiene checks (`algorithms/overlap_detector.py`) to flag:
  - repeated placements at the same position without cleanup
  - object accumulation (lots of Create/Write/FadeIn without FadeOut)
  - missing section cleanup between comment-delimited sections
  - long construct() complexity without lifecycle helpers
  - stale `.copy()` usage where originals are not removed
- Deterministic plan scaffolding (v1): `algorithms/plan/*` and `layout/engine.py`.

### Changed
- Upgraded injected layout helpers (`LAYOUT_HELPERS`) with explicit section lifecycle tools.
- Tightened generation/review rules to enforce scene hygiene (fadeouts between steps).
- Wired overlap detection into `app.py` generation pipeline with a one-pass auto-fix loop.

### Fixed
- Overlap detector now catches chained constructor placements like `MathTex(...).move_to(ORIGIN)`.

- Added unified LLM call routing: chat models use `chat.completions`, codex uses `responses` API.
- Updated request analysis + generation/review/fix/polish/eval paths to use the unified router.
