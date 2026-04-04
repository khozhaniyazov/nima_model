# Coding Conventions

**Analysis Date:** 2026-04-04

## Languages & Style

**Python (Backend/Flask):**
- Version: 3.11+
- Style: PEP 8 with snake_case naming
- Type hints: Used throughout (`typing.Optional`, `Dict`, `Any`, `Tuple`)
- Docstrings: Module-level and function-level with `"""docstring"""` format

**TypeScript/React (Frontend):**
- Version: ES2017+ target, strict mode enabled
- Framework: Next.js with React
- Config: `"strict": true` in `tsconfig.json`

## Naming Conventions

**Python:**

| Element | Pattern | Example |
|---------|---------|---------|
| Functions/variables | snake_case | `generate_manim_code`, `render_status` |
| Classes | PascalCase | `ManimDatabase`, `GeneratedScene` |
| Constants | UPPER_SNAKE_CASE | `MAX_RENDER_RETRIES`, `GENERATION_MODEL` |
| Private methods | _prefixed | `_exec()`, `_llm_text_with_retry` |
| Module-level imports | Grouped by type | stdlib → third-party → local |

**TypeScript:**

| Element | Pattern | Example |
|---------|---------|---------|
| Variables/functions | camelCase | `useState`, `jobId`, `fetchPrompts` |
| Types/interfaces | PascalCase | `JobStatus`, `Stats` |
| File names | kebab-case or camelCase | `page.tsx`, `layout.tsx` |
| Path aliases | `@/*` mapped to `./src/*` | `@/components/*` |

## Code Organization

**Python Import Order:**
```python
# 1. Standard library
import os
import time
import json
from typing import Optional, Dict, Any, Tuple

# 2. Third-party packages
from flask import Flask, render_template, request, jsonify
from openai import OpenAI
import psycopg2

# 3. Local application imports
from config import (DB_CONNECTION_STRING, USE_DATABASE, ...)
from algorithms.ai_functions import generate_manim_code, review_and_fix
```

**Flask Application Structure (`app.py`):**
- Lines 1-55: Imports and config loading
- Lines 99-300: Database class (`ManimDatabase`)
- Lines 304-705: Code generation pipeline (`generate_and_validate_code`)
- Lines 707-948: Render with self-healing retry loop (`save_and_render`)
- Lines 950-975: Async render wrapper (`render_async`)
- Lines 977-1175: Flask routes
- Lines 1177-1240: Startup and initialization

## Linting & Formatting

**Tools:**
- **Linter:** ruff (ignores E501, F401)
  ```bash
  ruff check . --ignore=E501,F401
  ```
- **Formatter:** black
  ```bash
  black --check .
  ```
- **Type Checker:** mypy

**Key ruff rules ignored:** E501 (line length), F401 (unused imports)

**ESLint (Frontend):**
- Config: `eslint.config.mjs` using `eslint-config-next/core-web-vitals` and `eslint-config-next/typescript`
- Ignores: `.next/**`, `out/**`, `build/**`

## Error Handling

**Python Pattern:**
```python
try:
    # operation
except Exception as e:
    print(f"[TAG] [ERR] Error: {e}")
    return None  # or fallback/default
```

**Error Logging Format:**
- `[TAG] [OK] message` — Success
- `[TAG] [ERR] message` — Error
- `[TAG] [WARN] message` — Warning
- `[TIMING] operation: {time:.2f}s` — Performance timing

**Database Errors:** Caught in `ManimDatabase._exec()` helper, returns `None` on failure

**LLM Errors:** Retry with exponential backoff (lines 62-112 in `algorithms/ai_functions.py`)

## Function Design

**Parameter Patterns:**
- Max ~5 parameters; use `**kwargs` or context dicts beyond that
- Environment-variable-driven config: `os.environ.get("VAR", "default")`
- Type hints on all public functions

**Return Patterns:**
- Tuple returns for multiple values: `Tuple[str, list, str, str, dict, list]`
- Empty collections for "nothing found": `return []` or `return {}`
- `None` for "error/unavailable": `return None`

## Logging

**Method:** Print statements with structured tags
```python
print(f"[STARTUP] Manim scripts: {MANIM_SCRIPTS.absolute()}")
print(f"[DB] [OK] Connected")
print(f"[GENERATE] [OK] {len(code)} chars generated")
```

**No logging framework** — uses built-in `print()` only

## Comments

**When Used:**
- Module-level docstrings explaining purpose
- Function docstrings for complex functions (generate_and_validate_code, save_and_render)
- Inline comments for non-obvious logic: `# Fallback to LLM path`
- Section dividers: `# ═══════════════════════════════════════════════════════════════════════════════`

**Prompts in ai_functions.py:**
- Large multi-line strings stored in `GENERATION_SYSTEM`, `REVIEW_SYSTEM`, `FIX_SYSTEM` constants
- Domain-specific guidance in `get_domain_specific_guidance(domain)` function

## Special Patterns

**AST-based Validation (`algorithms/code_digest.py`):**
- `validate_python_syntax()` — uses `ast.parse()`
- `validate_names_and_imports()` — AST walk for security checks
- Returns `(is_valid, error_message)` tuples

**Render-Error Self-Healing:**
- `fix_render_error()` feeds Manim stderr to LLM for targeted fixes
- Up to `MAX_RENDER_RETRIES` attempts with error parsing between

**Config Reloading in Tests:**
```python
import importlib
importlib.reload(config)
```

**Frontend API Calls:**
- Base URL: `http://localhost:5000`
- Polling pattern with `setInterval` and cleanup on unmount
- `useCallback` for stable function references

---

*Convention analysis: 2026-04-04*
