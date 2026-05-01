# GENERATION.md — Phase 1: Foundation & Stability

**Focus:** Code Generation Stability (GEN-01, GEN-02, HEAL-01-03, QUAL-01-04)
**Research Date:** 2026-04-04
**Confidence:** HIGH

---

## Executive Summary

The code generation pipeline has a multi-stage architecture: `generate_manim_code()` → `review_and_fix()` → `validate_*` → `save_and_render()` (with self-healing). The system has retry logic and fallback mechanisms, but generation instability stems from LLM non-determinism, prompt sensitivity, and API reliability issues rather than architectural flaws. The RAG system provides context but has limited corpus and simple keyword matching.

---

## 1. How `generate_manim_code()` Works

**Location:** `algorithms/ai_functions.py` lines 485-557

### Input Flow

```
generate_manim_code(prompt, analysis, plan, attempt, db, segment_durations)
    │
    ├─► retrieve_golden_example(domain, topic, subtopics, db)
    │       ├─► DB high-scoring examples (if available)
    │       └─► RAG corpus patterns (retrieve_patterns, up to 3)
    │
    ├─► get_error_warnings(db) — recurring error patterns to avoid
    ├─► get_domain_specific_guidance(domain) — domain-specific techniques
    │
    └─► Build system prompt with:
            - GENERATION_SYSTEM template (lines 313-482)
            - Error warnings
            - Domain guidance
            - Golden examples
            - Animation storyboard (plan)
            - Timing contract (if voiceover enabled)
```

### System Prompt Construction

The `GENERATION_SYSTEM` template (lines 313-482) is a **500+ line prompt** that specifies:
- Exact output format: `class GeneratedScene(Scene)` only
- Allowed imports: `from manim import *` + optionally `import numpy as np`
- API corrections (common mistakes that crash render)
- Screen layout zones (TOP 10%, CENTER 75%, BOTTOM 15%)
- Transition rules (BANNED: `self.clear()`, `self.remove()`)
- Visual styling requirements (NumberPlane opacity, etc.)
- Pedagogical structure (prerequisite → build up → full concept → insight)
- Quality requirements (MathTex for formulas, wait() distribution, etc.)

### The LLM Call

```python
code = _llm_text(
    [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": f"Create a Manim animation for: {prompt}"},
    ],
    model=GENERATION_MODEL,  # from config.py
)
```

**Model selection:**
- Primary: `GENERATION_MODEL` (default: `gpt-5.2-codex`)
- Fallback: `FALLBACK_MODEL` = `gpt-4o-mini` with `FALLBACK_BASE_URL = "https://api.openai.com/v1"`

### Output Processing

```python
print(f"[GENERATE] [OK] {len(code)} chars generated")
return extract_code(code)
```

`extract_code()` strips markdown fences (` ```python ... ``` `) and returns raw Python.

---

## 2. What Could Cause Flaky Generation

### 2.1 Model Non-Determinism

**Problem:** LLMs are inherently probabilistic. Same prompt → different output.

**Evidence:**
- No temperature/top_p settings visible in `_llm_text()` — defaults are used
- Code generation with `gpt-5.2-codex` (or similar frontier model) can vary significantly between calls
- No seed mechanism to force reproducibility

**Impact:**
- Same prompt may generate structurally different code
- Animation quality can vary wildly between attempts
- Retry may produce better OR worse results

**Fix direction:** Phase 1 should add temperature=0.3 or similar to reduce randomness while maintaining creativity.

### 2.2 Prompt Sensitivity

**Problem:** The massive system prompt (500+ lines) is fragile. Small changes can shift model behavior.

**Evidence:**
- `GENERATION_SYSTEM` has exact template sections with strict formatting requirements
- Many "MUST", "NEVER", "BANNED" directives — model may follow some but not all
- Multiple constraint types compete: API corrections vs. layout rules vs. pedagogical structure

**Known failure modes:**
- Model outputs markdown fences when told "no prose, no markdown fences"
- Model includes `CONFIG = {}` despite explicit prohibition
- Model uses `eq[0][k]` indexing despite explicit warning about crashes
- Model uses `self.clear()` despite being BANNED

**Impact:**
- Quality is inconsistent across generations
- Some generations are immediately renderable, others fail validation

### 2.3 RAG Context Quality

**Problem:** RAG retrieval is simple keyword matching — relevance is hit-or-miss.

**Evidence in `RAG_system.py` lines 1201-1239:**

```python
# Scoring:
# +1 for each individual keyword match
# +5 bonus for whole multi-word phrase match
score += token_overlap
if " " in tag_lower and tag_lower in query_text:
    score += 5
```

**Issues:**
- No semantic similarity — "matrix multiply" won't match "linear algebra" patterns unless exact keywords overlap
- `lru_cache(maxsize=128)` on `retrieve_patterns()` means cached results may be stale
- Corpus size is modest (~25 curated patterns + dynamic loading from `manim_examples_raw.json`)
- No relevance threshold — returns best match even if score is low

**Impact:**
- RAG examples may not be truly relevant to the animation topic
- Model may adopt inappropriate patterns for domain

### 2.4 API Reliability

**Problem:** External API calls fail in various ways.

**Evidence in `_llm_text_with_retry()` lines 53-112:**

```python
# Specific 524 handling (bad_response_status_code):
if "524" in error_str or "bad_response_status_code" in error_str:
    if not used_fallback:
        # Try fallback model immediately
        response = fallback_client.chat.completions.create(...)

# Exponential backoff:
wait_time = (2**attempt) * 2
time.sleep(wait_time)
```

**Known failure modes:**
- 524 timeout errors (caught, triggers fallback)
- Generic exceptions (caught, retried with backoff)
- Network timeouts (60s timeout set on client)
- Fallback model also fails (resets `used_fallback=False` for next retry)

**Impact:**
- Generation may be slow due to retries
- Fallback model (`gpt-4o-mini`) may produce lower quality code
- No hard failure guarantee — can exhaust retries

### 2.5 Domain Guidance Overload

**Problem:** Domain-specific guidance blocks are large but model attention is limited.

**Evidence:**
- Math domain guidance: ~30 lines of specific techniques
- CS domain guidance: ~10 lines
- Physics, Chemistry: ~8 lines each

**Issue:** When combined with the 500-line GENERATION_SYSTEM, the full prompt can exceed context window concerns and dilute critical instructions.

---

## 3. How Generation Retry Logic Works

### 3.1 Generation Attempts (app.py lines 486-704)

**Outer retry loop:** Up to `MAX_GENERATION_ATTEMPTS` (default: 2)

```python
for attempt in range(1, max_attempts + 1):
    # 1. Generate code
    code = generate_manim_code(prompt, analysis, plan, attempt, db, ...)
    
    # 2. Quality checks (FAST_PIPELINE skips unless critical errors)
    quality_passes, quality_feedback = check_code_quality(code)
    has_critical_errors = any(w.startswith("[ERR]") for w in quality_feedback)
    
    # 3. LaTeX validation (math domain only, skip FAST_PIPELINE)
    if not is_fast and analysis.get("domain") == "math":
        latex_valid, latex_issues = validate_latex_strings(code)
        if not latex_valid:
            code = review_and_fix(code, f"...[LATEX ERRORS]...", analysis)
    
    # 4. Security validation (skip FAST_PIPELINE)
    is_safe, safety_issues = validate_names_and_imports(code)
    if not is_safe:
        code = review_and_fix(code, f"...[SECURITY VIOLATIONS]...", analysis)
    
    # 5. Syntax validation
    syntax_valid, syntax_error = validate_python_syntax(code)
    if not syntax_valid:
        if not is_fast:
            code = polish_manim_code(code)  # LLM syntax fixer
            syntax_valid, syntax_error = validate_python_syntax(code)
        if not syntax_valid and attempt < max_attempts:
            continue  # Retry generation
        raise Exception(f"Syntax error could not be fixed")
    
    # 6. Structure validation
    structure_valid, structure_error = validate_manim_code(code)
    if not structure_valid and attempt < max_attempts:
        if not is_fast:
            code = polish_manim_code(code)
        continue
    
    # 7. Overlap detection (skip FAST_PIPELINE)
    overlap_warnings = detect_overlaps(code)
    if overlap_warnings:
        code = review_and_fix(code, f"...[LAYOUT OVERLAP ISSUES]...", analysis)
```

**Key behavior:**
- `MAX_GENERATION_ATTEMPTS = 2` by default — only 2 chances to generate
- FAST/DRAFT pipelines skip expensive checks (quality, overlap, LaTeX) — faster but less safe
- `review_and_fix()` is called conditionally (only when issues detected)
- Failure on attempt 2 raises Exception — no more retries

### 3.2 Render Self-Healing Loop (app.py lines 806-947)

**Separate retry loop:** Up to `MAX_RENDER_RETRIES` (default: 3)

```python
for render_attempt in range(1, render_retries + 1):
    result = _run_manim(current_code, filename, job_id)
    video_path = find_video_file(filename)
    
    if video_path:
        # SUCCESS
        return
    
    elif result.returncode == 0 and not video_path:
        # Edge case: returncode=0 but no video
        render_data["status"] = "error"
        return
    
    else:
        # RENDER FAILED
        if render_attempt < render_retries:
            # Feed error to LLM for fix
            current_code = fix_render_error(current_code, stderr, prompt)
            # Validate syntax before retry
            syn_ok, _ = validate_python_syntax(current_code)
            if not syn_ok:
                current_code = polish_manim_code(current_code)
            current_code = ensure_scene_class(current_code)
```

**Key behavior:**
- `MAX_RENDER_RETRIES = 3` — 3 chances to fix render errors
- `fix_render_error()` uses `FAST_MODEL` (gpt-5.2-codex by default) for targeted fixes
- `stderr` is parsed by `parse_manim_error()` and formatted for LLM context
- `FIX_SYSTEM` prompt (lines 680-735) has "FIX RECIPES BY ERROR TYPE"
- Syntax check before retry to avoid cascading errors

### 3.3 LLM Call Retry with Exponential Backoff

**Location:** `_llm_text_with_retry()` lines 53-112

```python
for attempt in range(max_retries):  # max_retries=3 default
    try:
        if _is_codex_model(model):
            # Codex: flatten messages into single input string
            response = client.chat.completions.create(model=model, ...)
        else:
            # Standard chat completions
            response = client.chat.completions.create(model=model, messages=...)
        return response.choices[0].message.content
    
    except Exception as e:
        error_str = str(e)
        last_error = e
        
        # 524 → immediate fallback model try
        if "524" in error_str or "bad_response_status_code" in error_str:
            if not used_fallback:
                response = fallback_client.chat.completions.create(
                    model=FALLBACK_MODEL, messages=prompt_messages
                )
                return response.choices[0].message.content
        
        # Exponential backoff: 2s, 4s, 8s
        wait_time = (2**attempt) * 2
        time.sleep(wait_time)
```

**Key behavior:**
- 3 retries per LLM call (independent of generation/render retries)
- 524 error triggers immediate fallback to `gpt-4o-mini`
- Exponential backoff: 2s → 4s → 8s between attempts
- Falls through to raise `Exception(f"LLM call failed after {max_retries} attempts")`

---

## 4. RAG System Status

**Location:** `RAG/RAG_system.py` (1276 lines total)

### 4.1 Corpus Composition

**Curated Patterns:** 25 patterns in `CORPUS` list (lines 26-1123)
- Function graphing
- ValueTracker / dynamic animation
- Derivative / tangent line
- Riemann sums
- Number line / number plane
- Linear transformation / matrix
- Step-by-step equations / TransformMatchingTex
- MathTex color highlighting
- Bar chart / histogram
- Traced path
- Vector field
- Sorting algorithm (bubble sort example)
- Binary tree
- Matrix multiplication
- Probability / pie chart
- Taylor series
- Eigenvalue / eigenvector
- Graph / network
- Fourier series
- Complex numbers / Argand plane
- Geometry proof
- Recursive / fractal
- Logistic growth
- Central limit theorem
- Monte Carlo pi estimation
- Number sieve
- Pendulum
- Supply and demand
- Process flow / timeline
- Complete mini-scene (Pythagorean theorem)

**Dynamic Loading:** Lines 1133-1193
- Loads from `training/manim_examples_raw.json` at module import
- Auto-generates tags from scene names (camelCase split)
- Adds extra tags based on code content (ValueTracker, NumberPlane, etc.)
- Skips patterns containing `_UNSAFE_PATTERNS` = `{"ImageMobject", "ThreeDScene", "MovingCameraScene"}`

### 4.2 Retrieval Mechanism

**`retrieve_patterns()`** (lines 1201-1239):
- LRU cache (maxsize=128) for performance
- Keyword matching with phrase bonus (+5 for multi-word phrase match)
- Falls back to domain-matched entries if no score
- Returns empty tuple → `retrieve_golden_example()` handles gracefully

**`retrieve_golden_example()`** (lines 1242-1276):
- Combines DB examples (high-scoring from past renders) + curated corpus patterns
- DB examples truncated to 1500 chars (lossy)
- Returns formatted string for injection into generation prompt

### 4.3 Known Limitations

| Issue | Impact | Severity |
|-------|--------|----------|
| Simple keyword matching | Irrelevant patterns returned | Medium |
| No semantic similarity | "matrix transform" won't match "eigenvector" pattern | Medium |
| LRU cache staleness | Old high-scoring DB examples cached | Low |
| Truncation at 1500 chars | DB examples lose context | Medium |
| Limited corpus diversity | Niche topics may have no good match | High |
| No relevance threshold | Returns low-score matches anyway | Medium |

---

## 5. Issues with Code Generation That Affect Stability

### 5.1 Critical Issues (Cause Rewrites/Failures)

#### Issue 1: LLM Non-Determinism
**Problem:** Same prompt → different code quality
**Root cause:** No temperature control, model randomness
**Impact:** Unpredictable generation quality, retry may not help
**Prevention:** Phase 1 should add `temperature` parameter to `_llm_text()`

#### Issue 2: Prompt Bloat Diluting Critical Instructions
**Problem:** 500+ line system prompt + domain guidance + RAG context → model may miss key constraints
**Root cause:** GENERATION_SYSTEM has too many sections competing for attention
**Impact:** Model violates "NEVER" rules (uses `self.clear()`, `ImageMobject`, etc.)
**Prevention:** Phase 1 should restructure prompt to prioritize critical rules

#### Issue 3: No Validation Between Generation and Review
**Problem:** `review_and_fix()` is called only conditionally, but generation is not re-validated after fix
**Root cause:** Review pass modifies code but doesn't re-run quality/safety checks
**Impact:** Fixed code may introduce new issues that go undetected until render
**Prevention:** Phase 1 should add post-review validation loop

### 5.2 Moderate Issues (Cause Instability/Suboptimal Output)

#### Issue 4: RAG Relevance Mismatch
**Problem:** Keyword matching returns irrelevant patterns
**Root cause:** No semantic similarity, no threshold filtering
**Impact:** Model receives unhelpful context, generates lower quality code
**Prevention:** Phase 1 should improve retrieval scoring or add semantic search

#### Issue 5: Retry Logic Exhausts Quickly
**Problem:** Only 2 generation attempts, 3 render attempts
**Root cause:** `MAX_GENERATION_ATTEMPTS=2`, `MAX_RENDER_RETRIES=3`
**Impact:** Complex errors may not be fully resolved
**Prevention:** Consider adaptive retry counts based on error type

#### Issue 6: Fallback Model Quality Gap
**Problem:** Fallback to `gpt-4o-mini` may produce lower quality code
**Root cause:** Fallback is `gpt-4o-mini` (cheaper/faster model)
**Impact:** If primary model has issues, fallback may not rescue the generation
**Prevention:** Phase 1 should evaluate if fallback is appropriate or if retry on same model is better

### 5.3 Minor Issues (Cause Warnings/Edge Cases)

#### Issue 7: Lambda Closure Heuristic is Weak
**Problem:** Only catches obvious `for...always_redraw(lambda:` patterns
**Root cause:** Regex-based detection, not AST analysis
**Impact:** Closure bugs in more complex loops slip through
**Prevention:** Phase 1 should add AST-based lambda analysis in code_digest.py

#### Issue 8: Overlap Detection is Comment-Based
**Problem:** `detect_missing_section_cleanup()` looks for comment markers
**Root cause:** Not analyzing actual mobject positions
**Impact:** Real overlaps go undetected until render time
**Prevention:** Phase 1 should add deterministic overlap detection

#### Issue 9: No Code Diff Between Attempts
**Problem:** Multiple generation attempts not compared
**Root cause:** Each attempt is independent
**Impact:** Can't identify what changed between attempts
**Prevention:** Phase 1 should log generation diffs for debugging

---

## 6. Phase 1 Recommendations for GEN-01, GEN-02, HEAL-01-03, QUAL-01-04

### GEN-01: Natural Language → Manim Code
**Status:** Works but unstable due to non-determinism
**Phase 1 Actions:**
- Add `temperature=0.3` to generation calls (reduce randomness)
- Extract "BANNED" rules into separate short prompt section (ensure model reads them)
- Consider adding few-shot examples for critical patterns

### GEN-02: Generation Retry Logic
**Status:** Basic retry exists (2 attempts) but could be improved
**Phase 1 Actions:**
- Increase `MAX_GENERATION_ATTEMPTS` to 3 (allow more recovery)
- Add retry reason logging (why did we retry?)
- Consider: if attempt 1 passes syntax/structure but has quality warnings, still accept (don't force retry)

### HEAL-01-03: Self-Healing Render Loop
**Status:** Working — parses stderr, feeds to LLM, retries
**Phase 1 Actions:**
- `fix_render_error()` currently uses FAST_MODEL — ensure it's appropriate for targeted fixes
- Add error type classification to decide if retry is worthwhile (some errors won't fix with LLM)
- Consider: max 1 render retry for syntax errors (these are easy fixes), save remaining retries for complex runtime errors

### QUAL-01-04: Code Validation
**Status:** Multi-layer validation exists but has gaps
**Phase 1 Actions:**
- Add AST-based lambda closure detection (current regex is weak)
- Add post-review validation loop (validate after `review_and_fix()` before proceeding)
- Consider adding "generation confidence score" — if prompt was ambiguous, warn user

---

## 7. Confidence Assessment

| Area | Level | Notes |
|------|-------|-------|
| generate_manim_code() behavior | HIGH | Fully traced through code |
| Retry logic flow | HIGH | Well-documented in app.py |
| LLM retry mechanism | HIGH | Detailed in ai_functions.py |
| RAG system architecture | HIGH | Fully read and analyzed |
| Flaky generation root causes | MEDIUM | Based on code analysis, not empirical testing |
| Quality validation coverage | MEDIUM | AST-based but some heuristics |

---

## 8. Open Questions for Phase 1 Deeper Research

1. **Temperature impact:** What temperature setting balances creativity vs. consistency?
2. **Model selection:** Is `gpt-5.2-codex` the right model, or should we use `gpt-4o` for generation?
3. **RAG improvement:** Would semantic embeddings improve retrieval quality significantly?
4. **Retry budgets:** Is 2 generation + 3 render retries optimal, or should we adjust?
5. **Prompt compression:** Would a shorter prompt with equal effectiveness improve stability?

---

*Research complete. Files created:*
- `.planning/phases/1-Foundation-Stability/GENERATION.md` (this file)
