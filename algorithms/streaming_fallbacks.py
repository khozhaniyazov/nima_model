"""Streaming deterministic-fallback scene builders (back-compat shim).

Deterministic fallbacks are split by video mode across four leaf modules
(issue #65). This module now holds only the tiny shared helpers
(``_safe_text_literal``, ``_factorization_line``, ``_is_final_short_scene``,
and the ``_clean_plan_text`` lazy shim that defers to ``algorithms.streaming``)
and re-exports every moved symbol so existing callers — ``algorithms.streaming``,
``streaming_orchestration``, ``streaming_render``, and the test suite — keep
working unchanged.

Module-load contract:

- This module is a leaf: it MUST NOT import from ``algorithms.streaming`` at
  module load time, because ``streaming`` imports this module during its own
  load. Any helper that lives in ``streaming`` (``_clean_plan_text`` today)
  is imported lazily inside the functions that need it.
- The per-mode leaves ``streaming_fallbacks_{short,standard,course,lecture}``
  import the core helpers FROM HERE, so this module must stay the authoritative
  home for them.
- Type hints use ``from __future__ import annotations`` so references to
  ``NarrativeContext`` remain string-form and never trigger a runtime lookup.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from algorithms.streaming import NarrativeContext


# Lazy-imported from algorithms.streaming at call time; see module docstring.
def _clean_plan_text(value):  # type: ignore[override]
    from algorithms.streaming import _clean_plan_text as _impl

    return _impl(value)


def _factorization_line(number: int) -> str:
    n = max(2, int(number))
    factors: list[int] = []
    divisor = 2
    while divisor * divisor <= n:
        while n % divisor == 0:
            factors.append(divisor)
            n //= divisor
        divisor += 1
    if n > 1:
        factors.append(n)
    return " x ".join(str(factor) for factor in factors)


def _is_final_short_scene(scene_plan: dict, context: NarrativeContext) -> bool:
    if scene_plan.get("type") == "question":
        return True
    if context.domain_state.get("video_mode") != "short":
        return False
    try:
        total = int(context.domain_state.get("total_scenes") or 0)
    except (TypeError, ValueError):
        total = 0
    return bool(total and int(context.scene_index or 0) >= total - 1)


def _safe_text_literal(value: str, max_chars: int = 44) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars].rsplit(" ", 1)[0].strip()
    return cut or cleaned[:max_chars].strip()


from algorithms.streaming_fallbacks_short import (  # noqa: E402,F401
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

from algorithms.streaming_fallbacks_standard import (  # noqa: E402,F401
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

from algorithms.streaming_fallbacks_course import (  # noqa: E402,F401
    _course_fallback_title,
    _make_course_compare_fallback_scene_code,
    _make_course_fallback_scene_code,
    _make_course_fallback_scene_code_raw,
    _make_course_map_fallback_scene_code,
    _make_course_mechanism_fallback_scene_code,
    _make_course_question_fallback_scene_code,
)

from algorithms.streaming_fallbacks_lecture import (  # noqa: E402,F401
    _lecture_fallback_steps,
    _lecture_fallback_title,
    _make_lecture_fallback_scene_code,
    _make_lecture_fallback_scene_code_raw,
    _make_lecture_question_fallback_scene_code,
)
