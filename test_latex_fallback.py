"""LaTeX-free render fallback checks."""

from algorithms.code_digest import downgrade_tex_to_text_if_needed


def test_tex_objects_are_downgraded_when_latex_is_missing():
    source = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        eq = MathTex(r"\\bar{x}=\\frac{1}{2}", color=WHITE, substrings_to_isolate=["x"])
        label = Tex("Central Limit Theorem", font_size=32)
        self.play(Write(eq), FadeIn(label))
        self.wait(1)
"""

    downgraded = downgrade_tex_to_text_if_needed(source, latex_available=False)

    assert "MathTex" not in downgraded
    assert "Tex(" not in downgraded
    assert "Text(" in downgraded
    assert "substrings_to_isolate" not in downgraded
    assert "mean x" in downgraded
    compile(downgraded, "<downgraded>", "exec")
    print("[OK] latex fallback - Tex objects downgrade to Text")


def test_tex_specific_operations_are_downgraded_when_latex_is_missing():
    source = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        eq1 = MathTex(r"x^2", color=WHITE)
        eq2 = MathTex(r"x^3", color=WHITE)
        eq1.set_color_by_tex("x", RED)
        x_part = eq2.get_part_by_tex("x")
        self.play(TransformMatchingTex(eq1, eq2))
        self.play(x_part.animate.set_color(YELLOW))
        self.wait(1)
"""

    downgraded = downgrade_tex_to_text_if_needed(source, latex_available=False)

    assert "TransformMatchingTex" not in downgraded
    assert "TransformMatchingShapes" in downgraded
    assert "set_color_by_tex" not in downgraded
    assert "get_part_by_tex" not in downgraded
    compile(downgraded, "<downgraded>", "exec")
    print("[OK] latex fallback - Tex-specific operations downgrade safely")


def test_tex_objects_stay_intact_when_latex_is_available():
    source = "eq = MathTex(r'x^2', color=WHITE)"

    assert downgrade_tex_to_text_if_needed(source, latex_available=True) == source
    print("[OK] latex fallback - available LaTeX keeps MathTex")


def test_text_latex_command_does_not_leak_visible_prefix():
    source = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        label = MathTex(r"\\text{Prime pieces}", color=WHITE)
        self.play(Write(label))
"""

    downgraded = downgrade_tex_to_text_if_needed(source, latex_available=False)

    assert "Text('Prime pieces'" in downgraded or 'Text("Prime pieces"' in downgraded
    assert "textPrime" not in downgraded
    compile(downgraded, "<downgraded>", "exec")
    print("[OK] latex fallback - text command content stays clean")


def test_latex_symbols_downgrade_to_readable_ascii():
    source = """from manim import *

class GeneratedScene(Scene):
    def construct(self):
        label = MathTex(r"n>1 \\Rightarrow n=p_1\\cdots p_k \\checkmark")
        self.play(Write(label))
"""

    downgraded = downgrade_tex_to_text_if_needed(source, latex_available=False)

    assert "Rightarrow" not in downgraded
    assert "checkmark" not in downgraded
    assert "=>" in downgraded
    assert "ok" in downgraded
    compile(downgraded, "<downgraded>", "exec")
    print("[OK] latex fallback - symbols downgrade to readable ASCII")


if __name__ == "__main__":
    test_tex_objects_are_downgraded_when_latex_is_missing()
    test_tex_specific_operations_are_downgraded_when_latex_is_missing()
    test_tex_objects_stay_intact_when_latex_is_available()
    test_text_latex_command_does_not_leak_visible_prefix()
    test_latex_symbols_downgrade_to_readable_ascii()
    print("\nALL LATEX FALLBACK CHECKS PASSED")
