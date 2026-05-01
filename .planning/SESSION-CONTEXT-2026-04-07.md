# Session Context - 2026-04-07

## Current Goal

Make the streaming pipeline good enough for long-form educational videos, not just short clips.

## What Is Working

- Streaming scene-by-scene generation is wired into `/api/generate`
- Render-while-generate overlap works
- Per-scene TTS generation works via `edge-tts`
- Per-scene audio/video mux works
- Repetition reporting exists in job status and harness output
- Stream reports are persisted to `C:\temp\outputs\stream_reports\<job_id>.json`
- Reliability harness exists: `test_streaming_reliability.py`
- Edge-case harness exists: `test_edge_cases.py`
- Report summarizer exists: `summarize_stream_reports.py`
- Backend render templates exist and are selected automatically by topic/domain
- **Video mode system implemented** — 4 modes with distinct behaviour (see below)

## Main Problems Still Being Solved

### 1. Final stitched video audio can still be broken — ✅ FIXED

**Fix applied:**
- `stitch_scenes()` in `algorithms/streaming.py` now normalizes every clip into a consistent intermediate format before concat:
  - video: `libx264`, `yuv420p`, `30 fps`, even pixel dimensions
  - audio: `aac`, `44100 Hz`, stereo
  - adds `+genpts` flag to final concat for clean PTS
- Intro/outro silent-audio clips in `app.py` now also normalize to the same standard (was previously `copy` video codec, now re-encodes to match)
- Temp normalized clips are cleaned up after stitch

### 2. Fallback narrated-plan path is still semantically weak — ✅ IMPROVED

**Fix applied:**
- `create_narrated_plan()` fallback in `algorithms/request_analysis.py` now:
  - Deduplicates subtopics before building segments
  - Uses per-scene helper functions (`_build_fallback_segment_narration`, `_build_fallback_visual_description`) that vary phrasing by position (opening / middle / closing)
  - Middle scenes explicitly tie their subtopic back to the main topic instead of using identical generic phrasing
  - Fills to a minimum of 4 segments when analysis is sparse, with sensible defaults ("intuition", "worked example", "common mistake", "takeaway")

### 3. Reliability for long course-style prompts is mixed

Observed:
- Short/medium prompts are much stronger now
- Broad course prompts can still lose scenes or timeout in the harness
- Example report summary showed only 4/13 historical jobs were full-scene successes, though recent batches improved

Important nuance:
- Many runs now produce usable final videos even when some scenes fail
- But the real target is 10 meaningful complete renders in a row, not just 10 technically completed stitched videos

### 4. Scene failure reporting improved but still needs refinement — ✅ IMPROVED

**Fix applied:**
- `classify_render_error()` in `algorithms/streaming.py` expanded from 6 patterns to 18+ patterns, covering:
  - `name_error`, `attribute_error`, `type_error`, `latex_error`, `value_error`, `import_error`, `recursion_error`, `zero_division`, `ffmpeg_error`, `memory_error`, `key_error`, `rendering_engine_error`, `video_not_found`
- `summarize_stream_reports.py` `classify_signature()` synced to same expanded pattern set
- `scene_results` builder in `app.py` now:
  - Also checks `completed_renders` for failed scenes that the `errors` list missed (recovery-swallowed errors)
  - Adds `error_type` field to each failed scene result
  - Provides a human-readable default ("Scene did not produce a video") instead of `null` for scenes with no explicit error message
- Summarizer now also counts per-scene `error_type` from `scene_results` (not just top-level `errors`)

### 5. Long-form support is not fully implemented yet

Important clarification:
- The system is not yet truly designed for 10-15 minute course videos by default
- Current analyzer/planner usually targets ~300-420s and medium scene counts
- Need explicit long-form support later:
  - `target_duration`
  - `course_mode`
  - longer duration buckets (600s / 900s / 1200s)
  - more scenes with lower per-scene complexity

## Current Testing Commands

### Start backend

```bash
cd C:\ai-manim
python app.py
```

### Start frontend

```bash
cd C:\ai-manim\nima-frontend
npm run dev
```

### Reliability sweep (broad course-style prompts by default)

```bash
cd C:\ai-manim
python test_streaming_reliability.py --count 3 --voiceover --branding --timeout 1800
```

### Edge-case sweep

```bash
cd C:\ai-manim
python test_edge_cases.py --count 5 --voiceover
```

### Summarize all saved reports

```bash
cd C:\ai-manim
python summarize_stream_reports.py
```

## Current Prompt Pools

- `prompt_pool.py` now exists
- `EDGE_PROMPTS`: narrow failure-mode probes
- `COURSE_PROMPTS`: broader lesson-style prompts
- `LONG_RUN_PROMPTS`: combined pool
- `test_streaming_reliability.py` defaults to `course` pool now

## Video Mode System — ✅ IMPLEMENTED

Four distinct video modes selected via API parameter `mode`:

### `short` — Instagram/TikTok (55-60s)
- **Duration:** 55-60s strict
- **Aspect:** 9:16 vertical (render pipeline TBD, framework ready)
- **Scenes:** 2-4
- **Questions:** Exactly 1 at end → "Type your answer in the comments!"
- **Style:** punchy, hook-first, social-media-friendly
- **Complexity cap:** BASIC

### `standard` — Default (2-5 min)
- **Duration:** 120-300s (target 240s)
- **Aspect:** 16:9
- **Scenes:** 4-12
- **Questions:** None — pure information delivery
- **Style:** clear, educational, well-paced

### `course` — Educational (≈15 min)
- **Duration:** 600-900s (target 900s)
- **Aspect:** 16:9
- **Scenes:** 8-20
- **Questions:** 3-6 open questions spaced throughout, 10s thinking pause each
- **Style:** thorough, builds intuition, recap transitions

### `lecture` — University (30+ min) — STUBBED
- **Duration:** 1200-2400s (target 1800s) — capped at 900s until full implementation
- **Aspect:** 16:9
- **Scenes:** 15-40
- **Questions:** 5-12 lecture-style questions
- **Style:** formal academic, thorough derivations

### How It Works
- API: `POST /api/generate` with `"mode": "short"` (or `standard`, `course`, `lecture`)
- If no mode specified, defaults to `standard`
- Mode overrides analysis duration and complexity cap
- `create_narrated_plan()` receives mode-specific LLM system prompt with question rules
- `_enforce_question_rules()` post-processes the plan to guarantee question count/placement
- Scene count is clamped to mode min/max
- Report includes `video_mode` field for analysis

### What's NOT Done Yet
- Vertical (9:16) rendering for short mode — needs Manim render resolution change
- Frontend mode selector UI
- Full lecture mode (30+ min) implementation — currently caps at 15 min
- Duration heuristic also improved independently: scales with topic count + breadth signals

## Current Backend Template System

Templates currently include:
- `dark-blueprint`
- `dark-cinema`
- `light-notebook`
- `light-minimal`
- `dark-linalg`
- `dark-graph`
- `light-calculus`
- `light-discrete`
- `dark-physics`
- `light-cs`
- `dark-game-theory`
- `light-proof`

Template routing was improved so game-theory keywords win before generic matrix routing.

## Intro/Outro Status

- Backend intro/outro support was added to streaming path
- Intro/outro settings are passed through the API now
- Intro/outro clips are rendered as title cards
- Silent audio added AND now fully normalized (libx264/yuv420p/30fps/aac/44100Hz/stereo) to match scene clips
- Intro/outro clips should now stitch cleanly with narrated scene clips

## Most Recent Important Insight

The mode system is now the primary way to control video output characteristics.

**Next priorities:**
- Test each mode with real renders to validate duration/question/scene count
- Build vertical (9:16) render support for short mode
- Add frontend mode selector
- Full lecture mode implementation (30+ scenes, chunked generation)

## Recommended Next Fix Order

1. ~~Normalize all clips before final stitch~~ ✅ Done
2. ~~Improve fallback narrated-plan quality~~ ✅ Done
3. ~~Tighten failed-scene reason propagation~~ ✅ Done
4. ~~Implement video mode system~~ ✅ Done
5. Run reliability sweep per mode to validate
6. Build vertical render support for short mode
7. Frontend mode selector
8. Full lecture mode implementation
