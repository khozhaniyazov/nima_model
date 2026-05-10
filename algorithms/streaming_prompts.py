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
from typing import Any, List, Optional, TYPE_CHECKING

from RAG.RAG_system import retrieve_golden_example, retrieve_patterns

if TYPE_CHECKING:  # pragma: no cover - typing only
    from algorithms.streaming import NarrativeContext


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


# ─── Scene-prompt helpers (extracted from streaming.py in the PR for #59) ────
STREAM_RAG_CONTEXT_CHARS = 5000

# FOCUS helper constants live in algorithms.streaming_validation; see
# the re-export block below.

SHORT_VERTICAL_RAG_REFERENCE = """\
# [OK] SHORT VERTICAL MANIM PATTERN: kinetic phone-safe explainer
config.frame_width = 8
config.frame_height = 14.222222
self.camera.background_color = "#0F1117"
title = Text("Fast hook", font_size=46, color="#F5F7FA", weight=BOLD).to_edge(UP, buff=0.65)
nodes = VGroup(*[
    Circle(radius=0.28, color="#58C4DD", fill_opacity=0.9).move_to(p)
    for p in [LEFT * 2 + UP * 2, RIGHT * 1.7 + UP * 1.2, LEFT * 1 + DOWN * 1.4, RIGHT * 2 + DOWN * 2]
])
edges = VGroup(
    Line(nodes[0].get_center(), nodes[1].get_center(), color="#334155", stroke_width=5),
    Line(nodes[0].get_center(), nodes[2].get_center(), color="#334155", stroke_width=5),
    Line(nodes[2].get_center(), nodes[3].get_center(), color="#334155", stroke_width=5),
    Line(nodes[1].get_center(), nodes[3].get_center(), color="#334155", stroke_width=5),
)
token = Dot(nodes[0].get_center(), radius=0.12, color="#F2C94C")
caption = Text("move the idea, not text", font_size=34, color="#F5F7FA").to_edge(DOWN, buff=0.8)
self.add(title, edges, nodes, token, caption)
self.play(Indicate(nodes[0], color="#F2C94C"), run_time=0.45)
self.play(MoveAlongPath(token, edges[0]), edges[0].animate.set_color("#F2C94C").set_stroke(width=9), run_time=0.9)
self.play(Transform(caption, Text("numbers change live", font_size=34, color="#F5F7FA").to_edge(DOWN, buff=0.8)), run_time=0.35)
self.play(MoveAlongPath(token, edges[3]), edges[3].animate.set_color("#22C55E").set_stroke(width=9), run_time=0.9)
self.wait(0.4)
"""

STANDARD_YOUTUBE_RAG_REFERENCE = """\
# [OK] STANDARD 16:9 MANIM PATTERN: retention-first YouTube explainer
self.camera.background_color = "#0F1117"
accent = "#58C4DD"
warm = "#F2C94C"
fg = "#F5F7FA"
title = Text("Why the obvious path fails", font_size=38, color=fg, weight=BOLD).to_edge(UP, buff=0.35)
axis = NumberLine(x_range=[0, 16, 2], length=9, color="#64748B").shift(DOWN * 1.6)
window = Rectangle(width=8.8, height=1.2, stroke_color=accent, stroke_width=4).move_to(axis)
mid = Dot(axis.n2p(8), radius=0.12, color=warm)
left_half = Rectangle(width=4.4, height=1.2, stroke_color="#EF4444", fill_color="#EF4444", fill_opacity=0.12).move_to(axis.n2p(4))
label = Text("Cut the search space", font_size=30, color=fg).next_to(axis, DOWN, buff=0.45)
self.add(title, axis, window, mid, label)
self.play(Create(axis), FadeIn(title, shift=DOWN * 0.2), run_time=0.8)
self.play(GrowFromCenter(window), Flash(mid, color=warm), run_time=0.9)
self.play(FadeIn(left_half), Indicate(left_half, color="#EF4444"), run_time=0.9)
self.play(left_half.animate.set_opacity(0.04), window.animate.set_width(4.4).move_to(axis.n2p(12)), mid.animate.move_to(axis.n2p(12)), run_time=1.1)
self.play(Transform(label, Text("Same rule, half the work", font_size=30, color=fg).next_to(axis, DOWN, buff=0.45)), run_time=0.6)
self.wait(1.2)
"""

COURSE_LESSON_RAG_REFERENCE = """\
# [OK] COURSE 16:9 MANIM PATTERN: modular lesson with checkpoint rail
self.camera.background_color = "#F9FAFB"
fg = "#111827"
muted = "#64748B"
accent = "#2563EB"
warm = "#F59E0B"
module = Text("Module 3 / 7", font_size=22, color=muted).to_corner(UL, buff=0.35)
rail = VGroup(*[
    Circle(radius=0.07, stroke_color=accent, fill_color=accent, fill_opacity=0.25)
    for _ in range(7)
]).arrange(RIGHT, buff=0.18).next_to(module, DOWN, aligned_edge=LEFT, buff=0.18)
title = Text("Invariant: the safe part stays safe", font_size=34, color=fg, weight=BOLD).to_edge(UP, buff=0.45)
boxes = VGroup(*[
    Rectangle(width=0.72, height=0.62, stroke_color=muted, fill_color="#E0F2FE", fill_opacity=0.45)
    for _ in range(9)
]).arrange(RIGHT, buff=0.08).shift(DOWN * 0.35)
window = Rectangle(width=4.2, height=0.86, stroke_color=accent, stroke_width=4).move_to(boxes[4])
invariant = Text("Everything outside the window is already ruled out", font_size=26, color=fg).next_to(boxes, DOWN, buff=0.55)
marker = Triangle(color=warm, fill_opacity=0.9).scale(0.18).next_to(boxes[4], UP, buff=0.2)
self.add(module, rail, title)
self.play(LaggedStart(*[FadeIn(b, shift=UP * 0.08) for b in boxes], lag_ratio=0.08), run_time=1.0)
self.play(GrowFromCenter(window), FadeIn(marker), run_time=0.8)
self.play(Write(invariant), rail[2].animate.set_fill(accent, opacity=1), run_time=0.8)
self.play(window.animate.set_width(2.0).move_to(boxes[6]), marker.animate.next_to(boxes[6], UP, buff=0.2), run_time=1.0)
self.play(Indicate(invariant, color=warm), run_time=0.8)
self.wait(1.2)
"""

LECTURE_ACADEMIC_RAG_REFERENCE = """\
# [OK] LECTURE 16:9 MANIM PATTERN: academic board with derivation focus
self.camera.background_color = "#F8FAFC"
fg = "#0F172A"
muted = "#64748B"
accent = "#1D4ED8"
warm = "#B45309"
section = Text("Section 4 - Main Proof", font_size=24, color=muted).to_corner(UL, buff=0.55)
claim = Text("Claim", font_size=28, color=fg, weight=BOLD).to_edge(UP, buff=0.62)
proof_map = VGroup(
    Text("assumptions", font_size=24, color=muted),
    Arrow(LEFT, RIGHT, color=accent),
    Text("lemma", font_size=24, color=accent),
    Arrow(LEFT, RIGHT, color=accent),
    Text("result", font_size=24, color=warm),
).arrange(RIGHT, buff=0.22).next_to(claim, DOWN, buff=0.32)
line_1 = Text("1. Start from the assumption", font_size=28, color=fg).shift(UP * 0.05)
line_2 = Text("2. Substitute the lemma result", font_size=28, color=fg).next_to(line_1, DOWN, aligned_edge=LEFT, buff=0.3)
old_layer = VGroup(proof_map, line_1)
self.add(section, claim)
self.play(FadeIn(proof_map, shift=DOWN * 0.08), Write(line_1), run_time=1.0)
focus_transition(self, old_layer, line_2, run_time=0.8)
self.play(Circumscribe(line_2, color=warm), run_time=0.7)
self.wait(1.0)
"""

FOCUS_LAYER_RAG_REFERENCE = """\
# [OK] FOCUS LAYER PATTERN: simulated depth without fragile blur filters
# Do not use Blur(...), GaussianBlur(...), PIL image filters, or camera post-processing.
# In Manim, readability is more reliable when older layers are dimmed and the
# active idea receives a translucent plate plus a higher z-index.
# The renderer injects fit_to_safe_frame(...), focus_plate(...), and
# focus_transition(scene, old_layer, active_layer) into every generated scene.

old_layer = VGroup(previous_diagram, previous_labels)
new_label = Text("new idea", font_size=28, color="#111827").move_to(RIGHT * 2 + UP * 0.8)
focus_transition(self, old_layer, new_label)
# Later, either keep the old layer dimmed as context or fade it out before the next dense panel.
"""

def _mark_scene_generation(scene_plan: dict, source: str, error: Exception | None = None) -> None:
    """Attach lightweight generation provenance directly to the mutable scene plan."""
    try:
        scene_plan["_generation_source"] = source
        if error is not None:
            detail = re.sub(r"\s+", " ", str(error)).strip()
            scene_plan["_generation_error"] = detail[:260]
    except Exception:
        return

def _coerce_scene_terms(value: Any) -> List[str]:
    """Return compact retrieval terms from scene plan values."""
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, (list, tuple, set)):
        terms: List[str] = []
        for item in value:
            terms.extend(_coerce_scene_terms(item))
        return terms
    if isinstance(value, dict):
        terms = []
        for key in ("topic", "title", "description", "narration", "name"):
            terms.extend(_coerce_scene_terms(value.get(key)))
        return terms
    return []

def _retrieve_streaming_rag_context(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """
    Fetch relevant Manim patterns for a single streaming scene.

    RAG is an optimization layer, not a reliability dependency. If retrieval fails
    for any reason, scene generation should continue with the normal prompt.
    """
    topic = (
        scene_plan.get("topic")
        or scene_plan.get("title")
        or scene_plan.get("description")
        or context.prompt
        or context.domain
    )
    terms: List[str] = []
    for key in ("objects", "animation_steps", "subtopics", "narration"):
        terms.extend(_coerce_scene_terms(scene_plan.get(key)))

    # Keep the query useful without stuffing full scene text into the cache key.
    seen = set()
    subtopics = []
    for term in terms:
        lowered = term.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        subtopics.append(term[:120])
        if len(subtopics) >= 8:
            break

    short_mode = context.domain_state.get("video_mode") == "short" or (
        context.domain_state.get("aspect") == "9:16"
    )
    if short_mode:
        sections = [SHORT_VERTICAL_RAG_REFERENCE]
        # Look up retrieval helpers via the streaming module so tests that
        # stub `streaming.retrieve_patterns` / `streaming.retrieve_golden_example`
        # continue to take effect after the extraction.
        from algorithms import streaming as _streaming  # lazy to avoid load cycle
        _retrieve_patterns = getattr(_streaming, "retrieve_patterns", retrieve_patterns)
        try:
            patterns = _retrieve_patterns(
                context.domain, str(topic), tuple(subtopics), limit=2
            )
        except Exception as exc:
            print(f"[STREAM] short RAG retrieval skipped: {exc}")
            patterns = []

        for pattern in patterns:
            notes = str(pattern.get("notes") or "").strip()
            tags = ", ".join(str(tag) for tag in pattern.get("tags", [])[:8])
            if notes:
                sections.append(
                    "# [OK] RELEVANT TECHNIQUE REFERENCE\n"
                    f"# Notes: {notes}\n"
                    f"# Tags: {tags}\n"
                    "# Short-mode adaptation: use the technique only; keep a "
                    "stacked 9:16 layout, large text, and safe frame bounds."
                )
        return "\n\n".join(sections)[:STREAM_RAG_CONTEXT_CHARS]

    standard_mode = context.domain_state.get("video_mode") == "standard"
    course_mode = context.domain_state.get("video_mode") == "course"
    lecture_mode = context.domain_state.get("video_mode") == "lecture"
    reference_sections = []
    if standard_mode:
        reference_sections.append(STANDARD_YOUTUBE_RAG_REFERENCE)
    if course_mode:
        reference_sections.append(COURSE_LESSON_RAG_REFERENCE)
    if lecture_mode:
        reference_sections.append(LECTURE_ACADEMIC_RAG_REFERENCE)
    if standard_mode or course_mode or lecture_mode:
        reference_sections.append(FOCUS_LAYER_RAG_REFERENCE)

    from algorithms import streaming as _streaming  # lazy to avoid load cycle
    _retrieve_golden_example = getattr(
        _streaming, "retrieve_golden_example", retrieve_golden_example
    )
    try:
        rag_context = _retrieve_golden_example(context.domain, str(topic), subtopics)
    except Exception as exc:
        print(f"[STREAM] RAG retrieval skipped: {exc}")
        return "\n\n".join(reference_sections)[:STREAM_RAG_CONTEXT_CHARS]

    rag_context = (rag_context or "").strip()
    if rag_context:
        reference_sections.append(rag_context)
    if not reference_sections:
        return ""
    return "\n\n".join(reference_sections)[:STREAM_RAG_CONTEXT_CHARS]

def _build_scene_prompt(
    scene_plan: dict, context: NarrativeContext, duration_hint: int
) -> str:
    """Build the generation prompt for a single scene."""
    scene_desc = scene_plan.get("description", "")
    scene_title = scene_plan.get("title", "")
    narration = scene_plan.get("narration", "")
    visual_description = scene_plan.get("visual_description", "")
    scene_role = scene_plan.get("scene_role", "")
    animation_steps = scene_plan.get("animation_steps", [])
    objects = scene_plan.get("objects", [])
    required_motions = scene_plan.get("required_motions", []) or []
    short_directives = scene_plan.get("short_directives", []) or []
    standard_directives = scene_plan.get("standard_directives", []) or []
    course_directives = scene_plan.get("course_directives", []) or []
    lecture_directives = scene_plan.get("lecture_directives", []) or []
    course_module = scene_plan.get("module", "")
    lecture_section = scene_plan.get("lecture_section", "")
    learning_objective = scene_plan.get("learning_objective", "")
    checkpoint_id = scene_plan.get("checkpoint_id", "")
    forbidden_visuals = scene_plan.get("forbidden_visuals", []) or []

    total_scenes = int(context.domain_state.get("total_scenes", 0) or 0)
    current_idx = int(context.scene_index)
    scene_position = (
        f"{current_idx + 1}/{total_scenes}" if total_scenes else str(current_idx + 1)
    )

    preamble_hint = generate_scene_preamble(context, scene_plan)
    rag_context = _retrieve_streaming_rag_context(scene_plan, context)

    prompt = f"""Create Manim CE scene for:

SCENE: {scene_desc}
SCENE POSITION: {scene_position}
DURATION HINT: ~{duration_hint} seconds
TITLE: {scene_title or "(none)"}
NARRATION TO MATCH: {narration or "(none)"}
VISUAL DESCRIPTION: {visual_description or "(none)"}
SCENE ROLE: {scene_role or "(unspecified)"}
MODULE: {course_module or "(none)"}
LECTURE SECTION: {lecture_section or "(none)"}
LEARNING OBJECTIVE: {learning_objective or "(none)"}
CHECKPOINT ID: {checkpoint_id or "(none)"}

ANIMATION STEPS:
"""

    for i, step in enumerate(animation_steps, 1):
        prompt += f"  {i}. {step}\n"

    if objects:
        prompt += f"\nOBJECTS TO ANIMATE: {', '.join(objects)}\n"
    if required_motions:
        prompt += "\nREQUIRED MOTIONS:\n"
        for i, motion in enumerate(required_motions, 1):
            prompt += f"  {i}. {motion}\n"

    short_mode = context.domain_state.get("video_mode") == "short" or (
        context.domain_state.get("aspect") == "9:16"
    )
    if short_mode:
        prompt += """
SHORT SOCIAL SCENE CONTRACT (MANDATORY):
- Treat this scene as one beat in a fast 9:16 social short.
- Do not build a title slide, bullet slide, text card, or lecture board.
- Start with a visible moving object before any long text.
- Use at least three distinct visual events before the final wait.
- Reuse or transform the central visual instead of clearing to another text layout.
- Keep all text as short HUD labels. The animation, not text, must explain the idea.
- End on a visual change, reveal, or challenge frame.
- Keep the final frame alive. Do not FadeOut the full graph/diagram/title before the scene ends.
- The code runtime must land near the duration hint; add active visual holds, pulses, route glows, or challenge pulses instead of dead air.
"""
        if short_directives:
            prompt += "\nEXTRA SHORT DIRECTIVES:\n"
            for i, directive in enumerate(short_directives, 1):
                prompt += f"  {i}. {directive}\n"
        if forbidden_visuals:
            prompt += "\nFORBIDDEN VISUALS:\n"
            for i, forbidden in enumerate(forbidden_visuals, 1):
                prompt += f"  {i}. {forbidden}\n"

    standard_mode = context.domain_state.get("video_mode") == "standard"
    if standard_mode:
        prompt += """
STANDARD YOUTUBE EXPLAINER CONTRACT (MANDATORY):
- Treat this as one chapter in a 2-5 minute YouTube explainer, not a lecture.
- No question pauses, no quizzes, no comment CTA, and no text-only chapter cards.
- Start with motion or a concrete visual within the first second.
- Keep a recurring anchor visual that evolves across the scene.
- Use pattern interrupts every 8-12 seconds: compare, zoom, transform, reveal, simulate, or show a common mistake.
- Explain with visual cause and effect. Text may label objects, equations, or chapter beats, but cannot carry the whole scene.
- When adding a new dense label, panel, or branch over existing material, do not use literal blur filters; dim the older layer and put a translucent focus plate behind the new layer.
- After building the main visual group, scale it into a safe inner frame around width 10.6 and height 5.1 so labels do not crowd the edges.
- Only the main title may use to_edge(UP). Put counters, arrows, labels, and beat markers next_to the anchor visual with at least 0.25 buff.
- Use distinct vertical lanes for labels above and below rows/graphs; never stack two labels on the same point or over cells.
- End on a living visual payoff or open loop. Do not FadeOut the full diagram before the scene ends.
- The code runtime must land near the duration hint; add active visual holds, replays, comparison pulses, or state updates instead of dead air.
"""
        if standard_directives:
            prompt += "\nEXTRA STANDARD DIRECTIVES:\n"
            for i, directive in enumerate(standard_directives, 1):
                prompt += f"  {i}. {directive}\n"
        if scene_plan.get("retention_hook"):
            prompt += (
                "\nRETENTION BEAT: This scene must contain a visible tension, "
                "misconception, reveal, or payoff moment.\n"
            )
        if forbidden_visuals:
            prompt += "\nFORBIDDEN VISUALS:\n"
            for i, forbidden in enumerate(forbidden_visuals, 1):
                prompt += f"  {i}. {forbidden}\n"

    course_mode = context.domain_state.get("video_mode") == "course"
    if course_mode:
        if scene_plan.get("type") == "question":
            prompt += """
COURSE CHECKPOINT CONTRACT (MANDATORY):
- Treat this as an intentional learner thinking pause, not a content lecture.
- Show exactly one question prompt with a faint reminder of the prior anchor visual.
- Add a small timer/progress pulse and hold near the duration hint.
- Do not reveal the answer during the pause, do not ask for comments, and do not add multiple quiz questions.
- Keep text readable: one prompt plus at most two short option/path labels.
"""
        else:
            prompt += """
COURSE CONTENT SCENE CONTRACT (MANDATORY):
- Treat this as one 10-30 second scenelet inside a chapter of a longer course lesson.
- Keep a module label or progress rail visible without making it the main content.
- Teach through a diagram, worked example, state table, graph, array, or concrete object that changes on screen.
- Avoid paragraph boards. Use short labels attached to objects and reveal definitions only when used.
- Use deliberate pacing: at least two visual teaching moves before any recap or takeaway.
- When introducing a new panel or label over existing material, do not use literal blur filters; first dim or fade the old group, then add a BackgroundRectangle/focus plate behind the new group and set the active group above it with z-index.
- End with a state that can carry into a checkpoint, recap map, or next module.
- Keep all important text and objects inside x=-5.7..5.7 and y=-2.9..2.9; scale the main visual group into a safe inner frame before playing animations.
- The code runtime must land near the duration hint and must not exceed 30 seconds; use example steps, state updates, checklist routing, or timer pulses instead of dead air.
"""
        if course_directives:
            prompt += "\nEXTRA COURSE DIRECTIVES:\n"
            for i, directive in enumerate(course_directives, 1):
                prompt += f"  {i}. {directive}\n"
        if learning_objective:
            prompt += (
                "\nLEARNING OBJECTIVE: The visual must make this objective "
                f"observable: {learning_objective}\n"
            )
        if forbidden_visuals:
            prompt += "\nFORBIDDEN VISUALS:\n"
            for i, forbidden in enumerate(forbidden_visuals, 1):
                prompt += f"  {i}. {forbidden}\n"

    lecture_mode = context.domain_state.get("video_mode") == "lecture"
    if lecture_mode:
        if scene_plan.get("type") == "question":
            prompt += """
LECTURE THINKING PAUSE CONTRACT (MANDATORY):
- Treat this as a quiet academic pause, not a quiz card or social prompt.
- Show exactly one proof/derivation question over a faint prior proof map.
- Add a subtle timer/progress pulse and hold near the duration hint.
- Do not reveal the answer during the pause and do not add multiple questions.
- Keep text sparse: one prompt plus at most one short reminder label.
"""
        else:
            prompt += """
LECTURE CONTENT SCENE CONTRACT (MANDATORY):
- Treat this as one academic scenelet inside a longer lecture.
- Build one formal move: definition expansion, lemma proof step, theorem implication, worked example step, pitfall repair, or recap map.
- Keep a section label, proof map, equation ladder, or assumption ledger visible without letting it dominate the frame.
- Use focus layering for new derivation lines: do not use literal blur filters; dim old proof context, add a BackgroundRectangle/focus plate behind the active line, and set active z-index above old context.
- Avoid paragraph proof walls. Use short lines attached to justifications, arrows, diagrams, or equation steps.
- Use font_size >= 24 for every label, justification, and equation line. Do not create tiny 18-23px proof labels.
- Keep all important notation inside x=-5.4..5.4 and y=-2.65..2.65; scale the main board into width 10.8 and height 5.3 before animations.
- Keep at most five active proof lines visible at once. Older context should become a dim proof map, not another crisp text stack.
- The code runtime must land near the duration hint and must not exceed 50 seconds; use derivation steps, proof-map pulses, and active holds instead of dead air.
"""
        if lecture_directives:
            prompt += "\nEXTRA LECTURE DIRECTIVES:\n"
            for i, directive in enumerate(lecture_directives, 1):
                prompt += f"  {i}. {directive}\n"
        if learning_objective:
            prompt += (
                "\nLEARNING OBJECTIVE: The academic board must make this objective "
                f"observable: {learning_objective}\n"
            )
        if forbidden_visuals:
            prompt += "\nFORBIDDEN VISUALS:\n"
            for i, forbidden in enumerate(forbidden_visuals, 1):
                prompt += f"  {i}. {forbidden}\n"

    prompt += f"""
DOMAIN: {context.domain}
TARGET TOTAL DURATION: {context.duration_target}s

CONTINUITY REQUIREMENTS (CRITICAL):
- This is scene {scene_position} of one continuous video.
- Do NOT repeat explanation from previous scenes.
- Do NOT restart from introductory framing unless this is scene 1.
- Preserve narrative progression from prior scenes in context.
- Avoid full-screen resets and unnecessary redraw of same objects.
- Use the theme colors from context exactly; do not choose a different background.
- Do not emit labels that start with literal prefixes such as "text", "label", or "title".

POSSIBLE CARRY-OVER HINTS:
{preamble_hint or "(none)"}

{context.to_context_string()}
"""

    if rag_context:
        prompt += f"""
RELEVANT PROVEN MANIM PATTERNS:
- Use these as technique references, not as copy-paste scene boilerplate.
- Preserve this scene's storyboard, duration, theme, and continuity rules.

{rag_context}
"""

    prompt += """
Generate the complete Python code for this single scene only.
"""

    return prompt


# Code post-processing, quality gates and classify_render_error were
# extracted to algorithms.streaming_validation in the PR for #11.
# Re-exported here so tests and internal callers can still reach them
# via streaming.<name>.

def _update_context_from_scene(
    context: NarrativeContext,
    code: str,
    scene_desc: str,
) -> NarrativeContext:
    """Update narrative context based on generated scene code."""
    import re

    # Extract MathTex/Text objects mentioned in code
    math_objects = re.findall(r"MathTex\((.*?)\)", code)
    text_objects = re.findall(r"Text\((.*?)\)", code)
    shapes = re.findall(r"(Circle|Line|Arrow|Square|Triangle|Polygon)\(", code)

    # Register created objects
    for tex in math_objects[:5]:
        clean = tex.strip()[:30]
        context.add_object(f"tex_{clean[:10]}", "MathTex", clean)

    for txt in text_objects[:3]:
        clean = txt.strip()[:20]
        context.add_object(f"text_{clean[:10]}", "Text", clean)

    for shape in shapes[:5]:
        context.add_object(f"shape_{shape.lower()}", shape, f"{shape} shape")

    context.add_scene_history(scene_desc)

    return context


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE-LEVEL RETRY
# ═══════════════════════════════════════════════════════════════════════════════

def generate_scene_preamble(context: NarrativeContext, scene_plan: dict) -> str:
    """
    Generate scene opening: recreates needed objects for continuity.

    For scenes that need objects from previous scenes, this generates
    the setup code to recreate those objects at the scene's start.
    """
    bg = context.domain_state.get("background_color", "#0F1117")
    preamble = f'# Scene preamble: keep visual theme consistent\nself.camera.background_color = "{bg}"\n'

    # Domain-specific setup
    if context.domain == "math":
        if not context.object_state:
            # First scene: set up axes
            preamble += (
                """
# Scene preamble: set up coordinate system
self.camera.background_color = "%s"
"""
                % bg
            )

    elif context.domain == "physics":
        preamble += """
# Scene preamble: physics domain setup
"""

    # Object recreation for continuity
    if context.object_state and len(context.scene_history) > 0:
        # This is NOT the first scene — recreate key objects
        recreations = []
        for name, info in list(context.object_state.items())[:5]:
            recreations.append(f"# Recreate {name}: {info['description']}")

        if recreations:
            preamble += "\n" + "\n".join(recreations) + "\n"

    return preamble


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE RENDERING (parallel)
# ═══════════════════════════════════════════════════════════════════════════════
