"""Pytest configuration for the NIMA test suite.

Ensures the project root (parent of tests/) is on sys.path so that test
modules can `import app`, `import config`, `from algorithms ...` regardless
of how pytest is invoked.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Default to a non-DB, non-real-key environment for unit tests so that import
# of `config` / `app` does not crash on a developer machine without secrets.
os.environ.setdefault("USE_DATABASE", "false")
os.environ.setdefault("OPENAI_API_KEY", "test")
