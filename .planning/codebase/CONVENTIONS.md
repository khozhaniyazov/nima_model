# Coding Conventions

**Analysis Date:** 2026-04-12

## Naming Patterns

**Files:**
- Use `snake_case.py` for backend Python modules (examples: `config.py`, `cache.py`, `algorithms/request_analysis.py`, `algorithms/ai_functions.py`).
- Use `test_*.py` for backend test/harness scripts at repository root (examples: `test_imports.py`, `test_optimizations.py`, `test_pipeline.py`, `test_streaming_reliability.py`, `test_edge_cases.py`).
- Use `PascalCase.tsx` for reusable React components (examples: `nima-frontend/src/components/ThemeProvider.tsx`, `nima-frontend/src/components/VideoPlayer.tsx`, `nima-frontend/src/components/dashboard/StatsGrid.tsx`).
- Use route-based `page.tsx` and `layout.tsx` in Next app router (examples: `nima-frontend/src/app/page.tsx`, `nima-frontend/src/app/dashboard/page.tsx`, `nima-frontend/src/app/library/page.tsx`, `nima-frontend/src/app/layout.tsx`).

**Functions:**
- Use `snake_case` for Python functions and methods (examples: `check_rate_limit()` in `app.py`, `generate_voiceover()` in `algorithms/tts.py`, `run_one()` in `test_streaming_reliability.py`).
- Use `camelCase` for TypeScript functions in frontend (examples: `fetchStats()` in `nima-frontend/src/lib/api.ts`, `toggleTheme()` in `nima-frontend/src/components/ThemeProvider.tsx`, `handleSubmit()` in `nima-frontend/src/app/page.tsx`).

**Variables:**
- Python constants are uppercase with underscores (examples in `config.py`: `OPENAI_TIMEOUT`, `MAX_RENDER_RETRIES`, `STREAM_SCENE_TIMEOUT`, `VIDEO_MODES`).
- Module-level mutable state in backend uses descriptive snake_case names (examples in `app.py`: `render_status`, `job_to_request`, `_rate_limit_storage`).
- Frontend state values use `camelCase` and React `setX` setters (examples in `nima-frontend/src/app/library/page.tsx`: `searchQuery`/`setSearchQuery`, `sortOrder`/`setSortOrder`).

**Types:**
- Use `interface` for TS shapes in API and component props (examples: `StatsResponse`, `Video`, `VideoListResponse` in `nima-frontend/src/lib/api.ts`; `VideoPlayerProps` in `nima-frontend/src/components/VideoPlayer.tsx`).
- Use Python typing annotations selectively for signatures and containers (examples in `app.py`: `Dict[str, dict]`, `Optional[dict]`; in `algorithms/streaming.py`: dataclass fields typed with `Dict`, `List`, `Any`).

## Code Style

## Style Patterns

- Prefer module docstrings at file top for backend modules (examples: `app.py`, `config.py`, `algorithms/ai_functions.py`, `algorithms/streaming.py`, `cache.py`).
- Prefer section dividers and labeled blocks in Python using comment banners (`# ═══...` and `# ── ...`) to organize long modules (`app.py`, `algorithms/ai_functions.py`, `algorithms/tts.py`, `test_optimizations.py`).
- Prefer early-return guard clauses in both Python and TS (examples: `if not RATE_LIMIT_ENABLED: return True, 0` in `app.py`; `if (!video) return;` in `nima-frontend/src/components/VideoPlayer.tsx`; `if (!searchQuery.trim()) return;` in `nima-frontend/src/app/library/page.tsx`).
- Prefer fallback/default return objects for frontend fetch failures instead of throwing (examples: `fetchStats()` and `fetchVideos()` in `nima-frontend/src/lib/api.ts`).

**Formatting:**
- Python formatting signal: CI runs `black --check .` in `.github/workflows/test.yml`.
- Frontend formatting config file (`.prettierrc*`) is not detected; formatting currently follows default tool/editor behavior.
- Inline style objects are heavily used in TSX pages (`nima-frontend/src/app/page.tsx`, `nima-frontend/src/app/dashboard/page.tsx`, `nima-frontend/src/app/library/page.tsx`).

**Linting:**
- Python lint signal: CI runs `ruff check . --ignore=E501,F401` in `.github/workflows/test.yml`.
- Next.js/TS lint signal: `nima-frontend/package.json` provides `"lint": "eslint"` and `nima-frontend/eslint.config.mjs` extends `eslint-config-next/core-web-vitals` + `eslint-config-next/typescript`.
- Lint exceptions are explicit in CI (`E501` line-length and `F401` unused-import ignored in `.github/workflows/test.yml`).

**Type-check Signals:**
- Frontend strict type-checking is enabled via `"strict": true` in `nima-frontend/tsconfig.json`.
- Alias `@/*` is configured to `./src/*` in `nima-frontend/tsconfig.json` and used in imports such as `@/lib/api` and `@/components/ThemeProvider`.
- Python `mypy` is installed in CI (`pip install ruff black mypy` in `.github/workflows/test.yml`) but no mypy command is executed; static type enforcement is partial.

## Import Organization

**Order:**
1. Standard library imports first (example: `app.py` imports `os`, `time`, `json`, `subprocess`, `uuid`, `threading` before project modules).
2. Third-party imports next (examples: `flask`, `openai`, `psycopg2`, `dotenv` in `app.py`; React hooks in TSX files).
3. Local/project imports last (examples: `from config import ...` and `from algorithms...` in `app.py`; `@/lib/api` imports in frontend pages).

**Path Aliases:**
- Use `@/*` for frontend internal imports (`nima-frontend/tsconfig.json`), e.g., `import { fetchStats } from "@/lib/api"` in `nima-frontend/src/app/dashboard/page.tsx`.

## Error Handling

**Patterns:**
- Backend uses broad `try/except Exception` with printed diagnostics in service code (examples: `ManimDatabase._exec()` in `app.py`, `_llm_text_with_retry()` in `algorithms/ai_functions.py`, `_generate_single_segment()` in `algorithms/tts.py`).
- Frontend API layer catches errors and returns safe fallback payloads for read operations (`nima-frontend/src/lib/api.ts`).
- UI components catch async failures and set local error state or silent fallback behavior (examples: `setError("FAILED_TO_CONNECT")` in `nima-frontend/src/app/dashboard/page.tsx`, silent catch in prompt refresh in `nima-frontend/src/app/page.tsx`).

## Logging

**Framework:**
- Backend primarily uses `print()` logs with tagged prefixes (`[STARTUP]`, `[DB]`, `[LLM]`, `[TTS]`, `[MERGE]`, `[ANALYZE]`) in `app.py`, `algorithms/ai_functions.py`, `algorithms/tts.py`, `algorithms/request_analysis.py`.
- Frontend uses `console.error()` in API/service and page actions (examples in `nima-frontend/src/lib/api.ts`, `nima-frontend/src/app/library/page.tsx`).

**Patterns:**
- Keep operational logs short and prefixed for greppable troubleshooting.
- Return structured status dicts for job progress and error propagation (see `JobStatus` shape in `nima-frontend/src/app/page.tsx` and status polling in `test_streaming_reliability.py`).

## Comments

**When to Comment:**
- Use section-level comments to separate phases/pipeline concerns in large Python files (`app.py`, `test_optimizations.py`).
- Use concise block labels in TSX (`/* ── Header Area ── */`, `/* Poll job status */`) to structure long JSX files (`nima-frontend/src/app/page.tsx`).

**JSDoc/TSDoc:**
- Limited in frontend TS/TSX; most explanation is inline comments.
- Python relies on docstrings for modules and many functions (examples: `generate_segment_audio()` and `merge_audio_video()` in `algorithms/tts.py`, helper methods in `app.py`).

## Function Design

**Size:**
- Backend includes very large orchestration modules/functions (notably `app.py`), while utility modules keep smaller focused helpers (`cache.py`).
- Frontend pages (`nima-frontend/src/app/page.tsx`, `nima-frontend/src/app/library/page.tsx`) centralize UI/state logic in single components; shared display logic is extracted into components (`nima-frontend/src/components/dashboard/*`).

**Parameters:**
- Backend frequently passes explicit config/context values and optional parameters with defaults (examples: `run_one(..., intro_outro: dict | None = None)` in `test_streaming_reliability.py`; `generate_voiceover(..., voice: str = None)` in `algorithms/tts.py`).
- Frontend service functions use typed parameter objects for extensibility (`fetchVideos(params: {...} = {})` in `nima-frontend/src/lib/api.ts`).

**Return Values:**
- Backend returns tuple/dict status payloads for multi-field outcomes (`check_rate_limit()` in `app.py`, `_generate_single_segment()` in `algorithms/tts.py`, `run_one()` in `test_streaming_reliability.py`).
- Frontend API functions return typed response objects with safe defaults on failure (`nima-frontend/src/lib/api.ts`).

## Module Design

**Exports:**
- Python modules export functions/classes directly; no centralized barrel module pattern.
- Frontend uses default exports for many components/pages and named exports where shared types/functions are needed (examples: named interfaces/functions in `nima-frontend/src/lib/api.ts`, `export function VideoCard` + `export default VideoCard` in `nima-frontend/src/components/VideoCard.tsx`).

**Barrel Files:**
- Not detected in frontend (`index.ts` re-export barrels are not present in `nima-frontend/src/components` or `nima-frontend/src/lib`).

---

*Convention analysis: 2026-04-12*
