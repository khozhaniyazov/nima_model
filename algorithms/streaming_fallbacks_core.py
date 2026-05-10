"""Streaming deterministic-fallback shared core helpers.

Extracted from ``algorithms/streaming_fallbacks.py`` (issue #65 follow-up) to
break a latent circular-import dependency between the shim and its per-mode
leaves.

Module-load contract:

- This module is a true leaf: it imports from *nothing* inside
  ``algorithms.streaming``, ``algorithms.streaming_fallbacks``, or any of the
  per-mode ``streaming_fallbacks_<mode>`` leaves. This is the only file in
  the ``streaming_fallbacks_*`` family that can be cold-imported
  standalone.
- All per-mode leaves (``streaming_fallbacks_short``, ``…_standard``,
  ``…_course``, ``…_lecture``) pull their shared helpers FROM HERE rather
  than from the shim, so leaves have no load-time edge to the shim — the
  shim and leaves no longer form a cycle.
- The shim ``streaming_fallbacks`` re-exports every name defined here for
  back-compat (tests and external callers access these via
  ``streaming._safe_text_literal`` etc.).
- ``_clean_plan_text`` is still a lazy shim that defers to
  ``algorithms.streaming`` at call time — the implementation lives in
  ``streaming.py`` and cannot reasonably move here without pulling large
  chunks of plan-text parsing with it.
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
