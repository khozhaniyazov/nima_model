"""Deterministic fallback scene generators for ``algorithms.streaming`` (#11).

Extracted from ``algorithms/streaming.py`` to keep the streaming orchestrator
below ~5000 LoC and to give the mode-specific "if the provider fails, render
something sensible" code a home of its own.

Every function here is pure Python string synthesis — no LLM calls, no
subprocesses, no file I/O. They all emit a Manim ``class GeneratedScene``
source string suitable for ``_render_single_scene``.

Module-load contract:

- This module is a leaf: it MUST NOT import from ``algorithms.streaming`` at
  module load time, because ``streaming`` imports this module during its own
  load. Any helper that lives in ``streaming`` (``_clean_plan_text`` today)
  is imported lazily inside the functions that need it.
- Type hints use ``from __future__ import annotations`` so references to
  ``NarrativeContext`` remain string-form and never trigger a runtime lookup.

The public ``algorithms.streaming`` module re-exports every name defined
here for backward compatibility; tests that reach into
``streaming._make_short_fallback_scene_code`` etc. continue to work.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from algorithms.i18n import localize_scene_code

if TYPE_CHECKING:  # pragma: no cover - typing only
    from algorithms.streaming import NarrativeContext


# Lazy-imported from algorithms.streaming at call time; see module docstring.
def _clean_plan_text(value):  # type: ignore[override]
    from algorithms.streaming import _clean_plan_text as _impl

    return _impl(value)


def _safe_text_literal(value: str, max_chars: int = 44) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars].rsplit(" ", 1)[0].strip()
    return cut or cleaned[:max_chars].strip()


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


def _short_fallback_lines(scene_plan: dict, context: NarrativeContext) -> list[str]:
    prompt = (context.prompt or "").lower()
    scene_desc = scene_plan.get("description") or scene_plan.get("narration") or ""
    scene_num = max(0, int(context.scene_index or 0))
    final_short_scene = _is_final_short_scene(scene_plan, context)

    if "bayes" in prompt or "false positive" in prompt:
        if final_short_scene:
            return ["Your turn", "false alarms double", "does 8% go up?"]
        variants = [
            ["1,000 tested", "10 sick", "990 healthy"],
            ["Positive tests mix", "9 true positives", "99 false alarms"],
            ["Result", "9 / 108", "about 8%"],
            ["Bayes asks", "sick among positives", "part / whole"],
        ]
        return variants[min(scene_num, len(variants) - 1)]

    if "dijkstra" in prompt:
        if final_short_scene:
            return ["Your turn", "which node is next?", "smallest distance wins"]
        variants = [
            ["Start at A", "distance A = 0", "others = infinity"],
            ["Pick smallest", "relax neighbors", "keep shorter paths"],
            ["A to C costs 2", "C to D costs 3", "total path = 5"],
            ["Final path", "settled nodes stay", "best distance wins"],
        ]
        return variants[min(scene_num, len(variants) - 1)]

    numbers = [int(match) for match in re.findall(r"\b\d{2,4}\b", context.prompt or "")]
    if ("factor" in prompt or "prime" in prompt) and numbers:
        if final_short_scene:
            target = numbers[-1]
            return ["Your turn", f"factor {target}", "which primes appear?"]
        first = numbers[0]
        second = numbers[1] if len(numbers) > 1 else numbers[0]
        variants = [
            [
                f"{first} = {_factorization_line(first)}",
                f"{second} = {_factorization_line(second)}",
                "prime pieces only",
            ],
            [
                "order can change",
                "prime pieces stay",
                "counts stay fixed",
            ],
            [
                f"{first}: {_factorization_line(first).replace(' x ', ', ')}",
                f"{second}: {_factorization_line(second).replace(' x ', ', ')}",
                "unique prime list",
            ],
            [
                "one prime recipe",
                "same counts",
                "order does not matter",
            ],
        ]
        return variants[min(scene_num, len(variants) - 1)]

    sentences = re.split(r"(?<=[.!?])\s+", scene_desc)
    lines = [_safe_text_literal(sentence, 34) for sentence in sentences if sentence.strip()]
    return (lines or [_safe_text_literal(context.prompt or "Key idea", 34)])[:3]


def _short_fallback_title(scene_plan: dict, context: NarrativeContext) -> str:
    if _is_final_short_scene(scene_plan, context):
        return "Your turn"

    prompt = (context.prompt or "").lower()
    if "bayes" in prompt or "false positive" in prompt:
        return "Bayes theorem"
    if "dijkstra" in prompt:
        return "Dijkstra path"
    if "factor" in prompt or "prime" in prompt:
        return "Prime factors"

    title = scene_plan.get("title") or context.prompt or scene_plan.get("description") or "Key idea"
    return _safe_text_literal(title, 22)


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


def _make_short_dijkstra_scene_code(
    scene_plan: dict,
    context: NarrativeContext,
    *,
    title: str,
    bg: str,
    fg: str,
    accent: str,
    warm: str,
) -> str:
    scene_index = int(context.scene_index or 0)
    final_scene = _is_final_short_scene(scene_plan, context)
    caption = "which node is next?" if final_scene else _short_fallback_lines(scene_plan, context)[0]
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        muted = ManimColor("#6B7280")
        title = Text({"Your turn" if final_scene else title!r}, font_size=38, color=fg, weight=BOLD)
        if title.width > 5.7:
            title.scale(5.7 / title.width)
        title.to_edge(UP, buff=0.82)
        caption = Text({caption!r}, font_size=28, color=warm if {final_scene!r} else fg)
        if caption.width > 5.6:
            caption.scale(5.6 / caption.width)
        caption.next_to(title, DOWN, buff=0.22)

        pos = {{
            "A": LEFT * 2.15 + UP * 1.55,
            "B": RIGHT * 1.35 + UP * 1.85,
            "C": LEFT * 1.45 + DOWN * 1.35,
            "D": RIGHT * 2.0 + DOWN * 1.05,
        }}
        weights = [("A", "B", "2"), ("A", "C", "5"), ("B", "C", "1"), ("B", "D", "4"), ("C", "D", "2")]
        edges = VGroup()
        edge_lookup = {{}}
        weight_labels = VGroup()
        for a, b, w in weights:
            line = Line(pos[a], pos[b], color=muted, stroke_width=4)
            edge_lookup[(a, b)] = line
            edge_lookup[(b, a)] = line
            label = Text(w, font_size=23, color=fg)
            label.move_to((pos[a] + pos[b]) / 2)
            label.set_z_index(5)
            weight_labels.add(label)
            edges.add(line)

        def node(label):
            circle = Circle(radius=0.34, stroke_color=accent, stroke_width=4, fill_color=ManimColor("#111824"), fill_opacity=0.95)
            circle.move_to(pos[label])
            text = Text(label, font_size=27, color=fg, weight=BOLD).move_to(circle)
            group = VGroup(circle, text)
            group.set_z_index(10)
            return group

        nodes = VGroup(node("A"), node("B"), node("C"), node("D"))
        dist = VGroup(
            Text("d(A)=0", font_size=24, color=warm),
            Text("d(B)=2", font_size=24, color=warm),
            Text("d(C)=3", font_size=24, color=warm),
            Text("d(D)=6", font_size=24, color=warm),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.16)
        dist.to_edge(DOWN, buff=0.78)
        dist_box = SurroundingRectangle(dist, color=accent, buff=0.2, corner_radius=0.12)

        self.play(FadeIn(title, shift=DOWN * 0.2), FadeIn(caption, shift=DOWN * 0.15), run_time=0.55)
        self.play(Create(edges), LaggedStart(*[GrowFromCenter(n) for n in nodes], lag_ratio=0.12), FadeIn(weight_labels), run_time=1.2)

        scene_index = {scene_index}
        if scene_index == 0:
            pulse_path = [("A", "B"), ("A", "C")]
            note = Text("start at A", font_size=30, color=warm).next_to(nodes[0], LEFT, buff=0.2)
            self.play(Indicate(nodes[0], color=warm), FadeIn(note), run_time=0.9)
        elif scene_index == 1:
            pulse_path = [("A", "B"), ("B", "C")]
            note = Text("relax neighbors", font_size=30, color=warm).move_to(DOWN * 2.75)
            self.play(FadeIn(note, shift=UP * 0.2), run_time=0.35)
        elif scene_index == 2:
            pulse_path = [("A", "B"), ("B", "D")]
            note = Text("best path so far", font_size=30, color=warm).move_to(DOWN * 2.75)
            self.play(FadeIn(note, shift=UP * 0.2), run_time=0.35)
        else:
            pulse_path = [("A", "B"), ("B", "C"), ("C", "D")]
            note = Text("smallest distance wins", font_size=29, color=warm).move_to(DOWN * 2.75)
            self.play(FadeIn(note, shift=UP * 0.2), run_time=0.35)

        for a, b in pulse_path:
            line = edge_lookup[(a, b)]
            glow = line.copy().set_color(warm).set_stroke(width=9, opacity=0.85)
            traveler = Dot(color=warm, radius=0.08).move_to(line.get_start())
            self.play(ShowPassingFlash(glow, time_width=0.5), MoveAlongPath(traveler, line), run_time=0.85)
            self.remove(traveler)
            line.set_color(warm)
            line.set_stroke(width=6)
        self.play(FadeIn(dist_box), LaggedStart(*[FadeIn(d, shift=RIGHT * 0.2) for d in dist], lag_ratio=0.1), run_time=0.8)
        self.play(Indicate(dist[min(scene_index, 3)], color=warm), run_time=0.8)
        self.play(Indicate(note, color=warm), run_time=0.75)
        self.wait(2.5)
"""


def _make_short_binary_search_scene_code(
    scene_plan: dict,
    context: NarrativeContext,
    *,
    title: str,
    bg: str,
    fg: str,
    accent: str,
    warm: str,
) -> str:
    scene_index = int(context.scene_index or 0)
    final_scene = _is_final_short_scene(scene_plan, context)
    headline = "Your turn" if final_scene else "Binary search"
    note = "which half survives?" if final_scene else _short_fallback_lines(scene_plan, context)[0]
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        title = Text({headline!r}, font_size=38, color=fg, weight=BOLD).to_edge(UP, buff=0.82)
        subtitle = Text({note!r}, font_size=27, color=warm if {final_scene!r} else fg)
        if subtitle.width > 5.6:
            subtitle.scale(5.6 / subtitle.width)
        subtitle.next_to(title, DOWN, buff=0.25)
        values = [1, 3, 5, 7, 9, 11, 13, 15]
        cells = VGroup()
        for value in values:
            box = RoundedRectangle(width=1.25, height=0.9, corner_radius=0.1, stroke_color=accent, stroke_width=3, fill_color=ManimColor("#111824"), fill_opacity=0.82)
            label = Text(str(value), font_size=28, color=fg, weight=BOLD).move_to(box)
            cells.add(VGroup(box, label))
        cells.arrange_in_grid(rows=2, cols=4, buff=0.22).move_to(DOWN * 0.05)
        target = Text("target = 7", font_size=31, color=warm).next_to(subtitle, DOWN, buff=0.42)
        pointer = Triangle(color=warm, fill_color=warm, fill_opacity=1).scale(0.17).rotate(PI)
        pointer.next_to(cells[3], UP, buff=0.16)
        window = SurroundingRectangle(cells, color=warm, buff=0.14, corner_radius=0.12)
        low_high = Text("low ........ high", font_size=24, color=fg).next_to(cells, DOWN, buff=0.42)

        self.play(FadeIn(title, shift=DOWN * 0.2), FadeIn(subtitle), FadeIn(target), run_time=0.55)
        self.play(LaggedStart(*[GrowFromCenter(cell) for cell in cells], lag_ratio=0.06), Create(window), FadeIn(low_high), run_time=1.2)
        scene_index = {scene_index}
        steps = [
            (3, 0, 7, "mid = 7"),
            (5, 4, 7, "7 is left of 11"),
            (3, 0, 3, "match found"),
            (2, 0, 3, "try the next mid"),
        ]
        mid, lo, hi, label = steps[min(scene_index, len(steps) - 1)]
        new_window = SurroundingRectangle(VGroup(*[cells[i] for i in range(lo, hi + 1)]), color=warm, buff=0.14, corner_radius=0.12)
        mid_label = Text(label, font_size=30, color=warm).to_edge(DOWN, buff=0.82)
        self.play(Transform(window, new_window), pointer.animate.next_to(cells[mid], UP, buff=0.16), FadeIn(mid_label, shift=UP * 0.25), run_time=1.0)
        self.play(cells[mid][0].animate.set_fill(warm, opacity=0.35), Indicate(cells[mid], color=warm), run_time=0.85)
        faded = [cells[i] for i in range(len(cells)) if i < lo or i > hi]
        if faded:
            self.play(*[cell.animate.set_opacity(0.25) for cell in faded], run_time=0.55)
        self.play(pointer.animate.shift(DOWN * 0.12), rate_func=there_and_back, run_time=0.75)
        self.play(Indicate(mid_label, color=warm), run_time=0.75)
        self.wait(2.6)
"""


def _make_short_molecule_scene_code(
    scene_plan: dict,
    context: NarrativeContext,
    *,
    title: str,
    bg: str,
    fg: str,
    accent: str,
    warm: str,
) -> str:
    scene_index = int(context.scene_index or 0)
    final_scene = _is_final_short_scene(scene_plan, context)
    caption = "which bond changes first?" if final_scene else _short_fallback_lines(scene_plan, context)[0]
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        title = Text({"Your turn" if final_scene else title!r}, font_size=37, color=fg, weight=BOLD).to_edge(UP, buff=0.82)
        caption = Text({caption!r}, font_size=27, color=warm if {final_scene!r} else fg)
        if caption.width > 5.6:
            caption.scale(5.6 / caption.width)
        caption.next_to(title, DOWN, buff=0.24)

        center = ORIGIN + DOWN * 0.25
        atom_specs = [
            ("C", center, 0.46, accent),
            ("O", center + LEFT * 1.75 + UP * 0.95, 0.38, warm),
            ("O", center + RIGHT * 1.75 + UP * 0.95, 0.38, warm),
            ("H", center + LEFT * 1.8 + DOWN * 1.05, 0.31, fg),
            ("H", center + RIGHT * 1.8 + DOWN * 1.05, 0.31, fg),
        ]
        atoms = VGroup()
        for label, pos, radius, color in atom_specs:
            circle = Circle(radius=radius, stroke_color=color, stroke_width=4, fill_color=color, fill_opacity=0.18).move_to(pos)
            text = Text(label, font_size=24, color=fg, weight=BOLD).move_to(circle)
            atoms.add(VGroup(circle, text))
        bonds = VGroup(
            Line(atom_specs[0][1], atom_specs[1][1], color=fg, stroke_width=7),
            Line(atom_specs[0][1], atom_specs[2][1], color=fg, stroke_width=7),
            Line(atom_specs[0][1], atom_specs[3][1], color=fg, stroke_width=5),
            Line(atom_specs[0][1], atom_specs[4][1], color=fg, stroke_width=5),
        )
        molecule = VGroup(bonds, atoms)
        label = Text("bonds store shape", font_size=29, color=warm).to_edge(DOWN, buff=0.84)
        scene_index = {scene_index}
        self.play(FadeIn(title, shift=DOWN * 0.2), FadeIn(caption), run_time=0.5)
        self.play(LaggedStart(*[GrowFromCenter(atom) for atom in atoms], lag_ratio=0.12), run_time=1.0)
        self.play(LaggedStart(*[Create(bond) for bond in bonds], lag_ratio=0.12), FadeIn(label, shift=UP * 0.2), run_time=1.1)
        if scene_index == 0:
            self.play(molecule.animate.rotate(PI / 10), rate_func=there_and_back, run_time=1.2)
        elif scene_index == 1:
            self.play(Indicate(bonds[0], color=warm), Indicate(bonds[1], color=warm), run_time=1.0)
        elif scene_index == 2:
            electron = Dot(color=warm, radius=0.08).move_to(bonds[0].get_start())
            self.play(MoveAlongPath(electron, bonds[0]), MoveAlongPath(Dot(color=warm, radius=0.08).move_to(bonds[1].get_start()), bonds[1]), run_time=1.2)
        else:
            self.play(molecule.animate.scale(1.08), Indicate(label, color=warm), rate_func=there_and_back, run_time=1.1)
        self.play(molecule.animate.rotate(-PI / 12), rate_func=there_and_back, run_time=1.05)
        self.play(Indicate(label, color=warm), run_time=0.75)
        self.wait(2.4)
"""


def _make_short_car_scene_code(
    scene_plan: dict,
    context: NarrativeContext,
    *,
    title: str,
    bg: str,
    fg: str,
    accent: str,
    warm: str,
) -> str:
    scene_index = int(context.scene_index or 0)
    final_scene = _is_final_short_scene(scene_plan, context)
    caption = "what changes after impact?" if final_scene else _short_fallback_lines(scene_plan, context)[0]
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        title = Text({"Your turn" if final_scene else title!r}, font_size=37, color=fg, weight=BOLD).to_edge(UP, buff=0.82)
        caption = Text({caption!r}, font_size=27, color=warm if {final_scene!r} else fg)
        if caption.width > 5.6:
            caption.scale(5.6 / caption.width)
        caption.next_to(title, DOWN, buff=0.24)
        track = Line(LEFT * 3.0 + DOWN * 1.0, RIGHT * 3.0 + DOWN * 1.0, color=fg, stroke_width=5)
        car_body = RoundedRectangle(width=1.35, height=0.55, corner_radius=0.12, stroke_color=accent, stroke_width=3, fill_color=accent, fill_opacity=0.22)
        roof = Polygon(LEFT * 0.38 + UP * 0.28, RIGHT * 0.38 + UP * 0.28, RIGHT * 0.2 + UP * 0.62, LEFT * 0.1 + UP * 0.62, color=accent, fill_color=accent, fill_opacity=0.16)
        wheels = VGroup(Circle(radius=0.13, color=warm, fill_color=warm, fill_opacity=0.8).shift(LEFT * 0.43 + DOWN * 0.32), Circle(radius=0.13, color=warm, fill_color=warm, fill_opacity=0.8).shift(RIGHT * 0.43 + DOWN * 0.32))
        car = VGroup(car_body, roof, wheels).move_to(LEFT * 2.4 + DOWN * 0.52)
        block = Square(side_length=0.72, color=warm, fill_color=warm, fill_opacity=0.16).move_to(RIGHT * 2.25 + DOWN * 0.58)
        velocity = Arrow(car.get_right(), car.get_right() + RIGHT * 0.95, color=warm, buff=0.05, stroke_width=6)
        label = Text("momentum moves", font_size=29, color=warm).to_edge(DOWN, buff=0.84)
        self.play(FadeIn(title, shift=DOWN * 0.2), FadeIn(caption), Create(track), FadeIn(label), run_time=0.65)
        self.play(FadeIn(car, shift=RIGHT * 0.4), FadeIn(block), GrowArrow(velocity), run_time=0.9)
        scene_index = {scene_index}
        if scene_index == 0:
            self.play(car.animate.shift(RIGHT * 1.5), velocity.animate.shift(RIGHT * 1.5), run_time=1.1)
        elif scene_index == 1:
            self.play(car.animate.shift(RIGHT * 2.45), velocity.animate.shift(RIGHT * 2.45), block.animate.shift(RIGHT * 0.35), run_time=1.2)
            self.play(Indicate(block, color=warm), run_time=0.6)
        elif scene_index == 2:
            self.play(car.animate.shift(RIGHT * 2.2), block.animate.shift(RIGHT * 1.2), velocity.animate.scale(0.65).shift(RIGHT * 2.0), run_time=1.25)
        else:
            self.play(car.animate.shift(RIGHT * 1.8), block.animate.shift(RIGHT * 0.8), Indicate(label, color=warm), run_time=1.15)
        self.play(wheels.animate.rotate(TAU), Indicate(label, color=warm), run_time=0.85)
        self.wait(2.5)
"""


def _make_short_generic_motion_scene_code(
    scene_plan: dict,
    context: NarrativeContext,
    *,
    title: str,
    bg: str,
    fg: str,
    accent: str,
    warm: str,
) -> str:
    scene_index = int(context.scene_index or 0)
    final_scene = _is_final_short_scene(scene_plan, context)
    lines = _short_fallback_lines(scene_plan, context)
    caption = lines[0] if lines else "watch the change"
    return f"""from manim import *
import numpy as np

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        title = Text({"Your turn" if final_scene else title!r}, font_size=37, color=fg, weight=BOLD)
        if title.width > 5.7:
            title.scale(5.7 / title.width)
        title.to_edge(UP, buff=0.82)
        caption = Text({caption!r}, font_size=27, color=warm if {final_scene!r} else fg)
        if caption.width > 5.6:
            caption.scale(5.6 / caption.width)
        caption.next_to(title, DOWN, buff=0.24)
        curve = ParametricFunction(lambda t: np.array([2.25 * np.cos(t), 1.05 * np.sin(2 * t) - 0.2, 0]), t_range=[0, TAU], color=accent, stroke_width=5)
        dot = Dot(color=warm, radius=0.1).move_to(curve.get_start())
        cards = VGroup()
        for label in {repr(lines[:3])}:
            text = Text(label, font_size=25, color=fg)
            if text.width > 4.9:
                text.scale(4.9 / text.width)
            box = RoundedRectangle(width=5.4, height=0.72, corner_radius=0.1, stroke_color=accent, stroke_width=2, fill_color=ManimColor("#111824"), fill_opacity=0.6)
            cards.add(VGroup(box, text))
        cards.arrange(DOWN, buff=0.18).to_edge(DOWN, buff=0.62)
        self.play(FadeIn(title, shift=DOWN * 0.2), FadeIn(caption), run_time=0.5)
        self.play(Create(curve), GrowFromCenter(dot), run_time=0.9)
        self.play(MoveAlongPath(dot, curve), LaggedStart(*[FadeIn(card, shift=UP * 0.18) for card in cards], lag_ratio=0.15), run_time=1.8)
        self.play(Indicate(cards[min({scene_index}, len(cards) - 1)], color=warm), run_time=0.75)
        self.play(dot.animate.scale(1.4), rate_func=there_and_back, run_time=0.75)
        self.wait(2.5)
"""


def _make_short_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Deterministic last-resort scene for strict short-mode reliability."""
    return localize_scene_code(_make_short_fallback_scene_code_raw(scene_plan, context))


def _make_short_fallback_scene_code_raw(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _short_fallback_title(scene_plan, context)
    lines = _short_fallback_lines(scene_plan, context)
    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    warm = context.domain_state.get("secondary_color", "#F2C94C")
    prompt = (context.prompt or "").lower()

    if "dijkstra" in prompt or "shortest path" in prompt or "weighted graph" in prompt:
        return _make_short_dijkstra_scene_code(
            scene_plan, context, title=title, bg=bg, fg=fg, accent=accent, warm=warm
        )
    if "binary search" in prompt or ("sorted" in prompt and "target" in prompt):
        return _make_short_binary_search_scene_code(
            scene_plan, context, title=title, bg=bg, fg=fg, accent=accent, warm=warm
        )
    if any(token in prompt for token in ["molecule", "bond", "atom", "chemical", "chemistry", "hybrid"]):
        return _make_short_molecule_scene_code(
            scene_plan, context, title=title, bg=bg, fg=fg, accent=accent, warm=warm
        )
    if any(token in prompt for token in ["car", "cart", "collision", "momentum", "velocity", "acceleration"]):
        return _make_short_car_scene_code(
            scene_plan, context, title=title, bg=bg, fg=fg, accent=accent, warm=warm
        )
    if "bayes" not in prompt and "false positive" not in prompt and "factor" not in prompt and "prime" not in prompt:
        return _make_short_generic_motion_scene_code(
            scene_plan, context, title=title, bg=bg, fg=fg, accent=accent, warm=warm
        )

    line_literals = ", ".join(repr(line) for line in lines[:3])
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        title = Text({title!r}, font_size=40, color=fg, weight=BOLD)
        if title.width > 5.4:
            title.scale(5.4 / title.width)
        title.to_edge(UP, buff=0.95)
        underline = Line(LEFT * 2.55, RIGHT * 2.55, color=accent, stroke_width=3)
        underline.next_to(title, DOWN, buff=0.25)
        panel = RoundedRectangle(
            width=5.8,
            height=6.8,
            corner_radius=0.18,
            stroke_color=accent,
            stroke_width=3,
            fill_color=ManimColor("#111824"),
            fill_opacity=0.55,
        ).move_to(ORIGIN + DOWN * 0.25)
        labels = [{line_literals}]
        rows = VGroup()
        for i, label in enumerate(labels):
            row = RoundedRectangle(
                width=5.0,
                height=1.25,
                corner_radius=0.14,
                stroke_color=accent if i != len(labels) - 1 else warm,
                stroke_width=2.5,
                fill_color=accent if i != len(labels) - 1 else warm,
                fill_opacity=0.08,
            )
            text = Text(label, font_size=35, color=fg if i != len(labels) - 1 else warm)
            if text.width > 4.5:
                text.scale(4.5 / text.width)
            row_group = VGroup(row, text)
            rows.add(row_group)
        rows.arrange(DOWN, buff=0.45).move_to(panel.get_center())
        self.add(title, underline, panel, rows)
        self.wait(1.0)
        self.play(Indicate(rows[-1], color=warm, scale_factor=1.03), run_time=1.0)
        self.wait(7.0)
"""
