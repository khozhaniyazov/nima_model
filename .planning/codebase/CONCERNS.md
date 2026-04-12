# Codebase Concerns

**Analysis Date:** 2026-04-12

## Tech Debt

**Monolithic server orchestration in one file (`app.py`):**
- Concern: Request handling, generation orchestration, rendering, DB access, webhooks, API key auth, LTI endpoints, and startup logic are combined in a single large module.
- Evidence: `app.py` is ~3,870 lines and defines all major flows and endpoints in one place (`C:\ai-manim\app.py`).
- Impact: High change risk; unrelated edits can regress core paths, and onboarding/maintenance cost is elevated.
- Mitigation direction: Split `app.py` into focused modules (`routes/`, `services/`, `db/`, `auth/`, `lti/`, `render/`) while keeping shared state interfaces explicit.

**Validation path references a missing function:**
- Concern: Parallel validation imports and uses `validate_no_forbidden_calls`, but this function is not implemented in `algorithms/code_digest.py`.
- Evidence: Import/use in `C:\ai-manim\app.py` (lines ~2130, ~2148); no definition found in `C:\ai-manim\algorithms\code_digest.py`.
- Impact: Validation worker can fail at runtime, reducing safety guarantees or breaking generation flow.
- Mitigation direction: Implement `validate_no_forbidden_calls` in `C:\ai-manim\algorithms\code_digest.py` or remove the dead import and route checks through existing validators.

**Legacy-focused tests are drifted from current config/runtime:**
- Concern: Some tests assert model defaults and flags that do not match current configuration.
- Evidence: `C:\ai-manim\test_imports.py` asserts `GENERATION_MODEL == "gpt-4o"` and `FAST_MODEL == "gpt-4o-mini"`, while `C:\ai-manim\config.py` defaults to `gpt-5.2-codex` for both.
- Impact: False failures hide real regressions and reduce trust in CI/local test signals.
- Mitigation direction: Update tests to assert behavior contracts (non-empty model, routing behavior) instead of stale literal defaults.

## Known Bugs

**Prompt variable capture bug in batch background workers:**
- Concern: Inner `background_generate()` closures in batch flow capture loop variables (`prompt`, `job_id`, `filename`) by reference.
- Evidence: Closure defined inside `for` loop in `C:\ai-manim\app.py` (`/api/batch` around lines ~2805–2871) without binding defaults.
- Impact: Jobs can process wrong prompt/metadata (typically last-iteration values), causing incorrect renders and attribution mismatch.
- Mitigation direction: Bind loop values as default args in worker definition (e.g., `def background_generate(prompt=prompt, job_id=job_id, ...)`).

**Potential webhook failure-path exception scoping issue:**
- Concern: Final failure logging in webhook delivery uses `e` after retry loop; value depends on prior exception path.
- Evidence: `db.save_webhook_delivery(..., str(e))` in `C:\ai-manim\app.py` around lines ~2049–2053.
- Impact: Secondary exception can mask primary delivery failure details.
- Mitigation direction: Track `last_error` explicitly through retry loop and persist that stable value.

## Security Considerations

**Hardcoded credential-bearing default DB connection string:**
- Concern: Configuration includes a credential-bearing PostgreSQL fallback string in source code.
- Evidence: `DB_CONNECTION_STRING` default in `C:\ai-manim\config.py` (lines ~30–33).
- Impact: Secret exposure risk in repository history and accidental environment misuse.
- Mitigation direction: Remove credential-bearing fallback; require env-provided DSN and fail fast when absent.

**Authentication coverage is inconsistent across sensitive endpoints:**
- Concern: API key protection exists (`require_api_key`) but applies only to selected key-management routes.
- Evidence: `@require_api_key` only on `GET/DELETE /api/keys` in `C:\ai-manim\app.py` (~3435+); routes like `/api/webhooks`, `/api/lti/platforms`, `/api/templates/*`, `/api/videos/cdn-url` are unprotected.
- Impact: Unauthorized mutation/read risk for operational configuration and metadata.
- Mitigation direction: Apply auth/authorization decorators consistently to all admin/configuration endpoints.

**LTI token processing skips signature verification:**
- Concern: LTI launch decodes JWT with signature verification disabled.
- Evidence: `jwt.decode(id_token, options={"verify_signature": False})` in `C:\ai-manim\app.py` (~3655).
- Impact: Forged tokens can impersonate users/roles, compromising trust boundaries.
- Mitigation direction: Verify signatures against platform JWKS, validate issuer/audience/nonce, and enforce clock-based claims.

## Performance Bottlenecks

**Repeated filesystem recursive scans for outputs:**
- Concern: Render path frequently uses recursive glob/rglob searches and stale-file cleanup on each request.
- Evidence: `find_video_file()` and cleanup loops use `OUTPUTS.rglob(...)` in `C:\ai-manim\app.py` (~1908+, ~2174+); scene pipeline also scans outputs in `C:\ai-manim\algorithms\streaming.py` (~1245+).
- Impact: I/O overhead scales with artifact volume and slows completion detection.
- Mitigation direction: Persist exact output paths from renderer and avoid broad recursive scans in hot paths.

**Heavy subprocess dependence with long timeouts:**
- Concern: Rendering/stitching/audio workflows run multiple ffmpeg/manim/ffprobe subprocesses with high timeout ceilings.
- Evidence: `subprocess.run(... timeout=...)` across `C:\ai-manim\app.py`, `C:\ai-manim\algorithms\streaming.py`, and `C:\ai-manim\algorithms\tts.py`.
- Impact: Worker occupancy is high under failure/slow environments; throughput drops quickly.
- Mitigation direction: Add per-stage budgets, cancellation propagation, and queued worker limits with backpressure.

## Fragile Areas

**In-memory job state is process-local and unbounded:**
- Concern: `render_status` and `job_to_request` are global dicts with no TTL/eviction/persistence.
- Evidence: Global state declarations and route reads/writes in `C:\ai-manim\app.py` (~106–159, status/batch endpoints).
- Impact: Memory growth over time, loss of job status on process restart, and inconsistent behavior in multi-worker deployments.
- Mitigation direction: Move job state to persistent store (DB/Redis) with retention policy and explicit lifecycle cleanup.

**Broad exception handling suppresses root-cause visibility:**
- Concern: Core pipeline modules use many `except Exception` blocks, sometimes returning defaults/fallbacks.
- Evidence: High density in `C:\ai-manim\app.py`, `C:\ai-manim\algorithms\request_analysis.py`, `C:\ai-manim\algorithms\streaming.py`, `C:\ai-manim\algorithms\ai_functions.py`, `C:\ai-manim\RAG\RAG_system.py`.
- Impact: Latent defects are hidden, making production diagnosis and regression isolation harder.
- Mitigation direction: Narrow exception classes, preserve context-rich error objects, and centralize structured error reporting.

## Scaling Limits

**Thread-per-request orchestration limits concurrency predictability:**
- Concern: Request flows spawn daemon threads (`render_async`, batch workers, webhook workers) without central queue management.
- Evidence: Thread creation in `C:\ai-manim\app.py` (~2555+, ~2762+, ~2870+, ~2069+).
- Impact: Under burst load, contention and scheduling overhead increase; graceful shutdown/reliability is weaker.
- Mitigation direction: Introduce task queue/worker model (RQ/Celery/Arq) with concurrency caps and durable retries.

**Rate limiting is in-memory and per-process:**
- Concern: Request throttling uses in-process dict storage.
- Evidence: `_rate_limit_storage` and `check_rate_limit()` in `C:\ai-manim\app.py` (~111–139).
- Impact: Limits are bypassable across multiple instances/processes and reset on restart.
- Mitigation direction: Use shared limiter backend (Redis) with atomic counters and standardized keys.

## Dependencies at Risk

**Optional embeddings path can silently degrade retrieval quality:**
- Concern: `sentence_transformers` load failures downgrade semantic retrieval to non-embedding behavior.
- Evidence: Conditional import and silent fallback logic in `C:\ai-manim\RAG\RAG_system.py` (~18–35, ~57–75).
- Impact: RAG relevance quality varies by environment without explicit operational signal.
- Mitigation direction: Emit explicit startup health status for embedding availability and fail/alert in environments expecting semantic search.

## Missing Critical Features

**No persistent audit trail for in-memory pipeline state transitions:**
- Concern: External clients rely on `/status/<job_id>` backed by volatile memory; lifecycle transitions are not durably event-sourced.
- Evidence: Status polling route and in-memory maps in `C:\ai-manim\app.py` (~2660+, ~106–159).
- Impact: Post-incident reconstruction and client reliability degrade after restarts or process crashes.
- Mitigation direction: Persist status transitions with timestamps in DB and serve status from durable records.

## Test Coverage Gaps

**Tests are script-style checks; critical API/security paths lack focused automated coverage:**
- Concern: Existing tests are mostly executable scripts and local harnesses; coverage for auth boundaries and endpoint protection is limited.
- Evidence: `C:\ai-manim\test_pipeline.py`, `C:\ai-manim\test_imports.py`, `C:\ai-manim\test_streaming_reliability.py`, `C:\ai-manim\test_edge_cases.py`, `C:\ai-manim\test_optimizations.py`.
- Impact: Security regressions and API contract breaks can ship undetected.
- Mitigation direction: Add deterministic unit/integration tests for auth decorators, LTI verification, batch closure correctness, webhook retry logic, and validator wiring.

---

*Concerns audit: 2026-04-12*
