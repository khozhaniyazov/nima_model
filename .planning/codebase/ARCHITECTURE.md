# Architecture

**Analysis Date:** 2026-04-12

## Pattern Overview

**Overall:** Monolithic Flask backend orchestrator with modular algorithm services, plus a separate Next.js frontend application.

**Key Characteristics:**
- Keep HTTP orchestration and route definitions centralized in `app.py`.
- Keep domain logic split into modules under `algorithms/`, `RAG/`, and `layout/`.
- Support two execution architectures: bulk generation (`generate_and_validate_code`) and streaming scene-by-scene generation (`stream_generate_and_render`).

## Layers

**HTTP/API Orchestration Layer:**
- Purpose: Accept requests, schedule background work, expose operational and admin APIs.
- Location: `app.py`
- Contains: Flask routes (`/api/generate`, `/status/<job_id>`, `/stats`, `/api/videos*`, `/api/templates*`, `/api/keys*`, `/api/webhooks*`, `/api/lti/*`), in-memory job state (`render_status`, `job_to_request`), rate limiting.
- Depends on: `config.py`, `algorithms/*`, `cache.py`, `psycopg2`, Python threading.
- Used by: `templates/index.html`, Next.js client in `nima-frontend/src/lib/api.ts`, external clients.

**Prompt Analysis & Planning Layer:**
- Purpose: Convert a prompt into structured analysis and plan/stage artifacts.
- Location: `algorithms/request_analysis.py`, `algorithms/template_registry.py`, `algorithms/plan/schema.py`
- Contains: Prompt/domain heuristics, duration estimation, narrated plan generation, deterministic plan JSON generation, template lookup.
- Depends on: OpenAI-compatible client setup and config settings from `config.py`.
- Used by: `generate_and_validate_code()` and `stream_generate_and_render()` in `app.py`.

**Code Generation & Repair Layer:**
- Purpose: Produce Manim code and apply LLM-based fix/review cycles.
- Location: `algorithms/ai_functions.py`
- Contains: `generate_manim_code`, `review_and_fix`, `polish_manim_code`, `fix_render_error`, LLM retry/fallback path, helper-code injection.
- Depends on: `RAG/RAG_system.py`, OpenAI-compatible endpoints from `config.py`.
- Used by: bulk generation flow and render self-healing in `app.py`.

**Deterministic Compile Layer:**
- Purpose: Compile validated plan JSON into deterministic Manim code.
- Location: `algorithms/plan/compiler.py`, `algorithms/plan/schema.py`, `layout/engine.py`
- Contains: schema dataclasses and validation, restricted object/action compiler, zone-based placement model.
- Depends on: `validate_plan_dict()` in `algorithms/plan/schema.py`.
- Used by: math plan-first path in `generate_and_validate_code()` (`app.py`).

**Validation & Safety Layer:**
- Purpose: Enforce syntax, safety, structure, and quality constraints before rendering.
- Location: `algorithms/code_digest.py`, `algorithms/overlap_detector.py`, `app.py` (`validate_in_parallel`)
- Contains: AST import/call checks, scene-structure checks, quality heuristics, overlap checks.
- Depends on: Python AST/regex and threaded validation in `app.py`.
- Used by: both compiled and LLM-generated code paths.

**Streaming Scene Pipeline Layer:**
- Purpose: Generate, render, and stitch scene outputs incrementally.
- Location: `algorithms/streaming.py`, `app.py` (`stream_generate_and_render`)
- Contains: `NarrativeContext`, scene splitting/deduping, provider routing (`zjuapi`/`wenwen`/`openai`), scene retry, render/stitch workflow.
- Depends on: Manim CLI, ffmpeg/ffprobe, provider configuration from `config.py`.
- Used by: `/api/generate` streaming mode (default true in `app.py`).

**Render & Media Layer:**
- Purpose: Execute Manim render commands, locate output files, merge narration, and expose media.
- Location: `app.py` (`_run_manim`, `save_and_render`, `find_video_file`, `/outputs/<path:filename>`), `algorithms/tts.py`
- Contains: render retries, cache short-circuiting, ffmpeg merge, output discovery.
- Depends on: `MANIM_SCRIPTS` and `OUTPUTS` paths in `config.py`, system binaries.
- Used by: bulk and streaming pipelines.

**Persistence & Analytics Layer:**
- Purpose: Persist pipeline events and serve analytics/query endpoints.
- Location: `app.py` (`class ManimDatabase`), `database_schema.sql`
- Contains: SQL helper methods and tables for requests, attempts, render jobs, evaluations, videos, templates, keys, webhooks, LTI platforms.
- Depends on: PostgreSQL via `DB_CONNECTION_STRING` in `config.py`.
- Used by: dashboard/library APIs and pipeline logging.

**Frontend Layer:**
- Purpose: Provide prompt submission UX, job tracking UX, analytics, and video library.
- Location: `templates/index.html`, `nima-frontend/src/app/page.tsx`, `nima-frontend/src/app/dashboard/page.tsx`, `nima-frontend/src/app/library/page.tsx`
- Contains: client-side polling and fetch flows to backend endpoints.
- Depends on: backend APIs exposed by `app.py`.
- Used by: users and operators.

## Data Flow

**Bulk pipeline (`streaming=false`):**

1. POST prompt to `/api/generate` in `app.py`.
2. Initialize `render_status[job_id]` in `app.py` and spawn background thread.
3. Run `generate_and_validate_code()` in `app.py`: analyze/plan via `algorithms/request_analysis.py`.
4. For eligible math cases, compile with `create_plan_json()` + `compile_plan()` (`algorithms/plan/compiler.py`); otherwise generate via `generate_manim_code()` (`algorithms/ai_functions.py`).
5. Validate with `validate_names_and_imports`, `validate_python_syntax`, `validate_manim_code`, `check_code_quality` (`algorithms/code_digest.py`).
6. Render through `save_and_render()` in `app.py`; on failures, feed stderr to `fix_render_error()` in `algorithms/ai_functions.py` and retry.
7. Optionally merge narration via `merge_audio_video()` in `algorithms/tts.py`; persist DB records and expose file via `/outputs/<filename>`.

**Streaming pipeline (`streaming=true`):**

1. POST prompt to `/api/generate` in `app.py` (default streaming enabled).
2. Enter `stream_generate_and_render()` in `app.py` and derive mode constraints from `VIDEO_MODES` in `config.py`.
3. Split plan into scenes via `split_plan_into_scenes()` in `algorithms/streaming.py`.
4. Generate scenes with narrative carryover from `NarrativeContext` in `algorithms/streaming.py`.
5. Render each scene via `_render_single_scene()` and retry failed scenes via `retry_scene()`.
6. Stitch scene MP4 outputs into final file via `stitch_scenes()` in `algorithms/streaming.py`.

**State Management:**
- Use process-local dictionaries in `app.py` (`render_status`, `job_to_request`) for live status.
- Guard shared updates with `_state_lock` in `app.py`.
- Persist long-lived history in PostgreSQL (`database_schema.sql`) via `ManimDatabase` in `app.py`.
- Reuse expensive results via `RenderCache` and `PromptCache` in `cache.py`.

## Key Abstractions

**Job State Record:**
- Purpose: Represent lifecycle and user-facing status for one generation job.
- Examples: `render_status` updates in `app.py`; status read in `/status/<job_id>`.
- Pattern: Mutable dict keyed by job ID with `status`, `message`, and optional media fields.

**ManimDatabase Gateway:**
- Purpose: Single persistence façade for SQL operations.
- Examples: `class ManimDatabase` in `app.py`; backing schema in `database_schema.sql`.
- Pattern: `_exec()` wrapper and typed helper methods (`save_request`, `save_render_job`, `save_ai_evaluation`, etc.).

**Plan JSON Contract (`v1`):**
- Purpose: Define a deterministic intermediate representation before code emission.
- Examples: `Plan`, `Beat`, `ObjectSpec` in `algorithms/plan/schema.py`; `compile_plan()` in `algorithms/plan/compiler.py`.
- Pattern: Validate first, then compile only whitelisted actions and object kinds.

**NarrativeContext:**
- Purpose: Preserve continuity across streaming scenes.
- Examples: `NarrativeContext` in `algorithms/streaming.py`.
- Pattern: Track scene history, object state, camera state, and domain state; inject with `to_context_string()`.

## Entry Points

**Backend runtime:**
- Location: `app.py` (`if __name__ == "__main__": ... app.run(...)`)
- Triggers: `python app.py`
- Responsibilities: Initialize startup logging/warmup and serve Flask routes.

**Root form entry:**
- Location: `@app.route("/")` in `app.py` with template `templates/index.html`
- Triggers: Browser GET/POST
- Responsibilities: Basic non-API prompt flow and status display.

**Programmatic generation entry:**
- Location: `@app.route("/api/generate", methods=["POST"])` in `app.py`
- Triggers: Next.js app and external clients
- Responsibilities: Validate payload, rate-limit caller, dispatch streaming/bulk execution, return `job_id`.

**Frontend route entries:**
- Location: `nima-frontend/src/app/page.tsx`, `nima-frontend/src/app/dashboard/page.tsx`, `nima-frontend/src/app/library/page.tsx`
- Triggers: Next.js routing
- Responsibilities: submit prompts, poll statuses, query metrics, browse and play videos.

## Error Handling

**Strategy:** Prefer layered retries and controlled fallbacks before terminal failure.

**Patterns:**
- LLM retry with exponential backoff/fallback model in `_llm_text_with_retry()` (`algorithms/ai_functions.py`).
- Render self-healing in `save_and_render()` (`app.py`) using stderr-guided `fix_render_error()`.
- Scene-level retry in streaming (`retry_scene()` in `algorithms/streaming.py`) to avoid full-job restart.
- Route-level `try/except` JSON responses in `app.py` for API endpoints.
- DB error containment via `ManimDatabase._exec()` returning `None` on failures.

## Cross-Cutting Concerns

**Logging:** Use print-based tracing in `app.py`, `algorithms/ai_functions.py`, `algorithms/streaming.py`, and `algorithms/tts.py`.
**Validation:** Use `algorithms/code_digest.py` plus plan schema checks in `algorithms/plan/schema.py`.
**Authentication:** Use API key checks via `require_api_key()` and LTI endpoints under `/api/lti/*` in `app.py`.

---

*Architecture analysis: 2026-04-12*
