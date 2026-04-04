# Testing Patterns

**Analysis Date:** 2026-04-04

## Test Framework

**Python (Backend):**
- **Approach:** Ad-hoc test scripts (no formal framework like pytest/unittest)
- **Runner:** Direct Python execution
  ```bash
  python test_imports.py
  python test_optimizations.py
  python test_pipeline.py
  ```
- **Assertion:** Standard Python `assert` statements
- **Mocking:** Manual — `sys.modules["openai"] = type(sys)("openai")` pattern (test_imports.py line 118-121)

**TypeScript (Frontend):**
- No test framework detected in `nima-frontend/`

## Test File Organization

**Location Pattern:** Root-level `test_*.py` files

| File | Purpose | Lines |
|------|---------|-------|
| `test_imports.py` | Import verification and wiring checks | 143 |
| `test_optimizations.py` | FAST/DRAFT pipeline optimization tests | 445 |
| `test_pipeline.py` | End-to-end pipeline smoke test | 31 |

**No test directory** — tests live alongside source code at project root

## Test Structure

**test_imports.py Pattern:**
```python
"""Quick import and wiring verification — run with: python test_imports.py"""
import os
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["USE_DATABASE"] = "false"

# ── config ────────────────────────────────────────────────────────────────────
import config
assert config.GENERATION_MODEL == "gpt-4o", "Wrong model"
print(f"[OK] config — GENERATION_MODEL={config.GENERATION_MODEL}")

# ── code_digest ────────────────────────────────────────────────────────────────
from algorithms.code_digest import validate_python_syntax

test_code = "from manim import *\nclass GeneratedScene(Scene):\n    def construct(self):\n        ..."
ok, err = validate_python_syntax(test_code)
assert ok, f"Syntax error: {err}"
```

**test_optimizations.py Pattern:**
```python
def test_config_flags():
    """Verify FAST_PIPELINE and DRAFT_PIPELINE flags work correctly."""
    print("\n[TEST] Config flags...")
    
    # Test DRAFT mode
    os.environ["DRAFT_PIPELINE"] = "true"
    import config
    importlib.reload(config)
    assert config.DRAFT_PIPELINE == True
    
    return True

def run_all_tests():
    """Run all optimization tests."""
    tests = [
        ("Config Flags", test_config_flags),
        ("Render Retries", test_render_retries_in_fast_mode),
        # ...
    ]
    passed = 0
    failed = 0
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {name}: {e}")
```

## Mocking Patterns

**Fake Module Replacement:**
```python
# test_imports.py lines 118-121
class _FakeOpenAI:
    def __init__(self, **kw): pass
sys.modules["openai"] = type(sys)("openai")
sys.modules["openai"].OpenAI = _FakeOpenAI
```

**Environment Variable Isolation:**
```python
os.environ["USE_DATABASE"] = "false"
os.environ["OPENAI_API_KEY"] = "test-key-for-testing"
# Set BEFORE importing config
import config
importlib.reload(config)  # Reload to pick up new env vars
```

**Cache Clearing (RAG):**
```python
from RAG.RAG_system import retrieve_patterns
retrieve_patterns.cache_clear()  # Clear LRU cache before testing
```

## Fixtures & Factories

**Test Data:** Inline literals in test functions
```python
test_code = (
    "from manim import *\n"
    "class GeneratedScene(Scene):\n"
    "    def construct(self):\n"
    "        self.play(Create(Circle()))\n"
)
```

**Error Samples:** Manually constructed traceback strings
```python
sample = (
    "Traceback (most recent call last):\n"
    '  File "test.py", line 42, in construct\n'
    "    self.play(Create(axes))\n"
    "AttributeError: 'Axes' object has no attribute 'foo'\n"
)
```

## Test Coverage

**No coverage enforcement** — CI does not run coverage reports

**What's Tested:**
- Import wiring (`test_imports.py`)
- Config flag behavior (`test_optimizations.py`)
- Pipeline mode logic (FAST/DRAFT skips validations)
- Code validation functions (syntax, AST security, quality)
- RAG retrieval caching
- Render flags per mode

**What's NOT Tested:**
- Database operations (USE_DATABASE=false in tests)
- Actual LLM calls (mocked)
- Frontend React components
- End-to-end with real Manim rendering

## CI Testing

**Workflow:** `.github/workflows/test.yml`

**Jobs:**
1. **test** — Runs on ubuntu-latest
   ```bash
   python test_imports.py
   python test_optimizations.py
   python benchmark.py
   ```

2. **lint** — Runs on ubuntu-latest
   ```bash
   pip install ruff black mypy
   ruff check . --ignore=E501,F401
   black --check .
   ```

3. **test-pipeline-modes** — Matrix build [DRAFT, FAST, FULL]
   - Sets env vars and validates config

4. **benchmark-comparison** — Manual trigger only

**Python Version:** 3.11 in CI

## Common Testing Patterns

**Timing Test:**
```python
t1 = time.time()
result1 = retrieve_patterns("math", "derivative", ("tangent",), limit=2)
t1_time = time.time() - t1

t2 = time.time()
result2 = retrieve_patterns("math", "derivative", ("tangent",), limit=2)
t2_time = time.time() - t2

assert t2_time < 0.01  # Cached should be instant
```

**Source File Inspection:**
```python
with open("app.py", "r", encoding="utf-8") as f:
    src = f.read()
assert "is_fast = FAST_PIPELINE or DRAFT_PIPELINE" in src
```

**Async/Promise Handling (Frontend):**
- No async testing patterns detected
- Frontend uses polling with `setInterval`, not testing libraries

---

*Testing analysis: 2026-04-04*
