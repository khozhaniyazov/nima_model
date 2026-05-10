"""Streaming lecture-mode deterministic fallbacks.

Split out of ``algorithms/streaming_fallbacks.py`` (issue #65). This module
holds the lecture-mode scene-code builders used when the LLM path fails and
we need to ship a valid Manim scene.

All functions are pure string synthesis — no LLM, subprocess, or I/O.
Callers reach these via ``algorithms.streaming_fallbacks`` (which re-exports
every name for back-compat) or via ``algorithms.streaming`` (the tests and
monkeypatch surface).

Module-load contract: leaf module. MUST NOT import ``algorithms.streaming``
at module load time — ``streaming_fallbacks`` imports from here, and
``streaming`` imports from ``streaming_fallbacks``. Any helper living in
``algorithms.streaming`` must be imported lazily inside the function body.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from algorithms.i18n import localize_scene_code
from algorithms.streaming_fallbacks import (
    _clean_plan_text,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from algorithms.streaming import NarrativeContext


def _lecture_fallback_title(scene_plan: dict, context: NarrativeContext) -> str:
    title = str(
        scene_plan.get("title")
        or scene_plan.get("lecture_section")
        or scene_plan.get("description")
        or context.prompt
        or "Lecture board"
    )
    title = _clean_plan_text(title) or "Lecture board"
    if len(title) > 54:
        title = title[:51].rstrip(" ,.;:-") + "..."
    return title


def _lecture_fallback_steps(scene_plan: dict) -> tuple[list[str], list[str], str]:
    role = _clean_plan_text(scene_plan.get("scene_role") or scene_plan.get("type")).lower()
    if "example" in role:
        return (
            ["instantiate symbols", "run the calculation", "interpret the result"],
            ["given values", "theorem rule", "computed target"],
            "the example follows the proof map",
        )
    if any(token in role for token in ("pitfall", "repair", "edge")):
        return (
            ["test the tempting step", "mark the missing assumption", "repair the route"],
            ["naive line", "failure point", "valid condition"],
            "the bad proof fails at one visible step",
        )
    if "definition" in role or "statement" in role:
        return (
            ["separate assumptions", "name the conclusion", "connect the implication"],
            ["assumption", "definition", "target claim"],
            "the statement is a map, not a paragraph",
        )
    return (
        ["start from the assumption", "apply the lemma", "arrive at the target"],
        ["assumption", "lemma", "target"],
        "one proof move stays active at a time",
    )


def _make_lecture_question_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _lecture_fallback_title(scene_plan, context)
    question = _clean_plan_text(
        scene_plan.get("narration")
        or scene_plan.get("description")
        or "Which assumption is doing the work here?"
    )
    if len(question) > 105:
        question = question[:102].rstrip(" ,.;:-") + "..."
    bg = context.domain_state.get("background_color", "#0B1020")
    fg = context.domain_state.get("foreground_color", "#F8FAFC")
    accent = context.domain_state.get("accent_color", "#93C5FD")
    secondary = context.domain_state.get("secondary_color", "#FBBF24")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")

        title = Text({title!r}, font_size=32, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        section = Text("thinking pause", font_size=22, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.14)

        prompt = Text({question!r}, font_size=29, color=fg, weight=BOLD)
        if prompt.width > 9.8:
            prompt.scale_to_fit_width(9.8)
        prompt.move_to(UP * 0.45)

        map_nodes = VGroup()
        for label in ["statement", "lemma", "target"]:
            box = RoundedRectangle(width=2.35, height=0.54, corner_radius=0.08, stroke_color=muted, stroke_width=1.8, fill_color=ManimColor("#111827"), fill_opacity=0.45)
            text = Text(label, font_size=20, color=muted).move_to(box)
            map_nodes.add(VGroup(box, text))
        map_nodes.arrange(RIGHT, buff=0.35).next_to(prompt, DOWN, buff=0.75)
        map_nodes.set_opacity(0.42)
        timer = Circle(radius=0.42, stroke_color=secondary, stroke_width=5).next_to(map_nodes, DOWN, buff=0.55)
        timer_label = Text("pause", font_size=21, color=secondary, weight=BOLD).move_to(timer)

        self.play(FadeIn(section), FadeIn(title, shift=DOWN * 0.12), run_time=0.8)
        self.play(FadeIn(prompt), FadeIn(map_nodes), run_time=0.9)
        self.play(Create(timer), FadeIn(timer_label), run_time=0.8)
        self.play(timer.animate.scale(1.12), rate_func=there_and_back, run_time=1.0)
        self.wait(6.4)
'''


def _make_lecture_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Deterministic academic scenelet for lecture-mode reliability."""
    return localize_scene_code(_make_lecture_fallback_scene_code_raw(scene_plan, context))


def _make_lecture_fallback_scene_code_raw(
    scene_plan: dict, context: NarrativeContext
) -> str:
    if scene_plan.get("type") == "question" or "question" in _clean_plan_text(scene_plan.get("scene_role")).lower():
        return _make_lecture_question_fallback_scene_code(scene_plan, context)

    title = _lecture_fallback_title(scene_plan, context)
    section = _clean_plan_text(scene_plan.get("lecture_section") or "Academic Board")
    if len(section) > 38:
        section = section[:35].rstrip(" ,.;:-") + "..."
    steps, assumptions, payoff_line = _lecture_fallback_steps(scene_plan)
    bg = context.domain_state.get("background_color", "#0B1020")
    fg = context.domain_state.get("foreground_color", "#F8FAFC")
    accent = context.domain_state.get("accent_color", "#93C5FD")
    secondary = context.domain_state.get("secondary_color", "#FBBF24")
    steps_literal = repr(steps)
    assumptions_literal = repr(assumptions)

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=32, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        section = Text({section!r}, font_size=21, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.14)

        assumptions = {assumptions_literal}
        ledger = VGroup()
        for label in assumptions:
            box = RoundedRectangle(width=2.75, height=0.58, corner_radius=0.08, stroke_color=muted, stroke_width=1.6, fill_color=ManimColor("#111827"), fill_opacity=0.75)
            text = Text(label, font_size=19, color=fg)
            if text.width > 2.35:
                text.scale_to_fit_width(2.35)
            text.move_to(box)
            ledger.add(VGroup(box, text))
        ledger.arrange(DOWN, buff=0.18).move_to(LEFT * 4.45 + DOWN * 0.18)
        ledger_title = Text("assumption ledger", font_size=20, color=muted, weight=BOLD).next_to(ledger, UP, buff=0.18)

        steps = {steps_literal}
        ladder = VGroup()
        for idx, label in enumerate(steps):
            plate = RoundedRectangle(width=5.55, height=0.64, corner_radius=0.09, stroke_color=accent if idx < len(steps) - 1 else good, stroke_width=2.0, fill_color=ManimColor("#111827"), fill_opacity=0.82)
            text = Text(label, font_size=22, color=fg if idx < len(steps) - 1 else good, weight=BOLD)
            if text.width > 5.05:
                text.scale_to_fit_width(5.05)
            text.move_to(plate)
            ladder.add(VGroup(plate, text))
        ladder.arrange(DOWN, buff=0.24).move_to(DOWN * 0.18)

        proof_map = VGroup()
        for label in ["statement", "lemma", "target"]:
            node = RoundedRectangle(width=2.15, height=0.52, corner_radius=0.08, stroke_color=secondary, stroke_width=1.8, fill_color=ManimColor("#1F2937"), fill_opacity=0.72)
            text = Text(label, font_size=18, color=secondary).move_to(node)
            proof_map.add(VGroup(node, text))
        proof_map.arrange(DOWN, buff=0.22).move_to(RIGHT * 4.45 + DOWN * 0.12)
        map_title = Text("proof map", font_size=20, color=muted, weight=BOLD).next_to(proof_map, UP, buff=0.18)
        arrows = VGroup()
        for idx in range(len(proof_map) - 1):
            arrows.add(Arrow(proof_map[idx].get_bottom(), proof_map[idx + 1].get_top(), buff=0.05, color=secondary, stroke_width=2.5))

        self.play(FadeIn(section), FadeIn(title, shift=DOWN * 0.12), run_time=0.8)
        self.play(FadeIn(ledger_title), LaggedStart(*[FadeIn(card, shift=RIGHT * 0.10) for card in ledger], lag_ratio=0.10), run_time=1.0)
        self.play(FadeIn(map_title), LaggedStart(*[FadeIn(node) for node in proof_map], lag_ratio=0.10), LaggedStart(*[Create(arrow) for arrow in arrows], lag_ratio=0.12), run_time=1.1)
        self.play(LaggedStart(*[FadeIn(line, shift=UP * 0.08) for line in ladder], lag_ratio=0.16), run_time=1.2)

        active = SurroundingRectangle(ladder[0], color=secondary, buff=0.08, stroke_width=3)
        self.play(Create(active), Indicate(ledger[0], color=secondary), run_time=0.9)
        next_active = SurroundingRectangle(ladder[1], color=secondary, buff=0.08, stroke_width=3)
        self.play(Transform(active, next_active), ledger[0].animate.set_opacity(0.45), Indicate(ladder[1], color=secondary), run_time=1.0)
        final_active = SurroundingRectangle(ladder[2], color=good, buff=0.08, stroke_width=3.5)
        self.play(Transform(active, final_active), proof_map[-1].animate.set_stroke(color=good, width=3), Indicate(ladder[2], color=good), run_time=1.0)

        plate = RoundedRectangle(width=6.7, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.88)
        plate.to_edge(DOWN, buff=0.42)
        payoff = Text({payoff_line!r}, font_size=27, color=fg, weight=BOLD).move_to(plate)
        if payoff.width > 6.2:
            payoff.scale_to_fit_width(6.2)
            payoff.move_to(plate)
        self.play(FadeIn(plate), FadeIn(payoff), Flash(ladder[-1].get_center(), color=good, flash_radius=0.55, line_length=0.16), run_time=0.9)
        self.wait(15.0)
'''
