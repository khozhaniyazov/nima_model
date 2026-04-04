# NIMA Architecture

**Analysis Date:** 2026-04-04

## System Overview

**NIMA** (Manim AI Generator) is an AI-powered educational animation generation system. It accepts natural language prompts and produces Manim-rendered videos.

**Architecture Pattern:** Layered pipeline with async render workers

**High-Level Flow:**
```
User Prompt → [Next.js Frontend] → [Flask API] → [AI Pipeline] → [Manim Renderer] → [Video Output]
                              ↓                                                    ↓
                        [PostgreSQL DB]                              [FFmpeg Merge (TTS)]
```

---

## Component Boundaries

### Frontend — Next.js (`nima-frontend/`)

**Role:** React 19 SPA for prompt entry, status monitoring, and video playback.

**Key Files:**
- `src/app/page.tsx` — main UI component

**Boundaries:**
- Communicates exclusively with Flask via HTTP REST
- No direct database access
- No direct file system access
- No Manim dependency

**API Endpoints Consumed:**
| Endpoint | Purpose |
|----------|---------|
| `POST /api/generate` | Submit animation request |
| `GET /status/<job_id>` | Poll job status |
| `GET /api/prompts?n=4` | Fetch example prompts |
| `GET /stats` | Display system telemetry |
| `GET /outputs/<file>` | Stream/playback rendered video |

---

### Backend — Flask (`app.py`)

**Role:** REST API + orchestration engine. Coordinates the full pipeline from prompt → rendered video.

**Boundaries:**
- Owns all file I/O (scripts dir, outputs dir)
- Owns all subprocess calls to `manim` CLI
- Owns all OpenAI API calls
- Manages job state in-memory (`render_status` dict)
- Optional PostgreSQL via `ManimDatabase` class

**Key Internal Classes:**
- `ManimDatabase` — PostgreSQL wrapper (connection, CRUD for requests/attempts/jobs/evaluations)
- Module-level `render_status: Dict[str, dict]` — in-memory job tracking
- Module-level `job_to_request: Dict[str, dict]` — job → request mapping

**Key Functions:**
- `generate_and_validate_code()` — full AI pipeline (analyze → plan → generate → review → validate)
- `save_and_render()` — render loop with self-healing retry
- `render_async()` — daemon thread wrapper for background rendering
- `_run_manim()` — writes script + spawns `manim` subprocess

---

### AI Pipeline (`algorithms/`)

All AI logic lives here. Flask imports and calls these functions.

#### `request_analysis.py`
**Role:** Prompt classification + animation planning.

Functions:
- `analyze_request_type(prompt)` → returns classification dict (type, domain, complexity, topic, subtopics, duration, depth)
- `create_animation_plan(prompt, analysis)` → LLM-generated storyboard text
- `create_narrated_plan(prompt, analysis)` → JSON timeline with TTS narration segments
- `create_plan_json(prompt, analysis, template_name)` → deterministic JSON plan for compiler
- `expand_short_prompt(prompt)` → expands truncated problem statements

**Boundary:** Stateless. Returns data structures. Does not write files or call render.

#### `ai_functions.py`
**Role:** Core LLM calls for code generation, review, and error fixing.

Functions:
- `generate_manim_code(prompt, analysis, plan, attempt, db, segment_durations)` → Manim Python code
- `review_and_fix(code, prompt, analysis)` → single-pass review fixing all issues
- `fix_render_error(code, stderr, prompt)` → targeted fix for render failures
- `polish_manim_code(code)` → lightweight syntax fixer
- `evaluate_with_gpt4(code, video_path, prompt, execution_data)` → quality scoring
- `inject_helpers(code)` → prepends layout helper functions

**Boundary:** All OpenAI API calls centralized here. Accepts DB reference for RAG retrieval.

#### `code_digest.py`
**Role:** Static validation — no LLM calls, pure AST + regex analysis.

Functions:
- `ensure_scene_class(code)` → wraps raw code in `GeneratedScene(Scene)` class
- `validate_python_syntax(code)` → `ast.parse()` check
- `validate_names_and_imports(code)` → security: forbids dangerous imports/calls
- `validate_manim_code(code)` → structural check (import, class, construct, play calls)
- `check_code_quality(code)` → non-blocking quality heuristics (timing, cleanup, MathTex indexing)
- `validate_latex_strings(code)` → LaTeX brace matching and common errors

**Boundary:** Read-only code inspection. Returns `(bool, issues_list)`.

#### `error_parser.py`
**Role:** Parses Manim stderr into structured error dicts.

Functions:
- `parse_manim_error(stderr)` → returns dict with `error_type`, `error_message`, `line_number`, `code_context`, `fix_hint`
- `format_error_for_prompt(parsed)` → formats for LLM injection

#### `overlap_detector.py`
**Role:** Static layout/hygiene analysis before rendering.

Functions:
- `detect_position_collisions(code)` → multiple objects at same position without FadeOut
- `detect_object_accumulation(code)` → too many creates without cleanup
- `detect_missing_section_cleanup(code)` → comment-section headers without FadeOut
- `detect_long_construct(code)` → construct() too long without section helpers
- `detect_stale_copies(code)` → `.copy()` without removing original
- `run_all_checks(code)` → runs all above

#### `tts.py`
**Role:** Text-to-speech generation + audio/video merging.

Functions:
- `generate_segment_audio(text, output_path, voice)` → calls OpenAI TTS API
- `generate_voiceover(segments, output_dir, voice)` → parallel TTS for all segments
- `merge_audio_video(video_path, audio_segments, segment_order, output_path)` → ffmpeg concat + merge

**Boundary:** File I/O (writes MP3 files). Calls `ffmpeg` subprocess.

#### `plan/compiler.py`
**Role:** Deterministic JSON plan → Manim code compiler.

Functions:
- `compile_plan(plan_dict)` → emits safe Manim Python from structured plan
- `compile_plan_json(plan_json)` → JSON wrapper

**Security:** Treats plan as data. Only emits known-safe Manim code patterns. No arbitrary code execution.

#### `plan/schema.py`
**Role:** Plan JSON schema definitions + validation.

Functions:
- `validate_plan_dict(data)` → validates required keys, object IDs, beats
- `adapt_from_narrated_segments(narrated)` → backward-compat adapter for narrated plan format

#### `template_registry.py`
**Role:** Figma-derived layout blueprints for deterministic plan generation.

Functions:
- `choose_template(prompt, domain)` → selects appropriate template by keyword matching

Templates: `two_panel_comparison`, `definition_to_example`, `step_by_step_derivation`, `graph_and_formula`, `mapping_diagram`

#### `RAG/RAG_system.py`
**Role:** Pattern retrieval from curated corpus + optional DB examples.

Functions:
- `retrieve_patterns(domain, topic, subtopics, limit)` → keyword-matched pattern retrieval from `CORPUS`
- `retrieve_golden_example(domain, topic, subtopics, db)` → formats patterns + DB examples for prompt injection

**Corpus:** 30+ proven Manim CE patterns (function graphing, ValueTracker, linear transformation, sorting algorithms, etc.) loaded from `training/manim_examples_raw.json`.

---

### Database — PostgreSQL

**Schema:** `database_schema.sql`

Tables:
| Table | Purpose |
|-------|---------|
| `requests` | User prompts + analysis metadata |
| `generation_attempts` | Per-attempt code, plan, quality feedback |
| `render_jobs` | Render status, stderr/stdout, video path, error type |
| `ai_evaluations` | Quality scores across 6 dimensions |
| `error_patterns` | Known error signatures + fix recipes |
| `training_examples` | High/low quality examples for future training |

**Boundary:** Flask reads/writes via `ManimDatabase` class. Algorithm functions receive `db` reference optionally.

---

### External Dependencies

| Dependency | Purpose |
|------------|---------|
| **OpenAI API** | LLM calls (GPT-4o codex for generation, GPT-4o-mini for fast tasks) |
| **Manim CE** | `manim` CLI — renders Python scene code to video |
| **FFmpeg** | Audio concatenation + video merge for voiceover pipeline |
| **PostgreSQL** | Persistent storage of requests, attempts, evaluations |
| **dotenv** | Environment variable loading |

---

## Data Flow

### Pipeline: `generate_and_validate_code()` (Full AI pipeline)

```
Input: prompt string
       job_id
       voiceover: bool
       max_attempts: int

Output: (code, attempts_log, request_id, attempt_id, audio_segments, segment_order)
```

**Step 1 — Analysis**
```
prompt → request_analysis.analyze_request_type() → analysis dict
```
Classifies: type, complexity, topic, subtopics, duration, depth, domain, approach

**Step 2 — Planning**
```
(voiceover=False): analysis → request_analysis.create_animation_plan() → plan (storyboard text)
(voiceover=True):  analysis → request_analysis.create_narrated_plan() → JSON segments
                   → tts.generate_voiceover() → audio_segments dict
```
If `FAST_PIPELINE`/`DRAFT_PIPELINE` + math domain + no voiceover:
```
prompt + analysis → request_analysis.create_plan_json()
                  → plan/schema.validate_plan_dict()
                  → plan/compiler.compile_plan() → code (deterministic, skips LLM)
```

**Step 3 — Code Generation (loop over attempts)**
```
prompt + analysis + plan → ai_functions.generate_manim_code() → raw Manim code
```

**Step 4 — Validation (per attempt)**
```
code → code_digest.validate_python_syntax()     → syntax check
     → code_digest.validate_names_and_imports() → security check
     → code_digest.validate_manim_code()        → structure check
     → code_digest.check_code_quality()         → quality heuristics
     → code_digest.validate_latex_strings()     → (math domain) LaTeX check
     → overlap_detector.run_all_checks()        → layout hygiene
```
On critical error: `ai_functions.review_and_fix()` → fix + re-validate

**Step 5 — Optional Voiceover Merge**
```
rendered_video + audio_segments + segment_order → tts.merge_audio_video() → narrated video
```

### Render Pipeline: `save_and_render()`

```
Input: code, filename, job_id, request_id, prompt, attempt_id, audio_segments, segment_order

Loop (up to MAX_RENDER_RETRIES = 3):
  1. _run_manim(code, filename, job_id)
       → writes code to MANIM_SCRIPTS/<filename.py>
       → spawns: manim <script> GeneratedScene -ql --format=mp4 ...
       → returns CompletedProcess (returncode, stdout, stderr)
  
  2. find_video_file(filename)
       → checks OUTPUTS/ for .mp4 (Manim writes to various subdirs)
  
  3a. SUCCESS (video found):
       → if audio_segments: tts.merge_audio_video()
       → save_render_job(status='done')
       → if not fast: evaluate_with_gpt4() → save_ai_evaluation()
       → return
  
  3b. FAIL (returncode != 0 or no video):
       → parse_manim_error(stderr) → error_parser.format_error_for_prompt()
       → ai_functions.fix_render_error(code, stderr, prompt) → fixed code
       → re-validate syntax
       → retry loop
```

### Frontend → Flask Communication

```
1. POST /api/generate {prompt, voiceover}
   → Returns {job_id} immediately (async)
   → Frontend starts polling /status/<job_id>

2. GET /status/<job_id>
   → Returns {status: "generating"|"rendering"|"done"|"error", message, video_file?}

3. GET /outputs/<video_file>
   → Flask: find_video_file(base) → send_from_directory()
   → Frontend: <video src=""> renders the stream
```

---

## Suggested Build Order

Dependencies between components (build = implement/test in this order):

### Phase 1: Foundation (no AI, no render)
**Goal:** End-to-end scaffold with stubbed AI.

1. **`config.py`** — Central configuration (paths, API keys, flags)
2. **`app.py`** — Flask app skeleton with routes (`/`, `/status/<id>`, `/api/generate`, `/outputs/<file>`) + in-memory `render_status` dict
3. **`nima-frontend/`** — Next.js app scaffold, API client pointing to `http://localhost:5000`, prompt input + status polling + video player
4. **Static stub response** — `generate_and_validate_code()` returns hardcoded sample code; `save_and_render()` writes a placeholder file

**Verify:** Frontend can submit job, poll status, display placeholder video.

---

### Phase 2: Manim Rendering (no AI)
**Goal:** Prompt → Manim code → video via subprocess.

5. **`algorithms/code_digest.py`** — `ensure_scene_class()`, `validate_python_syntax()`, `validate_manim_code()`, `validate_names_and_imports()`
6. **`app.py` render logic** — `_run_manim()`, `find_video_file()`, `save_and_render()` with hardcoded test code
7. **`config.py`** — `MANIM_SCRIPTS`, `OUTPUTS` paths; `RENDER_TIMEOUT_SECONDS`, `MAX_RENDER_RETRIES`

**Verify:** POST any prompt → gets Manim-rendered video (static test scene).

---

### Phase 3: AI Pipeline
**Goal:** LLM generates actual Manim code from prompt.

8. **`algorithms/request_analysis.py`** — `analyze_request_type()`, `create_animation_plan()`, `expand_short_prompt()`
9. **`RAG/RAG_system.py`** — `retrieve_golden_example()`, `retrieve_patterns()`, `CORPUS` dict
10. **`algorithms/ai_functions.py`** — `generate_manim_code()` with RAG injection, domain guidance
11. **`algorithms/error_parser.py`** — `parse_manim_error()`, `format_error_for_prompt()`
12. **Wire `generate_and_validate_code()`** — connect analysis → planning → generation → validation loop

**Verify:** "Explain the Pythagorean theorem" → AI-generated Manim code renders without syntax errors.

---

### Phase 4: Validation & Self-Healing
**Goal:** Auto-fix broken code and render errors.

13. **`algorithms/code_digest.py`** extensions — `check_code_quality()`, `validate_latex_strings()`
14. **`algorithms/overlap_detector.py`** — all `detect_*()` functions + `run_all_checks()`
15. **`algorithms/ai_functions.py`** — `review_and_fix()`, `fix_render_error()`, `polish_manim_code()`, `inject_helpers()`
16. **Render retry loop** — `save_and_render()` self-healing: parse stderr → LLM fix → retry

**Verify:** Intentionally broken code → review pass fixes it → renders successfully.

---

### Phase 5: Voiceover Pipeline
**Goal:** TTS narration synced to animation.

17. **`algorithms/tts.py`** — `generate_segment_audio()`, `generate_voiceover()`, `merge_audio_video()`
18. **`algorithms/request_analysis.py`** — `create_narrated_plan()`
19. **Voiceover wiring** — `generate_and_validate_code()` path when `voiceover=True`

**Verify:** Submit with voiceover → narrated video with audio synced to animation.

---

### Phase 6: Deterministic Plan Compiler
**Goal:** Fast math animations without LLM creativity.

20. **`algorithms/plan/schema.py`** — `validate_plan_dict()`, `adapt_from_narrated_segments()`
21. **`algorithms/template_registry.py`** — `TEMPLATES` dict, `choose_template()`
22. **`algorithms/plan/compiler.py`** — `compile_plan()`, `compile_plan_json()`
23. **Fast path wiring** — `generate_and_validate_code()` uses compiler for math domain when `FAST_PIPELINE`/`DRAFT_PIPELINE`

**Verify:** Math prompt in FAST mode → template-selected plan → deterministic code → renders correctly.

---

### Phase 7: Database Persistence
**Goal:** Track history, learn from errors.

24. **`database_schema.sql`** — all 6 tables with indexes
25. **`app.py` `ManimDatabase` class** — connection, `_exec()`, CRUD methods
26. **DB wiring** — save request → save attempt → save render job → save evaluation; `get_best_examples()`, `get_error_patterns()`, `record_error_pattern()`
27. **`/stats` route** — aggregate query → system telemetry

**Verify:** Submit 3 prompts → `/stats` shows correct counts and quality scores.

---

### Phase 8: Quality Evaluation
**Goal:** Score and track animation quality.

28. **`algorithms/ai_functions.py`** — `evaluate_with_gpt4()` quality scoring
29. **DB save** — `save_ai_evaluation()` after successful render
30. **Training loop** — high-scoring examples flagged in `training_examples` table

**Verify:** Render → evaluation score saved → high-quality examples retrievable for RAG.

---

## Directory Structure Summary

```
C:\ai-manim\
├── app.py                          # Flask server + ManimDatabase + orchestration
├── config.py                       # Central configuration
├── database_schema.sql             # PostgreSQL schema
├── algorithms/
│   ├── __init__.py
│   ├── request_analysis.py         # Prompt classification + planning
│   ├── ai_functions.py             # LLM calls (generate, review, fix, evaluate)
│   ├── code_digest.py              # Static validation (AST/regex)
│   ├── error_parser.py             # Manim stderr parsing
│   ├── overlap_detector.py         # Layout/hygiene static analysis
│   ├── tts.py                      # TTS generation + audio/video merge
│   ├── template_registry.py        # Layout blueprints
│   ├── plan/
│   │   ├── __init__.py
│   │   ├── compiler.py             # Deterministic JSON plan → Manim code
│   │   ├── schema.py               # Plan JSON schema + validation
│   │   └── examples.py
│   └── overlap_detector.py         # Static layout checks
├── RAG/
│   └── RAG_system.py               # Pattern corpus + retrieval
├── layout/
│   └── engine.py
├── training/
│   ├── questions.py
│   ├── manim_examples_raw.json
│   └── 3b1b/                       # 3b1b scene extraction scripts
├── nima-frontend/                  # Next.js 16 frontend
│   ├── package.json
│   ├── src/app/page.tsx            # Main UI
│   └── src/app/layout.tsx
├── templates/
│   └── index.html                  # Flask Jinja template (alternative frontend)
├── requirements.txt
└── .env                            # Environment variables (API keys, DB connection)
```

---

*Architecture analysis: 2026-04-04*
