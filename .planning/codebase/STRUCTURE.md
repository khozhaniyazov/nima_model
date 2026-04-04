# Codebase Structure

**Analysis Date:** 2026-04-04

## Directory Layout

```
C:\ai-manim\
├── app.py                      # Flask server + pipeline orchestration
├── config.py                    # Centralized configuration
├── requirements.txt             # Python dependencies
├── database_schema.sql          # PostgreSQL schema
├── nima-frontend/               # Next.js frontend application
│   ├── package.json
│   ├── next.config.ts
│   ├── public/
│   └── src/
│       └── app/
│           ├── page.tsx         # Main UI component
│           ├── layout.tsx       # Root layout with metadata
│           ├── globals.css      # Tailwind + custom CSS
│           └── favicon.ico
├── algorithms/                   # AI pipeline modules
│   ├── __init__.py
│   ├── request_analysis.py      # Prompt classification & planning
│   ├── ai_functions.py           # LLM generation, review, fix, evaluate
│   ├── code_digest.py            # Validation functions
│   ├── template_registry.py      # Animation pattern templates
│   ├── overlap_detector.py       # Layout overlap detection
│   ├── error_parser.py           # Manim error parsing
│   ├── tts.py                    # Text-to-speech voiceover
│   ├── plan/
│   │   ├── __init__.py
│   │   ├── compiler.py           # JSON plan → Manim code
│   │   ├── schema.py             # Plan validation schema
│   │   └── examples.py           # Plan examples
│   └── layout/
│       └── engine.py             # Deterministic layout engine
├── RAG/
│   └── RAG_system.py             # Retrieval-augmented generation
├── training/
│   ├── questions.py              # Example prompts for UI
│   ├── 3b1b/                     # 3Blue1Brown video reference scenes
│   └── scrape_manim_examples.py
├── templates/                    # Animation templates
├── prompts/                      # Prompt engineering files
├── notes/                        # Documentation notes
├── skills/                       # GSD skill definitions
├── media/                        # Rendered outputs
│   ├── images/
│   └── videos/
└── .planning/
    └── codebase/                 # This analysis output
```

## Directory Purposes

**Root Level (Python Backend):**
- `app.py` - Main Flask application entry point
- `config.py` - All configuration centralized here
- `requirements.txt` - Python package dependencies
- `database_schema.sql` - PostgreSQL schema definitions

**`nima-frontend/`:**
- Purpose: Next.js web application for user interaction
- Contains: React UI components, Tailwind styling, API client
- Key files: `src/app/page.tsx` (main component), `src/app/layout.tsx` (root layout)

**`algorithms/`:**
- Purpose: AI-powered code generation and validation
- Contains: Request analysis, code generation, validation, plan compilation, TTS
- Key modules: `request_analysis.py`, `ai_functions.py`, `code_digest.py`, `plan/compiler.py`

**`RAG/`:**
- Purpose: Retrieval-augmented generation for context-aware code
- Contains: `RAG_system.py` with golden example retrieval

**`layout/`:**
- Purpose: Deterministic layout engine for plan compilation
- Contains: Zone-based placement, frame calculations

**`training/`:**
- Purpose: Training data, example scenes, and question bank
- Contains: `questions.py` (example prompts), `3b1b/` (reference scenes)

**`media/`:**
- Purpose: Rendered video and image outputs
- Contains: Subdirectories for images and videos, organized by job_id

**`skills/`:**
- Purpose: GSD command skill definitions
- Contains: `webapp-testing/`, `fastapi/`, `mcp-builder/`, etc.

## Key File Locations

**Entry Points:**
- `app.py` - Flask server startup (line 1240: `app.run()`)
- `nima-frontend/` - `npm run dev` starts Next.js on port 3000

**Configuration:**
- `config.py` - Centralized settings (OpenAI, paths, pipeline modes)

**Core Logic:**
- `algorithms/request_analysis.py` - Request classification and planning (426 lines)
- `algorithms/ai_functions.py` - Main AI pipeline functions (897 lines)
- `algorithms/plan/compiler.py` - Plan compilation to Manim code
- `layout/engine.py` - Zone-based layout calculations

**Frontend:**
- `nima-frontend/src/app/page.tsx` - Main UI with API integration (392 lines)
- `nima-frontend/src/app/globals.css` - Tailwind + custom styling (468 lines)

**Database:**
- `database_schema.sql` - PostgreSQL table definitions
- `app.py` (ManimDatabase class, lines 104-299) - Database interface

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (e.g., `request_analysis.py`, `ai_functions.py`)
- React components: `PascalCase.tsx` (e.g., `page.tsx`, `layout.tsx`)
- Config: `camelCase.py` or `snake_case.py` (e.g., `config.py`)
- SQL schema: `snake_case.sql`

**Directories:**
- Python packages: `snake_case/` (e.g., `algorithms/`, `layout/`, `plan/`)
- Frontend: `camelCase/` or `kebab-case/` (e.g., `nima-frontend/`)

**Functions/Classes:**
- Python functions: `snake_case()` (e.g., `generate_manim_code()`, `analyze_request_type()`)
- Python classes: `PascalCase` (e.g., `ManimDatabase`, `GeneratedScene`)
- React components: `PascalCase` (e.g., `Home`, `WireframeLoader`)

**Variables:**
- Python: `snake_case` (e.g., `job_id`, `render_status`, `audio_segments`)
- TypeScript: `camelCase` for variables, `PascalCase` for types/interfaces

**Types/Interfaces:**
- TypeScript: `PascalCase` (e.g., `JobStatus`, `Stats` in `page.tsx`)

## Where to Add New Code

**New Algorithm Module:**
- Location: `algorithms/new_module.py`
- Import in `app.py`: `from algorithms.new_module import function_name`

**New Frontend Component:**
- Location: `nima-frontend/src/app/components/` (create if needed)
- Import in `page.tsx`: `from "./components/ComponentName"`

**New Database Table:**
- Add to `database_schema.sql`
- Add CRUD methods to `ManimDatabase` class in `app.py`

**New API Endpoint:**
- Location: `app.py` (Flask route decorator)
- Pattern: `@app.route("/api/endpoint", methods=["GET", "POST"])`

**New Validation Function:**
- Location: `algorithms/code_digest.py`
- Export and import where needed

**New Animation Template:**
- Location: `algorithms/template_registry.py`
- Add to `TEMPLATES` dict with slots/beats/notes

## Special Directories

**`media/`:**
- Purpose: Rendered video and image outputs from Manim
- Generated: Yes (by render pipeline)
- Committed: No (in .gitignore)

**`nima-frontend/.next/`:**
- Purpose: Next.js build cache and artifacts
- Generated: Yes (by `npm run build` or `npm run dev`)
- Committed: No (in .gitignore)

**`__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: Yes (by Python runtime)
- Committed: No (in .gitignore)

**`.ruff_cache/`:**
- Purpose: Ruff linter cache
- Generated: Yes
- Committed: No

**`.planning/`:**
- Purpose: GSD planning and analysis documents
- Generated: Yes (by GSD commands)
- Committed: Yes

---

*Structure analysis: 2026-04-04*
