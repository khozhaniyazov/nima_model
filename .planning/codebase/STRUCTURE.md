# Codebase Structure

**Analysis Date:** 2026-04-12

## Directory Layout

```
C:\ai-manim/
├── app.py                         # Flask backend entry + orchestration + routes
├── config.py                      # Central runtime and provider configuration
├── cache.py                       # Render/prompt hash caches
├── requirements.txt               # Python dependency manifest
├── database_schema.sql            # PostgreSQL schema for backend persistence
├── algorithms/                    # Core generation/validation/render support modules
│   ├── ai_functions.py            # LLM generation/review/fix/evaluate helpers
│   ├── request_analysis.py        # Prompt analysis + planning logic
│   ├── code_digest.py             # Static validation and quality checks
│   ├── streaming.py               # Scene streaming generation and stitching
│   ├── tts.py                     # Voiceover generation and muxing
│   ├── overlap_detector.py        # Overlap/layout checks
│   ├── error_parser.py            # Render error parsing helpers
│   ├── template_registry.py       # Structured generation templates
│   └── plan/
│       ├── schema.py              # Plan dataclasses + validators
│       ├── compiler.py            # Plan JSON → deterministic Manim code
│       └── examples.py            # Plan examples/support
├── layout/
│   └── engine.py                  # Deterministic zone layout primitives
├── RAG/
│   ├── RAG_system.py              # Retrieval system for generation context
│   └── fine_tuning.py             # Fine-tuning support script(s)
├── templates/
│   └── index.html                 # Flask-rendered fallback UI
├── nima-frontend/                 # Next.js frontend app (separate project)
│   ├── package.json               # Node scripts and dependencies
│   ├── tsconfig.json              # TS compiler config + path alias
│   ├── next.config.ts             # Next.js config
│   └── src/
│       ├── app/
│       │   ├── layout.tsx         # Global frontend layout wrapper
│       │   ├── page.tsx           # Prompt submission and status polling page
│       │   ├── dashboard/page.tsx # Analytics dashboard page
│       │   └── library/page.tsx   # Video library page
│       ├── components/            # UI component modules
│       └── lib/api.ts             # Frontend API client functions/types
├── training/                      # Prompt dataset and reference assets/scripts
├── media/                         # Generated media/output artifacts
├── .planning/
│   └── codebase/                  # Codebase analysis docs consumed by GSD
└── skills/                        # Local skill packs and examples
```

## Directory Purposes

**`algorithms/`:**
- Purpose: Keep backend business logic out of route handlers in `app.py`.
- Contains: analysis, generation, validation, streaming, TTS, error handling, templates.
- Key files: `algorithms/request_analysis.py`, `algorithms/ai_functions.py`, `algorithms/code_digest.py`, `algorithms/streaming.py`.

**`algorithms/plan/`:**
- Purpose: Define and compile deterministic plan format.
- Contains: plan schema, compiler, examples.
- Key files: `algorithms/plan/schema.py`, `algorithms/plan/compiler.py`.

**`layout/`:**
- Purpose: Hold deterministic layout utilities separate from LLM-driven generation.
- Contains: frame zone calculations and placement helpers.
- Key files: `layout/engine.py`.

**`RAG/`:**
- Purpose: Store retrieval corpus and matching logic used by LLM prompts.
- Contains: corpus + retrieval logic and fine-tuning helpers.
- Key files: `RAG/RAG_system.py`.

**`nima-frontend/src/app/`:**
- Purpose: Route-level pages for Next.js app router.
- Contains: main generator view, dashboard, library.
- Key files: `nima-frontend/src/app/page.tsx`, `nima-frontend/src/app/dashboard/page.tsx`, `nima-frontend/src/app/library/page.tsx`.

**`nima-frontend/src/components/`:**
- Purpose: Reusable UI components for pages in `src/app/`.
- Contains: theme provider, video player/card, dashboard widgets.
- Key files: `nima-frontend/src/components/ThemeProvider.tsx`, `nima-frontend/src/components/VideoPlayer.tsx`, `nima-frontend/src/components/dashboard/StatsGrid.tsx`.

**`nima-frontend/src/lib/`:**
- Purpose: Centralize typed fetch wrappers and response interfaces.
- Contains: API base URL and endpoint clients.
- Key files: `nima-frontend/src/lib/api.ts`.

**`templates/`:**
- Purpose: Keep Flask-rendered HTML fallback UI.
- Contains: one form template.
- Key files: `templates/index.html`.

**`training/`:**
- Purpose: Store reference examples and prompt pools used by generation/prompt APIs.
- Contains: question sets and large reference corpus folders.
- Key files: `training/questions.py`, `training/manim_examples_raw.json`.

**`.planning/codebase/`:**
- Purpose: Persist architecture/stack/conventions/testing/concerns docs for automation.
- Contains: `ARCHITECTURE.md`, `STRUCTURE.md`, `STACK.md`, `INTEGRATIONS.md`, `CONVENTIONS.md`, `TESTING.md`, `CONCERNS.md`.
- Key files: `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/STRUCTURE.md`.

## Key File Locations

**Entry Points:**
- `app.py`: Backend runtime entry and all Flask routes.
- `nima-frontend/src/app/page.tsx`: Main frontend route for prompt submission.

**Configuration:**
- `config.py`: Backend environment-derived configuration and feature toggles.
- `nima-frontend/tsconfig.json`: Frontend TypeScript + path alias config.
- `nima-frontend/next.config.ts`: Next.js runtime config.

**Core Logic:**
- `algorithms/request_analysis.py`: Request classification and plan creation.
- `algorithms/ai_functions.py`: LLM generation, review, and error-fix operations.
- `algorithms/streaming.py`: Scene splitting, streaming generation, per-scene rendering, stitching.
- `algorithms/plan/compiler.py`: Deterministic plan compiler.
- `algorithms/code_digest.py`: Static safety/quality validation checks.

**Testing:**
- `test_pipeline.py`: Pipeline-oriented backend tests.
- `test_streaming_reliability.py`: Streaming reliability tests.
- `test_edge_cases.py`: Edge-case tests.
- `test_imports.py`: Import integrity checks.
- `test_optimizations.py`: Optimization-related tests.

## Naming Conventions

**Files:**
- Backend modules: `snake_case.py` (example: `request_analysis.py`).
- Plan submodules: `snake_case.py` in nested package (example: `algorithms/plan/compiler.py`).
- Frontend components: `PascalCase.tsx` (example: `VideoPlayer.tsx`).
- Next.js route files: reserved `page.tsx` and `layout.tsx` in route directories.

**Directories:**
- Backend feature groups: lowercase names (example: `algorithms/`, `layout/`, `RAG/`).
- Frontend app-router routes: nested lowercase route folders under `nima-frontend/src/app/` (example: `dashboard/`, `library/`).

## Where to Add New Code

**New backend feature (pipeline behavior):**
- Primary code: `algorithms/<feature_module>.py`
- Integration point: import and call from `app.py` route/pipeline function.

**New deterministic plan capability:**
- Schema updates: `algorithms/plan/schema.py`
- Compiler updates: `algorithms/plan/compiler.py`
- Optional layout behavior: `layout/engine.py`

**New backend API endpoint:**
- Route handler: add in `app.py` near related endpoint group.
- If DB-backed: add helper method to `ManimDatabase` in `app.py` and matching table/index updates in `database_schema.sql`.

**New frontend page:**
- Route file: `nima-frontend/src/app/<route>/page.tsx`
- Shared UI components: `nima-frontend/src/components/`
- API bindings: `nima-frontend/src/lib/api.ts`

**New shared frontend utility or API type:**
- Place in `nima-frontend/src/lib/`.

**New tests:**
- Backend test modules: add root-level `test_*.py` files consistent with existing naming.

## Special Directories

**`nima-frontend/node_modules/`:**
- Purpose: frontend package dependencies.
- Generated: Yes.
- Committed: No.

**`nima-frontend/.next/`:**
- Purpose: Next.js build/dev artifacts.
- Generated: Yes.
- Committed: No.

**`media/`:**
- Purpose: generated render artifacts.
- Generated: Yes.
- Committed: Not detected as required for source control.

**`__pycache__/` and `.ruff_cache/`:**
- Purpose: Python bytecode and lint cache.
- Generated: Yes.
- Committed: No.

**`.planning/`:**
- Purpose: project planning and codebase intelligence docs.
- Generated: Yes (by tooling).
- Committed: Yes.

---

*Structure analysis: 2026-04-12*
