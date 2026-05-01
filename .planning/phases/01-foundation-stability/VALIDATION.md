# Phase 1 Validation Pipeline Research

**Phase:** 1-Foundation-Stability  
**Focus:** Validation and Error Handling  
**Researched:** 2026-04-04  
**Confidence:** HIGH

---

## Executive Summary

The validation pipeline operates at two distinct layers: **pre-render static validation** (code_digest.py, overlap_detector.py) and **post-render self-healing** (app.py save_and_render loop). Short prompts are expanded before analysis via simple keyword matching in `expand_short_prompt()`.

**Critical gaps identified:**
1. FAST/DRAFT pipeline modes skip ALL quality validation entirely — QUAL-01 through QUAL-04 are effectively no-ops in these modes
2. Self-healing loop does not validate the fixed code's safety or structure before re-rendering — a malicious or structurally broken fix could cause cascading failures
3. `expand_short_prompt()` uses only 6 hardcoded keyword patterns with no LLM fallback for edge cases
4. Error parsing relies on regex pattern matching that can miss novel error formats

---

## 1. How Validation Currently Works

### 1.1 Pre-Render Static Validation (`code_digest.py`)

The `code_digest.py` module provides AST-based and regex-based static checks with no LLM calls:

| Function | Purpose | Returns |
|----------|---------|---------|
| `validate_python_syntax()` | Parse code with `ast.parse()` | `(bool, str)` — valid + error msg |
| `validate_names_and_imports()` | AST walk for forbidden imports/calls | `(bool, List[str])` — safe + issues |
| `validate_manim_code()` | Check Scene structure, `self.play()` | `(bool, str)` — valid + error |
| `check_code_quality()` | Regex/heuristic quality checks | `(bool, list)` — passes + warnings |
| `validate_latex_strings()` | Check MathTex/Tex brace matching | `(bool, List[str])` — valid + issues |
| `ensure_scene_class()` | Wrap bare `construct()` in Scene class | `str` — corrected code |

**Critical quality checks in `check_code_quality()`:**
- MathTex indexing (`eq[0][k]`) — CRASH RISK, flagged as `[ERR]`
- Total `self.wait()` time — warns if < 10s
- `self.clear()` usage — warns (breaks continuity)
- `NumberPlane()` without opacity — warns (grid dominates)
- Lambda closure in loops — warns (late binding bug)
- Repeated `move_to` to same position — warns (overlap risk)
- `SVGMobject`/`ImageMobject` — `[ERR]` blocks render
- `DashedArrow` — `[ERR]` (doesn't exist in Manim CE)
- `from manimlib` — `[ERR]` wrong library

### 1.2 Layout Overlap Detection (`overlap_detector.py`)

Five separate detectors run via `run_all_checks()`:

| Detector | What it Catches |
|----------|-----------------|
| `detect_position_collisions()` | Multiple objects at same `move_to` without FadeOut |
| `detect_object_accumulation()` | >10 Create/Write with <40% effective cleanup |
| `detect_missing_section_cleanup()` | Comment-section headers (`# === SCENE`) without cleanup |
| `detect_long_construct()` | >25 `self.play()` calls without section helpers |
| `detect_stale_copies()` | `.copy()` without removing original |

**Key limitation:** All detection is regex/AST-based. It cannot reason about actual spatial relationships — e.g., two objects at `ORIGIN` and `LEFT*2+ORIGIN` would be flagged as collision even if visually distinct.

### 1.3 Error Parsing (`error_parser.py`)

`parse_manim_error()` strips noise from Manim stderr then matches against 24 regex patterns:

```python
_ERROR_PATTERNS = [
    (r"AttributeError: '(.+)' object has no attribute '(.+)'", "AttributeError", ...),
    (r"TypeError: (.+)\(\) (takes|got) (.+)", "TypeError", ...),
    # ... 22 more patterns
]
```

**Noise stripping removes:**
- tqdm progress bars (`it/s]`, `|`, percentage bars)
- ANSI escape sequences
- Manim INFO logs (`[03/05/26 17:46:40] INFO ...`)
- Animation progress lines (`Animation 1:` with `|`)

**Gap:** Pattern matching is exhaustive but finite. Novel error messages (e.g., from new Manim versions) fall through to `UnknownError` with generic fix hint.

### 1.4 Self-Healing Render Loop (`app.py: save_and_render()`)

The render loop implements a retry mechanism with LLM-powered error correction:

```
for render_attempt in 1..MAX_RENDER_RETRIES (3):
    1. _run_manim() → subprocess.run manim CLI
    2. Check for video file first (Manim may return exit 1 with video)
    3. If video found → SUCCESS
    4. If no video AND returncode != 0:
       a. Parse stderr → fix_render_error() → LLM fix
       b. Re-validate syntax (polish_manim_code if invalid)
       c. Re-ensure scene class
       d. Retry with fixed code
    5. If no video AND returncode == 0 → treat as error (file not found)
```

**Gap in retry logic (line 921-926):**
```python
syn_ok, _ = validate_python_syntax(current_code)
if not syn_ok:
    from algorithms.ai_functions import polish_manim_code as _polish
    current_code = _polish(current_code)
current_code = ensure_scene_class(current_code)
```

Only syntax is re-validated post-fix. **Safety (`validate_names_and_imports`) and structure (`validate_manim_code`) are NOT re-checked** before retry.

---

## 2. Gaps in Validation That Could Cause Render Failures

### Gap 1: FAST/DRAFT Pipeline Skips ALL Validation

```python
# app.py lines 511-514
if is_fast:
    quality_passes, quality_feedback = True, []
    has_critical_errors = False
```

In FAST_PIPELINE or DRAFT_PIPELINE mode:
- `check_code_quality()` is skipped
- `validate_latex_strings()` is skipped  
- `validate_names_and_imports()` is skipped
- `detect_overlaps()` is skipped

**Effect:** Any `[ERR]` quality issue (MathTex indexing, SVGMobject, DashedArrow, forbidden imports) silently passes through to render. The self-healing loop then catches these at runtime, but the initial feedback loop (catching errors before render) is bypassed.

### Gap 2: No Validation of LLM-Fixed Code Before Retry

When `fix_render_error()` returns fixed code (line 919):
```python
current_code = fix_render_error(current_code, stderr, prompt)
# Re-validate syntax before retrying
syn_ok, _ = validate_python_syntax(current_code)
```

Only syntax is validated. The LLM could:
- Remove a required `from manim import *`
- Delete the `construct()` method
- Introduce a forbidden import
- Leave MathTex indexing bugs

None of these would be caught before the retry render.

### Gap 3: MathTex Indexing Detection is Pattern-Based

```python
# code_digest.py lines 151-163
mathtex_index_pattern = r"\b(eq\d*|tex|formula|expression)\s*\[\s*\d+\s*\]\s*\[\s*\d+\s*\]"
```

Only variables matching `eq`, `eq1`, `tex`, `formula`, `expression` followed by `[n][m]` are flagged. A variable like `equation_result[0][3]` would NOT be caught. The pattern only catches the most common naming convention.

### Gap 4: Position Collision Detection Cannot Reason About Space

`detect_position_collisions()` flags any two objects placed at the same normalized position expression. However:
- `move_to(ORIGIN)` and `move_to(LEFT*0)` normalize to same position but are visually identical
- `move_to(UP)` and `move_to(ORIGIN+UP)` normalize differently but could overlap visually

The detector is a heuristic, not a spatial reasoner.

### Gap 5: No Maximum Retry Depth for Same Error

If `fix_render_error()` produces code that fails with the SAME error (e.g., a bad fix introduces a new problem that recreates the original error), the loop continues:
```python
for render_attempt in 1..MAX_RENDER_RETRIES:
    ...
    current_code = fix_render_error(current_code, stderr, prompt)
```

There's no check that the error changed. A pathological fix→fail→fix cycle could consume all retries without progress.

### Gap 6: Error Pattern Recording Uses Hash of Stderr

```python
# app.py line 906
"signature": str(hash(stderr[-500:])),
```

500 characters of stderr is a fragile signature. Two similar errors with different line numbers or memory addresses would have different hashes, preventing pattern coalescence in the database.

---

## 3. How Self-Healing Works

### 3.1 The Render Loop Flow

```
┌─────────────────────────────────────────┐
│  save_and_render(code, filename, job_id) │
└───────────────┬─────────────────────────┘
                │
        ┌───────▼────────┐
        │ _run_manim()   │ ← Write script + run manim CLI
        └───────┬────────┘
                │
        ┌───────▼────────┐
        │ Video exists?  │ ← find_video_file() checks OUTPUTS
        └───────┬────────┘
                │
       ┌────Yes─┴─No─────┐
       │                │
   ┌───▼───┐      ┌──────▼──────┐
   │SUCCESS│      │ returncode==0?
   │ + audio│     └──────┬──────┘
   │ merge  │            │
   │ + eval │       ┌─No─┴─Yes─┐
   └────────┘       │          │
              ┌─────▼───┐  ┌────▼────┐
              │ ERROR   │  │ FILE    │
              │ (retry) │  │ NOT     │
              └─────┬───┘  │ FOUND   │
                    │      └─────────┘
         ┌──────────┼──────────┐
         │          │          │
    attempt<3?  attempt>=3?  attempt>=3?
         │          │          │
    ┌────▼────┐ ┌───▼───┐ ┌───▼───┐
    │fix +    │ │return │ │return │
    │validate │ │ error │ │ error │
    │ + retry │ │(exhausted)│(exhausted)│
    └─────────┘ └───────┘ └───────┘
```

### 3.2 Error Fix Flow (`fix_render_error()`)

1. `parse_manim_error(stderr)` → structured dict with type, message, line, context, hint
2. `format_error_for_prompt(parsed)` → formatted string for LLM
3. LLM call with `FIX_SYSTEM` prompt containing error summary + original code
4. `extract_code()` strips markdown fences
5. Returns fixed code (or original if LLM call fails)

### 3.3 Pre-Render Validation Order (for LLM path)

In `generate_and_validate_code()` (lines 486-702):

```
1. generate_manim_code() — LLM generates
2. check_code_quality() — if not FAST
3. validate_latex_strings() — if math domain AND not FAST
4. If critical errors → review_and_fix()
5. validate_names_and_imports() — if not FAST; if fail → review_and_fix()
6. validate_python_syntax() — if fail → polish_manim_code(); retry or raise
7. ensure_scene_class()
8. validate_manim_code() — if fail → polish + retry
9. check_code_quality() — if not FAST (non-blocking)
10. detect_overlaps() — if not FAST; if issues → review_and_fix()
```

---

## 4. Issues with Error Parsing and Fix Flow

### Issue 1: Error Type Detection Can Misclassify

The 24 patterns in `_ERROR_PATTERNS` match specific formats. A TypeError like:
```
TypeError: unsupported operand type(s) for +: 'float' and 'str'
```

Matches the generic `TypeError: unsupported operand` pattern (line 52-53), which gives the fix hint:
> "Math operation on incompatible types"

But this might be caused by a Manim API misuse (e.g., adding a `Dot` to a `Text`), not a Python type error. The fix hint would mislead the LLM.

### Issue 2: Line Numbers from Traceback Use Innermost Frame

```python
# error_parser.py line 217
line_matches = re.findall(r'File ["\'].+?["\'], line (\d+)', cleaned)
if line_matches:
    result["line_number"] = int(line_matches[-1])  # last = innermost
```

Using the last (innermost) frame is usually correct, but for errors in generated code called from `ensure_scene_class()` wrapping, the line number may point to wrapper code, not the actual bug.

### Issue 3: Noise Stripping Can Remove Relevant Context

Lines matching these patterns are stripped:
- `Animation \d+: ...` with `|` or `%`
- `INFO` lines containing "movie file", "cached", "Rendered"

For errors that occur during animation rendering (e.g., object not found during Animation 5), the `Animation 5:` context line could be the only indicator of WHICH animation failed. If it contains a progress bar character (`|`), it's stripped.

### Issue 4: No Fix Validation

After `fix_render_error()` returns, there's no check that:
- The fix actually addresses the error
- The fix doesn't introduce new errors
- The fix preserves visual intent

The code goes directly to syntax validation then retry.

### Issue 5: FIX_SYSTEM Prompt May Conflict with Original Constraints

The `FIX_SYSTEM` prompt at `ai_functions.py:680-735` contains:
```
FIX RECIPES BY ERROR TYPE:
AttributeError (wrong API method or property):
  - axes.get_graph → axes.plot
  - obj.color = X  → obj.set_color(X)
```

But the original `GENERATION_SYSTEM` prompt already forbids many of these mistakes. If the LLM made a mistake once, feeding it a fix prompt with the same constraints may not be sufficient — especially if the original code had a subtle misunderstanding that the fix prompt doesn't address.

---

## 5. Prompt Expansion Logic and Edge Cases

### 5.1 How `expand_short_prompt()` Works

```python
# request_analysis.py lines 379-426
def expand_short_prompt(prompt: str) -> str:
    original = prompt
    is_truncated = prompt.endswith("…") or prompt.endswith("...")
    starts_with_verb = re.match(
        r"^(solve|compute|find|calculate|evaluate|determine|prove|show|derive)",
        prompt.lower(),
    )
```

**Expansion rules (6 patterns):**

| Trigger | Extension |
|---------|-----------|
| `"log"` anywhere | " Show the step-by-step solution with clear visual explanation of logarithms." |
| `"lim"` or `"limit"` | " Show the graphical interpretation and step-by-step evaluation of the limit." |
| `"derivative"` or `"differentiate"` | " Show the step-by-step differentiation with visual interpretation of the rate of change." |
| `"integral"` | " Show the step-by-step integration with area under curve visualization." |
| `"solve"` + `"equation"` or `"="` | " Show each step of solving the equation with visual transformation." |
| `"compute"` or `"calculate"` | " Show the computation step-by-step with clear visual explanation." |

### 5.2 Edge Cases and Issues

**Issue 1: Keyword collision**
A prompt like "Why do we need to compute the derivative for this?" would trigger `"derivative"` AND `"compute"` extensions, potentially creating a confusing double-expansion.

**Issue 2: No LLM fallback for unknown patterns**
Prompts like "Differentiate f(x) = x^2 + 3x" would expand correctly (derivative pattern matches). But "Sketch the graph of y = sin(x)" would not expand at all — no pattern for "sketch", "graph", or trigonometric functions.

**Issue 3: Truncation detection is fragile**
```python
is_truncated = prompt.endswith("…") or prompt.endswith("...")
```
- "Solve x^2 = 4..." (ends with three dots) → correctly detected
- "Solve x^2 = 4…" (ends with single ellipsis character) → correctly detected  
- "Solve x^2 = 4" (no ellipsis) → not detected as truncated

A mathematically truncated prompt like "Solve x^2 + " (incomplete equation) with no trailing ellipsis would NOT be expanded.

**Issue 4: Single-word verb matching**
```python
starts_with_verb = re.match(r"^(solve|compute|find|calculate|...", prompt.lower())
```
Matches "Solve this" but NOT "How to solve this" (starts with "How"). A user asking "How do I find the derivative?" would not get expansion.

**Issue 5: Expansions are generic**
All expansions add ~20 words of generic guidance. There's no attempt to:
- Detect the specific mathematical operation (e.g., "derivative of polynomial" vs "derivative of trig function")
- Add domain-appropriate visual suggestions (e.g., "show the tangent line slope")

**Issue 6: No validation of expansion quality**
After expansion, the result is passed directly to `analyze_request_type()`. There's no check that the expansion actually improves the prompt or makes it more suitable for animation generation.

---

## Phase 1 Roadmap Implications

### Validation Requirements Map

| Requirement | Current Implementation | Gap |
|-------------|----------------------|-----|
| QUAL-01: Syntax validation | `validate_python_syntax()` (AST) | None — working |
| QUAL-02: Structure validation | `validate_manim_code()` (contains Scene, construct, self.play) | None — working |
| QUAL-03: Safety validation | `validate_names_and_imports()` (AST) | Skipped in FAST/DRAFT |
| QUAL-04: Quality heuristics | `check_code_quality()` (regex/AST) | Skipped in FAST/DRAFT; non-blocking anyway |
| HEAL-01: Error detection | `parse_manim_error()` (24 regex patterns) | Pattern coverage incomplete for novel errors |
| HEAL-02: Fix application | `fix_render_error()` → LLM | No validation of fix before retry |
| HEAL-03: Retry loop | `save_and_render()` (3 retries) | Same error can cycle; no error-type-change check |
| EXP-01: Short prompt detection | `expand_short_prompt()` (6 keyword patterns) | Misses many prompt types |
| EXP-02: Expansion quality | Generic 20-word extensions | No domain-specific or operation-specific guidance |

### Recommended Validation Additions for Phase 1

1. **QUAL-03/04 enforcement in FAST/DRAFT**: Add a `STRICT_VALIDATION` config that blocks on `[ERR]` quality issues even in fast modes

2. **Post-fix validation**: After `fix_render_error()`, run at minimum:
   - `validate_python_syntax()`
   - `validate_names_and_imports()`
   - `validate_manim_code()`

3. **Retry progress check**: Track error type per attempt; if same error persists for 2+ attempts, apply a different fix strategy or escalate

4. **Expand pattern coverage**: Add patterns for "graph", "sketch", "prove", "explain", "show", "visualize" + domain-specific math operations (trig, matrix, etc.)

5. **LLM-assisted expansion fallback**: If no keyword matches, call LLM to expand the prompt rather than returning unchanged

6. **Error pattern database improvement**: Use structured error type + message hash instead of raw stderr hash for better pattern coalescence

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Validation pipeline flow | HIGH | Source code analysis confirms exact paths |
| Gap analysis | HIGH | Direct code inspection shows FAST/DRAFT bypass and post-fix validation gap |
| Error parser coverage | MEDIUM | 24 patterns + noise stripping — reasonable but incomplete for novel errors |
| Self-healing loop behavior | HIGH | Clear retry logic with up to 3 attempts |
| Prompt expansion coverage | MEDIUM | 6 hardcoded patterns; no LLM fallback observed |

---

## Files Analyzed

| File | Key Content |
|------|-------------|
| `algorithms/code_digest.py` | Static validation functions |
| `algorithms/overlap_detector.py` | Layout hygiene checks |
| `algorithms/error_parser.py` | Manim stderr parsing |
| `algorithms/ai_functions.py` | `fix_render_error()`, `review_and_fix()`, `polish_manim_code()` |
| `app.py` | `save_and_render()`, `generate_and_validate_code()`, `find_video_file()` |
| `algorithms/request_analysis.py` | `expand_short_prompt()`, `analyze_request_type()` |
| `config.py` | Pipeline mode flags, retry limits |
| `.planning/codebase/ARCHITECTURE.md` | Pipeline flow documentation |
| `.planning/codebase/CONCERNS.md` | Known technical concerns |
