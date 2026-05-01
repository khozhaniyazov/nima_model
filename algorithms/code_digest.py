"""
Static code validation utilities — no LLM calls.
(Polish/fix functions moved to ai_functions.py)
"""

import re
import ast
import shutil
from functools import lru_cache
from typing import List, Tuple


# Imports allowed in generated code
_ALLOWED_IMPORT_TOPS = {
    "manim",
    "numpy",
    "np",
    "math",
    "random",
    "itertools",
    "collections",
}

# Dangerous builtins / patterns that should never appear in generated code
_FORBIDDEN_CALLS = {
    "exec",
    "eval",
    "__import__",
    "os.system",
    "os.popen",
    "os.remove",
    "os.rmdir",
    "subprocess.run",
    "subprocess.call",
    "subprocess.Popen",
}
_FORBIDDEN_NAMES = {"SVGMobject", "ImageMobject", "manimlib"}
_FORBIDDEN_GENERATED_TOKENS = {
    "SurroundingCircle": "Use Circle(...).surround(...) or Circumscribe instead of SurroundingCircle.",
}


def ensure_scene_class(code: str) -> str:
    """Ensure the code has a class GeneratedScene(Scene) with construct()."""
    if "class GeneratedScene(Scene)" in code:
        return code
    if "class " in code and "(Scene)" in code:
        code = re.sub(
            r"class\s+\w+\(Scene\)", "class GeneratedScene(Scene)", code, count=1
        )
        return code
    # Wrap raw construct code in a class
    indented = "\n".join("        " + ln for ln in code.split("\n") if ln.strip())
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
{indented}
"""


@lru_cache(maxsize=1)
def latex_toolchain_available() -> bool:
    """Return whether Manim's default LaTeX render path can run locally."""
    return bool(shutil.which("latex") and shutil.which("dvisvgm"))


def _latex_to_plain_text(value: str) -> str:
    text = value
    # Keep the content of text-like LaTeX wrappers instead of leaving command
    # names behind as visible labels, e.g. \text{Prime} -> Prime.
    text = re.sub(
        r"\\(?:text|mathrm|mathbf|operatorname)\s*\{([^{}]*)\}",
        r"\1",
        text,
    )
    replacements = {
        r"\bar": "mean ",
        r"\frac": " fraction ",
        r"\sqrt": " sqrt ",
        r"\sum": "sum",
        r"\int": "integral",
        r"\mu": "mu",
        r"\sigma": "sigma",
        r"\Delta": "Delta",
        r"\theta": "theta",
        r"\alpha": "alpha",
        r"\beta": "beta",
        r"\pi": "pi",
        r"\Rightarrow": "=>",
        r"\rightarrow": "to",
        r"\to": "to",
        r"\leq": "<=",
        r"\geq": ">=",
        r"\neq": "!=",
        r"\cdots": "...",
        r"\ldots": "...",
        r"\dots": "...",
        r"\cdot": "*",
        r"\times": "x",
        r"\checkmark": "ok",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[{}$]", "", text)
    text = text.replace("\\", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip() or value


class _TexToTextTransformer(ast.NodeTransformer):
    _TEXT_KEYWORDS = {
        "color",
        "font_size",
        "font",
        "slant",
        "weight",
        "line_spacing",
        "t2c",
        "t2f",
        "t2g",
        "t2s",
        "t2w",
    }

    def visit_Call(self, node: ast.Call):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "TransformMatchingTex":
            node.func.id = "TransformMatchingShapes"
            return node

        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "set_color_by_tex":
                node.func.attr = "set_color"
                if len(node.args) >= 2:
                    node.args = node.args[1:]
                return node
            if node.func.attr == "set_color_by_tex_to_color_map":
                node.func.attr = "set_color"
                node.args = []
                node.keywords = []
                return node
            if node.func.attr == "get_part_by_tex":
                return node.func.value

        if not isinstance(node.func, ast.Name) or node.func.id not in {"MathTex", "Tex"}:
            return node

        text_parts = []
        dynamic_args = []
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text_parts.append(_latex_to_plain_text(arg.value))
            else:
                dynamic_args.append(arg)

        if text_parts:
            args = [ast.Constant(value=" ".join(part for part in text_parts if part))]
        else:
            args = dynamic_args[:1] if dynamic_args else [ast.Constant(value="")]

        node.func = ast.Name(id="Text", ctx=ast.Load())
        node.args = args
        node.keywords = [
            keyword
            for keyword in node.keywords
            if keyword.arg in self._TEXT_KEYWORDS
        ]
        return node


def downgrade_tex_to_text_if_needed(
    code: str,
    *,
    latex_available: bool | None = None,
) -> str:
    """Replace MathTex/Tex with Text when the local LaTeX toolchain is absent."""
    has_tex = "MathTex" in code or re.search(r"(?<!Math)Tex\s*\(", code)
    if not has_tex:
        return code
    if latex_available is None:
        latex_available = latex_toolchain_available()
    if latex_available:
        return code
    try:
        tree = ast.parse(code)
        tree = _TexToTextTransformer().visit(tree)
        ast.fix_missing_locations(tree)
        return ast.unparse(tree)
    except Exception as exc:
        print(f"[LATEX] [WARN] Could not downgrade Tex objects: {exc}")
        return code


def validate_python_syntax(code: str) -> Tuple[bool, str]:
    """Parse the code with ast to detect syntax errors."""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"Parse error: {str(e)}"


def validate_names_and_imports(code: str) -> Tuple[bool, List[str]]:
    """
    AST-based pre-render security and safety check.
    Returns (is_safe, list_of_issues).

    Catches forbidden imports, dangerous builtins, and forbidden Manim objects
    BEFORE sending code to the Manim renderer — preventing hangs and crashes.
    """
    issues = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"SyntaxError at line {e.lineno}: {e.msg}"]

    for node in ast.walk(tree):
        # ── Import checks ─────────────────────────────────────────────────────
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in _ALLOWED_IMPORT_TOPS:
                    issues.append(
                        f"Forbidden import: `import {alias.name}` — only manim/numpy allowed"
                    )

        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod not in _ALLOWED_IMPORT_TOPS:
                issues.append(
                    f"Forbidden import: `from {node.module} import ...` — only manim/numpy allowed"
                )

        # ── Dangerous call checks ─────────────────────────────────────────────
        elif isinstance(node, ast.Call):
            func = node.func
            # exec("..."), eval("..."), __import__(...)
            if isinstance(func, ast.Name) and func.id in {"exec", "eval", "__import__"}:
                issues.append(
                    f"Forbidden call: `{func.id}()` — dangerous builtin not allowed"
                )
            # os.system(...), subprocess.run(...), etc.
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                call_str = f"{func.value.id}.{func.attr}"
                if call_str in _FORBIDDEN_CALLS:
                    issues.append(
                        f"Forbidden call: `{call_str}()` — potential security risk"
                    )

        # ── Forbidden Manim object names ──────────────────────────────────────
        elif isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_NAMES:
                issues.append(
                    f"Forbidden object: `{node.id}` — will crash render (no files on disk)"
                )

    return len(issues) == 0, issues


def validate_manim_code(code: str) -> Tuple[bool, str]:
    """Check required Manim scene structure."""
    required = [
        ("from manim import", "Missing `from manim import *`"),
        ("class GeneratedScene(Scene)", "Missing `class GeneratedScene(Scene)`"),
        ("def construct(self)", "Missing `def construct(self)` method"),
    ]
    for token, msg in required:
        if token not in code:
            return False, msg

    # Verify construct has at least one animation call. Streaming scenes may use
    # injected focus helpers that call scene.play(...) internally.
    if "self.play(" not in code and "focus_transition(self" not in code:
        return False, "construct() has no self.play() calls — animation would be empty"

    for token, fix_hint in _FORBIDDEN_GENERATED_TOKENS.items():
        if token in code:
            return False, f"Unsupported generated pattern `{token}`. {fix_hint}"

    if re.search(r"(?<!Manim)\bColor\(", code):
        return (
            False,
            "Unsupported generated pattern `Color(`. Use ManimColor(...) or built-in color constants instead of Color(...).",
        )

    if re.search(r"(?<!\.)\brotate\s*\(", code):
        return (
            False,
            "Unsupported helper `rotate(...)` detected. Use mobject.rotate(...) or import a concrete helper explicitly.",
        )

    return True, ""


def check_code_quality(code: str) -> Tuple[bool, list]:
    """Run non-blocking quality heuristics. Returns (passes, warnings)."""
    print("[QUALITY] Running quality checks...")
    issues = []
    warnings = []

    # ── MathTex indexing (CRASH RISK) ─────────────────────────────────────────
    # Pattern: eq[0][k] or eq[k] on MathTex objects — token positions are unstable
    mathtex_index_pattern = (
        r"\b(eq\d*|tex|formula|expression)\s*\[\s*\d+\s*\]\s*\[\s*\d+\s*\]"
    )
    if re.search(mathtex_index_pattern, code):
        issues.append(
            "[ERR] MathTex indexing detected (eq[0][k]) — will crash. Use get_part_by_tex() or TransformMatchingTex"
        )
    # Also catch single-level indexing on likely MathTex vars
    single_index_pattern = r"\b(eq\d*|tex|formula)\s*\[\s*\d+\s*\]\.set_color\b"
    if re.search(single_index_pattern, code):
        warnings.append(
            "[WARN] MathTex variable indexing — prefer set_color_by_tex() for stability"
        )

    # ── Timing ────────────────────────────────────────────────────────────────
    wait_times = re.findall(r"self\.wait\((\d+\.?\d*)\)", code)
    if wait_times:
        total = sum(float(w) for w in wait_times)
        if total < 10:
            warnings.append(
                f"[WARN] Very short total wait time: {total}s (aim for 15+)"
            )
    else:
        issues.append("[ERR] No self.wait() calls — animation will have no pauses")

    # ── Cleanup balance ───────────────────────────────────────────────────────
    fade_in_count = code.count("self.play(FadeIn")
    fade_out_count = code.count("self.play(FadeOut")
    clear_count = code.count("self.clear()")
    if fade_in_count > 8 and fade_out_count < 3:
        warnings.append(
            f"[WARN] Many FadeIn ({fade_in_count}) but few FadeOut ({fade_out_count})"
        )

    # ── self.clear() breaks visual continuity ─────────────────────────────────
    if clear_count > 0:
        warnings.append(
            f"[WARN] self.clear() used {clear_count}x — breaks visual continuity. "
            f"Use self.play(FadeOut(*self.mobjects)) instead."
        )

    # ── Bare NumberPlane() dominates the scene ────────────────────────────────
    if "NumberPlane()" in code and "stroke_opacity" not in code:
        warnings.append(
            "[WARN] NumberPlane() without opacity styling — grid will dominate "
            "the scene. Add background_line_style={'stroke_opacity': 0.15}"
        )

    # ── Forbidden patterns ────────────────────────────────────────────────────
    if "SVGMobject" in code:
        issues.append("[ERR] SVGMobject — will crash (no SVG files on disk)")
    if "ImageMobject" in code:
        issues.append("[ERR] ImageMobject — will crash (no image files on disk)")
    if "from manimlib" in code:
        issues.append(
            "[ERR] `from manimlib` — wrong library; use `from manim import *`"
        )
    if "DashedArrow" in code:
        issues.append(
            "[ERR] `DashedArrow` does not exist in Manim CE — use `DashedLine(...).add_tip()`"
        )
    if "SurroundingCircle" in code:
        issues.append(
            "[ERR] `SurroundingCircle` does not exist in Manim CE — use Circle(...).surround(...) or Circumscribe"
        )
    if re.search(r"(?<!Manim)\bColor\(", code):
        issues.append(
            "[ERR] `Color(...)` is not available from `from manim import *` in this runtime — use ManimColor(...) or built-in colors"
        )
    if re.search(r"(?<!\.)\brotate\s*\(", code):
        issues.append(
            "[ERR] Bare helper `rotate(...)` detected — use mobject.rotate(...) to avoid NameError"
        )
    if ".tip.length" in code:
        warnings.append(
            "[WARN] `.tip.length =` is read-only — use max_tip_length_to_length_ratio in Arrow() constructor"
        )
    if ".side_length" in code and "Line(" in code:
        warnings.append(
            "[WARN] `.side_length` referenced in code that also creates Line objects — verify shape-specific properties before render"
        )

    # ── Lambda closure in loops (heuristic) ───────────────────────────────────
    if re.search(r"for\s+\w+\s+in\b.+\n.*always_redraw\(lambda\s*:", code):
        warnings.append(
            "[WARN] always_redraw lambda inside for loop — verify variable capture "
            "(use `lambda x=x:` pattern)"
        )

    # ── Repeated move_to on same position ─────────────────────────────────────
    move_to_positions = re.findall(r"\.move_to\((.+?)\)", code)
    if move_to_positions:
        from collections import Counter

        pos_counts = Counter(p.strip() for p in move_to_positions)
        for pos, count in pos_counts.items():
            if count >= 3:
                warnings.append(
                    f"[WARN] Position '{pos}' used in move_to() {count} times — "
                    f"high overlap risk. Use VGroup.arrange() or different positions."
                )

    # ── 3b1b-quality indicators ───────────────────────────────────────────────
    good_patterns = [
        "ValueTracker",
        "always_redraw",
        "MathTex",
        "TransformMatchingTex",
        "TracedPath",
    ]
    used = [p for p in good_patterns if p in code]
    if not used:
        warnings.append(
            "[INFO] No advanced Manim patterns detected (ValueTracker/MathTex/TracedPath)"
        )

    print(f"[QUALITY] Issues: {len(issues)}, Warnings: {len(warnings)}")
    return len(issues) == 0, issues + warnings


def validate_latex_strings(code: str) -> Tuple[bool, List[str]]:
    """Validate MathTex/Tex strings in the code for common LaTeX errors.

    Returns (is_valid, list_of_issues)
    """
    issues = []

    mathtex_pattern = r'MathTex\s*\(\s*r?["\']([^"\']*)["\']'
    tex_pattern = r'Tex\s*\(\s*r?["\']([^"\']*)["\']'

    all_matches = set(re.findall(mathtex_pattern, code) + re.findall(tex_pattern, code))

    for latex_str in all_matches:
        issue = _check_single_latex(latex_str)
        if issue:
            issues.append(f"[LATEX] {issue}")

    return len(issues) == 0, issues


def _check_single_latex(latex_str: str) -> str:
    """Check a single LaTeX string for common errors."""
    if not latex_str:
        return "Empty MathTex string"

    open_braces = latex_str.count("{")
    close_braces = latex_str.count("}")
    if open_braces != close_braces:
        return f"Unmatched braces in '{latex_str[:50]}...': {open_braces} open, {close_braces} close"

    open_brackets = latex_str.count("[")
    close_brackets = latex_str.count("]")
    if open_brackets != close_brackets:
        return f"Unmatched brackets in '{latex_str[:50]}...': {open_brackets} open, {close_brackets} close"

    if latex_str.count("$") % 2 != 0:
        return f"Unmatched $ in '{latex_str[:50]}...'"

    common_bad_patterns = [
        ("log_", "Use \\log instead of log_ for subscript"),
        ("sin_", "Use \\sin instead of sin_ for subscript"),
        ("cos_", "Use \\cos instead of cos_ for subscript"),
        ("tan_", "Use \\tan instead of tan_ for subscript"),
        ("lim_(", "Use \\lim_{x \\to a} instead of lim_(x->a)"),
    ]

    for pattern, msg in common_bad_patterns:
        idx = latex_str.find(pattern)
        if idx != -1:
            if idx == 0 or latex_str[idx - 1] != "\\":
                return f"{msg} in '{latex_str[:50]}...'"

    return ""
