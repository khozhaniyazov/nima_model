"""Streaming course-mode deterministic fallbacks.

Split out of ``algorithms/streaming_fallbacks.py`` (issue #65). This module
holds the course-mode scene-code builders used when the LLM path fails and
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


def _course_fallback_title(scene_plan: dict, context: NarrativeContext) -> str:
    title = str(
        scene_plan.get("title")
        or scene_plan.get("module")
        or scene_plan.get("description")
        or context.prompt
        or "Lesson scene"
    )
    title = _clean_plan_text(title) or "Lesson scene"
    if len(title) > 54:
        title = title[:51].rstrip(" ,.;:-") + "..."
    return title


def _make_course_question_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _course_fallback_title(scene_plan, context)
    prompt = _clean_plan_text(
        scene_plan.get("narration")
        or scene_plan.get("description")
        or "Which path matches the idea we just built?"
    )
    if len(prompt) > 104:
        prompt = prompt[:101].rstrip(" ,.;:-") + "..."
    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    secondary = context.domain_state.get("secondary_color", "#F2C94C")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")

        title = Text({title!r}, font_size=30, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        module = Text("checkpoint", font_size=20, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.22)

        question = Text({prompt!r}, font_size=29, color=fg, weight=BOLD)
        if question.width > 9.8:
            question.scale_to_fit_width(9.8)
        question.move_to(UP * 0.55)

        left = RoundedRectangle(width=3.3, height=0.9, corner_radius=0.1, stroke_color=accent, stroke_width=2.5, fill_color=ManimColor("#111827"), fill_opacity=0.72).shift(LEFT * 2.25 + DOWN * 0.8)
        right = RoundedRectangle(width=3.3, height=0.9, corner_radius=0.1, stroke_color=secondary, stroke_width=2.5, fill_color=ManimColor("#111827"), fill_opacity=0.72).shift(RIGHT * 2.25 + DOWN * 0.8)
        left_text = Text("use the rule", font_size=23, color=accent, weight=BOLD).move_to(left)
        right_text = Text("test an example", font_size=23, color=secondary, weight=BOLD).move_to(right)
        timer = Line(LEFT * 2.0, RIGHT * 2.0, color=muted, stroke_width=5).to_edge(DOWN, buff=0.75)
        tick = Dot(color=secondary, radius=0.08).move_to(timer.get_left())

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(module), run_time=0.8)
        self.play(FadeIn(question), run_time=0.8)
        self.play(FadeIn(left), FadeIn(right), FadeIn(left_text), FadeIn(right_text), run_time=0.8)
        self.play(Create(timer), GrowFromCenter(tick), run_time=0.7)
        self.play(tick.animate.move_to(timer.get_right()), rate_func=linear, run_time=1.2)
        self.wait(6.3)
'''


def _make_course_map_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _course_fallback_title(scene_plan, context)
    module = _clean_plan_text(scene_plan.get("module") or "Course Map")
    if len(module) > 36:
        module = module[:33].rstrip(" ,.;:-") + "..."
    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    secondary = context.domain_state.get("secondary_color", "#F2C94C")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=30, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        module = Text({module!r}, font_size=19, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.22)

        milestones = VGroup()
        labels = ["anchor", "rule", "practice", "transfer"]
        for idx, label in enumerate(labels):
            box = RoundedRectangle(width=2.0, height=0.68, corner_radius=0.09, stroke_color=accent if idx < 2 else muted, stroke_width=2.2, fill_color=ManimColor("#111827"), fill_opacity=0.82)
            text = Text(label, font_size=21, color=fg if idx < 2 else muted, weight=BOLD).move_to(box)
            milestones.add(VGroup(box, text))
        milestones.arrange(DOWN, buff=0.28).shift(LEFT * 3.25 + DOWN * 0.18)

        path = VMobject(color=secondary, stroke_width=5)
        points = [m.get_center() for m in milestones]
        path.set_points_as_corners(points)
        learner = Dot(color=secondary, radius=0.12).move_to(points[0])

        board = RoundedRectangle(width=4.7, height=2.6, corner_radius=0.14, stroke_color=accent, stroke_width=3, fill_color=ManimColor("#111827"), fill_opacity=0.82).shift(RIGHT * 1.8 + DOWN * 0.05)
        board_title = Text("course route", font_size=24, color=fg, weight=BOLD).move_to(board.get_top() + DOWN * 0.45)
        route_a = Line(board.get_left() + RIGHT * 0.55 + UP * 0.25, board.get_center() + LEFT * 0.2, color=secondary, stroke_width=5)
        route_b = Line(board.get_center() + LEFT * 0.2, board.get_right() + LEFT * 0.65 + DOWN * 0.35, color=good, stroke_width=5)
        final_dot = Dot(color=good, radius=0.12).move_to(route_b.get_end())

        plate = RoundedRectangle(width=6.2, height=0.78, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.88)
        plate.to_edge(DOWN, buff=0.42)
        objective = Text("keep the lesson route visible", font_size=27, color=fg, weight=BOLD).move_to(plate)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(module), run_time=0.8)
        self.play(LaggedStart(*[FadeIn(m, shift=RIGHT * 0.12) for m in milestones], lag_ratio=0.12), run_time=1.1)
        self.play(Create(path), GrowFromCenter(learner), run_time=0.9)
        self.play(learner.animate.move_to(points[1]), Indicate(milestones[1], color=secondary), run_time=1.0)
        self.play(FadeIn(board), FadeIn(board_title), run_time=0.8)
        self.play(Create(route_a), learner.animate.move_to(points[2]), run_time=1.0)
        self.play(Create(route_b), GrowFromCenter(final_dot), Indicate(milestones[-1], color=good), run_time=1.0)
        self.play(FadeIn(plate), FadeIn(objective), Flash(final_dot.get_center(), color=good, flash_radius=0.5, line_length=0.16), run_time=0.9)
        self.wait(14.2)
'''


def _make_course_mechanism_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _course_fallback_title(scene_plan, context)
    module = _clean_plan_text(scene_plan.get("module") or "Mechanism")
    if len(module) > 36:
        module = module[:33].rstrip(" ,.;:-") + "..."
    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    secondary = context.domain_state.get("secondary_color", "#F2C94C")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=30, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        module = Text({module!r}, font_size=19, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.22)

        labels = ["current", "rule", "next"]
        panels = VGroup()
        for idx, label in enumerate(labels):
            color = accent if idx != 2 else good
            panel = RoundedRectangle(width=2.55, height=1.18, corner_radius=0.1, stroke_color=color, stroke_width=2.5, fill_color=ManimColor("#111827"), fill_opacity=0.82)
            text = Text(label, font_size=24, color=fg, weight=BOLD).move_to(panel)
            panels.add(VGroup(panel, text))
        panels.arrange(RIGHT, buff=0.52).shift(UP * 0.25)

        arrows = VGroup(
            Arrow(panels[0].get_right(), panels[1].get_left(), color=secondary, stroke_width=4, buff=0.12),
            Arrow(panels[1].get_right(), panels[2].get_left(), color=secondary, stroke_width=4, buff=0.12),
        )
        token = Dot(color=secondary, radius=0.13).move_to(panels[0].get_center() + DOWN * 0.34)

        invariant = RoundedRectangle(width=7.4, height=0.64, corner_radius=0.1, stroke_color=good, stroke_width=2.5, fill_color=ManimColor("#052E16"), fill_opacity=0.72)
        invariant.shift(DOWN * 1.55)
        invariant_text = Text("invariant stays true while state changes", font_size=24, color=good, weight=BOLD)
        if invariant_text.width > 6.9:
            invariant_text.scale_to_fit_width(6.9)
        invariant_text.move_to(invariant)

        counter_line = NumberLine(x_range=[0, 4, 1], length=4.6, color=muted, include_numbers=False).to_edge(DOWN, buff=0.72)
        low_dot = Dot(color=accent, radius=0.09).move_to(counter_line.n2p(0))
        high_dot = Dot(color=good, radius=0.09).move_to(counter_line.n2p(4))
        scan = Dot(color=secondary, radius=0.1).move_to(counter_line.n2p(0))

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(module), run_time=0.8)
        self.play(LaggedStart(*[FadeIn(panel, shift=DOWN * 0.1) for panel in panels], lag_ratio=0.15), GrowFromCenter(token), run_time=1.1)
        self.play(Create(arrows[0]), token.animate.move_to(panels[1].get_center() + DOWN * 0.34), run_time=0.9)
        self.play(Create(invariant), FadeIn(invariant_text), Indicate(panels[1], color=secondary), run_time=1.0)
        self.play(Create(arrows[1]), token.animate.move_to(panels[2].get_center() + DOWN * 0.34), run_time=0.9)
        self.play(Create(counter_line), GrowFromCenter(low_dot), GrowFromCenter(high_dot), GrowFromCenter(scan), run_time=0.9)
        self.play(scan.animate.move_to(counter_line.n2p(2.5)), low_dot.animate.move_to(counter_line.n2p(1)), Indicate(invariant, color=good), run_time=1.1)
        self.play(Flash(token.get_center(), color=good, flash_radius=0.48, line_length=0.16), run_time=0.8)
        self.wait(14.4)
'''


def _make_course_compare_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _course_fallback_title(scene_plan, context)
    module = _clean_plan_text(scene_plan.get("module") or "Compare")
    if len(module) > 36:
        module = module[:33].rstrip(" ,.;:-") + "..."
    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    secondary = context.domain_state.get("secondary_color", "#F2C94C")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        bad = ManimColor("#EF4444")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=30, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        module = Text({module!r}, font_size=19, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.22)

        left = RoundedRectangle(width=3.35, height=2.05, corner_radius=0.12, stroke_color=bad, stroke_width=3, fill_color=ManimColor("#111827"), fill_opacity=0.82).shift(LEFT * 2.35 + DOWN * 0.15)
        right = RoundedRectangle(width=3.35, height=2.05, corner_radius=0.12, stroke_color=good, stroke_width=3, fill_color=ManimColor("#111827"), fill_opacity=0.82).shift(RIGHT * 2.35 + DOWN * 0.15)
        wrong_label = Text("near miss", font_size=24, color=bad, weight=BOLD).move_to(left.get_top() + DOWN * 0.42)
        right_label = Text("valid move", font_size=24, color=good, weight=BOLD).move_to(right.get_top() + DOWN * 0.42)

        wrong_path = VGroup(
            Line(left.get_left() + RIGHT * 0.55 + DOWN * 0.2, left.get_center() + RIGHT * 0.2 + UP * 0.25, color=bad, stroke_width=5),
            Line(left.get_center() + RIGHT * 0.2 + UP * 0.25, left.get_right() + LEFT * 0.55 + DOWN * 0.4, color=bad, stroke_width=5),
        )
        right_path = VGroup(
            Line(right.get_left() + RIGHT * 0.55 + DOWN * 0.35, right.get_center() + LEFT * 0.1, color=secondary, stroke_width=5),
            Line(right.get_center() + LEFT * 0.1, right.get_right() + LEFT * 0.55 + UP * 0.25, color=good, stroke_width=5),
        )
        fail = Text("X", font_size=42, color=bad, weight=BOLD).move_to(left.get_bottom() + UP * 0.44)
        ok = Text("OK", font_size=34, color=good, weight=BOLD).move_to(right.get_bottom() + UP * 0.44)

        bridge = Arrow(left.get_right() + RIGHT * 0.2, right.get_left() + LEFT * 0.2, color=accent, stroke_width=4, buff=0.12)
        repair = Text("repair the assumption", font_size=25, color=fg, weight=BOLD).next_to(bridge, UP, buff=0.25)
        if repair.width > 4.4:
            repair.scale_to_fit_width(4.4)

        plate = RoundedRectangle(width=6.4, height=0.78, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.88)
        plate.to_edge(DOWN, buff=0.42)
        takeaway = Text("compare, mark, then repair", font_size=27, color=fg, weight=BOLD).move_to(plate)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(module), run_time=0.8)
        self.play(FadeIn(left), FadeIn(right), FadeIn(wrong_label), FadeIn(right_label), run_time=0.9)
        self.play(LaggedStart(*[Create(line) for line in wrong_path], lag_ratio=0.15), run_time=0.9)
        self.play(Write(fail), Wiggle(left), run_time=0.9)
        self.play(Create(bridge), FadeIn(repair), run_time=0.8)
        self.play(LaggedStart(*[Create(line) for line in right_path], lag_ratio=0.15), run_time=0.9)
        self.play(Write(ok), Indicate(right, color=good), wrong_path.animate.set_opacity(0.35), run_time=1.0)
        self.play(FadeIn(plate), FadeIn(takeaway), Flash(ok.get_center(), color=good, flash_radius=0.48, line_length=0.16), run_time=0.9)
        self.wait(14.6)
'''


def _make_course_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Deterministic lesson scenelet for course-mode reliability."""
    return localize_scene_code(_make_course_fallback_scene_code_raw(scene_plan, context))


def _make_course_fallback_scene_code_raw(
    scene_plan: dict, context: NarrativeContext
) -> str:
    if scene_plan.get("type") == "question" or "question" in _clean_plan_text(scene_plan.get("scene_role")).lower():
        return _make_course_question_fallback_scene_code(scene_plan, context)

    title = _course_fallback_title(scene_plan, context)
    module = _clean_plan_text(scene_plan.get("module") or "Course Module")
    if len(module) > 36:
        module = module[:33].rstrip(" ,.;:-") + "..."
    role = _clean_plan_text(scene_plan.get("scene_role") or scene_plan.get("type")).lower()
    plan_text = " ".join(
        _clean_plan_text(scene_plan.get(key)).lower()
        for key in ("title", "description", "narration", "visual_description", "module", "scene_role")
    )
    if any(token in plan_text for token in ("map", "orientation", "recap", "summary", "takeaway", "synthesis")):
        return _make_course_map_fallback_scene_code(scene_plan, context)
    if any(token in plan_text for token in ("mechanism", "rule", "invariant", "state", "cost", "tradeoff", "complexity", "counter")):
        return _make_course_mechanism_fallback_scene_code(scene_plan, context)
    if any(token in plan_text for token in ("mistake", "edge", "boundary", "break", "repair", "non-example", "near miss", "wrong")):
        return _make_course_compare_fallback_scene_code(scene_plan, context)
    if "example" in role or "practice" in role:
        steps = ["set up toy case", "run the rule", "read the result"]
        objective = "practice turns the rule into a move"
    elif "definition" in role or "vocabulary" in role:
        steps = ["name the object", "attach the label", "test the definition"]
        objective = "attach a name, then test it"
    else:
        steps = ["build the anchor", "change one state", "keep the useful rule"]
        objective = "one lesson beat, one durable idea"

    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    secondary = context.domain_state.get("secondary_color", "#F2C94C")
    steps_literal = repr(steps)

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=30, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        module = Text({module!r}, font_size=19, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.22)

        rail = VGroup()
        for idx in range(4):
            dot = Circle(radius=0.11, stroke_color=accent, stroke_width=2, fill_color=accent if idx <= 1 else muted, fill_opacity=0.85 if idx <= 1 else 0.2)
            rail.add(dot)
        rail.arrange(RIGHT, buff=0.22).to_edge(LEFT, buff=0.78).shift(UP * 2.08)

        anchor = RoundedRectangle(width=3.0, height=2.1, corner_radius=0.14, stroke_color=accent, stroke_width=3, fill_color=ManimColor("#111827"), fill_opacity=0.82).shift(LEFT * 3.25 + DOWN * 0.15)
        anchor_label = Text("anchor visual", font_size=23, color=fg, weight=BOLD).move_to(anchor.get_center() + UP * 0.45)
        start_point = anchor.get_center() + DOWN * 0.25 + LEFT * 0.75
        end_point = anchor.get_center() + DOWN * 0.25 + RIGHT * 0.75
        state = Dot(color=secondary, radius=0.11).move_to(start_point)
        target = Dot(color=good, radius=0.11).move_to(end_point)
        path = Arrow(start_point, end_point, color=secondary, stroke_width=4, buff=0.12)
        practice_marker = Dot(color=accent, radius=0.08).move_to(start_point + UP * 0.36)

        steps = {steps_literal}
        cards = VGroup()
        for idx, label in enumerate(steps):
            card = RoundedRectangle(width=4.7, height=0.62, corner_radius=0.09, stroke_color=accent if idx < len(steps) - 1 else good, stroke_width=2.0, fill_color=ManimColor("#111827"), fill_opacity=0.82)
            text = Text(label, font_size=22, color=fg if idx < len(steps) - 1 else good, weight=BOLD)
            if text.width > 4.25:
                text.scale_to_fit_width(4.25)
            text.move_to(card)
            cards.add(VGroup(card, text))
        cards.arrange(DOWN, buff=0.22).shift(RIGHT * 2.15 + DOWN * 0.1)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(module), FadeIn(rail), run_time=0.8)
        self.play(FadeIn(anchor), FadeIn(anchor_label), GrowFromCenter(state), GrowFromCenter(target), run_time=0.9)
        self.play(Create(path), state.animate.move_to(target.get_center()), run_time=1.0)
        self.play(GrowFromCenter(practice_marker), run_time=0.4)
        self.play(practice_marker.animate.move_to(end_point + UP * 0.36), Indicate(target, color=good), run_time=0.9)
        self.play(LaggedStart(*[FadeIn(card, shift=LEFT * 0.10) for card in cards], lag_ratio=0.15), run_time=1.1)
        focus = SurroundingRectangle(cards[0], color=secondary, buff=0.07, stroke_width=3)
        self.play(Create(focus), Indicate(cards[0], color=secondary), run_time=0.8)
        next_focus = SurroundingRectangle(cards[-1], color=good, buff=0.07, stroke_width=3)
        self.play(Transform(focus, next_focus), cards[0].animate.set_opacity(0.55), Indicate(cards[-1], color=good), run_time=1.0)

        plate = RoundedRectangle(width=6.7, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.88)
        plate.to_edge(DOWN, buff=0.42)
        objective = Text({objective!r}, font_size=27, color=fg, weight=BOLD).move_to(plate)
        if objective.width > 6.2:
            objective.scale_to_fit_width(6.2)
            objective.move_to(plate)
        self.play(FadeIn(plate), FadeIn(objective), Flash(cards[-1].get_center(), color=good, flash_radius=0.5, line_length=0.16), run_time=0.9)
        self.wait(14.2)
'''
