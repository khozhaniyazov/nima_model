"""Streaming short-mode deterministic fallbacks.

Split out of ``algorithms/streaming_fallbacks.py`` (issue #65). This module
holds the short-mode scene-code builders used when the LLM path fails and
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

import re
from typing import TYPE_CHECKING

from algorithms.i18n import localize_scene_code
from algorithms.streaming_fallbacks_core import (
    _factorization_line,
    _is_final_short_scene,
    _safe_text_literal,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from algorithms.streaming import NarrativeContext


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
