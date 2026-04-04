---
phase: 1-Foundation-Stability
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - app.py
  - config.py
autonomous: true
requirements:
  - AUTH-01
  - GEN-01
  - GEN-02
  - GEN-03
  - GEN-04
  - GEN-05
  - QUAL-01
  - QUAL-02
  - QUAL-03
  - QUAL-04
  - HEAL-01
  - HEAL-02
  - HEAL-03
  - MODE-01
  - MODE-02
  - MODE-03
  - EXP-01
  - EXP-02
user_setup: []

must_haves:
  truths:
    - "Flask server binds to 127.0.0.1:5000, not 0.0.0.0"
    - "is_fast is passed explicitly to save_and_render() and _run_manim(), not captured from closure"
    - "Video file detection polls with retry when returncode=0 but file not yet written"
    - "render_status and job_to_request are protected by threading.Lock"
    - "Post-fix validation runs validate_names_and_imports(), validate_manim_code(), and validate_latex_strings() after fix_render_error()"
    - "MANIM_SCRIPTS and OUTPUTS can be set via environment variables"
  artifacts:
    - path: "app.py"
      provides: "Fixed scoping, thread safety, retry logic, validation enforcement"
    - path: "config.py"
      provides: "Configurable paths from environment"
  key_links:
    - from: "generate_and_validate_code()"
      to: "save_and_render()"
      via: "is_fast parameter (new)"
    - from: "save_and_render()"
      to: "_run_manim()"
      via: "is_fast parameter (new)"
    - from: "fix_render_error()"
      to: "validate_names_and_imports()"
      via: "post-fix validation calls (new)"
    - from: "render_status dict"
      to: "background threads + Flask main thread"
      via: "threading.Lock (new)"
---

<objective>
Fix all critical bugs that make the pipeline unreliable: is_fast scoping, video file race condition, thread-unsafe dicts, missing post-fix validation, network exposure, and hardcoded paths.
</objective>

<execution_context>
@$HOME/.config/opencode/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/phases/1-Foundation-Stability/RESEARCH.md
@.planning/phases/1-Foundation-Stability/VALIDATION.md
@.planning/phases/1-Foundation-Stability/PIPELINE.md
@.planning/phases/1-Foundation-Stability/GENERATION.md
@.planning/REQUIREMENTS.md
@.planning/codebase/ARCHITECTURE.md

## Key Bug Locations (from RESEARCH.md)

| Bug | File | Lines |
|-----|------|-------|
| is_fast scoping | app.py | 322, 753, 804 |
| Video detection race | app.py | 828-830 |
| Flask 0.0.0.0 binding | app.py | 1240 |
| Thread-unsafe dicts | app.py | 95-96 |
| Hardcoded paths | config.py | 23-24 |
| Validation bypass in FAST/DRAFT | app.py | 511-514 |
| Post-fix validation missing | app.py | 921-926 |

## is_fast Call Chain

```
generate_and_validate_code() [line 322]
  └── is_fast = FAST_PIPELINE or DRAFT_PIPELINE
  └── save_and_render(current_code, filename, job_id)  [line 806]
        └── _run_manim(code, filename, job_id)  [line 753: references is_fast]
              └── is_fast checked but NOT passed as parameter
```

## Post-fix Validation Gap (VALIDATION.md lines 99-108)

After `fix_render_error()` at line 919:
```python
current_code = fix_render_error(current_code, stderr, prompt)
# Re-validate syntax before retrying
syn_ok, _ = validate_python_syntax(current_code)
if not syn_ok:
    current_code = _polish(current_code)
current_code = ensure_scene_class(current_code)
```

**Missing:** `validate_names_and_imports()`, `validate_manim_code()`, `validate_latex_strings()` are NOT called post-fix.

## Video Detection Race (PIPELINE.md lines 298-304)

```python
video_path = find_video_file(filename)  # First check
if video_path:
    return success
elif result.returncode == 0:
    # returncode=0 but file not found → FALSE ERROR
    return error
```

Manim exits 0 before file is fully written. No retry.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix is_fast scoping — pass explicitly to save_and_render() and _run_manim()</name>
  <files>app.py</files>
  <action>
    Fix the is_fast scoping bug so FAST/DRAFT pipeline modes correctly reduce retry counts.

    **Step 1:** In `save_and_render()` function signature (line ~782), add `is_fast: bool` parameter:
    ```python
    def save_and_render(code: str, filename: str, job_id: str, is_fast: bool = False) -> dict:
    ```

    **Step 2:** Update the retry count calculation (line ~804) to use the passed parameter:
    ```python
    render_retries = 1 if is_fast else MAX_RENDER_RETRIES
    ```

    **Step 3:** Update the call site in `generate_and_validate_code()` (line ~806) to pass explicitly:
    ```python
    render_result = save_and_render(current_code, filename, job_id, is_fast=is_fast)
    ```

    **Step 4:** In `_run_manim()` function signature (line ~734), add `is_fast: bool` parameter:
    ```python
    def _run_manim(code: str, filename: str, job_id: str, is_fast: bool = False) -> subprocess.CompletedProcess:
    ```

    **Step 5:** Remove the module-level `is_fast` check in `_run_manim()` (line ~753) — replace closure capture with parameter:
    ```python
    elif is_fast:
        quality_flag = "-ql"  # Low quality
    ```

    **Step 6:** Update the call from `save_and_render()` to `_run_manim()` to pass `is_fast`:
    ```python
    result = _run_manim(current_code, filename, job_id, is_fast=is_fast)
    ```

    **Rationale:** The current code relies on Python closure to capture `is_fast` from `generate_and_validate_code()`. While this works in practice because FAST_PIPELINE/DRAFT_PIPELINE are module-level constants, it is fragile. Explicit parameter passing makes the contract clear and prevents future breakage.
  </action>
  <verify>
    <automated>python -c "import ast; ast.parse(open('app.py').read()); print('Syntax OK')"</automated>
  </verify>
  <done>
    `is_fast` is passed as an explicit parameter from `generate_and_validate_code()` → `save_and_render()` → `_run_manim()`. No closure capture of `is_fast` remains in `_run_manim()`.
  </done>
</task>

<task type="auto">
  <name>Task 2: Fix video file detection race condition — poll/retry when returncode=0 but file not found</name>
  <files>app.py</files>
  <action>
    Fix the race condition where Manim returns exit code 0 but the video file is not yet written.

    **In `save_and_render()`, after `_run_manim()` returns but BEFORE treating returncode=0 + no file as an error:**

    Add a poll/retry loop (3 attempts, 1 second sleep) when `returncode == 0` but `find_video_file()` returns None:

    ```python
    video_path = find_video_file(filename)

    # Race condition fix: poll if returncode=0 but file not found yet
    if not video_path and result.returncode == 0:
        for poll_attempt in range(3):
            time.sleep(1)
            video_path = find_video_file(filename)
            if video_path:
                break

    if video_path:
        # SUCCESS (existing logic)
        ...
    elif result.returncode == 0 and not video_path:
        # After polling, still no file → genuine error (not race)
        render_data["status"] = "error"
        render_data["error"] = "file_not_found_after_retry"
        return render_data
    ```

    **Also fix stale file glob:** In `find_video_file()`, add a timestamp check to the glob fallback to avoid returning very old stale files:

    ```python
    # After line 163: glob fallback
    now = time.time()
    for mp4 in OUTPUTS.rglob(f"{filename}*.mp4"):
        # Reject files older than 5 minutes as stale
        if now - mp4.stat().st_mtime < 300:
            return mp4
    return None
    ```

    **Rationale:** Manim's ffmpeg encoding finishes after the process returns. The 1-second polling window catches files that are being written. The 5-minute staleness check prevents returning old files from failed cleanup.
  </action>
  <verify>
    <automated>python -c "import ast; ast.parse(open('app.py').read()); print('Syntax OK')"</automated>
  </verify>
  <done>
    Video file detection polls up to 3 times with 1s sleep when returncode=0 but file not found on first check. Stale files (>5 min old) are excluded from glob fallback.
  </done>
</task>

<task type="auto">
  <name>Task 3: Add thread safety — threading.Lock for render_status and job_to_request</name>
  <files>app.py</files>
  <action>
    Protect `render_status` and `job_to_request` module-level dicts with `threading.Lock` since they are written from background render threads and read from the Flask main thread.

    **Step 1:** Add lock at module level (after the dict definitions at lines 95-96):
    ```python
    render_status: Dict[str, dict] = {}
    job_to_request: Dict[str, dict] = {}
    _state_lock = threading.Lock()
    ```

    **Step 2:** Create helper functions for thread-safe access:

    ```python
    def get_job_status(job_id: str) -> Optional[dict]:
        with _state_lock:
            return render_status.get(job_id)

    def set_job_status(job_id: str, status: dict) -> None:
        with _state_lock:
            render_status[job_id] = status

    def get_job_request(job_id: str) -> Optional[dict]:
        with _state_lock:
            return job_to_request.get(job_id)

    def set_job_request(job_id: str, request: dict) -> None:
        with _state_lock:
            job_to_request[job_id] = request
    ```

    **Step 3:** Replace all direct accesses to `render_status[job_id]` and `job_to_request[job_id]` with the helper functions. Key locations:
    - `api_generate()`: writes to both dicts
    - `api_status()`: reads `render_status[job_id]`
    - `save_and_render()`: reads/writes `render_status[job_id]`
    - `render_async()`: writes to both dicts

    Use `grep -n "render_status\[" app.py` and `grep -n "job_to_request\[" app.py` to find all occurrences.

    **Rationale:** Under concurrent requests, background threads writing to these dicts while the Flask main thread reads can cause KeyError or inconsistent state. A simple threading.Lock prevents this.
  </action>
  <verify>
    <automated>python -c "import ast; ast.parse(open('app.py').read()); print('Syntax OK')"</automated>
  </verify>
  <done>
    All reads/writes to `render_status` and `job_to_request` are protected by `_state_lock`. No bare dict access outside of lock context.
  </done>
</task>

<task type="auto">
  <name>Task 4: Add post-fix validation — run safety/structure/LaTeX checks after fix_render_error()</name>
  <files>app.py</files>
  <action>
    After `fix_render_error()` returns in the render retry loop, run full validation (not just syntax) before retrying render.

    **In the render retry loop (around line 921-926), after `current_code = fix_render_error(...)`:**

    ```python
    current_code = fix_render_error(current_code, stderr, prompt)

    # Post-fix validation: ensure the LLM fix didn't break safety or structure
    is_safe, safety_issues = validate_names_and_imports(current_code)
    if not is_safe:
        print(f"[{job_id}] [WARN] Post-fix safety check failed: {safety_issues}")
        # Fall back to syntax-only polish for safety issues
        from algorithms.ai_functions import polish_manim_code as _polish
        current_code = _polish(current_code)
        is_safe, safety_issues = validate_names_and_imports(current_code)
        if not is_safe:
            print(f"[{job_id}] [ERR] Safety issues persist after polish: {safety_issues}")

    structure_valid, structure_error = validate_manim_code(current_code)
    if not structure_valid:
        print(f"[{job_id}] [WARN] Post-fix structure check failed: {structure_error}")
        current_code = ensure_scene_class(current_code)

    # Math domain: re-validate LaTeX after fix
    if analysis.get("domain") == "math" and not is_fast:
        latex_valid, latex_issues = validate_latex_strings(current_code)
        if not latex_valid:
            print(f"[{job_id}] [WARN] Post-fix LaTeX check failed: {latex_issues}")

    # Syntax check (existing)
    syn_ok, _ = validate_python_syntax(current_code)
    if not syn_ok:
        from algorithms.ai_functions import polish_manim_code as _polish
        current_code = _polish(current_code)
    current_code = ensure_scene_class(current_code)
    ```

    **Note:** You need to ensure `analysis` is available in `save_and_render()`. Pass it as a parameter if not already present. If `analysis` is not available, skip the LaTeX re-check and log a warning.

    **Rationale:** Currently only syntax is re-checked post-fix. A bad LLM fix could introduce forbidden imports, remove the Scene class, or break LaTeX strings. These should be caught before wasting a render attempt.
  </action>
  <verify>
    <automated>python -c "import ast; ast.parse(open('app.py').read()); print('Syntax OK')"</automated>
  </verify>
  <done>
    After each `fix_render_error()` call in the render retry loop, `validate_names_and_imports()`, `validate_manim_code()`, and `validate_latex_strings()` (for math domain) are called before the next render attempt.
  </done>
</task>

<task type="auto">
  <name>Task 5: Fix Flask network exposure — bind to 127.0.0.1 and restrict CORS</name>
  <files>app.py</files>
  <action>
    Change Flask server binding from `0.0.0.0` (all interfaces) to `127.0.0.1` (localhost only), and restrict CORS.

    **Step 1:** Change `app.run()` binding (line ~1240):
    ```python
    # BEFORE:
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
    # AFTER:
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
    ```

    **Step 2:** Restrict CORS to localhost:3000 (update the CORS initialization near line ~982):
    ```python
    # BEFORE:
    CORS(app)
    # AFTER:
    CORS(app, origins=["http://localhost:3000"], methods=["GET", "POST"], allow_headers=["Content-Type"])
    ```

    **Rationale:** The code comments in CONCERNS.md state "localhost only" but Flask was binding to all interfaces. On a shared LAN, this exposes the unauthenticated API. Restricting to 127.0.0.1 fixes this per AUTH-01.
  </action>
  <verify>
    <automated>python -c "import ast; ast.parse(open('app.py').read()); print('Syntax OK')"</automated>
  </verify>
  <done>
    Flask binds to 127.0.0.1:5000. CORS is restricted to http://localhost:3000.
  </done>
</task>

<task type="auto">
  <name>Task 6: Make paths configurable — MANIM_SCRIPTS and OUTPUTS from environment variables</name>
  <files>config.py</files>
  <action>
    Replace hardcoded `C:/temp/` paths with environment variable overrides in config.py.

    **In config.py (lines 22-26), replace:**

    ```python
    # BEFORE:
    MANIM_SCRIPTS = Path("C:/temp/manim_scripts")
    OUTPUTS = Path("C:/temp/outputs")
    MANIM_SCRIPTS.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    # AFTER:
    MANIM_SCRIPTS = Path(os.environ.get("MANIM_SCRIPTS", "C:/temp/manim_scripts"))
    OUTPUTS = Path(os.environ.get("OUTPUTS", "C:/temp/outputs"))
    MANIM_SCRIPTS.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    ```

    **Rationale:** Hardcoded `C:/temp` paths fail on non-Windows or if the directory doesn't exist. Environment variable overrides make the app portable and deployable.
  </action>
  <verify>
    <automated>python -c "import ast; ast.parse(open('config.py').read()); print('Syntax OK')"</automated>
  </verify>
  <done>
    `MANIM_SCRIPTS` defaults to `C:/temp/manim_scripts` but can be overridden with `MANIM_SCRIPTS` env var. `OUTPUTS` defaults to `C:/temp/outputs` but can be overridden with `OUTPUTS` env var.
  </done>
</task>

<task type="auto">
  <name>Task 7: Improve error pattern recording feedback — log when DB recording fails</name>
  <files>app.py</files>
  <action>
    The `_exec()` method in `app.py` (lines 116-130) silently swallows all DB errors with just a print. Make DB recording failures visible without breaking the pipeline.

    **In the `record_error_pattern()` call site (around line 906), wrap with visible logging:**

    ```python
    if db and db.available:
        try:
            db.record_error_pattern({...})
        except Exception as e:
            # Log to stderr/stdout so it's visible in server logs
            print(f"[{job_id}] [DB] [ERR] Failed to record error pattern: {e}", flush=True)
    else:
        print(f"[{job_id}] [DB] [WARN] Database unavailable — error pattern not recorded", flush=True)
    ```

    Also in `_exec()` method: instead of silently returning None on exception, log at minimum:
    ```python
    except Exception as e:
        print(f"[DB] [ERR] Query failed: {e}", flush=True)
        return None
    ```

    **Rationale:** The error pattern learning system provides zero feedback when broken. Visible logging helps diagnose why pattern coalescence isn't working.
  </action>
  <verify>
    <automated>python -c "import ast; ast.parse(open('app.py').read()); print('Syntax OK')"</automated>
  </verify>
  <done>
    DB errors during `record_error_pattern()` are logged to stdout with `[DB] [ERR]` prefix. When DB is unavailable, a `[DB] [WARN]` is logged.
  </done>
</task>

<task type="auto">
  <name>Task 8: Add warmup failure logging — log when manim pre-warm fails</name>
  <files>app.py</files>
  <action>
    The manim pre-warm runs in a daemon thread and its failure is silently ignored (line 1232-1234). Make warmup failures visible.

    **Around line 1232-334, update:**

    ```python
    warmup_thread = threading.Thread(target=prewarm_manim, daemon=True)
    warmup_thread.start()

    # Add: check if warmup completed within 30s
    def _check_warmup():
        warmup_thread.join(timeout=30)
        if warmup_thread.is_alive():
            print("[WARMUP] [WARN] Manim warmup did not complete within 30s — first render will pay cold-start cost", flush=True)
        else:
            print("[WARMUP] [OK] Manim warmup completed", flush=True)

    threading.Thread(target=_check_warmup, daemon=True).start()
    ```

    Also in `prewarm_manim()`: wrap the body in try/except and log any exceptions:
    ```python
    def prewarm_manim():
        try:
            # existing warmup code
        except Exception as e:
            print(f"[WARMUP] [ERR] Manim warmup failed: {e}", flush=True)
    ```

    **Rationale:** If manim is not installed or ffmpeg is missing, the first real render fails with a confusing error. Visible warmup failure helps debug faster.
  </action>
  <verify>
    <automated>python -c "import ast; ast.parse(open('app.py').read()); print('Syntax OK')"</automated>
  </verify>
  <done>
    Warmup failures are logged with `[WARMUP] [ERR]` prefix. Warmup completion is confirmed with `[WARMUP] [OK]`. Timeout after 30s triggers a warning.
  </done>
</task>

</tasks>

<verification>
All tasks modify `app.py` and `config.py`. After all changes:
1. `python -c "import ast; ast.parse(open('app.py').read())"` — app.py has valid Python syntax
2. `python -c "import ast; ast.parse(open('config.py').read())"` — config.py has valid Python syntax
3. Grep for `host="0.0.0.0"` — should return no matches in app.py
4. Grep for `is_fast` in `_run_manim` scope — should show parameter, not closure capture
5. Grep for `threading.Lock` — should find `_state_lock` definition and usage
</verification>

<success_criteria>
- Flask binds to 127.0.0.1 not 0.0.0.0 (AUTH-01)
- is_fast is passed as explicit parameter, not closure-captured (MODE-01, MODE-02, MODE-03)
- Video file detection polls/retry on race condition (GEN-03, GEN-05)
- render_status and job_to_request are thread-safe (GEN-04)
- Post-fix validation runs safety, structure, and LaTeX checks (QUAL-03, QUAL-04, HEAL-02, HEAL-03)
- Paths are configurable via environment variables (infrastructure)
- Error pattern recording logs failures visibly (HEAL-01)
- Warmup failures are logged visibly (infrastructure)
</success_criteria>

<output>
After completion, create `.planning/phases/1-Foundation-Stability/1-01-PLAN-SUMMARY.md`
</output>
