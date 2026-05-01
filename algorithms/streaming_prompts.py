"""Retry-prompt helpers for `algorithms.streaming` (extracted in PR for #11).

This module owns the gate-aware retry prompt machinery introduced in PR #7
(commit `6f3d0a3`): given a quality-gate error blob, classify it, name the
offending objects, and emit a surgical "rebuild from scratch" template that
the in-loop retry and `retry_scene` paths can append to their prompts.

These functions are **pure** (no I/O, no streaming, no LLM call) so they live
in their own module to keep `streaming.py` focused on orchestration. The
public `streaming` module re-exports every name defined here for backward
compatibility — call sites and existing tests that monkeypatch
``streaming._classify_retry_error`` etc. continue to work unchanged.
"""
from __future__ import annotations

import re
from typing import Optional


# Recognised gate categories from `_reject_layout_hygiene_code` and the static
# layout detector. Mapping a gate to a surgical recovery template lets the
# retry prompt do something more useful than re-asserting the original storyboard
# with the raw error blob appended.
# Anchor token forms emitted by `algorithms/overlap_detector.py:_normalize_pos`:
#   - edge:<DIR> and the multi-token edge:UP+LEFT case (joined by "+"), so the
#     character class includes "+".
#   - anchor:<name> with arbitrary punctuation (e.g. anchor:card:UP).
#   - tup:x,y,z for raw-coordinate collisions.
# Without the multi-token edge support and tup: alternation, real overlap
# warnings either truncate the anchor or fall through to the generic block.
_OVERLAP_PATTERN = re.compile(
    r"\[OVERLAP\][^\[\]\n]*?\(([^)]+)\)[^\[\]\n]*?\(([^)]+)\)[^\[\]\n]*?"
    r"(edge:[A-Z+]+|anchor:[^\s,.]+|tup:[^\s,]+(?:,[^\s,]+){0,2})",
    flags=re.IGNORECASE,
)


def _extract_overlap_pair(error_text: str) -> Optional[tuple[str, str, str]]:
    """Parse an [OVERLAP] error of the form '... (a) ... (b) ... edge:UP ...'.

    Returns (first_name, second_name, anchor_token) or None when the error
    isn't an overlap or doesn't match the expected shape. Used to feed the
    retry prompt concrete object names so the model has something to hook
    its FadeOut into.
    """
    # Use case-insensitive guard to stay consistent with the IGNORECASE regex
    # below; the static detector emits uppercase today but a future log
    # normalizer mustn't silently break extraction.
    if "[overlap]" not in error_text.lower():
        return None
    match = _OVERLAP_PATTERN.search(error_text)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip(), match.group(3).strip()


def _classify_retry_error(error_text: str) -> str:
    """Return a coarse category label for a retry failure.

    Mirrors the gate names emitted by ``_reject_layout_hygiene_code`` and the
    upstream detectors so the retry prompt can branch to a surgical template
    instead of always shipping the same generic plea. Order matters because
    multiple gates can appear in one error string.
    """
    lowered = error_text.lower()
    if "[overlap]" in lowered:
        return "overlap"
    if "[accumulation]" in lowered:
        return "accumulation"
    if "[section_leak]" in lowered or "[no_cleanup]" in lowered:
        return "leftover"
    if "crowd frame edges" in lowered:
        return "edge_crowding"
    # Word-boundary match to avoid 'context' triggering 'text' (substring match
    # would route any error mentioning narrative/scene context + overlap into
    # the wrong branch). Reviewer flagged this in the PR #7 self-review.
    if re.search(r"\bocr\b|\btext\s+overlap\b", lowered):
        return "text_overlap"
    return "generic"


def _surgical_repair_tips(error_text: str) -> str:
    """Return a gate-specific repair-tips block, or empty string if no gate matches.

    Pure tips — no PREVIOUS-ATTEMPT preamble — so it can be appended to either
    the in-loop retry (which prepends a preamble) or `retry_scene`'s prompt
    (which already has its own RENDER ERROR section) without duplication.
    """
    category = _classify_retry_error(error_text)

    if category == "overlap":
        pair = _extract_overlap_pair(error_text)
        if pair:
            first, second, anchor = pair
            specifics = (
                f"- Identified offenders: `{first}` and `{second}` collide at "
                f"`{anchor}`. Before introducing `{second}` (or any object at "
                f"the same anchor), call `self.play(FadeOut({first}))` (or "
                f"`self.remove({first})`) so the anchor is empty.\n"
            )
        else:
            specifics = (
                "- Two visible objects share the same edge or anchor without a "
                "FadeOut between them. Before introducing the second object, "
                "explicitly remove or FadeOut the first.\n"
            )
        return (
            "\nSURGICAL OVERLAP REPAIR (rebuild from scratch — do NOT preserve previous coordinates):\n"
            f"{specifics}"
            "- Lay out anchors as a small set of named slots (top, center, bottom, left_lane, right_lane).\n"
            "- Each slot holds at most ONE object at a time. When you reuse a slot, FadeOut or Transform the prior occupant first.\n"
            "- Prefer `self.play(ReplacementTransform(old, new))` over re-adding into the same anchor.\n"
            "- Keep buff>=0.25 between any two visible objects.\n"
            "- Re-derive every coordinate; do not patch the previous code's positions.\n"
        )

    if category == "accumulation":
        return (
            "\nSURGICAL ACCUMULATION REPAIR (rebuild from scratch):\n"
            "- Track every object you Create/Write/Add and pair it with an explicit FadeOut/Remove before the next dense step.\n"
            "- Group ephemeral helpers into a single VGroup and FadeOut the group together.\n"
            "- Cap the number of simultaneously visible objects to <= 8 in short mode and <= 14 in standard/lecture/course.\n"
            "- Use `focus_transition` style: dim previous step to opacity<=0.25 instead of leaving it at full opacity.\n"
            "- Do not extend the previous code; re-derive the construct() body from the storyboard.\n"
        )

    if category == "leftover":
        return (
            "\nSURGICAL LEFTOVER REPAIR (rebuild from scratch):\n"
            "- A prior section's objects survived past their narrative window. Add explicit `self.play(FadeOut(VGroup(...)))` at the END of every storyboard beat before the next beat begins.\n"
            "- Do not rely on later objects to occlude earlier ones.\n"
        )

    if category == "edge_crowding":
        return (
            "\nSURGICAL EDGE-CROWDING REPAIR:\n"
            "- Pull every label inward by buff>=0.4 from frame edges.\n"
            "- Use `move_to(ORIGIN + …)` over `to_edge` for non-title elements.\n"
            "- Scale the main visual to fit width<=10.4 / height<=5.0.\n"
        )

    if category == "text_overlap":
        return (
            "\nSURGICAL TEXT REPAIR:\n"
            "- Place captions in a dedicated lane (e.g., DOWN*2.4) that no animated object occupies.\n"
            "- Replace stacked Text labels with a single VGroup that fades through them via Transform.\n"
        )

    return ""


def _build_retry_addendum(
    last_error: Exception | str,
    *,
    attempt: int,
    scene_plan: dict,
) -> str:
    """Compose a surgical retry addendum for ``generate_scene``'s in-loop retry.

    Why: the previous behaviour was a single generic blob ("Regenerate the
    whole scene, keeping the same storyboard..."). On live runs (job
    ``smoke-69f588b0``) the model would respond with near-identical code that
    tripped the same gate again, eating the entire 2-attempt budget. By
    branching on the gate that fired we name the offending objects and
    cleanup primitive so the second attempt can actually recover instead of
    always falling to the deterministic fallback.

    When a surgical block applies, the ``attempt`` counter is intentionally
    ignored — surgical tips already imply "rebuild from scratch", so the
    final-attempt escalation paragraph would be redundant or contradictory.
    The ``scene_plan`` parameter is currently unused and reserved for
    future per-mode tuning of the surgical templates.
    """
    error_text = str(last_error)

    base = (
        "\n\nPREVIOUS ATTEMPT FAILED QUALITY/RENDER CONTRACT:\n"
        f"{error_text}\n"
        "Regenerate the whole scene, keeping the same storyboard and mode contract. "
        "Do not merely patch around the error with static holds or smaller text.\n"
    )
    tips = _surgical_repair_tips(error_text)
    if tips:
        return base + tips

    if attempt > 1:
        return base + (
            "\nThis is your final attempt. Discard the previous code's structure entirely "
            "and rebuild the scene from the storyboard, treating each beat as an isolated step "
            "with explicit FadeOut/Remove cleanup before the next beat.\n"
        )

    return base
