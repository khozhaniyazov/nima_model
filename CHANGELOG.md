# Changelog

## Unreleased

### Changed
- `STREAM_PROVIDER_TOTAL_TIMEOUT` default raised from 90s to 120s. With `gpt-5.4` on `zjuapi.com` and 2200-token caps, per-scene generation routinely lands at 40-90s; the previous 90s default tripped `_partial_scene_content_is_usable` on later scenes even when the provider was healthy. Operators on faster providers can override via env. Closes #9.
- `_render_short_final_fallback` now reuses scenes that are already marked `_generation_source == "deterministic_short_fallback"` and have a valid prior MP4 on disk, instead of re-rendering them. Reduces wall-clock when the per-scene fallback already produced output that the job-level retry would regenerate identically. Closes #10.

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
