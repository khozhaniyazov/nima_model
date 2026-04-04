# Codebase Concerns

**Analysis Date:** 2026-04-04

---

## Tech Debt

### Hardcoded Filesystem Paths
- **Issue:** `config.py` lines 23-24 hardcode `C:/temp/manim_scripts` and `C:/temp/outputs`. No environment variable override.
- **Files:** `config.py`
- **Impact:** Cross-environment deployment fails; dev/prod path mismatch.
- **Fix approach:** Environment variable with fallback to `Path(".")` for portability.
- **Phase:** `infrastructure`

### Hardcoded Database Credentials
- **Issue:** Default connection string in `config.py` line 30 contains credentials `Zk201910902!`. This is visible in source.
- **Files:** `config.py`
- **Impact:** Credential exposure if committed to VCS; production DB connection misconfiguration.
- **Fix approach:** Require all credentials from environment; fail fast if missing.
- **Phase:** `security`

### Duplicate OpenAI Client Initialization
- **Issue:** `OpenAI` client created in 3 places independently: `app.py` line 90, `ai_functions.py` line 35, `request_analysis.py` line 16. No shared instance.
- **Files:** `app.py`, `algorithms/ai_functions.py`, `algorithms/request_analysis.py`
- **Impact:** Connection pool fragmentation; inconsistent timeout/settings across calls.
- **Fix approach:** Single client module imported everywhere.
- **Phase:** `refactor`

### Global In-Memory State
- **Issue:** `render_status: Dict[str, dict] = {}` and `job_to_request: Dict[str, dict] = {}` at `app.py` lines 95-96 are process globals. Lost on restart; not thread-safe for concurrent writes.
- **Files:** `app.py`
- **Impact:** Job status lost across health-checks/restarts; race conditions with concurrent requests.
- **Fix approach:** Database-backed job state; Redis as alternative.
- **Phase:** `infrastructure`

### Codex API Inconsistency
- **Issue:** `request_analysis.py` uses `client.responses.create()` for Codex models (line 31) but `ai_functions.py` uses `client.chat.completions.create()` (line 73). Different APIs with different response formats.
- **Files:** `algorithms/request_analysis.py`, `algorithms/ai_functions.py`
- **Impact:** Model-specific code paths harder to maintain; responses parsed differently.
- **Fix approach:** Unified LLM abstraction with model-agnostic interface.
- **Phase:** `refactor`

### Unverified Model Names
- **Issue:** `config.py` lines 15-19 reference `gpt-5.2-codex` which may not exist at this version. Default values chosen without verifying model availability.
- **Files:** `config.py`
- **Impact:** Pipeline fails silently or uses wrong model if name is incorrect.
- **Fix approach:** Validate model names on startup; use well-known model aliases.
- **Phase:** `infrastructure`

### Lambda Closure Bug in RAG Corpus
- **Issue:** RAG pattern at `RAG/RAG_system.py` line 664:
  ```python
  graph = axes.plot(lambda x, n=n: square_wave_approx(x, [1,3,5,11][n]), ...)
  ```
  The `n=n` default argument is shadowed by the positional `x` parameter position — `n` in the body resolves to the loop variable, not the default. This is a late-binding closure bug.
- **Files:** `RAG/RAG_system.py`
- **Impact:** Fourier series approximation renders with wrong `n` value per iteration.
- **Fix approach:** Change signature to `lambda x, n_=n: square_wave_approx(x, [1,3,5,11][n_])`.
- **Phase:** `bug`

---

## Known Bugs

### Manim Exit Code False Negatives
- **Issue:** `app.py` lines 828-837 check for video file first, then treat `returncode != 0` as warning only when video exists. But Manim can exit 1 for non-fatal warnings (cache full) and exit 0 while producing nothing.
- **Files:** `app.py` (save_and_render)
- **Trigger:** Run with full cache; check for "file not found" case with exit 0.
- **Workaround:** Video file existence check first.
- **Phase:** `bug`

### LLM Fix Loop Without New-Error Check
- **Issue:** `save_and_render` loop at `app.py` lines 806-947 feeds stderr back to LLM and retries. But if LLM fix introduces a NEW error (not the original), the loop retries with buggy code and same error pattern matcher may not catch new error type.
- **Files:** `app.py` (save_and_render, fix_render_error)
- **Trigger:** Fix introduces syntax error that was not in original.
- **Workaround:** Syntax re-validation before retry (partial fix at line 921-925).
- **Phase:** `bug`

### Template Registry KeyError Risk
- **Issue:** `request_analysis.py` line 210 checks `if template_name in TEMPLATES` but `TEMPLATES` dict may not have all keys the LLM generates. If LLM returns unknown template name, falls back silently.
- **Files:** `algorithms/request_analysis.py`, `algorithms/template_registry.py`
- **Trigger:** LLM generates non-standard template name.
- **Workaround:** Fallback to None path.
- **Phase:** `bug`

### Plan Compiler Unsupported Kind Crash
- **Issue:** `compile_plan` at `algorithms/plan/compiler.py` line 123 raises `ValueError("Unsupported kind: {kind}")` for unknown object kinds. This propagates up and fails the entire render.
- **Files:** `algorithms/plan/compiler.py`
- **Trigger:** Plan JSON with new/different object kind not in compiler's supported set.
- **Workaround:** Validation catches some issues via schema, but not all runtime errors.
- **Phase:** `bug`

---

## Security

### SQL Injection via String Formatting
- **Issue:** `ManimDatabase.get_best_examples()` at `app.py` line 244-256 uses Python `%` formatting with domain variable directly in SQL — though psycopg2 param substitution is used correctly at lines 256, 265-266. However `record_error_pattern` at line 271 uses `error_data["signature"]` in params correctly too. Actually safe — psycopg2 param substitution IS used. Minor concern: `execute()` raw strings could be mistaken for unsafe patterns.
- **Files:** `app.py` (ManimDatabase methods)
- **Impact:** Low if all queries use param substitution (they do).
- **Recommendation:** Audit all `cur.execute()` calls to ensure no `.format()` or f-string in SQL.
- **Phase:** `security`

### Path Traversal in Download Endpoint
- **Issue:** `/outputs/<path:filename>` at `app.py` line 1120-1126 calls `find_video_file(base)` which does glob matching. If `base` contains `../`, could escape output directory in glob fallback (line 729: `OUTPUTS.rglob(f"{filename}*.mp4")`).
- **Files:** `app.py`
- **Impact:** Could serve arbitrary files within project directory.
- **Recommendation:** Validate `filename` contains no `..` or path separators before glob.
- **Phase:** `security`

### No Authentication on API Endpoints
- **Issue:** `/api/generate`, `/api/prompts`, `/stats`, `/health` have no authentication. Anyone can trigger renders, query stats.
- **Files:** `app.py`
- **Impact:** Resource exhaustion via prompt injection; data exposure via `/stats`.
- **Recommendation:** Add API key middleware; rate limiting.
- **Phase:** `security`

### Generated Code Execution Risk
- **Issue:** `validate_names_and_imports()` at `algorithms/code_digest.py` catches some dangerous calls but not all. `_FORBIDDEN_CALLS` at line 23-33 includes `exec`, `eval`, `__import__`, `subprocess.*`. But `_ALLOWED_IMPORT_TOPS` at line 12-19 includes `random`, `itertools`, `collections` — these could be abused in generation prompts.
- **Files:** `algorithms/code_digest.py`
- **Current mitigation:** AST validation; `--disable_caching` in render; `subprocess.run` with limited args.
- **Recommendation:** Audit all allowed imports for runtime abuse potential.
- **Phase:** `security`

### API Key in Environment (Risk of Logging)
- **Issue:** `OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")` at `app.py` line 88. If this value is printed in logs (e.g., error messages), key could leak.
- **Files:** `app.py`
- **Impact:** Key exposure in log files.
- **Recommendation:** Mask key in all log output; use `print(f"[OK] Key: {'*' * 8}{key[-4:]}")` pattern.
- **Phase:** `security`

---

## Performance

### Blocking Render Thread Still Blocks Event Loop
- **Issue:** `render_async()` at `app.py` lines 950-974 spawns a daemon thread, but the Flask server is `threaded=True`. With many concurrent jobs, daemon threads can be killed abruptly. More critically, the `subprocess.run` in `_run_manim` at line 777 has `timeout=RENDER_TIMEOUT_SECONDS` (900s = 15 min) per attempt — with 3 retries = 45 min potential blocking per job.
- **Files:** `app.py`
- **Impact:** Thread pool exhaustion; jobs queue up behind long renders.
- **Fix approach:** Process-based isolation (multiprocessing) instead of threading; render queue.
- **Phase:** `performance`

### No Render Job Queue
- **Issue:** Each `render_async()` fires immediately. Multiple concurrent renders compete for CPU/GPU/memory.
- **Files:** `app.py`
- **Impact:** Resource contention on heavy loads; unpredictable render times.
- **Fix approach:** Redis queue with worker pool; limit concurrent renders.
- **Phase:** `performance`

### TTS Fallback Duration Estimate Unreliable
- **Issue:** `_get_audio_duration()` at `algorithms/tts.py` line 53-75 has a fallback: if ffprobe fails, estimate `size / 2000.0` bytes per second. This is ~2KB/s for speech — could be off 2-3x for different voices/speeds.
- **Files:** `algorithms/tts.py`
- **Impact:** Voiceover sync desyncs if duration estimate wrong.
- **Fix approach:** Require ffprobe; fail if not available rather than estimate.
- **Phase:** `performance`

### RAG JSON Loading on Every Import
- **Issue:** `_load_json_examples()` at `RAG/RAG_system.py` line 1133 opens and parses `training/manim_examples_raw.json` at module import time. For a large corpus, this adds startup latency and memory.
- **Files:** `RAG/RAG_system.py`
- **Impact:** Slow cold starts; memory bloat if corpus grows.
- **Fix approach:** Lazy loading; cache parsed results.
- **Phase:** `performance`

### Video File Search Heuristic
- **Issue:** `find_video_file()` at `app.py` lines 712-731 tries 7 different paths before globbing. This is fragile — Manim output location depends on version and CLI args.
- **Files:** `app.py`
- **Impact:** Video found in wrong location → "file not found" error even when render succeeded.
- **Fix approach:** Pass exact output path from manim CLI; use `--output_file` consistently.
- **Phase:** `performance`

---

## Fragile Areas

### Error Parser Pattern Matching
- **Issue:** `_ERROR_PATTERNS` at `algorithms/error_parser.py` lines 47-105 maps stderr patterns to error types using regex. Manim version updates may change stderr format, breaking all pattern matches.
- **Files:** `algorithms/error_parser.py`
- **Why fragile:** Single point of failure for entire self-healing render loop.
- **Safe modification:** Add new patterns conservatively; never remove existing without migration path.
- **Test coverage:** No unit tests for error_parser — would silently break on Manim update.
- **Phase:** `quality`

### Plan JSON Schema Validation
- **Issue:** `validate_plan_dict()` at `algorithms/plan/schema.py` validates structure but not semantic correctness (e.g., referenced object IDs must exist).
- **Files:** `algorithms/plan/schema.py`, `algorithms/plan/compiler.py`
- **Why fragile:** Bad plan JSON compiles partially then fails at runtime with cryptic errors.
- **Safe modification:** Add cross-reference validation (all `target`/`source` beat references point to valid object IDs).
- **Test coverage:** Insufficient — no property-based testing for schema.
- **Phase:** `quality`

### Overlap Detector Regex Coverage
- **Issue:** `overlap_detector.py` uses regex and AST to find position collisions. Complex Manim chains like `Circle().move_to(ORIGIN).set_color(RED)` may not be detected (line 28-33 only matches assignment patterns).
- **Files:** `algorithms/overlap_detector.py`
- **Why fragile:** Many valid Manim patterns slip through; raises false confidence.
- **Safe modification:** Add integration test with known problematic code; expand AST coverage.
- **Test coverage:** No test suite for overlap_detector.
- **Phase:** `quality`

### Database Connection Resilience
- **Issue:** `ManimDatabase` at `app.py` line 104 sets `autocommit=True` and `available` flag. If connection drops mid-session, no reconnection logic.
- **Files:** `app.py`
- **Why fragile:** Long-running server vs. DB connection timeout; `db.available = False` permanently if one query fails.
- **Safe modification:** Connection pool with ping-and-reconnect; wrap all DB calls in retry.
- **Test coverage:** No test for DB failure recovery.
- **Phase:** `infrastructure`

### Fast/Draft Pipeline Flag Evaluation
- **Issue:** `is_fast` is set from config at `app.py` line 322 then reassigned at line 511 and line 804. The logic is spread across multiple locations with different conditions — `FAST_PIPELINE or DRAFT_PIPELINE` checked at 5+ places.
- **Files:** `app.py`, `algorithms/ai_functions.py`
- **Why fragile:** Easy to add code that only checks one flag; behavior becomes inconsistent.
- **Safe modification:** Single `pipeline_mode()` helper; one authoritative source of truth.
- **Test coverage:** No test verifying all validations are correctly skipped in FAST/DRAFT.
- **Phase:** `refactor`

### LLM Response Parsing in extract_code
- **Issue:** `extract_code()` at `algorithms/ai_functions.py` lines 777-785 splits on ````python` or ` ``` ` markdown fences. If model returns no fences, returns raw text including prompt context. If model returns different fence language (e.g., ` ```py`), returns empty.
- **Files:** `algorithms/ai_functions.py`
- **Why fragile:** LLM non-determinism means fence format can vary; no validation that returned text is actually Python.
- **Safe modification:** Validate AST parseability after extraction; fall back to whole response if no fences found.
- **Phase:** `robustness`

### Template Registry Template Selection
- **Issue:** `choose_template()` at `algorithms/template_registry.py` — selection logic not visible here. If template selection fails silently, falls back to `None` and uses LLM-only path.
- **Files:** `algorithms/template_registry.py`
- **Why fragile:** Silent fallback hides template selection failures; user gets different quality path without knowing why.
- **Safe modification:** Log template selection decisions explicitly; alert if template matching fails for known domain types.
- **Phase:** `quality`

---

## Summary Table

| Area | Concern | Severity | Phase |
|------|---------|----------|-------|
| config | Hardcoded paths & credentials | High | infrastructure |
| app.py | Global in-memory state | High | infrastructure |
| app.py | Path traversal risk | High | security |
| app.py | No API authentication | High | security |
| app.py | Blocking render threads | Medium | performance |
| ai_functions.py | Duplicate client init | Medium | refactor |
| ai_functions.py | extract_code fragile parsing | Medium | robustness |
| error_parser.py | Pattern matching fragile | Medium | quality |
| RAG_system.py | Lambda closure bug | Medium | bug |
| plan/compiler.py | Unsupported kind crash | Medium | bug |
| overlap_detector.py | Limited regex coverage | Medium | quality |
| code_digest.py | Allowed imports attack surface | Medium | security |
| tts.py | Duration estimate fallback | Low | performance |
| app.py | No render job queue | Medium | performance |
| request_analysis.py | Template name mismatch | Low | bug |

---

*Concerns audit: 2026-04-04*
