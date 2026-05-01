"""Static layout-hygiene detector tests."""

from algorithms.overlap_detector import (
    detect_position_collisions,
    detect_stale_copies,
    run_all_checks,
)


def test_arranged_vgroup_move_is_not_reported_as_child_overlap():
    code = """from manim import *
class GeneratedScene(Scene):
    def construct(self):
        eq_A = MathTex("A")
        eq_v1 = MathTex("v")
        eq_eq = MathTex("=")
        equation = VGroup(eq_A, eq_v1, eq_eq).arrange(RIGHT, buff=0.2)
        equation.to_edge(UP + LEFT)
        self.play(FadeIn(equation))
"""

    warnings = detect_position_collisions(code)

    assert not [warning for warning in warnings if warning.startswith("[OVERLAP]")]
    print("[OK] overlap detector - arranged VGroup movement is not child overlap")


def test_background_card_can_share_center_with_inner_content():
    code = """from manim import *
class GeneratedScene(Scene):
    def construct(self):
        theorem_box = RoundedRectangle(width=4, height=1.2)
        theorem_title = Text("Theorem", font_size=28)
        theorem_text = Text("Every vector splits into basis coordinates.", font_size=24)
        theorem_title.move_to(theorem_box.get_center() + UP * 0.25)
        theorem_text.move_to(theorem_box.get_center() + DOWN * 0.25)
        self.play(FadeIn(theorem_box), Write(theorem_title), Write(theorem_text))
"""

    warnings = run_all_checks(code)

    assert not [warning for warning in warnings if warning.startswith("[OVERLAP]")]
    print("[OK] overlap detector - card text offsets are parsed distinctly")


def test_distinct_card_centers_are_not_collapsed_to_same_edge():
    code = """from manim import *
class GeneratedScene(Scene):
    def construct(self):
        theorem_box = RoundedRectangle(width=3, height=1)
        example_box = RoundedRectangle(width=3, height=1).shift(RIGHT * 3)
        theorem_title = Text("Theorem")
        example_title = Text("Example")
        theorem_title.move_to(theorem_box.get_center() + UP * 0.25)
        example_title.move_to(example_box.get_center() + UP * 0.25)
        self.play(Write(theorem_title), Write(example_title))
"""

    warnings = detect_position_collisions(code)

    assert not [warning for warning in warnings if warning.startswith("[OVERLAP]")]
    print("[OK] overlap detector - distinct card anchors stay distinct")


def test_real_same_anchor_text_overlap_is_still_reported():
    code = """from manim import *
class GeneratedScene(Scene):
    def construct(self):
        first = Text("First")
        second = Text("Second")
        first.move_to(ORIGIN)
        second.move_to(ORIGIN)
        self.play(Write(first), Write(second))
"""

    warnings = detect_position_collisions(code)

    assert any(warning.startswith("[OVERLAP]") for warning in warnings)
    print("[OK] overlap detector - real same-anchor text overlap is reported")


def test_decorative_container_copy_is_not_stale_content():
    code = """from manim import *
class GeneratedScene(Scene):
    def construct(self):
        theorem_box = RoundedRectangle(width=4, height=1)
        glow = theorem_box.copy().set_opacity(0.2)
        self.play(FadeIn(theorem_box), FadeIn(glow))
"""

    warnings = detect_stale_copies(code)

    assert not [warning for warning in warnings if warning.startswith("[STALE_COPY]")]
    print("[OK] overlap detector - decorative container copies are allowed")


def test_lifecycle_section_group_is_not_reported_as_visible_overlap():
    code = """from manim import *
class GeneratedScene(Scene):
    def construct(self):
        section = VGroup(Text("old")).to_edge(DOWN + RIGHT)
        ladder = VGroup(Text("new")).to_edge(DOWN + RIGHT)
        self.play(FadeIn(section), FadeIn(ladder))
"""

    warnings = detect_position_collisions(code)

    assert not [warning for warning in warnings if warning.startswith("[OVERLAP]")]
    print("[OK] overlap detector - lifecycle section groups are ignored")
