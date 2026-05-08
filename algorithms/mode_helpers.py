"""Shared plan-shaping helpers for the four mode planners.

`algorithms/course.py`, `algorithms/standard.py`, `algorithms/lecture.py` and
`algorithms/shorts.py` previously redeclared the same small set of plan-shaping
utilities — text normalisation, positive-int parsing, raw-segment extraction,
and generic-phrase / motion-word detection. The bodies were identical; drift
only showed up in the *data* each mode used (phrase sets and motion vocab).

This module owns:

* The pure helpers (``clean_text``, ``text_blob``, ``positive_int``,
  ``raw_plan_segments``) that were byte-identical across all four mode
  modules.
* Parameterised versions of the shape-matching helpers (``looks_generic``,
  ``has_motion``) so each mode can supply its own phrase set / field list /
  motion vocab without reproducing the detection body.

Mode-specific text (GENERIC_*_PHRASES, MOTION / ACADEMIC_MOTION word sets,
``_topic_from`` regexes) stays inside each mode module because the vocabulary
is genuinely mode-specific and divergence is intentional.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable


def clean_text(value: Any) -> str:
    """Collapse whitespace and strip. Safe on ``None`` (returns empty str)."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def text_blob(value: Any) -> str:
    """Lowercase JSON serialisation for substring matching, with a plain-str fallback."""
    try:
        return json.dumps(value, ensure_ascii=True).lower()
    except TypeError:
        return str(value or "").lower()


def positive_int(value: Any, default: int) -> int:
    """Coerce ``value`` to a positive int, falling back to ``default`` on failure."""
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = int(default)
    return max(1, parsed)


def raw_plan_segments(plan_data: dict) -> list[dict]:
    """Return the first non-empty list of dicts under segments/scenes/beats."""
    for key in ("segments", "scenes", "beats"):
        items = [item for item in plan_data.get(key, []) if isinstance(item, dict)]
        if items:
            return items
    return []


def looks_generic(segment: dict, phrases: Iterable[str]) -> bool:
    """True if ``segment`` serialises to a blob containing any of ``phrases``."""
    blob = text_blob(segment)
    return any(phrase in blob for phrase in phrases)


def has_motion(
    segment: dict,
    *,
    fields: Iterable[str],
    words: Iterable[str],
    threshold: int = 2,
) -> bool:
    """Count how many motion vocab ``words`` appear anywhere in ``segment``'s
    ``fields`` (as a single JSON blob), and return True if at least ``threshold``
    words match. Preserves the ``>= 2`` default that every mode used previously.
    """
    blob = text_blob([segment.get(field) for field in fields])
    return sum(1 for word in words if word in blob) >= threshold
