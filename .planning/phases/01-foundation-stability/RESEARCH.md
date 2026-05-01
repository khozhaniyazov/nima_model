# Phase 1 Research: Foundation & Stability

**Phase:** 1-Foundation-Stability  
**Researched:** 2026-04-04  
**Confidence:** MEDIUM-HIGH (code inspection; no runtime testing performed)

---

## Executive Summary

The codebase implements all Phase 1 requirements in architecture, but **multiple critical bugs and architectural flaws** will cause failures in production. The pipeline is designed correctly but has scoping bugs, hardcoded paths, network exposure, and race conditions that must be fixed before Phase 1 can be considered stable.

---

## AUTH-01: Web Interface Accessible Without Auth (localhost)

### Current Implementation

Flask serves on `0.0.0.0:5000` (all interfaces), CORS is enabled for all origins. No authentication middleware exists anywhere.

### Issues Found

| Issue | Severity | Location |
|-------|----------|----------|
| Flask binds to `0.0.0.0` not `127.0.0.1` | **HIGH** | `app.py:1240` — `app.run(host="0.0.0.0", ...)` |
| CORS allows all origins | MEDIUM | `app.py:982` — `CORS(app)` with no restrictions |
| No API key or token auth | Low (by design) | Intended for localhost only |

### Analysis

The code comments state "localhost only" (CONCERNS.md), but the server is actually exposed on all network interfaces. On a development machine, this means any device on the LAN can access the API. Combined with no authentication, this is a significant exposure if the dev machine is on a shared network.

### Required Fix for Phase 1

```python
# Change from:
app.run(host="0.0.0.0", port=5000, ...)
# To:
app.run(host="127.0.0.1", port=5000, ...)
```

CORS should be restricted to `localhost:3000` explicitly.

---

## GEN-01 to GEN-05: Complete Pipeline Flow

### GEN-01: Submit Prompt

**Status:** ✅ IMPLEMENTED  
**Location:** `nima-frontend/src/app/page.tsx:131-165`

The frontend captures the prompt, trims whitespace, and POSTs to `/api/generate`. No issues.

### GEN-02: AI Generates Manim Code

**Status:** ✅ IMPLEMENTED  
**Location:** `app.py:309-704` (`generate_and_validate_code`)

Pipeline: `expand_short_prompt()` → `analyze_request_type()` → `create_animation_plan()` → `generate_manim_code()` → `review_and_fix()` → validation layers → return code.

### GEN-03: Render to Video

**Status:** ⚠️ FLAKY — multiple issues  
**Location:** `app.py:782-947` (`save_and_render`), `app.py:734-779` (`_run_manim`)

**Issue 1 — Race condition in video file detection (`app.py:828-830`):**
```python
video_path = find_video_file(filename)
if video_path:
    # SUCCESS
elif result.returncode == 0:
    # returncode=0 but file not found → ERROR
```
Manim sometimes takes extra time to write the file after returning. There's no retry/wait logic — first check misses = false error.

**Issue 2 — Multiple candidate paths cause stale file returns (`find_video_file`, `app.py:712-731`):**
```python
candidates = [
    OUTPUTS / "videos" / filename / "1080p60" / "GeneratedScene.mp4",
    OUTPUTS / "videos" / "1080p60" / "GeneratedScene.mp4",
    OUTPUTS / filename / "GeneratedScene.mp4",
    OUTPUTS / "GeneratedScene.mp4",
]
```
Glob fallback `OUTPUTS.rglob(f"{filename}*.mp4")` can return a stale file from a previous run if cleanup fails.

**Issue 3 — `_run_manim` quality flags use wrong variable (`app.py:753`):**
```python
elif is_fast:
    quality_flag = "-ql"  # Low quality
```
`is_fast` is referenced here but is NOT in scope for `_run_manim`. It's a local variable in `generate_and_validate_code`, not passed in. The function relies on a closure but this may be `None` or stale in some call paths.

### GEN-04: Poll Status

**Status:** ✅ IMPLEMENTED  
**Location:** `nima-frontend/src/app/page.tsx:96-122`

Polls `/status/{job_id}` every 1500ms. Stops polling on `done` or `error`. **Missing:** No overall timeout — if a job is stuck in `generating` forever, the UI just polls indefinitely.

### GEN-05: Download Video

**Status:** ✅ IMPLEMENTED  
**Location:** `nima-frontend/src/app/page.tsx:369-371`

Download link at `/outputs/{video_file}`. Backend route at `app.py:1120-1126`.

---

## QUAL-01 to QUAL-04: Validation Layers

### QUAL-01: Syntax Validation

**Status:** ✅ IMPLEMENTED  
**Function:** `validate_python_syntax()` in `algorithms/code_digest.py:57-65`

Uses Python AST parsing to detect syntax errors. Returns `(True, "")` on success, `(False, error_message)` on failure.

### QUAL-02: Manim Structure Validation

**Status:** ✅ IMPLEMENTED  
**Function:** `validate_manim_code()` in `algorithms/code_digest.py:125-140`

Checks for:
- `from manim import *`
- `class GeneratedScene(Scene)`
- `def construct(self)`
- At least one `self.play()` call

### QUAL-03: Security Validation

**Status:** ✅ IMPLEMENTED  
**Function:** `validate_names_and_imports()` in `algorithms/code_digest.py:68-122`

AST-based check blocking:
- Forbidden imports (anything not in `manim`, `numpy`, `math`, etc.)
- Dangerous calls: `exec`, `eval`, `__import__`, `os.system`, `subprocess.run`
- Forbidden objects: `SVGMobject`, `ImageMobject`, `manimlib`

### QUAL-04: LaTeX Validation

**Status:** ✅ IMPLEMENTED  
**Function:** `validate_latex_strings()` in `algorithms/code_digest.py:255-307`

Checks for:
- Unmatched braces `{ }`
- Unmatched brackets `[ ]`
- Unmatched `$` signs
- Common bad patterns: `log_`, `sin_`, `cos_` (missing backslash)

**Note:** LaTeX validation only runs in FULL pipeline (not FAST/DRAFT) for math domain (`app.py:521-531`).

---

## HEAL-01 to HEAL-03: Self-Healing Render Loop

### HEAL-01: Parse Render Errors

**Status:** ✅ IMPLEMENTED  
**Function:** `parse_manim_error()` in `algorithms/error_parser.py:174-232`

Strips tqdm noise and ANSI escapes, then pattern-matches against 20+ error patterns (AttributeError, TypeError, LaTeXError, etc.). Returns structured dict with error_type, message, line_number, code_context, fix_hint.

### HEAL-02: LLM-Powered Fixing

**Status:** ✅ IMPLEMENTED  
**Function:** `fix_render_error()` in `algorithms/ai_functions.py:738-769`

Feeds parsed error + original code + prompt to LLM with FIX_SYSTEM prompt containing per-error-type recipes. Returns fixed code.

### HEAL-03: Up to 3 Retries

**Status:** ⚠️ BUGGY — retry count is incorrectly scoped  
**Location:** `app.py:804`, `app.py:806-807`

```python
render_retries = 1 if is_fast else MAX_RENDER_RETRIES  # BUG: is_fast not in scope!

for render_attempt in range(1, render_retries + 1):
```

`is_fast` is a local variable in `generate_and_validate_code()` (line 322), not passed to `save_and_render()`. In practice, `is_fast` evaluates to `True` or `False` based on the `FAST_PIPELINE` or `DRAFT_PIPELINE` env vars at the time `generate_and_validate_code()` was called, which should be correct since those are set at module load time. However, this is fragile — the scoping is misleading and `is_fast` should be explicitly passed as a parameter.

**More critical:** The retry loop calls `fix_render_error()` (line 919), which calls `validate_python_syntax()` before retry (lines 921-925). But if syntax is still invalid after the fix, there's no additional retry — it proceeds to render again anyway (line 926: `current_code = ensure_scene_class(current_code)`), which will fail again.

### Gap: Error Pattern Recording May Silence Errors

```python
if db and db.available:
    db.record_error_pattern({...})  # Silently ignored if DB unavailable
```

No fallback logging when DB is disabled. Errors in `record_error_pattern()` exceptions are caught and ignored inside `_exec()`.

---

## MODE-01 to MODE-03: Pipeline Modes

### MODE-01: FULL Pipeline

**Status:** ✅ IMPLEMENTED

Full validation, overlap detection, quality checks, evaluation. 30fps, INFO verbosity.

### MODE-02: FAST Pipeline

**Status:** ⚠️ BROKEN in one area  
**Environment:** `FAST_PIPELINE=true`

Skips: overlap detection, quality checks, LaTeX validation, review pass (unless critical errors). Uses 15fps, WARNING verbosity.

**Issue:** `is_fast = FAST_PIPELINE or DRAFT_PIPELINE` is computed inside `generate_and_validate_code()` (line 322). But this same logic is NOT replicated in `_run_manim()` — instead `_run_manim` checks `DRAFT_PIPELINE` first, then `is_fast`, but `is_fast` isn't passed in. The manim quality flag selection works by accident of Python closure/scope, not by design.

### MODE-03: DRAFT Pipeline

**Status:** ✅ IMPLEMENTED

Uses `-qk` (keep edges, lowest quality), 10fps, ERROR verbosity. Manim warmup skipped (`app.py:1185-1187`).

---

## EXP-01 to EXP-02: Prompt Expansion

### EXP-01: Truncated Prompt Detection

**Status:** ✅ IMPLEMENTED  
**Function:** `expand_short_prompt()` in `algorithms/request_analysis.py:379-426`

Detects trailing `…` or `...` and prompts starting with `solve`, `compute`, `find`, `calculate`, `evaluate`, `determine`, `prove`, `show`, `derive`.

### EXP-02: Prompt Expansion

**Status:** ✅ IMPLEMENTED  
**Function:** `expand_short_prompt()` in `algorithms/request_analysis.py:379-426`

Adds domain-specific extension:
- `log` → "Show the step-by-step solution with clear visual explanation of logarithms."
- `lim`/`limit` → "Show the graphical interpretation and step-by-step evaluation of the limit."
- `derivative`/`differentiate` → visual interpretation of rate of change
- `integral` → area under curve visualization
- `solve` + `equation` → visual equation solving steps
- `compute`/`calculate` → step-by-step computation with visuals

Called at the start of `generate_and_validate_code()` (line 328): `prompt = expand_short_prompt(prompt)`.

---

## Critical Flaky Components

### 1. `is_fast` Scope Bug in Render Loop

**File:** `app.py:753`, `app.py:804`

The variable `is_fast` is computed inside `generate_and_validate_code()` but referenced inside `_run_manim()` and `save_and_render()` without being passed as a parameter. While `FAST_PIPELINE` is a module-level constant that works today, this is fragile — a future refactor or threading issue could break it silently.

**Impact:** FAST_PIPELINE may not correctly reduce retries from 3 to 1 because `is_fast` in `save_and_render()` is not the same variable.

**Fix needed:** Pass `is_fast` explicitly to `save_and_render()` and `_run_manim()`.

### 2. Video File Detection Race Condition

**File:** `app.py:828-894`

Manim's `result.returncode == 0` does NOT guarantee the video file is written. There's a 1-2 second gap between Manim returning and the file appearing on disk, especially with ffmpeg encoding.

**Impact:** False "file not found" errors even when render succeeded.

**Fix needed:** Add a poll/retry loop (3 attempts, 1s sleep) when `returncode == 0` but file not found.

### 3. Stale File Return from Glob

**File:** `app.py:729-730`

```python
for mp4 in OUTPUTS.rglob(f"{filename}*.mp4"):
    return mp4
```

If cleanup of old files fails (line 741-745), the glob can return a stale file from a previous job with the same `job_id` prefix (8-char UUID fragment, so collisions are unlikely but possible under load).

### 4. Network Exposure (AUTH-01)

**File:** `app.py:1240`

Server binds to `0.0.0.0:5000`, not `127.0.0.1:5000`. Any device on the LAN can access the unauthenticated API.

### 5. Hardcoded Windows Paths

**File:** `config.py:23-24`

```python
MANIM_SCRIPTS = Path("C:/temp/manim_scripts")
OUTPUTS = Path("C:/temp/outputs")
```

Not portable. No environment variable override. `C:/temp` may not exist or may have permission issues on non-Windows or certain Windows configs.

### 6. Threading: `render_status` and `job_to_request` Not Thread-Safe

**File:** `app.py:95-96`

```python
render_status: Dict[str, dict] = {}
job_to_request: Dict[str, dict] = {}
```

These module-level dicts are written from background threads and read from the Flask main thread with no locks. Under concurrent requests, this can cause `KeyError` or inconsistent state.

### 7. No Job Timeout in Polling

**File:** `nima-frontend/src/app/page.tsx:96-122`

Polling continues indefinitely even if the backend job is stuck. No timeout triggers an error state in the UI.

### 8. Error Pattern Recording Silently Fails

**File:** `app.py:116-130` (`_exec` method)

```python
except Exception as e:
    print(f"[DB] [ERR] {e}")
    return None
```

Any DB error is swallowed. `record_error_pattern()` calls `_exec()` which can fail silently. The error pattern learning system provides zero feedback when broken.

### 9. Manim Pre-warm is Fire-and-Forget

**File:** `app.py:1232-1233`

```python
warmup_thread = threading.Thread(target=prewarm_manim, daemon=True)
warmup_thread.start()
```

If warmup fails (manim not installed, ffmpeg missing, etc.), it's silently ignored. First real render pays the cold-start penalty anyway.

---

## Phase 1 Stability Issues to Address

### Must Fix (Blockers)

1. **Scope `is_fast` properly** — pass as parameter to `save_and_render()` and `_run_manim()`
2. **Fix video file detection race** — poll/retry when `returncode == 0` but file not found
3. **Restrict Flask to localhost** — `host="127.0.0.1"` not `"0.0.0.0"`
4. **Make paths configurable** — `MANIM_SCRIPTS` and `OUTPUTS` from env vars, not hardcoded `C:/temp`

### Should Fix (Reliability)

5. **Add job timeout** — frontend polling should fail after ~15 minutes
6. **Add thread safety** — use `threading.Lock` for `render_status` and `job_to_request`
7. **Log warmup failures** — don't silently swallow manim pre-warm errors
8. **Fix error pattern recording feedback** — at minimum log when DB recording fails

### Consider Fixing (Quality)

9. **Improve video file candidate list** — Manim output structure varies by version; document exact expected paths
10. **Improve glob robustness** — add file age check to avoid returning very old stale files
11. **CORS restriction** — `CORS(app, origins=["http://localhost:3000"])`

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| AUTH-01 | HIGH | Code clearly shows `0.0.0.0` binding |
| GEN-01-05 | MEDIUM | Architecture sound, but video detection race is real |
| QUAL-01-04 | HIGH | All validators exist and use appropriate techniques |
| HEAL-01-03 | MEDIUM | Error parsing is comprehensive, but retry scoping is buggy |
| MODE-01-03 | MEDIUM | Logic exists, but `is_fast` scoping undermines reliability |
| EXP-01-02 | HIGH | Implementation is straightforward and correct |

---

## Sources

- `app.py` — Flask server, pipeline orchestration, render loop
- `algorithms/code_digest.py` — Syntax, structure, security, LaTeX validation
- `algorithms/error_parser.py` — Manim stderr parsing for self-healing
- `algorithms/ai_functions.py` — LLM generation, review, fix, evaluation
- `algorithms/request_analysis.py` — Prompt analysis, planning, expansion
- `algorithms/overlap_detector.py` — Layout overlap detection
- `nima-frontend/src/app/page.tsx` — Frontend UI
- `config.py` — Configuration including pipeline modes
- `.planning/codebase/ARCHITECTURE.md` — System architecture overview
- `.planning/codebase/CONCERNS.md` — Known technical concerns
