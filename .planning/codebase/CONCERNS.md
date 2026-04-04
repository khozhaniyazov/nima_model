# Technical Concerns

**Analysis Date:** 2026-04-04

## High Priority Concerns

### Manim Version Compatibility

**Issue:** Code uses `manim>=0.18` but some API patterns are fragile
**Risk:** API changes between versions could break rendering
**Affected Patterns:**
- `axes.get_graph(f)` → `axes.plot(f, x_range=...)` (API changed)
- `axes.c2p(x, y, 0)` → `axes.c2p(x, y)` (z-axis default changed)
- `DashedArrow` class doesn't exist in some versions

**Mitigation:** Comprehensive error parser in `algorithms/error_parser.py` with fix hints

### MathTex Indexing Instability

**Issue:** `eq[0][k]` style indexing on MathTex objects is unstable
**Risk:** Token positions vary unpredictably → IndexError at render time
**Evidence:** `code_digest.py` has explicit warnings for this pattern

**Mitigation:** Enforce `get_part_by_tex()`, `set_color_by_tex()`, `TransformMatchingTex`

### Lambda Closure Bugs

**Issue:** `always_redraw(lambda: Dot(x=i))` inside loops captures late binding
**Risk:** All dots end up at same position
**Evidence:** Common crash pattern documented in `ai_functions.py`

**Mitigation:** Must use `lambda i=i:` pattern; quality checks warn about this

### Self-Clear Breaking Continuity

**Issue:** `self.clear()` wipes all visual context
**Risk:** Breaks pedagogical flow, jarring transitions
**Evidence:** Banned in conventions, but no AST-level enforcement

**Mitigation:** Section lifecycle helpers (`start_section`/`end_section`)

## Medium Priority Concerns

### No Test Suite

**Issue:** No unit/integration tests for backend algorithms
**Risk:** Refactoring could break pipeline without detection
**Current Validation:** Only static analysis (AST-based validation)

**Recommendation:** Add pytest for algorithm modules

### Database Dependency

**Issue:** Pipeline designed for PostgreSQL but falls back gracefully
**Risk:** If `USE_DATABASE=false`, lose error pattern learning
**Evidence:** `db = ManimDatabase(...) if USE_DATABASE else None`

**Mitigation:** Graceful degradation in `app.py`

### Manim Pre-warm Latency

**Issue:** First Manim render is slow (scene compilation)
**Risk:** Poor UX for first request
**Evidence:** `prewarm_manim()` function at startup

**Mitigation:** Background warmup thread at Flask startup

### Frontend State Management

**Issue:** No state management library (Redux/Zustand)
**Risk:** Complex state could become inconsistent
**Evidence:** Simple React hooks in `page.tsx` with polling

**Current:** Job status polled from Flask API every 1.5s

## Lower Priority Concerns

### Hardcoded Paths

**Issue:** `MANIM_SCRIPTS` and `OUTPUTS` hardcoded in `config.py`
```python
MANIM_SCRIPTS = Path("C:/temp/manim_scripts")
OUTPUTS = Path("C:/temp/outputs")
```
**Risk:** Not portable across environments

### No Authentication

**Issue:** Flask API has no authentication
**Risk:** Anyone with network access can use the API
**Context:** Designed for localhost use only

### RAG Corpus Size

**Issue:** RAG system uses database examples (limited corpus)
**Risk:** May not have good examples for niche domains
**Evidence:** `RAG/RAG_system.py` with `retrieve_golden_example()`

### Template Registry Limited

**Issue:** Only 5 animation templates in `template_registry.py`
**Risk:** May not fit all animation types
**Templates:** `two_panel_comparison`, `definition_to_example`, `step_by_step_derivation`, `graph_and_formula`, `mapping_diagram`

---

*Concerns analysis: 2026-04-04*
