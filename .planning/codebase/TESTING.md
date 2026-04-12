# Testing Patterns

**Analysis Date:** 2026-04-12

## Test Framework

**Runner:**
- Backend uses script-style Python test harnesses executed directly with `python` (no `pytest`/`unittest` runner config detected).
- CI config: `.github/workflows/test.yml`.

**Assertion Library:**
- Native Python `assert` statements in scripts (examples: `test_imports.py`, `test_optimizations.py`).

**Run Commands:**
```bash
python test_imports.py              # Quick import/wiring checks
python test_optimizations.py        # Optimization/flag regression checks
python test_streaming_reliability.py --count 10 --host http://localhost:5000   # Reliability sweep
```

## Test File Organization

**Location:**
- Primary tests are root-level Python scripts (`test_imports.py`, `test_optimizations.py`, `test_pipeline.py`, `test_streaming_reliability.py`, `test_edge_cases.py`).
- Additional legacy sample test exists under training content (`training/3b1b/videos/_2020/med_test.py`) and is not integrated with CI workflow steps.

**Naming:**
- `test_*.py` naming is the dominant pattern at repo root.

**Structure:**
```
project-root/
├── test_imports.py                  # static/import and wiring checks
├── test_optimizations.py            # multi-test function suite + custom runner
├── test_pipeline.py                 # local end-to-end smoke path
├── test_streaming_reliability.py    # HTTP-driven reliability harness
└── test_edge_cases.py               # edge prompt stress wrapper
```

## Test Structure

## Test Pyramid / Status

- Unit-style checks: present but lightweight and mostly static/assertion-driven (`test_imports.py` validates parser outputs and safety checks using in-memory strings).
- Integration checks: present and dominant (`test_pipeline.py` imports backend functions and attempts generation + render; `test_streaming_reliability.py` interacts with live HTTP server and filesystem outputs).
- E2E checks: partial/manual via reliability harness against running backend (`/api/generate` + `/status/{job_id}`), but not full browser automation.
- Current CI status shape (`.github/workflows/test.yml`): runs selective backend scripts (`test_imports.py`, `test_optimizations.py`) plus benchmark; does not run frontend tests and does not run streaming harness by default.

**Suite Organization:**
```python
# pattern from `test_optimizations.py`
def test_config_flags():
    ...
    assert ...
    return True

def run_all_tests():
    tests = [
        ("Config Flags", test_config_flags),
        ...
    ]
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            failed += 1
```

**Patterns:**
- Setup pattern: environment variables are set at top of scripts before imports (examples in `test_imports.py`, `test_optimizations.py`, `test_pipeline.py`).
- Teardown pattern: minimal explicit teardown; most tests rely on process exit and local variable scope.
- Assertion pattern: direct `assert` with human-readable messages and stdout markers (`[OK]`, `[FAIL]`, `[ERROR]`) in `test_imports.py` and `test_optimizations.py`.

## Mocking

**Framework:**
- No dedicated mocking framework (e.g., `unittest.mock`/`pytest-mock`) is in active use.

**Patterns:**
```python
# pattern from `test_imports.py` (module monkeypatch)
class _FakeOpenAI:
    def __init__(self, **kw):
        pass

sys.modules["openai"] = type(sys)("openai")
sys.modules["openai"].OpenAI = _FakeOpenAI
from algorithms import ai_functions
```

**What to Mock:**
- External API client constructors and other boundary dependencies at import-time for lightweight smoke tests (`test_imports.py`).

**What NOT to Mock:**
- Reliability harness intentionally avoids mocks and exercises real HTTP/status/video existence paths (`test_streaming_reliability.py`, `test_edge_cases.py`).

## Fixtures and Factories

**Test Data:**
```python
# pattern from `test_imports.py`
sample = (
    "Traceback (most recent call last):\n"
    '  File "test.py", line 42, in construct\n'
    "AttributeError: 'Axes' object has no attribute 'foo'\n"
)
parsed = parse_manim_error(sample)
assert parsed["error_type"] == "AttributeError"
```

**Location:**
- Inline fixture data in each script; no shared `tests/fixtures/` directory detected.

## Coverage

**Requirements:**
- No coverage threshold or coverage tooling configured (no `coverage.py`, no `pytest --cov`, no coverage upload step in `.github/workflows/test.yml`).

**View Coverage:**
```bash
Not configured
```

## Test Types

**Unit Tests:**
- Present as direct function validation and static source-contains checks (e.g., `test_imports.py` checks parser logic; `test_optimizations.py` checks for markers in `app.py`/`algorithms/ai_functions.py`).

**Integration Tests:**
- Present for backend generation/render flow and HTTP polling flow (`test_pipeline.py`, `test_streaming_reliability.py`, `test_edge_cases.py`).

**E2E Tests:**
- Browser/UI E2E framework not used (no Playwright/Cypress detected).
- System-level API E2E-like sweeps are script-driven (`test_streaming_reliability.py`).

## Common Patterns

**Async Testing:**
```python
# polling pattern from `test_streaming_reliability.py`
while time.time() < deadline:
    last = get_json(f"{host}/status/{job_id}")
    status = (last.get("status") or "").lower()
    if status in ("done", "error"):
        return {...}
    time.sleep(poll_interval)
```

**Error Testing:**
```python
# pattern from `test_imports.py`
bad_code = "import os\nfrom manim import *\nclass GeneratedScene(Scene): ..."
is_safe_bad, bad_issues = validate_names_and_imports(bad_code)
assert not is_safe_bad, "Should flag os import as forbidden"
```

## Gaps and Risks

- Frontend tests are not detected (no `*.test.ts(x)`/`*.spec.ts(x)` under `nima-frontend/src` and no frontend test runner config).
- CI does not execute all root integration scripts (`test_pipeline.py`, `test_streaming_reliability.py`, `test_edge_cases.py` are not in `.github/workflows/test.yml` jobs).
- Some tests are brittle string-presence checks against source code (examples in `test_optimizations.py` scanning literal snippets in `app.py` and `algorithms/ai_functions.py`), which can fail on benign refactors.
- Environment-sensitive tests rely on local services/binaries (Flask server availability, ffmpeg/ffprobe, writable output paths), increasing nondeterminism for local runs (`test_pipeline.py`, `test_streaming_reliability.py`, `algorithms/tts.py` behaviors exercised indirectly).
- No unified test discovery/reporting output format (custom print-based summaries in `test_optimizations.py`) and no machine-readable test report artifacts in CI.

---

*Testing analysis: 2026-04-12*
