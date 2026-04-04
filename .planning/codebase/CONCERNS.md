# Codebase Concerns

**Analysis Date:** 2026-04-04

## Tech Debt

**[Hardcoded Database Credentials in config.py]:**
- Issue: Database connection string contains plaintext password `Zk201910902!`
- Files: `config.py` (line 30)
- Impact: If this file is committed to version control, credentials are leaked. Also means credentials cannot be changed without code changes.
- Fix approach: Move credentials entirely to environment variables with no fallback hardcoded value.

**[No Real Unit Tests]:**
- Issue: `test_optimizations.py` only tests configuration flags, not actual pipeline functionality. `test_pipeline.py` is a manual end-to-end test, not automated unit tests.
- Files: `test_optimizations.py`, `test_pipeline.py`
- Impact: No regression detection for algorithm functions, validation logic, or code generation.
- Fix approach: Add pytest suite with mocking of LLM calls, tests for each algorithm module, and integration tests.

**[extract_code() Uses Fragile String Parsing]:**
- Issue: `extract_code()` splits on `"```python"` or `"```"`. Malformed LLM output (missing fences, extra backticks, etc.) causes silent failures or wrong code extraction.
- Files: `algorithms/ai_functions.py` (lines 777-785)
- Impact: Generated code could be truncated or empty, causing downstream failures.
- Fix approach: Use regex with proper escaping, or parse as markdown with a library like `mistune`.

**[Plan Compiler Limited Object Kinds]:**
- Issue: `compile_plan()` only supports 12 object kinds (Text, MathTex, VGroup, NumberPlane, Axes, Dot, Line, Arrow, Rectangle, Circle, Square, Polygon). Any LLM-generated plan using unsupported objects raises `ValueError: Unsupported kind`.
- Files: `algorithms/plan/compiler.py` (lines 56-123)
- Impact: Plan-first deterministic compilation fails for complex scenes requiring other Manim objects.
- Fix approach: Extend `_ctor()` to support more Manim types, or fall back to LLM generation when unsupported kinds are detected.

**[Double Client Initialization in ai_functions.py]:**
- Issue: `client` and `fallback_client` are initialized at module import time with the same API key. If the key is None/empty, both will fail immediately on any import.
- Files: `algorithms/ai_functions.py` (lines 35-46)
- Impact: Module import fails when API key is missing, breaking all algorithm imports.
- Fix approach: Lazy initialization of clients, or graceful handling of missing API keys.

**[render_status and job_to_request are Global Mutable State]:**
- Issue: These dicts are module-level globals in `app.py`. They persist across requests but have no cleanup mechanism for old jobs.
- Files: `app.py` (lines 95-96)
- Impact: Memory leak over time as completed job entries accumulate. No TTL or size limit.
- Fix approach: Use `collections.OrderedDict` with max size, or a proper job queue with cleanup.

## Known Bugs

**[LaTeX Validation Regex Incomplete]:**
- Issue: `_check_single_latex()` only checks for `log_`, `sin_`, `cos_`, `tan_`, `lim_(`. Many other common LaTeX errors (like missing `\left`, unmatched `\right`, wrong `\frac` syntax) are not caught.
- Files: `algorithms/code_digest.py` (lines 275-306)
- Trigger: Complex LaTeX expressions with nested structures
- Workaround: None - validation passes but render fails with LaTeX errors

**[RAG System Loads Entire JSON Corpus at Import Time]:**
- Issue: `_load_json_examples()` reads `training/manim_examples_raw.json` at module import, appending all entries to `CORPUS`. No pagination or lazy loading.
- Files: `RAG/RAG_system.py` (lines 1133-1193)
- Impact: Slow import time, high memory usage if JSON is large
- Workaround: Set `RAG_retrieve_golden_example` caching to reduce repeated loads

## Security Considerations

**[LLM-Generated Code Executed via subprocess]:**
- Risk: `generate_manim_code()` produces Python code that is written to disk and executed via `manim`. While `validate_names_and_imports()` uses AST to block dangerous calls, the LLM prompt injection could potentially circumvent static analysis.
- Files: `app.py` (lines 734-779), `algorithms/code_digest.py` (lines 68-122)
- Current mitigation: AST-based import and call checking, limited to `manim`, `numpy`, `math`, `random`, `itertools`, `collections`. Forbidden names: `exec`, `eval`, `__import__`, `os.system`, etc.
- Recommendations: 
  - Add sandboxing (docker container or `seccomp`) for manim execution
  - Add code size limits
  - Log all generated code for audit

**[API Endpoints Have No Rate Limiting]:**
- Risk: `/api/generate` could be hammered to exhaust OpenAI quota or overload the render pipeline.
- Files: `app.py` (lines 1047-1100)
- Current mitigation: None
- Recommendations: Add Flask-Limiter or similar, per-IP and per-key rate limits

**[Database Password in Source Code]:**
- Risk: Credentials hardcoded in `config.py` line 30 could be committed to git.
- Files: `config.py` (line 30)
- Current mitigation: `.env` should override, but fallback exists
- Recommendations: Remove fallback entirely, fail fast if env var missing

## Performance Bottlenecks

**[Manim Render Runs Synchronously in Background Thread]:**
- Problem: `save_and_render()` runs manim in a daemon thread but the render itself is sequential. Each render attempt waits for manim to complete before retry logic.
- Files: `app.py` (lines 782-948)
- Cause: No parallelization of render attempts; each retry is blocking
- Improvement path: Use multiprocessing or separate process pool for renders

**[RAG Corpus Loaded at Import Without Lazy Loading]:**
- Problem: `RAG/RAG_system.py` loads all examples from `manim_examples_raw.json` into memory at import time.
- Files: `RAG/RAG_system.py` (lines 1133-1193)
- Cause: `_load_json_examples()` called unconditionally
- Improvement path: Lazy load on first retrieval, or use database for examples

**[No Database Connection Pooling]:**
- Problem: `ManimDatabase` creates a single connection at startup. If the connection drops, no reconnection logic.
- Files: `app.py` (lines 104-131)
- Impact: Database operations fail silently after a connection drop
- Improvement path: Use `psycopg2.pool.ThreadedConnectionPool`

**[Large Corpus Without Index]:
- Problem: `CORPUS` list has ~30+ entries. `retrieve_patterns()` does linear scan scoring. With many requests, this could be slow.
- Files: `RAG/RAG_system.py` (lines 1218-1239)
- Impact: RAG retrieval O(n) complexity
- Improvement path: Pre-compute scores or use inverted index

## Fragile Areas

**[error_parser._strip_noise() Relies on Heuristics]:**
- Files: `algorithms/error_parser.py` (lines 9-43)
- Why fragile: Uses regex patterns to filter tqdm output and INFO logs. Manim could change log format and error detection breaks.
- Safe modification: Add fallback to return raw stderr if no error pattern matches after cleaning
- Test coverage: None

**[plan/compiler.py Raises on Unknown Kind]:**
- Files: `algorithms/plan/compiler.py` (line 123)
- Why fragile: `ValueError: Unsupported kind: {kind}` is raised at compile time, not gracefully handled
- Safe modification: Catch in `compile_plan()` and fall back to LLM path instead of crashing
- Test coverage: None

**[Multiple OpenAI Client Instances Across Modules]:**
- Files: `algorithms/ai_functions.py` (client), `algorithms/request_analysis.py` (client)
- Why fragile: Each algorithm module creates its own OpenAI client. No shared client or singleton.
- Safe modification: Create a shared `get_client()` function
- Test coverage: None

**[Thread-Safety of Global render_status]:**
- Files: `app.py` (line 95)
- Why fragile: `render_status` dict is accessed from multiple threads (Flask request threads + background render thread) without locks
- Safe modification: Use `threading.Lock` or `queue.Queue`
- Test coverage: None

## Scaling Limits

**[In-Memory Job State Cannot Scale Horizontally]:**
- Current capacity: Single Flask process with in-memory dicts
- Limit: Multiple server instances don't share `render_status` or `job_to_request`
- Scaling path: Use Redis for job state, separate worker processes for renders

**[Database Schema Has No Indexes on Foreign Keys]:**
- Files: `app.py` (DB operations reference `requests`, `render_jobs`, `ai_evaluations` tables)
- Impact: `/stats` endpoint with large tables will be slow
- Scaling path: Add indexes on `request_id` in `render_jobs`, `render_job_id` in `ai_evaluations`

**[CORPUS List Grows Linearly with JSON Loading]:**
- Current capacity: ~30 curated + N from `manim_examples_raw.json`
- Limit: If JSON has thousands of examples, memory and retrieval time suffer
- Scaling path: Paginate corpus, use SQLite or PostgreSQL for examples

## Dependencies at Risk

**[manim>=0.18]:**
- Risk: Manim CE is actively developed. API changes (method renames, parameter changes) can break generated code and validation logic.
- Impact: `generate_manim_code()` prompts reference `manim CE v0.18`, validation assumes specific APIs
- Migration plan: Pin to minor version, update prompts and validation when upgrading

**[openai>=1.30]:**
- Risk: The `responses.create()` API in `request_analysis.py` uses a different interface than `chat.completions.create()`. If the Responses API changes, analysis breaks.
- Impact: `analyze_request_type()` specifically uses `client.responses.create()`
- Migration plan: Add compatibility layer, or use only `chat.completions.create()`

## Missing Critical Features

**[No Code Caching Between Retries]:**
- Problem: If generation fails syntax validation, the code is passed to `polish_manim_code()` but not cached. Identical retries recompute.
- Blocks: Efficient retry without repeated LLM calls for known failure modes
- Priority: Medium

**[No Video Output Validation]:**
- Problem: After render success, there's no validation that the output video is playable (not empty, correct format).
- Blocks: Detecting corrupted renders
- Priority: Medium

**[No Cleanup of Old Render Files]:**
- Problem: Manim output files accumulate in `OUTPUTS` directory. No cleanup job.
- Blocks: Disk space exhaustion on long-running server
- Priority: Low

## Test Coverage Gaps

**[No Tests for Core Algorithm Functions]:**
- Untested: `analyze_request_type()`, `create_animation_plan()`, `create_plan_json()`, `create_narrated_plan()`
- Files: `algorithms/request_analysis.py`
- Risk: Prompt changes or API changes break generation silently
- Priority: High

**[No Tests for Validation Functions]:**
- Untested: `validate_python_syntax()`, `validate_names_and_imports()`, `validate_manim_code()`, `validate_latex_strings()`
- Files: `algorithms/code_digest.py`
- Risk: New code patterns bypass validation
- Priority: High

**[No Tests for Error Parser]:**
- Untested: `parse_manim_error()`, `format_error_for_prompt()`, `_strip_noise()`
- Files: `algorithms/error_parser.py`
- Risk: Error parsing breaks when Manim output format changes
- Priority: Medium

**[No Tests for Overlap Detector]:**
- Untested: `detect_position_collisions()`, `detect_object_accumulation()`, `detect_missing_section_cleanup()`, etc.
- Files: `algorithms/overlap_detector.py`
- Risk: Layout issues not caught before render
- Priority: Medium

**[No Tests for Plan Compiler]:**
- Untested: `compile_plan()`, `compile_plan_json()`
- Files: `algorithms/plan/compiler.py`
- Risk: Invalid plans produce wrong code, unsupported kinds crash
- Priority: High

**[No Tests for RAG System]:**
- Untested: `retrieve_patterns()`, `retrieve_golden_example()`, `_load_json_examples()`
- Files: `RAG/RAG_system.py`
- Risk: Pattern retrieval returns wrong or irrelevant examples
- Priority: Medium

---

*Concerns audit: 2026-04-04*
