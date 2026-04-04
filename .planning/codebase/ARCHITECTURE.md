# Architecture

**Analysis Date:** 2026-04-04

## Pattern Overview

**Overall:** Client-Server with Pipeline Orchestration

**Key Characteristics:**
- Flask backend (Python) serves as the orchestration engine for AI-powered Manim animation generation
- Next.js frontend (TypeScript/React) provides a reactive UI with job polling
- Asynchronous job processing with background threads for render tasks
- Multi-stage AI pipeline: analyze → plan → generate → validate → render → evaluate
- Self-healing render loop that feeds Manim errors back to LLM for automatic fixes

## Layers

**Frontend (Next.js):**
- Purpose: User interface for submitting animation prompts and monitoring job status
- Location: `nima-frontend/src/`
- Contains: React components, Tailwind CSS styling, API client logic
- Depends on: Flask API (localhost:5000)
- Used by: End users via browser

**Backend API (Flask):**
- Purpose: Orchestrates the animation generation pipeline and exposes REST endpoints
- Location: `app.py`
- Contains: Flask routes, job management, database operations, pipeline orchestration
- Depends on: algorithms/, database, config.py, OpenAI API
- Used by: Next.js frontend via JSON API

**Algorithm Layer:**
- Purpose: AI-powered code generation, analysis, validation, and rendering
- Location: `algorithms/`
- Contains: Request analysis, code generation, review/fix, plan compilation, validation
- Key files:
  - `algorithms/request_analysis.py` - Prompt classification and storyboard planning
  - `algorithms/ai_functions.py` - Core LLM calls for generation, review, fixing, evaluation
  - `algorithms/code_digest.py` - Validation (syntax, structure, safety, quality)
  - `algorithms/plan/compiler.py` - JSON plan to Manim code compilation
  - `algorithms/overlap_detector.py` - Layout overlap detection
  - `algorithms/template_registry.py` - Animation pattern templates
  - `algorithms/tts.py` - Text-to-speech voiceover generation
- Depends on: OpenAI API, RAG system, config settings
- Used by: app.py pipeline functions

**RAG System:**
- Purpose: Retrieve relevant example code for context-aware generation
- Location: `RAG/RAG_system.py`
- Contains: Golden example retrieval based on domain/topic
- Depends on: Database (for examples)
- Used by: algorithms/ai_functions.py

**Layout Engine:**
- Purpose: Deterministic zone-based layout for plan compilation
- Location: `layout/engine.py`
- Contains: Zone definitions, frame calculations, placement helpers
- Depends on: Plan schema
- Used by: algorithms/plan/compiler.py

**Database Layer:**
- Purpose: Persistent storage for requests, generation attempts, render jobs, evaluations
- Location: `database_schema.sql` (schema), `app.py` (ManimDatabase class)
- Contains: PostgreSQL schema and connection management
- Depends on: PostgreSQL
- Used by: app.py for tracking and quality scoring

**Configuration:**
- Purpose: Centralized settings for all modules
- Location: `config.py`
- Contains: OpenAI credentials, file paths, pipeline modes, render settings

## Data Flow

**Request to Animation Flow:**

1. **Frontend Submit** → `nima-frontend/src/app/page.tsx`
   - User enters prompt, clicks "DEPLOY COMPILE"
   - POST to `/api/generate` with `{prompt, voiceover}`

2. **API Reception** → `app.py:api_generate()`
   - Creates job_id, initializes render_status[job_id]
   - Spawns background thread for generation

3. **Analysis** → `algorithms/request_analysis.py:analyze_request_type()`
   - LLM classifies prompt: type, complexity, topic, domain, duration, subtopics

4. **Planning** → `algorithms/request_analysis.py:create_animation_plan()`
   - LLM generates scene-by-scene storyboard
   - Or for math domains: `create_plan_json()` for deterministic compilation

5. **Code Generation** → `algorithms/ai_functions.py:generate_manim_code()`
   - LLM generates Manim Python code following storyboard
   - Injects layout helpers and domain-specific guidance

6. **Validation** → `algorithms/code_digest.py`
   - `validate_python_syntax()` - Check syntax errors
   - `validate_manim_code()` - Check structure
   - `validate_names_and_imports()` - Security check
   - `check_code_quality()` - Quality warnings
   - `validate_latex_strings()` - Math domain LaTeX validation
   - `detect_overlaps()` - Layout overlap detection

7. **Review & Fix** → `algorithms/ai_functions.py:review_and_fix()`
   - Combined review pass for critical errors, layout issues, API corrections

8. **Render** → `app.py:save_and_render()`
   - Write code to `MANIM_SCRIPTS/` directory
   - Execute `manim` command via subprocess
   - Self-healing: on failure, feed stderr to `fix_render_error()` and retry (up to MAX_RENDER_RETRIES)

9. **Voiceover Merge** → `algorithms/tts.py:merge_audio_video()`
   - If voiceover enabled, merge pre-generated TTS audio with video

10. **Evaluation** → `algorithms/ai_functions.py:evaluate_with_gpt4()`
    - Score animation quality across dimensions
    - Store in database for training data

11. **Polling Response** → `nima-frontend/src/app/page.tsx`
    - Frontend polls `/status/{job_id}` every 1.5s
    - On "done" status, displays video URL
    - On "error" status, displays error message

**State Management:**
- `render_status` dict: In-memory job status (status, message, video_file)
- `job_to_request` dict: Maps job_id to request metadata
- Database: Persistent history of requests, attempts, renders, evaluations

## Key Abstractions

**ManimDatabase:**
- Purpose: Database interface for persisting pipeline data
- Location: `app.py` (lines 104-299)
- Pattern: Connection wrapper with CRUD methods
- Methods: `save_request()`, `save_generation_attempt()`, `save_render_job()`, `save_ai_evaluation()`, `get_best_examples()`, `get_error_patterns()`, `record_error_pattern()`

**generate_and_validate_code():**
- Purpose: Orchestrates the full AI code generation pipeline
- Location: `app.py` (lines 309-704)
- Pattern: Sequential pipeline with early returns for fast path
- Returns: (code, attempts_log, request_id, attempt_id, audio_segments, segment_order)

**save_and_render():**
- Purpose: Manages the render loop with self-healing
- Location: `app.py` (lines 782-947)
- Pattern: Retry loop with LLM-powered error correction
- Handles: Video file detection, audio merge, evaluation, database recording

**Plan Compiler:**
- Purpose: Compile JSON plan to deterministic Manim code
- Location: `algorithms/plan/compiler.py`
- Pattern: Schema-driven code generation
- Uses: `layout/engine.py` for zone-based placement

## Entry Points

**Flask Server:**
- Location: `app.py` (line 1240: `app.run()`)
- Triggers: `python app.py` or `start_nima_server.bat`
- Responsibilities: HTTP server on port 5000, route handling, job orchestration

**Frontend Dev Server:**
- Location: `nima-frontend/` (Next.js)
- Triggers: `npm run dev` in nima-frontend directory
- Responsibilities: Next.js dev server on port 3000, serves UI

**Job Background Thread:**
- Location: `app.py:render_async()` (lines 950-974)
- Triggers: Called after code generation completes
- Responsibilities: Async render in daemon thread

## Error Handling

**Strategy:** Multi-layer error handling with self-healing

**Patterns:**
1. **Generation Errors:** Retry up to MAX_GENERATION_ATTEMPTS with different prompts
2. **Render Errors:** Parse stderr → `fix_render_error()` → retry up to MAX_RENDER_RETRIES
3. **Syntax Errors:** Fallback to `polish_manim_code()` for lightweight fixes
4. **Critical Errors:** Automatic fallback from plan compiler to LLM generation path
5. **Database Errors:** Graceful degradation (USE_DATABASE=false) - pipeline continues without persistence
6. **LLM API Errors:** Exponential backoff retry with fallback model support

**Error Pattern Recording:**
- Failed renders recorded in `error_patterns` table
- Patterns fed back to `get_error_warnings()` for future generation avoidance

## Cross-Cutting Concerns

**Logging:** Print statements with timing markers (`[TIMING]`, `[DB]`, `[ERR]`, etc.)

**Validation:** 
- Security: `validate_names_and_imports()` blocks dangerous patterns
- Syntax: `validate_python_syntax()` before render
- Structure: `validate_manim_code()` for scene class requirements
- LaTeX: `validate_latex_strings()` for math domain

**Authentication:** None (localhost only) - API key managed via environment variables

**Voiceover:**
- TTS generation via OpenAI TTS API
- Audio-video merge via `merge_audio_video()`
- Timing contract passed to generation for sync

---

*Architecture analysis: 2026-04-04*
