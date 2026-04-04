# Testing

**Analysis Date:** 2026-04-04

## Testing Status

**Current State:** No formal test framework configured

- No test scripts in `package.json` (frontend)
- No pytest configuration detected (backend)
- No unit tests found in codebase

## Validation Approach

The project uses **static analysis validation** instead of traditional unit tests:

### Code Quality Validation (`algorithms/code_digest.py`)

**Syntax Validation:**
- `validate_python_syntax()` - Uses AST parsing to detect syntax errors
- Runs before any render attempt

**Security Validation:**
- `validate_names_and_imports()` - AST-based check for forbidden imports/calls
- Blocks: `exec`, `eval`, `__import__`, `os.system`, `subprocess`, `SVGMobject`, `ImageMobject`

**Structure Validation:**
- `validate_manim_code()` - Checks for `class GeneratedScene(Scene)` and `self.play()`

**Quality Heuristics:**
- `check_code_quality()` - Non-blocking warnings for:
  - MathTex indexing (unstable positions)
  - Missing `self.wait()` calls
  - `self.clear()` usage
  - NumberPlane without opacity styling
  - Lambda closure issues in loops

**LaTeX Validation:**
- `validate_latex_strings()` - Checks brace matching, common math errors

### Overlap Detection (`algorithms/overlap_detector.py`)

Static analysis to catch layout issues before rendering:
- `detect_position_collisions()` - Multiple objects at same position
- `detect_object_accumulation()` - Too many creates without cleanup
- `detect_missing_section_cleanup()` - Comment-based sections without cleanup
- `detect_long_construct()` - Complex scenes without section helpers
- `detect_stale_copies()` - `.copy()` without original removal

### Error Parsing (`algorithms/error_parser.py`)

Manim stderr parsing for self-healing:
- `parse_manim_error()` - Structured error info from stderr
- `format_error_for_prompt()` - Error formatted for LLM fix prompt
- Pattern-based error type detection

### Render Self-Healing (`app.py`)

Render loop with automatic error recovery:
- On failure: Parse stderr → Feed to LLM → Get fixed code → Retry
- Up to `MAX_RENDER_RETRIES` attempts (default: 3)

## Database Testing

**Schema:** `database_schema.sql`

**Tables tracked:**
- `requests` - User prompts with analysis
- `generation_attempts` - Code versions with validation results
- `render_jobs` - Render outcomes (success/failure)
- `ai_evaluations` - Quality scores
- `error_patterns` - Known error signatures
- `training_examples` - Quality-scored examples

## Quality Scoring

Post-render evaluation via `evaluate_with_gpt4()`:
- Layout quality
- Educational value
- Technical accuracy
- Pacing
- Manim idiom usage

Scores stored in database for training data selection.

---

*Testing analysis: 2026-04-04*
