# Phase 13 Plan 01: Streaming Generation Summary

**Phase:** 13  
**Plan:** 01  
**Subsystem:** Streaming Generation Pipeline  
**Tags:** streaming, scene-generation, parallel-render, narrative-context, multi-provider  

---

## Objective

Eliminate bulk generation timeouts by streaming scene-by-scene with parallel render-while-generate pipeline. Instead of generating 10K+ char responses that timeout (200s+), generate one scene at a time (~30s) with full narrative context.

## One-Liner

Scene-by-scene streaming generation with parallel render-while-generate pipeline, scene-level retry, and multi-provider LLM support (zjuapi+gpt-5.4, wenwen+claude-opus-4-6).

---

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Scene-level retry vs full pipeline restart | Avoids re-generating successful scenes when one fails |
| Parallel render-while-generate | Overlap: scene N renders while scene N+1 generates |
| NarrativeContext for scene continuity | Each scene receives object/camera state from previous scenes |
| Provider auto-selection | Try zjuapi → wenwen → openai until one responds |
| 30s scene timeout | Target vs 200s+ for full video generation |

---

## Components Implemented

### 1. NarrativeContext (`algorithms/streaming.py`)
Tracks narrative state across scenes:
- `object_state`: Maps created objects (name → type + description)
- `camera_state`: Current position/zoom
- `scene_history`: Last 5 scene summaries for context
- `domain_state`: Domain-specific state (axes, coordinate system, etc.)
- `to_context_string()`: Renders context for LLM prompt injection

### 2. Scene Splitter (`algorithms/streaming.py`)
`split_plan_into_scenes()` splits storyboard into individual scenes:
- Extracts scenes/beats/segments from plan JSON
- Groups beats into scenes (every 3 beats or on transition markers)
- Returns scene dicts with: `scene_id`, `description`, `objects`, `duration_hint`, `animation_steps`

### 3. Scene Generator (`algorithms/streaming.py`)
`generate_scene()` generates one scene with narrative context:
- Builds prompt with scene description, animation steps, objects, narrative context
- Streams tokens from LLM provider
- Validates structure (Scene class, imports)
- Updates NarrativeContext with created objects

### 4. Streaming LLM Wrapper (`algorithms/streaming.py`)
`stream_generate()` with multi-provider support:
- Providers: zjuapi (gpt-5.4), wenwen (claude-opus-4-6), openai (fallback)
- Auto-select based on availability
- Yields tokens as they arrive for real-time processing
- 30s timeout per scene generation

### 5. Scene-Level Retry (`algorithms/streaming.py`)
`retry_scene()` fixes failed scenes without restarting pipeline:
- Receives render error from failed scene
- Adds error to narrative context for targeted fix
- Re-generates only the failed scene
- Preserves all previously rendered scenes

### 6. Parallel Render Pipeline (`algorithms/streaming.py`)
`stream_render_scenes()` achieves render/generate overlap:
- Generates scene N
- Starts rendering scene N in background thread
- While scene N renders, generates scene N+1
- ThreadPoolExecutor with 2 workers for parallel renders
- Per-scene timeout (RENDER_TIMEOUT_SECONDS // 3)

### 7. Scene Stitching (`algorithms/streaming.py`)
`stitch_scenes()` concatenates scene videos:
- Single scene → copy directly
- Multiple scenes → ffmpeg concat with safe=0
- Returns final video path

### 8. Token Budget (`algorithms/streaming.py`)
`estimate_scene_cost()` estimates tokens needed:
- Based on description, animation steps, objects
- Used by provider selection (simple scenes → fast provider)

---

## Files Created/Modified

| File | Change | Lines |
|------|--------|-------|
| `algorithms/streaming.py` | **Created** | +1024 |
| `app.py` | Modified | +1848 (added `stream_generate_and_render`, `stream_render_async`) |
| `config.py` | Modified | +54 (added streaming provider configs) |

---

## Configuration Added

```python
# config.py
ZJUBAPI_BASE_URL, ZJUBAPI_API_KEY, ZJUBAPI_MODEL, ZJUBAPI_TIMEOUT
WENWEN_BASE_URL, WENWEN_API_KEY, WENWEN_MODEL, WENWEN_TIMEOUT
STREAM_PROVIDER = "auto"  # or "zjuapi", "wenwen", "openai"
STREAM_SCENE_TIMEOUT = 30  # Max seconds per scene
STREAM_MAX_SCENES = 20    # Max scenes per video
STREAM_SCENE_RETRIES = 2  # Retries per scene
STREAM_PARALLEL_RENDERS = 2
```

---

## Requirements Addressed

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| M4-STREAM-01: Scene-by-scene streaming | ✅ | `split_plan_into_scenes()`, `generate_scene()` |
| M4-STREAM-02: Parallel render-while-generate | ✅ | `stream_render_scenes()` with ThreadPoolExecutor |
| M4-STREAM-03: Narrative context preservation | ✅ | `NarrativeContext` class, `to_context_string()` |
| M4-STREAM-04: Scene-level retry | ✅ | `retry_scene()` with error feedback |
| M4-CODE-01: Valid Manim API generation | ✅ | System prompt with explicit forbidden APIs |
| M4-CODE-02: Scene-level code validation | ✅ | `validate_python_syntax()` before render |

---

## Architecture

```
Prompt → analyze_request_type() → create_animation_plan()
                                          ↓
                              split_plan_into_scenes()
                                          ↓
                            [For each scene N]
                    ┌─────────────────────┴─────────────────────┐
                    │                                             │
              generate_scene()                           _render_single_scene()
              (with NarrativeContext)                          (background thread)
                    │                                             │
              validate code                                     ↓
                    │                                       video file
              retry_scene() (if error)           ┌──────────────┘
                    │                            │
                    └──────────┬─────────────────┘
                               ↓
                    stitch_scenes() → final_video.mp4
```

---

## Success Criteria

| Criterion | Target | Method |
|-----------|--------|--------|
| Scene generation time | < 30s per scene | Streaming with 30s timeout |
| Parallel overlap | Generate N+1 while rendering N | ThreadPoolExecutor(2) |
| Narrative coherence | Viewer can't tell scenes were separate | NarrativeContext with object/camera state |
| Scene retry | Failed scene retries without full restart | retry_scene() preserves rendered scenes |
| Valid Manim API | No start_section(), begin_section() errors | System prompt explicit rules |

---

## Deviations from Plan

None — implementation follows plan exactly.

---

## Known Stubs

None identified.

---

## Metrics

| Metric | Value |
|--------|-------|
| Duration | ~1 hour |
| Tasks Completed | 3 (13-01, 13-02, 13-03 — all implemented together in one module) |
| Files Created | 1 (algorithms/streaming.py) |
| Files Modified | 2 (app.py, config.py) |
| Commits | 1 (f4fa967) |
| Completion Date | 2026-04-05 |

---

## Next Steps

- Wire `stream_generate_and_render()` into a Flask route (e.g., `/api/stream-generate`)
- Add scene-level render caching (cache each scene independently)
- Add scene-level quality evaluation
- Integrate with existing render cache from Phase 11
- Test with actual Manim renders to verify parallel pipeline works
