"""Streaming deterministic-fallback scene builders (back-compat shim).

Deterministic fallbacks are split by video mode across four per-mode leaf
modules (issue #65); shared helpers live in ``streaming_fallbacks_core``.
This module is a **pure re-export shim**: it owns no code of its own beyond
the import block, and exists so existing callers — ``algorithms.streaming``,
``streaming_orchestration``, ``streaming_render``, and the test suite —
continue to reach every helper via a single stable import path.

Dependency graph (no cycles):

::

    streaming.py
        └── streaming_fallbacks  (this file, shim)
                ├── streaming_fallbacks_core       (safe to cold-import)
                ├── streaming_fallbacks_short      (imports core only)
                ├── streaming_fallbacks_standard   (imports core only)
                ├── streaming_fallbacks_course     (imports core only)
                └── streaming_fallbacks_lecture    (imports core only)

Each per-mode leaf is independently cold-importable because it only reaches
back into ``streaming_fallbacks_core`` — never into this shim and never into
a sibling leaf. The shim is the only entity with edges to every leaf, which
is fine because nothing imports the shim during one of its own loads.
"""
from __future__ import annotations

from algorithms.streaming_fallbacks_core import (  # noqa: F401
    _clean_plan_text,
    _factorization_line,
    _is_final_short_scene,
    _safe_text_literal,
)
from algorithms.streaming_fallbacks_course import (  # noqa: F401
    _course_fallback_title,
    _make_course_compare_fallback_scene_code,
    _make_course_fallback_scene_code,
    _make_course_fallback_scene_code_raw,
    _make_course_map_fallback_scene_code,
    _make_course_mechanism_fallback_scene_code,
    _make_course_question_fallback_scene_code,
)
from algorithms.streaming_fallbacks_lecture import (  # noqa: F401
    _lecture_fallback_steps,
    _lecture_fallback_title,
    _make_lecture_fallback_scene_code,
    _make_lecture_fallback_scene_code_raw,
    _make_lecture_question_fallback_scene_code,
)
from algorithms.streaming_fallbacks_short import (  # noqa: F401
    _make_short_binary_search_scene_code,
    _make_short_car_scene_code,
    _make_short_dijkstra_scene_code,
    _make_short_fallback_scene_code,
    _make_short_fallback_scene_code_raw,
    _make_short_generic_motion_scene_code,
    _make_short_molecule_scene_code,
    _short_fallback_lines,
    _short_fallback_title,
)
from algorithms.streaming_fallbacks_standard import (  # noqa: F401
    _make_standard_fallback_ladder_scene_code,
    _make_standard_fallback_linear_scan_scene_code,
    _make_standard_fallback_payoff_scene_code,
    _make_standard_fallback_race_scene_code,
    _make_standard_fallback_scene_code,
    _make_standard_fallback_sorted_order_scene_code,
    _make_standard_fallback_takeaway_scene_code,
    _make_standard_fallback_window_scene_code,
    _standard_fallback_title,
)
