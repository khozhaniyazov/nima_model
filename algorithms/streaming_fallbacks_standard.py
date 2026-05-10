"""Streaming standard-mode deterministic fallbacks.

Split out of ``algorithms/streaming_fallbacks.py`` (issue #65). This module
holds the standard-mode scene-code builders used when the LLM path fails and
we need to ship a valid Manim scene.

All functions are pure string synthesis — no LLM, subprocess, or I/O.
Callers reach these via ``algorithms.streaming_fallbacks`` (which re-exports
every name for back-compat) or via ``algorithms.streaming`` (the tests and
monkeypatch surface).

Module-load contract: true leaf module. Shared helpers are imported from
``streaming_fallbacks_core`` (never from the ``streaming_fallbacks`` shim,
which would create a cycle because the shim re-exports this module).
``algorithms.streaming`` is imported lazily inside the function bodies
where it's needed — nothing reaches ``streaming`` at module load time.
This leaf is safe to cold-import standalone.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from algorithms.i18n import localize_scene_code
from algorithms.streaming_fallbacks_core import (
    _clean_plan_text,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from algorithms.streaming import NarrativeContext


def _standard_fallback_title(scene_plan: dict) -> str:
    title = str(
        scene_plan.get("title")
        or scene_plan.get("description")
        or scene_plan.get("narration")
        or "Binary search cuts the problem"
    )
    title = _clean_plan_text(title) or "Binary search cuts the problem"
    if len(title) > 48:
        title = title[:45].rstrip(" ,.;:-") + "..."
    return title


def _make_standard_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Deterministic 16:9 fallback for standard-mode continuity.

    This is a provider safety net, not the preferred creative path. It rotates
    through distinct storyboards so a provider outage does not collapse a full
    standard video into repeated text changes.
    """
    scene_index = int(context.scene_index or 0)
    plan_text = " ".join(
        str(scene_plan.get(key) or "")
        for key in ("title", "description", "narration", "visual_description")
    ).lower()
    if "linear" in plan_text and any(token in plan_text for token in ("scan", "obvious", "one by one")):
        code = _make_standard_fallback_linear_scan_scene_code(scene_plan, context)
    elif any(token in plan_text for token in ("sorted", "order", "needs order")):
        code = _make_standard_fallback_sorted_order_scene_code(scene_plan, context)
    elif any(token in plan_text for token in ("payoff", "gap", "grow", "larger", "comparison count")):
        code = _make_standard_fallback_payoff_scene_code(scene_plan, context)
    elif any(token in plan_text for token in ("takeaway", "best use", "mental model", "end")):
        code = _make_standard_fallback_takeaway_scene_code(scene_plan, context)
    elif any(token in plan_text for token in ("race", "side by side", "together")):
        code = _make_standard_fallback_race_scene_code(scene_plan, context)
    elif any(token in plan_text for token in ("middle", "midpoint", "mechanism", "half")):
        code = _make_standard_fallback_window_scene_code(scene_plan, context)
    else:
        variant = scene_index % 3
        if variant == 1:
            code = _make_standard_fallback_race_scene_code(scene_plan, context)
        elif variant == 2:
            code = _make_standard_fallback_ladder_scene_code(scene_plan, context)
        else:
            code = _make_standard_fallback_window_scene_code(scene_plan, context)
    return localize_scene_code(code)


def _make_standard_fallback_window_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated shrinking-window fallback for standard-mode continuity."""
    title = _standard_fallback_title(scene_plan)
    scene_index = int(context.scene_index or 0)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")
    target_index = min(14, max(2, 11 + (scene_index % 3)))
    target_value = target_index + 1
    first_mid = 7
    second_left = 8 if target_index > first_mid else 0
    second_right = 15 if target_index > first_mid else 6
    second_mid = (second_left + second_right) // 2
    relation = "<" if first_mid < target_index else ">"
    direction = "keep right half" if target_index > first_mid else "keep left half"

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")
        danger = ManimColor("#EF4444")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        values = list(range(1, 17))
        cells = VGroup()
        for value in values:
            box = RoundedRectangle(
                width=0.58,
                height=0.62,
                corner_radius=0.08,
                stroke_color=muted,
                stroke_width=1.4,
                fill_color=ManimColor("#1F2937"),
                fill_opacity=0.92,
            )
            label = Text(str(value), font_size=24, color=fg, weight=BOLD).move_to(box)
            cells.add(VGroup(box, label))
        cells.arrange(RIGHT, buff=0.08).move_to(DOWN * 0.15)

        target = SurroundingRectangle(cells[{target_index}], color=good, buff=0.06, stroke_width=3)
        target_label = Text("target = {target_value}", font_size=24, color=good, weight=BOLD).next_to(target, DOWN, buff=0.25)

        window = SurroundingRectangle(VGroup(*[cells[i] for i in range(16)]), color=accent, buff=0.11, stroke_width=3)
        mid_marker = Triangle(fill_color=secondary, fill_opacity=1, stroke_color=secondary).scale(0.13).rotate(PI)
        mid_marker.next_to(cells[{first_mid}], UP, buff=0.18)
        mid_label = Text("mid = {first_mid + 1}", font_size=23, color=secondary, weight=BOLD).next_to(mid_marker, UP, buff=0.08)

        compare_plate = RoundedRectangle(width=4.8, height=0.75, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.8)
        compare_plate.next_to(cells, UP, buff=1.05)
        compare_text = Text("{first_mid + 1} {relation} {target_value}  ->  {direction}", font_size=27, color=fg, weight=BOLD)
        compare_text.move_to(compare_plate)
        compare_text.set_z_index(2)

        counter = Text("comparisons: 1    remaining: 16", font_size=24, color=muted)
        counter.next_to(cells, DOWN, buff=0.82)

        self.play(FadeIn(title, shift=DOWN * 0.15), LaggedStart(*[FadeIn(c, shift=UP * 0.05) for c in cells], lag_ratio=0.025), run_time=1.5)
        self.play(Create(window), FadeIn(target), FadeIn(target_label), run_time=0.8)
        self.play(FadeIn(mid_marker, shift=DOWN * 0.08), FadeIn(mid_label), FadeIn(compare_plate), FadeIn(compare_text), FadeIn(counter), run_time=0.9)
        self.play(Flash(cells[{first_mid}].get_center(), color=secondary, flash_radius=0.45, line_length=0.16), Indicate(cells[{first_mid}], color=secondary), run_time=0.9)

        discard = VGroup(*[cells[i] for i in range({second_left})]) if {target_index} > {first_mid} else VGroup(*[cells[i] for i in range({second_right + 1}, 16)])
        keep = VGroup(*[cells[i] for i in range({second_left}, {second_right + 1})])
        next_window = SurroundingRectangle(keep, color=accent, buff=0.11, stroke_width=3)
        next_marker = Triangle(fill_color=secondary, fill_opacity=1, stroke_color=secondary).scale(0.13).rotate(PI)
        next_marker.next_to(cells[{second_mid}], UP, buff=0.18)
        next_mid_label = Text("mid = {second_mid + 1}", font_size=23, color=secondary, weight=BOLD).next_to(next_marker, UP, buff=0.08)
        next_counter = Text("comparisons: 2    remaining: {second_right - second_left + 1}", font_size=24, color=muted).next_to(cells, DOWN, buff=0.82)

        self.play(discard.animate.set_opacity(0.25), Transform(window, next_window), Transform(mid_marker, next_marker), Transform(mid_label, next_mid_label), Transform(counter, next_counter), run_time=1.3)
        self.play(Indicate(keep, color=accent), run_time=0.8)

        payoff_plate = RoundedRectangle(width=5.6, height=1.0, corner_radius=0.14, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        payoff_plate.to_edge(DOWN, buff=0.42)
        payoff_plate.set_z_index(0)
        payoff = Text("One comparison deletes half the map", font_size=28, color=fg, weight=BOLD).move_to(payoff_plate)
        payoff.set_z_index(2)
        self.play(FadeOut(compare_plate), FadeIn(payoff_plate), Transform(compare_text, payoff), run_time=0.9)
        self.play(Flash(target, color=good, flash_radius=0.55, line_length=0.16), target.animate.set_stroke(width=5), run_time=0.9)
        self.wait(7.5)
'''


def _make_standard_fallback_linear_scan_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated linear-scan fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        row = VGroup()
        for value in range(1, 17):
            box = RoundedRectangle(width=0.55, height=0.58, corner_radius=0.07, stroke_color=muted, stroke_width=1.3, fill_color=ManimColor("#1F2937"), fill_opacity=0.92)
            label = Text(str(value), font_size=22, color=fg, weight=BOLD).move_to(box)
            row.add(VGroup(box, label))
        row.arrange(RIGHT, buff=0.065).move_to(UP * 0.15)

        marker = Triangle(fill_color=secondary, fill_opacity=1, stroke_color=secondary).scale(0.13).rotate(PI)
        marker.next_to(row[0], UP, buff=0.18)
        target = SurroundingRectangle(row[11], color=good, buff=0.06, stroke_width=3)
        counter = Text("comparisons: 1", font_size=27, color=accent, weight=BOLD).next_to(row, DOWN, buff=0.45)
        rule = Text("linear search earns certainty one cell at a time", font_size=28, color=fg, weight=BOLD)
        if rule.width > 9.8:
            rule.scale_to_fit_width(9.8)
        rule.next_to(title, DOWN, buff=0.35)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(rule), FadeIn(row), run_time=1.0)
        self.play(FadeIn(marker), FadeIn(counter), FadeIn(target), run_time=0.7)
        scanned_a = VGroup(*[row[i] for i in range(0, 4)])
        counter_a = Text("comparisons: 4", font_size=27, color=accent, weight=BOLD).move_to(counter)
        self.play(marker.animate.next_to(row[3], UP, buff=0.18), scanned_a.animate.set_opacity(0.35), Transform(counter, counter_a), run_time=1.0)
        scanned_b = VGroup(*[row[i] for i in range(4, 8)])
        counter_b = Text("comparisons: 8", font_size=27, color=accent, weight=BOLD).move_to(counter)
        self.play(marker.animate.next_to(row[7], UP, buff=0.18), scanned_b.animate.set_opacity(0.35), Transform(counter, counter_b), run_time=1.0)
        scanned_c = VGroup(*[row[i] for i in range(8, 12)])
        counter_c = Text("comparisons: 12", font_size=27, color=good, weight=BOLD).move_to(counter)
        self.play(marker.animate.next_to(row[11], UP, buff=0.18), scanned_c.animate.set_opacity(0.55), Transform(counter, counter_c), target.animate.set_stroke(width=5), run_time=1.0)

        plate = RoundedRectangle(width=6.9, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        plate.to_edge(DOWN, buff=0.42)
        payoff = Text("easy to trust, expensive to repeat", font_size=28, color=fg, weight=BOLD).move_to(plate)
        self.play(FadeIn(plate), FadeIn(payoff), Flash(target, color=good, flash_radius=0.55, line_length=0.16), run_time=1.0)
        self.wait(9.0)
'''


def _make_standard_fallback_sorted_order_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated sorted-order requirement fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")
        danger = ManimColor("#EF4444")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        def make_row(values, fill):
            row = VGroup()
            for value in values:
                box = RoundedRectangle(width=0.52, height=0.54, corner_radius=0.07, stroke_color=muted, stroke_width=1.2, fill_color=ManimColor(fill), fill_opacity=0.92)
                label = Text(str(value), font_size=20, color=fg, weight=BOLD).move_to(box)
                row.add(VGroup(box, label))
            row.arrange(RIGHT, buff=0.055)
            return row

        unsorted = make_row([8, 1, 13, 4, 10, 2, 16, 7, 3, 12, 5, 15, 6, 11, 9, 14], "#1F2937").scale(0.92).shift(UP * 0.72)
        sorted_row = make_row(list(range(1, 17)), "#111827").scale(0.92).shift(DOWN * 0.88)
        top_label = Text("unsorted: no safe half", font_size=23, color=danger, weight=BOLD).next_to(unsorted, UP, buff=0.16)
        bottom_label = Text("sorted: halves mean something", font_size=23, color=secondary, weight=BOLD).next_to(sorted_row, UP, buff=0.16)

        slash = Cross(unsorted, stroke_color=danger, stroke_width=5)
        window = SurroundingRectangle(VGroup(*[sorted_row[i] for i in range(8, 16)]), color=accent, buff=0.10, stroke_width=3)
        mid = SurroundingRectangle(sorted_row[7], color=secondary, buff=0.06, stroke_width=3)
        target = SurroundingRectangle(sorted_row[11], color=good, buff=0.06, stroke_width=3)

        rule = Text("binary search buys speed with order", font_size=29, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.35)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(rule), run_time=0.8)
        self.play(FadeIn(top_label), FadeIn(unsorted), run_time=0.8)
        self.play(Wiggle(unsorted), Create(slash), run_time=0.9)
        self.play(FadeIn(bottom_label), FadeIn(sorted_row), run_time=0.8)
        self.play(Create(mid), Flash(sorted_row[7].get_center(), color=secondary, flash_radius=0.42, line_length=0.15), run_time=0.8)
        self.play(Create(window), FadeOut(slash), unsorted.animate.set_opacity(0.22), run_time=1.0)
        self.play(Create(target), Indicate(VGroup(*[sorted_row[i] for i in range(8, 16)]), color=accent), run_time=0.9)

        plate = RoundedRectangle(width=6.6, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        plate.to_edge(DOWN, buff=0.42)
        payoff = Text("without order, the jump is a guess", font_size=28, color=fg, weight=BOLD).move_to(plate)
        self.play(FadeIn(plate), FadeIn(payoff), run_time=0.8)
        self.wait(9.2)
'''


def _make_standard_fallback_payoff_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated comparison-count payoff fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        danger = ManimColor("#EF4444")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)
        note = Text("the gap gets bigger as the list grows", font_size=28, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.30)

        labels = ["16", "64", "1024"]
        linear = [16, 64, 1024]
        binary = [4, 6, 10]
        groups = VGroup()
        for idx, label in enumerate(labels):
            base = LEFT * 3.1 + RIGHT * (idx * 3.1) + DOWN * 1.2
            x_label = Text("n=" + label, font_size=23, color=muted).move_to(base + DOWN * 0.45)
            lin_bar = Rectangle(width=0.42, height=2.45, stroke_width=0, fill_color=danger, fill_opacity=0.85).move_to(base + LEFT * 0.25 + UP * 0.05)
            bin_bar = Rectangle(width=0.42, height=0.45 + idx * 0.20, stroke_width=0, fill_color=secondary, fill_opacity=0.92).align_to(lin_bar, DOWN).shift(RIGHT * 0.55)
            lin_count = Text(str(linear[idx]), font_size=22, color=danger, weight=BOLD).next_to(lin_bar, UP, buff=0.08)
            bin_count = Text(str(binary[idx]), font_size=22, color=secondary, weight=BOLD).next_to(bin_bar, UP, buff=0.08)
            groups.add(VGroup(lin_bar, bin_bar, lin_count, bin_count, x_label))

        legend = VGroup(
            Text("linear checks", font_size=23, color=danger, weight=BOLD),
            Text("binary checks", font_size=23, color=secondary, weight=BOLD),
        ).arrange(RIGHT, buff=0.55).to_edge(DOWN, buff=0.45)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(note), run_time=0.8)
        for idx, group in enumerate(groups):
            self.play(GrowFromEdge(group[0], DOWN), GrowFromEdge(group[1], DOWN), FadeIn(group[2]), FadeIn(group[3]), FadeIn(group[4]), run_time=0.75)
        self.play(FadeIn(legend), run_time=0.5)
        self.play(Indicate(groups[-1][1], color=good), Flash(groups[-1][1].get_top(), color=good, flash_radius=0.5, line_length=0.16), run_time=0.9)

        plate = RoundedRectangle(width=6.8, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        plate.next_to(note, DOWN, buff=0.35)
        payoff = Text("cutting beats counting", font_size=29, color=fg, weight=BOLD).move_to(plate)
        self.play(FadeIn(plate), FadeIn(payoff), run_time=0.8)
        self.wait(11.0)
'''


def _make_standard_fallback_takeaway_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated decision-rule takeaway fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        question = RoundedRectangle(width=3.9, height=1.0, corner_radius=0.12, stroke_color=accent, stroke_width=3, fill_color=ManimColor("#1F2937"), fill_opacity=0.92)
        q_text = Text("is the data sorted?", font_size=25, color=fg, weight=BOLD).move_to(question)
        question_group = VGroup(question, q_text).shift(UP * 1.15)

        yes = RoundedRectangle(width=3.2, height=0.92, corner_radius=0.12, stroke_color=good, stroke_width=3, fill_color=ManimColor("#064E3B"), fill_opacity=0.86)
        yes_text = Text("use binary search", font_size=23, color=good, weight=BOLD).move_to(yes)
        yes_group = VGroup(yes, yes_text).shift(LEFT * 2.35 + DOWN * 0.45)

        no = RoundedRectangle(width=3.2, height=0.92, corner_radius=0.12, stroke_color=secondary, stroke_width=3, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        no_text = Text("linear still works", font_size=23, color=secondary, weight=BOLD).move_to(no)
        no_group = VGroup(no, no_text).shift(RIGHT * 2.35 + DOWN * 0.45)

        yes_arrow = Arrow(question_group.get_bottom(), yes_group.get_top(), color=good, buff=0.10, stroke_width=4)
        no_arrow = Arrow(question_group.get_bottom(), no_group.get_top(), color=secondary, buff=0.10, stroke_width=4)
        yes_label = Text("yes", font_size=22, color=good, weight=BOLD).next_to(yes_arrow, LEFT, buff=0.08)
        no_label = Text("no", font_size=22, color=secondary, weight=BOLD).next_to(no_arrow, RIGHT, buff=0.08)

        bottom = Text("same problem, different promise", font_size=29, color=accent, weight=BOLD)
        bottom.to_edge(DOWN, buff=0.55)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(question_group), run_time=0.8)
        self.play(Create(yes_arrow), Create(no_arrow), FadeIn(yes_label), FadeIn(no_label), run_time=0.8)
        self.play(FadeIn(yes_group, shift=UP * 0.12), FadeIn(no_group, shift=UP * 0.12), run_time=0.8)
        self.play(Indicate(yes_group, color=good), Indicate(no_group, color=secondary), run_time=0.9)
        self.play(FadeIn(bottom), run_time=0.7)
        self.play(question_group.animate.scale(1.04), rate_func=there_and_back, run_time=0.8)
        self.wait(9.6)
'''


def _make_standard_fallback_race_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated linear-vs-binary race fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    scene_index = int(context.scene_index or 0)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")
    target_index = min(14, max(8, 10 + (scene_index % 5)))
    target_value = target_index + 1

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")
        danger = ManimColor("#EF4444")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        values = list(range(1, 17))
        target_index = {target_index}
        target_value = {target_value}

        def make_row(fill_color):
            row = VGroup()
            for value in values:
                box = RoundedRectangle(
                    width=0.52,
                    height=0.52,
                    corner_radius=0.07,
                    stroke_color=muted,
                    stroke_width=1.2,
                    fill_color=ManimColor(fill_color),
                    fill_opacity=0.94,
                )
                label = Text(str(value), font_size=20, color=fg, weight=BOLD).move_to(box)
                row.add(VGroup(box, label))
            row.arrange(RIGHT, buff=0.055)
            return row

        linear_cells = make_row("#1F2937").shift(UP * 0.72 + RIGHT * 0.45)
        binary_cells = make_row("#111827").shift(DOWN * 0.85 + RIGHT * 0.45)
        linear_label = Text("linear scan", font_size=24, color=muted, weight=BOLD).next_to(linear_cells, LEFT, buff=0.35)
        binary_label = Text("binary split", font_size=24, color=secondary, weight=BOLD).next_to(binary_cells, LEFT, buff=0.35)

        target_box = SurroundingRectangle(linear_cells[target_index], color=good, buff=0.055, stroke_width=3)
        target_text = Text("target = " + str(target_value), font_size=25, color=good, weight=BOLD).to_edge(DOWN, buff=0.43)

        scan_marker = Triangle(fill_color=danger, fill_opacity=1, stroke_color=danger).scale(0.12).rotate(PI)
        scan_marker.next_to(linear_cells[0], UP, buff=0.16)
        jump_marker = Triangle(fill_color=secondary, fill_opacity=1, stroke_color=secondary).scale(0.12).rotate(PI)
        jump_marker.next_to(binary_cells[7], UP, buff=0.16)

        binary_window = SurroundingRectangle(binary_cells, color=accent, buff=0.10, stroke_width=3)
        right_keep = VGroup(*[binary_cells[i] for i in range(8, 16)])
        narrow_window = SurroundingRectangle(right_keep, color=accent, buff=0.10, stroke_width=3)
        second_marker = Triangle(fill_color=secondary, fill_opacity=1, stroke_color=secondary).scale(0.12).rotate(PI)
        second_marker.next_to(binary_cells[11], UP, buff=0.16)

        verdict_plate = RoundedRectangle(width=6.4, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.84)
        verdict_plate.next_to(title, DOWN, buff=0.32)
        verdict = Text("same target, different tempo", font_size=27, color=fg, weight=BOLD).move_to(verdict_plate)

        self.play(FadeIn(title, shift=DOWN * 0.15), FadeIn(verdict_plate), FadeIn(verdict), run_time=0.9)
        self.play(FadeIn(linear_label), FadeIn(binary_label), FadeIn(linear_cells), FadeIn(binary_cells), run_time=1.0)
        self.play(FadeIn(scan_marker), FadeIn(jump_marker), Create(binary_window), FadeIn(target_box), FadeIn(target_text), run_time=0.9)

        linear_scanned = VGroup(*[linear_cells[i] for i in range(target_index + 1)])
        self.play(
            scan_marker.animate.next_to(linear_cells[target_index], UP, buff=0.16),
            linear_scanned.animate.set_opacity(0.42),
            Transform(binary_window, narrow_window),
            Transform(jump_marker, second_marker),
            run_time=1.45,
        )
        self.play(Indicate(right_keep, color=accent), Flash(binary_cells[11].get_center(), color=secondary, flash_radius=0.45, line_length=0.16), run_time=0.85)

        binary_win = Text("binary: 4 jumps", font_size=28, color=secondary, weight=BOLD)
        linear_cost = Text("linear: " + str(target_value) + " checks", font_size=28, color=danger, weight=BOLD)
        result = VGroup(binary_win, linear_cost).arrange(RIGHT, buff=0.55).next_to(binary_cells, DOWN, buff=0.55)
        self.play(Transform(verdict, binary_win.copy().move_to(verdict)), FadeIn(result), run_time=0.9)
        self.play(Flash(target_box, color=good, flash_radius=0.55, line_length=0.16), target_box.animate.set_stroke(width=5), run_time=0.9)
        self.wait(8.2)
'''


def _make_standard_fallback_ladder_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated decision-ladder fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        note = Text("every question halves the uncertainty", font_size=27, color=accent, weight=BOLD)
        note.next_to(title, DOWN, buff=0.26)

        labels = ["16 candidates", "8 remain", "4 remain", "2 remain", "1 answer"]
        levels = VGroup()
        for idx, label in enumerate(labels):
            fill = "#1F2937" if idx < len(labels) - 1 else "#064E3B"
            stroke = accent if idx < len(labels) - 1 else good
            plate = RoundedRectangle(
                width=3.0,
                height=0.58,
                corner_radius=0.09,
                stroke_color=stroke,
                stroke_width=2.2,
                fill_color=ManimColor(fill),
                fill_opacity=0.94,
            )
            text = Text(label, font_size=23, color=fg if idx < len(labels) - 1 else good, weight=BOLD).move_to(plate)
            levels.add(VGroup(plate, text))
        levels.arrange(DOWN, buff=0.20).shift(RIGHT * 2.15 + DOWN * 0.18)

        arrows = VGroup()
        for idx in range(len(levels) - 1):
            arrows.add(Arrow(levels[idx].get_bottom(), levels[idx + 1].get_top(), buff=0.05, color=secondary, stroke_width=3))

        left_panel = VGroup(
            Text("bad version:", font_size=25, color=muted, weight=BOLD),
            Text("check one item", font_size=23, color=muted),
            Text("then another", font_size=23, color=muted),
            Text("then another...", font_size=23, color=muted),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.18)
        left_panel.shift(LEFT * 3.25 + DOWN * 0.08)

        fast_panel = VGroup(
            Text("good version:", font_size=25, color=secondary, weight=BOLD),
            Text("ask the midpoint", font_size=23, color=fg),
            Text("throw away half", font_size=23, color=fg),
            Text("repeat with focus", font_size=23, color=fg),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.18)
        fast_panel.next_to(left_panel, DOWN, buff=0.56, aligned_edge=LEFT)

        formula_plate = RoundedRectangle(width=5.6, height=0.78, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        formula_plate.to_edge(DOWN, buff=0.42)
        formula = Text("16 items need only 4 clean cuts", font_size=28, color=fg, weight=BOLD).move_to(formula_plate)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(note), run_time=0.8)
        self.play(FadeIn(left_panel, shift=RIGHT * 0.12), run_time=0.8)
        self.play(FadeIn(fast_panel, shift=RIGHT * 0.12), run_time=0.8)
        self.play(LaggedStart(*[FadeIn(level) for level in levels], lag_ratio=0.14), run_time=1.2)
        self.play(LaggedStart(*[Create(arrow) for arrow in arrows], lag_ratio=0.18), run_time=0.9)
        self.play(Indicate(levels[-1], color=good), FadeIn(formula_plate), FadeIn(formula), run_time=1.0)
        earlier_levels = VGroup(*[levels[i] for i in range(len(levels) - 1)])
        self.play(earlier_levels.animate.set_opacity(0.55), levels[-1].animate.scale(1.08), run_time=0.8)
        self.wait(8.4)
'''
