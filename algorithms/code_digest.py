"""
Static code validation utilities — no LLM calls.
(Polish/fix functions moved to ai_functions.py)
"""
import re
import ast
from typing import List, Tuple


# Imports allowed in generated code
_ALLOWED_IMPORT_TOPS = {"manim", "numpy", "np", "math", "random", "itertools", "collections"}

# Dangerous builtins / patterns that should never appear in generated code
_FORBIDDEN_CALLS = {
    "exec", "eval", "__import__",
    "os.system", "os.popen", "os.remove", "os.rmdir",
    "subprocess.run", "subprocess.call", "subprocess.Popen",
}
_FORBIDDEN_NAMES = {"SVGMobject", "ImageMobject", "manimlib"}


def ensure_scene_class(code: str) -> str:
    """Ensure the code has a class GeneratedScene(Scene) with construct()."""
    if "class GeneratedScene(Scene)" in code:
        return code
    if "class " in code and "(Scene)" in code:
        code = re.sub(r"class\s+\w+\(Scene\)", "class GeneratedScene(Scene)", code, count=1)
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
                issues.append(f"Forbidden call: `{func.id}()` — dangerous builtin not allowed")
            # os.system(...), subprocess.run(...), etc.
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                call_str = f"{func.value.id}.{func.attr}"
                if call_str in _FORBIDDEN_CALLS:
                    issues.append(f"Forbidden call: `{call_str}()` — potential security risk")

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

    # ── Timing ────────────────────────────────────────────────────────────────
    wait_times = re.findall(r"self\.wait\((\d+\.?\d*)\)", code)
    if wait_times:
        total = sum(float(w) for w in wait_times)
        if total < 10:
            warnings.append(f"[WARN] Very short total wait time: {total}s (aim for 15+)")
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
        issues.append("[ERR] `from manimlib` — wrong library; use `from manim import *`")
    if "DashedArrow" in code:
        issues.append("[ERR] `DashedArrow` does not exist in Manim CE — use `DashedLine(...).add_tip()`")
    if ".tip.length" in code:
        warnings.append("[WARN] `.tip.length =` is read-only — use max_tip_length_to_length_ratio in Arrow() constructor")

    # ── Lambda closure in loops (heuristic) ───────────────────────────────────
    if re.search(r"for\s+\w+\s+in\b.+\n.*always_redraw\(lambda\s*:", code):
        warnings.append(
            "[WARN] always_redraw lambda inside for loop — verify variable capture "
            "(use `lambda x=x:` pattern)"
        )

    # ── 3b1b-quality indicators ───────────────────────────────────────────────
    good_patterns = ["ValueTracker", "always_redraw", "MathTex", "TransformMatchingTex", "TracedPath"]
    used = [p for p in good_patterns if p in code]
    if not used:
        warnings.append("[INFO] No advanced Manim patterns detected (ValueTracker/MathTex/TracedPath)")

    print(f"[QUALITY] Issues: {len(issues)}, Warnings: {len(warnings)}")
    return len(issues) == 0, issues + warnings