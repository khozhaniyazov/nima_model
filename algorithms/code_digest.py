"""
Static code validation utilities — no LLM calls.
(Polish/fix functions moved to ai_functions.py)
"""

import re
import ast
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

    # Verify construct has at least one self.play call
    if "self.play(" not in code:
        return False, "construct() has no self.play() calls — animation would be empty"

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
    if ".tip.length" in code:
        warnings.append(
            "[WARN] `.tip.length =` is read-only — use max_tip_length_to_length_ratio in Arrow() constructor"
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
