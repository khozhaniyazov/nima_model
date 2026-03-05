"""
Parses Manim stderr output into structured error info
so the LLM fix prompt can be laser-focused.
"""
import re
from typing import Optional


def _strip_noise(stderr: str) -> str:
    """Remove tqdm progress bars, ANSI escapes, and Manim INFO logs from stderr.

    Manim emits hundreds of tqdm progress-bar lines (containing `it/s]`,
    `|`, percentage bars) and `[INFO]` log lines that obscure the actual
    Python traceback.  This function keeps only the lines that matter.
    """
    if not stderr:
        return stderr

    # Strip ANSI escape sequences
    ansi_re = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
    stderr = ansi_re.sub('', stderr)

    cleaned = []
    for line in stderr.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip tqdm progress bars
        if 'it/s]' in stripped or 'it/s)' in stripped:
            continue
        if re.match(r'^Animation \d+:', stripped) and ('|' in stripped or '%|' in stripped):
            continue
        # Skip pure percentage lines like "  0%|          | 0/27"
        if re.match(r'^\s*\d+%\|', stripped):
            continue
        # Skip Manim INFO log lines (e.g. "[03/05/26 17:46:40] INFO ...")
        if re.match(r'^\[[\d/]+ [\d:]+\]\s+INFO', stripped):
            continue
        if stripped.startswith('INFO') and ('movie file' in stripped or 'cached' in stripped or 'Rendered' in stripped):
            continue
        cleaned.append(line)

    return '\n'.join(cleaned) if cleaned else stderr


# Patterns that map stderr signatures to human-readable categories
_ERROR_PATTERNS = [
    (r"AttributeError: '(.+)' object has no attribute '(.+)'",
     "AttributeError", "Wrong Manim API — attribute does not exist on this object"),
    (r"TypeError: (.+)\(\) (takes|got) (.+)",
     "TypeError", "Wrong number of arguments or wrong type passed to Manim function"),
    (r"TypeError: unsupported operand",
     "TypeError", "Math operation on incompatible types"),
    (r"NameError: name '(.+)' is not defined",
     "NameError", "Variable or class used before definition — missing import or typo"),
    (r"ValueError: (.+)",
     "ValueError", "Invalid value passed to Manim function"),
    (r"KeyError: (.+)",
     "KeyError", "Dictionary key missing"),
    (r"IndexError: (.+)",
     "IndexError", "List/tuple index out of range"),
    (r"ImportError: cannot import name '(.+)' from '(.+)'",
     "ImportError", "Trying to import something that doesn't exist in this Manim version"),
    (r"ModuleNotFoundError: No module named '(.+)'",
     "ImportError", "Module not installed or wrong name — only manim and numpy are available"),
    (r"! LaTeX Error: (.+)",
     "LaTeXError", "LaTeX compilation failed — check MathTex string syntax"),
    (r"! Package (.+) Error",
     "LaTeXError", "LaTeX package error — use standard packages only"),
    (r"! Emergency stop",
     "LaTeXError", "LaTeX fatal error — likely malformed expression or missing brace"),
    (r"RuntimeError: (.+)",
     "RuntimeError", "Manim runtime error"),
    (r"AttributeError: (can't set attribute|property .+ of .+ object has no setter)",
     "AttributeError", "Read-only property — use the correct setter method instead of direct assignment"),
    (r"AttributeError: .*setter",
     "AttributeError", "Read-only property — do not assign directly; use .set_*() methods"),
    (r"FileNotFoundError",
     "FileNotFoundError", "Manim tried to load a file (SVG/image) that doesn't exist"),
    (r"RecursionError",
     "RecursionError", "Infinite recursion — likely in always_redraw or updater"),
    (r"ZeroDivisionError",
     "ZeroDivisionError", "Division by zero in animation math"),
    (r"MemoryError",
     "MemoryError", "Scene too complex — reduce number of objects or animation steps"),
    # Cairo / Pango (font/rendering engine errors)
    (r"cairo\.Error",
     "CairoError", "Cairo rendering engine error — likely caused by special unicode in Text()"),
    (r"Pango(.*)Error",
     "PangoError", "Pango font error — remove unicode characters from Text(); use ASCII only"),
    (r"gi\.repository",
     "PangoError", "GTK/Pango error — Text() contains characters that can't be rendered"),
    # ffmpeg errors
    (r"ffmpeg(.*)returned non.zero exit",
     "FFmpegError", "ffmpeg failed to encode — check video stream settings"),
    (r"ffmpeg(.*)error",
     "FFmpegError", "ffmpeg encoding error — animation may be too short or have no frames"),
    # Manim-specific animation errors
    (r"Scene\.play expects (.+) but got",
     "AnimationError", "Wrong object passed to self.play() — wrap in Create(), FadeIn(), Write()"),
    (r"Animation (.+) has already been played",
     "AnimationError", "Animation object reused — create a new animation instance"),
    (r"There are no animations",
     "AnimationError", "self.play() called with no arguments or empty list"),
]

# Map error types to concrete fix hints
_FIX_HINTS = {
    "AttributeError": (
        "Check the Manim CE v0.18 docs for the correct attribute name. "
        "Common fixes: use `.animate` for animation chains, "
        "use `.set_color()` not `.color=`, "
        "use `axes.plot()` not `axes.get_graph()`."
    ),
    "TypeError": (
        "Check argument counts and types. "
        "VGroup takes positional args — use `VGroup(*my_list)` not `VGroup(my_list)`. "
        "Angles must be radians: use PI/2, not 90."
    ),
    "NameError": (
        "Add the missing import or define the variable before use. "
        "Make sure `from manim import *` is present. "
        "Check for typos in variable or class names. "
        "If referencing a variable after self.clear() or FadeOut, redefine it."
    ),
    "LaTeXError": (
        "Fix the MathTex/Tex string. "
        "Use raw strings: r\"\\frac{1}{2}\". "
        "Check for unmatched braces { }. "
        "Remove unusual LaTeX packages; use only basic amsmath. "
        "Use `\\\\` for LaTeX newlines inside Python strings."
    ),
    "FileNotFoundError": (
        "Remove SVGMobject and ImageMobject calls. "
        "Replace with built-in Manim shapes (Circle, Square, Arrow, Polygon, etc.)."
    ),
    "ImportError": (
        "Only use `from manim import *` (and optionally `import numpy as np`). "
        "Do not import from internal Manim modules or any other library."
    ),
    "CairoError": (
        "Remove all non-ASCII unicode characters from Text() calls. "
        "Use plain ASCII text; put math symbols in MathTex() instead."
    ),
    "PangoError": (
        "Remove unicode/emoji/special characters from Text(). "
        "If showing symbols, use MathTex(r\"\\pi\") instead of Text(\"\u03c0\")."
    ),
    "FFmpegError": (
        "Ensure the scene has at least 2 seconds of animation (add self.wait(2)). "
        "Do not call ffmpeg or subprocess directly — Manim handles output."
    ),
    "AnimationError": (
        "Wrap objects in animation classes: self.play(Create(obj)) or FadeIn(obj). "
        "Never pass a raw Mobject to self.play(). "
        "Don't reuse the same Animation instance across multiple self.play() calls."
    ),
    "MemoryError": (
        "Reduce the number of objects. "
        "Limit TracedPath and always_redraw — they create many points. "
        "Use fewer Riemann rectangles (n < 50 rather than n=1000)."
    ),
    "RecursionError": (
        "Check always_redraw lambda — it must be a pure getter, never call self.play() inside. "
        "Use ValueTracker.animate instead of recursive updates."
    ),
    "ZeroDivisionError": (
        "Add a guard: `if denominator != 0:` before division. "
        "Use max(abs(val), 1e-9) to clamp very small denominators."
    ),
}


def parse_manim_error(stderr: str) -> dict:
    """
    Parse Manim stderr into a structured dict with:
      - error_type: str
      - error_message: str
      - line_number: Optional[int]
      - code_context: str (the relevant lines from traceback)
      - fix_hint: str
      - raw_stderr: str (last 3000 chars, noise-stripped)
    """
    # Strip tqdm progress bars, ANSI escapes, and INFO logs first
    cleaned = _strip_noise(stderr)

    result = {
        "error_type": "UnknownError",
        "error_message": "",
        "line_number": None,
        "code_context": "",
        "fix_hint": "Review the full error and fix the Manim code accordingly.",
        "raw_stderr": cleaned[-3000:] if len(cleaned) > 3000 else cleaned,
    }

    if not cleaned:
        return result

    # --- Find error type and message ---
    for pattern, err_type, _ in _ERROR_PATTERNS:
        match = re.search(pattern, cleaned)
        if match:
            result["error_type"] = err_type
            result["error_message"] = match.group(0)
            result["fix_hint"] = _FIX_HINTS.get(err_type, result["fix_hint"])
            break

    # Fallback: grab last non-empty line as message
    if not result["error_message"]:
        lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
        if lines:
            result["error_message"] = lines[-1]

    # --- Find line number from traceback ---
    line_matches = re.findall(r'File ["\'].+?["\'], line (\d+)', cleaned)
    # Take the last occurrence (innermost frame — closest to user code)
    if line_matches:
        result["line_number"] = int(line_matches[-1])

    # --- Extract code context (the File/line section of traceback) ---
    context_lines = []
    in_traceback = False
    for line in cleaned.splitlines():
        if "Traceback (most recent call last)" in line:
            in_traceback = True
        if in_traceback:
            context_lines.append(line)
        if len(context_lines) > 30:
            break
    result["code_context"] = "\n".join(context_lines) if context_lines else ""

    return result


def format_error_for_prompt(parsed: dict) -> str:
    """Format parsed error as a concise string for injection into the LLM fix prompt."""
    parts = [
        f"ERROR TYPE: {parsed['error_type']}",
        f"ERROR MESSAGE: {parsed['error_message']}",
    ]
    if parsed["line_number"]:
        parts.append(f"AT LINE: {parsed['line_number']}")
    if parsed["code_context"]:
        parts.append(f"\nTRACEBACK:\n{parsed['code_context']}")
    parts.append(f"\nFIX HINT: {parsed['fix_hint']}")
    return "\n".join(parts)
