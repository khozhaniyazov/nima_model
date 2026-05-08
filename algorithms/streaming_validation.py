"""Code post-processing, quality gates, and error classification for
``algorithms.streaming`` (#11).

Extracted from ``algorithms/streaming.py`` to keep the streaming
orchestrator below ~3500 LoC. This module owns:

- ``FOCUS_HELPERS_SENTINEL`` / ``FOCUS_HELPERS_CODE`` — the Manim helper
  source injected into every generated scene.
- ``_extract_manim_code``, ``_sanitize_generated_code``,
  ``_enforce_minimum_font_size``, ``_inject_focus_helpers``,
  ``_strip_injected_focus_helpers`` — post-LLM code shaping.
- ``_reject_*`` — mode-aware pre-render quality gates that return a
  concrete error message when the generated scene violates a hygiene
  contract (layout overlap, duration too short, engagement too static,
  etc.), else ``None``.
- ``classify_render_error`` — maps a render-error blob into a short
  machine-readable signature shared with
  ``scripts/summarize_stream_reports.py``.

Module-load contract:

- This module is a leaf. It MUST NOT import from ``algorithms.streaming``
  at module-load time (streaming imports this module during its own
  load). Where a runtime lookup is needed — notably
  ``detect_static_layout_risks`` — it is resolved against
  ``algorithms.streaming`` *inside* the caller, so tests that monkeypatch
  ``streaming.detect_static_layout_risks`` keep working.
- ``NarrativeContext`` only appears in string-form type hints, guarded by
  ``from __future__ import annotations`` + ``TYPE_CHECKING``.

The public ``algorithms.streaming`` module re-exports every name defined
here for backward compatibility; tests that reach into
``streaming._reject_layout_hygiene_code`` etc. continue to work.
"""
from __future__ import annotations

import re
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from algorithms.streaming import NarrativeContext


# ─── FOCUS helper constants ─────────────────────────────────────────────────
FOCUS_HELPERS_SENTINEL = "# NIMA focus helpers"
FOCUS_HELPERS_CODE = f"""
{FOCUS_HELPERS_SENTINEL}
def fit_to_safe_frame(group, max_width=11.4, max_height=5.8):
    if group.width > max_width:
        group.scale_to_fit_width(max_width)
    if group.height > max_height:
        group.scale_to_fit_height(max_height)
    group.move_to(ORIGIN)
    return group

def _focus_luma(color):
    try:
        rgb = ManimColor(color).to_rgb()
    except Exception:
        return 1.0
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

def focus_plate(target, scene=None, color=None, opacity=None, buff=0.16):
    bg = None
    if scene is not None:
        bg = getattr(getattr(scene, "camera", None), "background_color", None)
    if color is None:
        color = BLACK if _focus_luma(bg or WHITE) < 0.45 else WHITE
    if opacity is None:
        opacity = 0.58 if _focus_luma(color) < 0.45 else 0.82
    plate = BackgroundRectangle(target, color=color, fill_opacity=opacity, buff=buff)
    plate.set_z_index(getattr(target, "z_index", 0) - 1)
    return plate

def focus_transition(scene, background, active, color=None, opacity=None, dim_opacity=0.22, buff=0.16, run_time=0.7):
    active_group = active if isinstance(active, Mobject) else VGroup(*active)
    active_group.set_z_index(10)
    plate = focus_plate(active_group, scene=scene, color=color, opacity=opacity, buff=buff)
    anims = []
    if background is not None:
        anims.append(background.animate.set_opacity(dim_opacity))
    anims.extend([FadeIn(plate), FadeIn(active_group, shift=UP * 0.08)])
    scene.play(*anims, run_time=run_time)
    return plate
""".strip()


# ─── Code post-processing ───────────────────────────────────────────────────
def _extract_manim_code(text: str) -> str:
    """Extract Python code from LLM response."""
    if "```python" in text:
        return text.split("```python")[1].split("```")[0].strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            return parts[1].lstrip("python").strip()
    return text.strip()


def _sanitize_generated_code(code: str) -> str:
    """Apply targeted repairs for recurring Manim generation mistakes."""
    code = str(code or "").strip()
    from_idx = code.find("from manim import")
    if from_idx > 0:
        code = code[from_idx:].strip()
    elif "from manim import" not in code and "class GeneratedScene(Scene)" in code:
        class_idx = code.find("class GeneratedScene(Scene)")
        code = "from manim import *\n\n" + code[class_idx:].strip()

    # Some providers leak pseudo-AST labels into Text strings, e.g.
    # Text("textPrime pieces"). Strip only obvious label prefixes.
    code = re.sub(
        r"(\bText\s*\(\s*['\"])(?:text|label|title)\s*[:_-]?\s*(?=[A-Za-z0-9])",
        r"\1",
        code,
        flags=re.IGNORECASE,
    )
    # Repair average_color("#hex", "#hex") into ManimColor-wrapped args.
    code = re.sub(
        r'average_color\(\s*"(#?[A-Fa-f0-9]{3,8})"\s*,\s*"(#?[A-Fa-f0-9]{3,8})"\s*\)',
        r'average_color(ManimColor("\1"), ManimColor("\2"))',
        code,
    )
    code = re.sub(
        r"average_color\(\s*'(#?[A-Fa-f0-9]{3,8})'\s*,\s*'(#?[A-Fa-f0-9]{3,8})'\s*\)",
        r'average_color(ManimColor("\1"), ManimColor("\2"))',
        code,
    )
    # Replace common invalid camera frame usages with camera-safe no-ops/comments handled by regeneration.
    code = code.replace("self.camera.frame", "self.camera")
    # The runtime exposes ManimColor reliably; normalize fragile Color(...) calls.
    code = re.sub(r"(?<!Manim)\bColor\(", "ManimColor(", code)
    # Literal blur filters are not a dependable Manim primitive. When the model
    # tries a simple blur animation, repair it into the safer focus-depth move.
    code = re.sub(
        r"\b(?:Blur|GaussianBlur)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:,[^)]*)?\)",
        r"\1.animate.set_opacity(0.22)",
        code,
    )
    # Manim CE does not accept dash_array in set_stroke; removing it is safer
    # than spending a render retry on a decorative dashed outline.
    dash_value = r"(?:\[[^\]]*\]|\([^\)]*\))"
    code = re.sub(rf"\s*,\s*dash_array\s*=\s*{dash_value}", "", code)
    code = re.sub(rf"dash_array\s*=\s*{dash_value}\s*,\s*", "", code)
    code = re.sub(rf"dash_array\s*=\s*{dash_value}", "", code)
    # Overlay label groups sometimes get arranged into a 1x1 grid even though
    # they contain a background, border, and text. That is invalid in Manim and
    # should be a no-op because the submobjects are already positioned.
    code = re.sub(
        r"\.arrange_in_grid\(\s*rows\s*=\s*1\s*,\s*cols\s*=\s*1\s*\)",
        "",
        code,
    )
    # Manim has ORIGIN/UP/DOWN/etc., not CENTER as an arrange direction.
    code = re.sub(r"\.arrange\(\s*CENTER\s*,", ".arrange(RIGHT,", code)
    code = re.sub(r"\.arrange\(\s*CENTER\s*\)", ".arrange(RIGHT)", code)
    return _inject_focus_helpers(code)


def _enforce_minimum_font_size(code: str, min_size: int) -> str:
    """Raise literal font_size values below the active mode readability floor."""
    try:
        floor = max(1, int(min_size))
    except (TypeError, ValueError):
        return code

    def replace(match: re.Match) -> str:
        prefix = match.group(1)
        value = int(match.group(2))
        if value >= floor:
            return match.group(0)
        return f"{prefix}{floor}"

    return re.sub(r"(\bfont_size\s*=\s*)(\d+)", replace, code)


def _inject_focus_helpers(code: str) -> str:
    """Make focus-layer helpers available in every generated Manim scene."""
    if FOCUS_HELPERS_SENTINEL in code:
        return code

    import_match = re.search(r"^from\s+manim\s+import\s+.*$", code, flags=re.MULTILINE)
    if not import_match:
        return code

    insert_at = import_match.end()
    return (
        code[:insert_at]
        + "\n\n"
        + FOCUS_HELPERS_CODE
        + "\n"
        + code[insert_at:]
    )


def _strip_injected_focus_helpers(code: str) -> str:
    """Remove injected helper definitions before scene-content heuristics."""
    start = code.find(FOCUS_HELPERS_SENTINEL)
    if start < 0:
        return code
    end = code.find("\nclass GeneratedScene", start)
    if end < 0:
        return code[:start]
    return code[:start] + code[end:]


def _reject_known_bad_patterns(code: str) -> Optional[str]:
    """Return a concrete pre-render error for recurring unsupported code patterns."""
    if re.search(
        r"\bText\s*\(\s*['\"](?:text|label|title)\s*[:_-]?\s*[A-Za-z0-9]",
        code,
        flags=re.IGNORECASE,
    ):
        return "Malformed text label prefix leaked into Text(); remove literal text/label/title prefix."
    if "SurroundingCircle" in code:
        return "Unsupported generated symbol `SurroundingCircle` — use Circle(...).surround(...) or Circumscribe."
    if re.search(r"(?<!\.)\brotate\s*\(", code):
        return "Unsupported helper `rotate(...)` detected — use mobject.rotate(...) explicitly."
    if "Matrix(" in code:
        try:
            from algorithms.code_digest import latex_toolchain_available
        except Exception:
            latex_toolchain_available = lambda: False
        if not latex_toolchain_available():
            return (
                "Matrix(...) requires LaTeX brackets in this Manim runtime, but "
                "LaTeX is unavailable. Build matrix visuals with VGroup/Text "
                "cells, bracket Lines, or a small Rectangle grid instead."
            )
    if re.search(r"\b(?:Blur|GaussianBlur)\s*\(", code) or "ImageFilter.GaussianBlur" in code:
        return (
            "Unsupported blur filter detected. Simulate depth by dimming older "
            "VGroups, adding a translucent BackgroundRectangle behind active "
            "content, and raising active z-index."
        )
    for block in _iter_call_blocks(code, "always_redraw"):
        if re.search(
            r"lambda\s*:\s*(?:Text|MarkupText|Paragraph|MathTex|Tex|Integer|DecimalNumber)\s*\(",
            block,
        ) and not re.search(
            r"\.(?:move_to|next_to|to_edge|to_corner|align_to|shift)\s*\(",
            block,
        ):
            return (
                "Unanchored always_redraw text detected. Put move_to/next_to/"
                "to_edge inside the lambda or use an updater that preserves "
                "the label position."
            )
    if ".side_length" in code and re.search(r"\bLine\(", code):
        return "Potential invalid `.side_length` access in scene that constructs Line objects."
    return None


def _reject_layout_hygiene_code(
    code: str, context: NarrativeContext, scene_plan: dict
) -> Optional[str]:
    """Reject high-risk static layout issues before spending render time."""
    mode = str(context.domain_state.get("video_mode") or "").lower()
    if mode not in {"short", "standard", "course", "lecture"}:
        return None

    check_code = _strip_injected_focus_helpers(code)
    from algorithms import streaming as _streaming  # lazy to preserve monkeypatch
    warnings = _streaming.detect_static_layout_risks(check_code)
    if not warnings:
        return None

    is_question = scene_plan.get("type") == "question"

    def _is_severe_layout_warning(warning: str) -> bool:
        if warning.startswith("[ACCUMULATION]"):
            match = re.search(r"create-load\s+(\d+)", warning)
            create_load = int(match.group(1)) if match else 0
            threshold = 18 if mode == "short" else 40
            return create_load >= threshold
        return warning.startswith(
            (
                "[OVERLAP]",
                "[SECTION_LEAK]",
                "[NO_CLEANUP]",
                "[COMPLEXITY]",
                "[ANIMATION_QUEUE]",
            )
        )

    severe = [warning for warning in warnings if _is_severe_layout_warning(warning)]
    if not severe:
        return None

    # Question pauses intentionally hold a small board. Only block them for direct
    # overlap or obvious copy/section leaks.
    if is_question:
        severe = [
            warning
            for warning in severe
            if warning.startswith(("[OVERLAP]", "[SECTION_LEAK]"))
        ]
        if not severe:
            return None

    return (
        "Static layout hygiene risk detected before render: "
        + " | ".join(severe[:2])
        + ". Use VGroup.arrange/next_to, focus_transition, opacity dimming, "
        "and explicit FadeOut/remove cleanup before adding new dense elements."
    )


def _reject_unbounded_long_text_code(
    code: str, context: NarrativeContext, scene_plan: dict
) -> Optional[str]:
    """Reject long Text literals unless the code visibly constrains width."""
    mode = str(context.domain_state.get("video_mode") or "").lower()
    if mode not in {"short", "standard", "course", "lecture"}:
        return None

    check_code = _strip_injected_focus_helpers(code)
    lines = check_code.splitlines()
    assignment_pattern = re.compile(
        r"^\s*(\w+)\s*=\s*(?:Text|MarkupText)\s*\(\s*([\"'])(.+?)\2",
        flags=re.S,
    )

    for idx, line in enumerate(lines):
        match = assignment_pattern.search(line)
        if not match:
            # Handle common multiline constructor form:
            # label = Text(
            #     "long literal",
            #     ...
            # )
            multiline = re.match(r"^\s*(\w+)\s*=\s*(?:Text|MarkupText)\s*\(\s*$", line)
            if multiline and idx + 1 < len(lines):
                literal_match = re.search(r"([\"'])(.+?)\1", lines[idx + 1].strip())
                if literal_match:
                    var_name = multiline.group(1)
                    text_value = literal_match.group(2)
                else:
                    continue
            else:
                continue
        else:
            var_name = match.group(1)
            text_value = match.group(3)

        if mode == "short" and len(text_value) >= 46:
            return (
                f"Short mode long text '{var_name}' is too dense ({len(text_value)} chars). "
                "Use a short caption split across beats, not a sentence panel."
            )
        text_threshold = 72 if mode == "standard" else 78
        if len(text_value) < text_threshold:
            continue

        nearby = "\n".join(lines[idx : min(len(lines), idx + 10)])
        has_width_guard = any(
            token in nearby
            for token in (
                f"{var_name}.scale_to_fit_width",
                f"{var_name}.scale(",
                f"{var_name}.width",
                "Paragraph(",
            )
        ) or ".scale_to_fit_width(" in line or ".scale(" in line
        if not has_width_guard:
            return (
                f"Long text object '{var_name}' has {len(text_value)} characters "
                "without a width guard. Use Paragraph, split into shorter labels, "
                "or add `if obj.width > safe_width: obj.scale_to_fit_width(safe_width)`."
            )
    return None


def _reject_static_short_code(code: str, context: NarrativeContext) -> Optional[str]:
    """Reject text-card shorts before spending render time on them."""
    short_mode = context.domain_state.get("video_mode") == "short" or (
        context.domain_state.get("aspect") == "9:16"
    )
    if not short_mode:
        return None
    code = _strip_injected_focus_helpers(code)

    motion_tokens = [
        ".animate",
        "focus_transition",
        "MoveAlongPath",
        "Transform",
        "ReplacementTransform",
        "FadeTransform",
        "TransformMatching",
        "Indicate",
        "Circumscribe",
        "Flash",
        "Wiggle",
        "Rotate",
        "Rotating",
        "GrowFromCenter",
        "GrowFromEdge",
        "GrowArrow",
        "LaggedStart",
        "AnimationGroup",
        "Succession",
        "MoveToTarget",
        "ApplyMethod",
    ]
    domain_object_tokens = [
        "Dot(",
        "Circle(",
        "Line(",
        "Arrow(",
        "Vector(",
        "Graph(",
        "NumberLine(",
        "Axes(",
        "Rectangle(",
        "Square(",
        "Polygon(",
        "Arc(",
        "ParametricFunction(",
        "VGroup(",
    ]
    text_count = len(
        re.findall(r"\b(?:Text|MarkupText|Paragraph|MathTex|Tex)\s*\(", code)
    )
    motion_count = sum(code.count(token) for token in motion_tokens)
    domain_object_count = sum(code.count(token) for token in domain_object_tokens)
    write_only_count = code.count("Write(") + code.count("FadeIn(")

    if domain_object_count < 3 and text_count >= 3:
        return (
            "Short scene is text-card heavy. Regenerate with moving domain objects "
            "as the main visual."
        )
    if motion_count < 3 and write_only_count >= motion_count + 2:
        return (
            "Short scene is too static. Regenerate with at least three non-text "
            "motion events such as MoveAlongPath, Transform, Indicate, or .animate."
        )
    return None


def _parse_first_number(text: str) -> Optional[float]:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text or "")
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _iter_call_blocks(code: str, call_name: str) -> List[str]:
    blocks: List[str] = []
    needle = f"{call_name}("
    pos = 0
    while True:
        idx = code.find(needle, pos)
        if idx == -1:
            break
        start = idx + len(call_name)
        depth = 0
        end = None
        quote: Optional[str] = None
        escaped = False
        for j in range(start, len(code)):
            ch = code[j]
            if quote:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = None
                continue
            if ch in ("'", '"'):
                quote = ch
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end is None:
            pos = idx + len(needle)
            continue
        blocks.append(code[idx:end])
        pos = end
    return blocks


def _estimate_manim_code_duration(code: str) -> float:
    """Approximate Manim runtime from simple self.play/self.wait calls."""
    code = _strip_injected_focus_helpers(code)
    total = 0.0
    for block in _iter_call_blocks(code, "self.play"):
        match = re.search(r"run_time\s*=\s*([-+]?\d+(?:\.\d+)?)", block)
        total += float(match.group(1)) if match else 1.0
    for block in _iter_call_blocks(code, "focus_transition"):
        match = re.search(r"run_time\s*=\s*([-+]?\d+(?:\.\d+)?)", block)
        total += float(match.group(1)) if match else 0.7
    for block in _iter_call_blocks(code, "self.wait"):
        parsed = _parse_first_number(block)
        total += parsed if parsed is not None else 1.0
    return total


def _short_ends_with_full_fadeout(code: str) -> bool:
    code = _strip_injected_focus_helpers(code)
    lines = [line.strip() for line in code.splitlines() if line.strip()]
    tail = "\n".join(lines[-12:])
    return bool(
        re.search(r"FadeOut\s*\(\s*\*self\.mobjects", tail)
        or (
            tail.count("FadeOut(") >= 3
            and re.search(r"self\.wait\s*\(\s*(?:0(?:\.\d+)?|0?\.?\d{0,2})\s*\)", tail)
        )
    )


def _reject_short_duration_code(
    code: str, context: NarrativeContext, scene_plan: dict
) -> Optional[str]:
    """Reject short scenes that cannot meet the beat duration contract."""
    short_mode = context.domain_state.get("video_mode") == "short" or (
        context.domain_state.get("aspect") == "9:16"
    )
    if not short_mode:
        return None

    target = float(scene_plan.get("duration_hint") or 0)
    if target <= 0:
        return None

    estimated = _estimate_manim_code_duration(code)
    if estimated < target * 0.82:
        return (
            f"Short scene runtime is too short ({estimated:.1f}s estimated vs "
            f"{target:.1f}s target). Add more active visual beats, pulses, "
            "route highlights, object motion, and a living final hold."
        )
    if _short_ends_with_full_fadeout(code):
        return (
            "Short scene ends by fading out the main visual. Keep the final "
            "graph/diagram/challenge frame alive through the last wait."
        )
    return None


def _reject_standard_engagement_code(
    code: str, context: NarrativeContext, scene_plan: dict
) -> Optional[str]:
    """Reject standard-mode scenes that collapse into static lecture cards."""
    if context.domain_state.get("video_mode") != "standard":
        return None
    code = _strip_injected_focus_helpers(code)

    text_count = len(
        re.findall(r"\b(?:Text|MarkupText|Paragraph|MathTex|Tex)\s*\(", code)
    )
    motion_tokens = [
        ".animate",
        "focus_transition",
        "MoveAlongPath",
        "Transform",
        "ReplacementTransform",
        "FadeTransform",
        "TransformMatching",
        "Indicate",
        "Circumscribe",
        "Flash",
        "Wiggle",
        "Rotate",
        "Rotating",
        "GrowFromCenter",
        "GrowFromEdge",
        "GrowArrow",
        "Create",
        "DrawBorderThenFill",
        "LaggedStart",
        "AnimationGroup",
        "Succession",
        "MoveToTarget",
        "ApplyMethod",
    ]
    domain_object_tokens = [
        "Dot(",
        "Circle(",
        "Line(",
        "Arrow(",
        "Vector(",
        "Graph(",
        "NumberLine(",
        "Axes(",
        "Rectangle(",
        "Square(",
        "Polygon(",
        "Arc(",
        "ParametricFunction(",
        "Brace(",
        "Table(",
        "VGroup(",
    ]
    motion_count = sum(code.count(token) for token in motion_tokens)
    domain_object_count = sum(code.count(token) for token in domain_object_tokens)
    write_only_count = code.count("Write(") + code.count("FadeIn(")

    if domain_object_count < 3 and text_count >= 5:
        return (
            "Standard scene is too text-card heavy. Regenerate with concrete "
            "objects, diagrams, state markers, and visual cause-and-effect."
        )
    if motion_count < 3 and write_only_count >= motion_count + 3:
        return (
            "Standard scene is too static. Add transformations, comparisons, "
            "moving markers, reveals, or simulation-style state updates."
        )

    lowered = code.lower()
    banned_prompts = (
        "your turn",
        "pause the video",
        "comment below",
        "type your answer",
        "quiz",
    )
    if any(marker in lowered for marker in banned_prompts):
        return "Standard mode cannot include quiz pauses or social comment CTAs."

    target = float(scene_plan.get("duration_hint") or 0)
    if target > 0:
        estimated = _estimate_manim_code_duration(code)
        if estimated < target * 0.60:
            return (
                f"Standard scene runtime is too short ({estimated:.1f}s estimated "
                f"vs {target:.1f}s target). Extend with active visual beats, "
                "comparison pulses, state updates, and a living payoff frame."
            )

    if _short_ends_with_full_fadeout(code):
        return (
            "Standard scene ends by clearing the full visual. Keep the final "
            "diagram, comparison, or mental model alive through the last wait."
        )
    return None


def _reject_course_instructional_code(
    code: str, context: NarrativeContext, scene_plan: dict
) -> Optional[str]:
    """Reject course-mode scenes that collapse into unreadable lecture boards."""
    if context.domain_state.get("video_mode") != "course":
        return None
    code = _strip_injected_focus_helpers(code)

    is_question = scene_plan.get("type") == "question"
    text_count = len(
        re.findall(r"\b(?:Text|MarkupText|Paragraph|MathTex|Tex)\s*\(", code)
    )
    motion_tokens = [
        ".animate",
        "focus_transition",
        "MoveAlongPath",
        "Transform",
        "ReplacementTransform",
        "FadeTransform",
        "TransformMatching",
        "Indicate",
        "Circumscribe",
        "Flash",
        "Wiggle",
        "Rotate",
        "Rotating",
        "GrowFromCenter",
        "GrowArrow",
        "Create",
        "DrawBorderThenFill",
        "LaggedStart",
        "AnimationGroup",
        "Succession",
        "MoveToTarget",
        "ApplyMethod",
    ]
    domain_object_tokens = [
        "Dot(",
        "Circle(",
        "Line(",
        "Arrow(",
        "Vector(",
        "Graph(",
        "NumberLine(",
        "Axes(",
        "Rectangle(",
        "Square(",
        "Polygon(",
        "Arc(",
        "ParametricFunction(",
        "Brace(",
        "Table(",
        "VGroup(",
    ]
    motion_count = sum(code.count(token) for token in motion_tokens)
    domain_object_count = sum(code.count(token) for token in domain_object_tokens)
    write_only_count = code.count("Write(") + code.count("FadeIn(")

    lowered = code.lower()
    banned_social = (
        "comment below",
        "type your answer",
        "subscribe",
        "like and",
        "share this",
    )
    if any(marker in lowered for marker in banned_social):
        return "Course mode cannot include social CTAs."

    target = float(scene_plan.get("duration_hint") or 0)
    if is_question:
        if text_count >= 12 and domain_object_count < 3:
            return (
                "Course checkpoint is too dense. Keep exactly one prompt with "
                "one or two short visual paths."
            )
        # Checkpoint pauses are intentionally pad-friendly. If the generated
        # question frame is valid and readable, final-frame padding can supply
        # the thinking time without forcing the model to over-animate a pause.
        return None

    if domain_object_count < 3 and text_count >= 6:
        return (
            "Course content scene is a text wall. Regenerate with a diagram, "
            "worked example, progress rail, and object-attached labels."
        )
    if motion_count < 2 and write_only_count >= motion_count + 3:
        return (
            "Course content scene is too static. Add worked-example steps, "
            "state updates, checklist routing, or diagram transformations."
        )
    if target > 0:
        estimated = _estimate_manim_code_duration(code)
        if estimated < target * 0.60:
            return (
                f"Course content runtime is too short ({estimated:.1f}s "
                f"estimated vs {target:.1f}s target). Extend with deliberate "
                "teaching moves, state updates, and a visible recap state."
            )
        if estimated > max(32.0, target * 1.35):
            return (
                f"Course content runtime is too long ({estimated:.1f}s estimated "
                f"vs {target:.1f}s target). Split the idea into one focused "
                "10-30 second scenelet and avoid accumulating stale objects."
            )
    return None


def _reject_lecture_academic_code(
    code: str, context: NarrativeContext, scene_plan: dict
) -> Optional[str]:
    """Reject lecture scenes that become social videos or unreadable proof walls."""
    if context.domain_state.get("video_mode") != "lecture":
        return None
    code = _strip_injected_focus_helpers(code)

    is_question = scene_plan.get("type") == "question"
    text_count = len(
        re.findall(r"\b(?:Text|MarkupText|Paragraph|MathTex|Tex)\s*\(", code)
    )
    motion_tokens = [
        ".animate",
        "focus_transition",
        "MoveAlongPath",
        "Transform",
        "ReplacementTransform",
        "FadeTransform",
        "TransformMatching",
        "Indicate",
        "Circumscribe",
        "Flash",
        "GrowFromCenter",
        "GrowArrow",
        "Create",
        "DrawBorderThenFill",
        "LaggedStart",
        "AnimationGroup",
        "Succession",
        "MoveToTarget",
        "ApplyMethod",
    ]
    domain_object_tokens = [
        "Dot(",
        "Circle(",
        "Line(",
        "Arrow(",
        "Vector(",
        "Graph(",
        "NumberLine(",
        "Axes(",
        "Rectangle(",
        "Square(",
        "Polygon(",
        "Arc(",
        "ParametricFunction(",
        "Brace(",
        "Table(",
        "VGroup(",
    ]
    motion_count = sum(code.count(token) for token in motion_tokens)
    domain_object_count = sum(code.count(token) for token in domain_object_tokens)
    write_only_count = code.count("Write(") + code.count("FadeIn(")

    lowered = code.lower()
    banned_social = (
        "comment below",
        "type your answer",
        "subscribe",
        "like and",
        "share this",
    )
    if any(marker in lowered for marker in banned_social):
        return "Lecture mode cannot include social CTAs."

    target = float(scene_plan.get("duration_hint") or 0)
    if is_question:
        if text_count >= 10 and domain_object_count < 2:
            return (
                "Lecture pause is too dense. Keep one proof question with a "
                "faint prior proof map and no answer reveal."
            )
        return None

    if domain_object_count < 3 and text_count >= 7:
        return (
            "Lecture content is a proof text wall. Regenerate with an equation "
            "ladder, proof map, assumption ledger, diagram, or worked example."
        )
    if motion_count < 2 and write_only_count >= motion_count + 4:
        return (
            "Lecture content is too static. Add derivation transforms, proof-map "
            "routing, active-line focus, or example-state updates."
        )
    if target > 0:
        estimated = _estimate_manim_code_duration(code)
        if estimated < target * 0.60:
            return (
                f"Lecture scene runtime is too short ({estimated:.1f}s estimated "
                f"vs {target:.1f}s target). Extend with proof steps, derivation "
                "transforms, and active board holds."
            )
        if estimated > max(52.0, target * 1.35):
            return (
                f"Lecture scene runtime is too long ({estimated:.1f}s estimated "
                f"vs {target:.1f}s target). Keep one focused academic scenelet "
                "instead of one giant board."
            )
    return None

# ─── Render-error classifier ────────────────────────────────────────────────
def classify_render_error(error_text: str) -> str:
    """Classify a render error into a short machine-readable signature.

    The order matters: more specific patterns are checked first.
    Keeping this in sync with summarize_stream_reports.classify_signature.
    """
    text = (error_text or "").lower()
    if "camera" in text and "frame" in text:
        return "camera_frame"
    if "interpolate" in text and "str" in text:
        return "color_string_interpolate"
    if "indexerror" in text or "list index out of range" in text:
        return "index_out_of_range"
    if "syntax error" in text or "was never closed" in text:
        return "syntax_error"
    if "timeout" in text:
        return "timeout"
    if "nameerror" in text or "is not defined" in text:
        return "name_error"
    if "attributeerror" in text or "has no attribute" in text:
        return "attribute_error"
    if "typeerror" in text:
        return "type_error"
    if "latex" in text or "emergency stop" in text or "mathtex" in text:
        return "latex_error"
    if "valueerror" in text:
        return "value_error"
    if "importerror" in text or "modulenotfounderror" in text:
        return "import_error"
    if "recursionerror" in text:
        return "recursion_error"
    if "zerodivisionerror" in text:
        return "zero_division"
    if "ffmpeg" in text:
        return "ffmpeg_error"
    if "memoryerror" in text:
        return "memory_error"
    if "keyerror" in text:
        return "key_error"
    if "cairo" in text or "pango" in text:
        return "rendering_engine_error"
    if "file not found" in text or "video file not found" in text:
        return "video_not_found"
    return "other_render"
