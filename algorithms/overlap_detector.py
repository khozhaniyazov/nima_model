"""
Static overlap & scene-hygiene detector.

Analyzes generated Manim code (AST + regex) BEFORE rendering to catch
high-risk layout problems:
  - Multiple objects placed at the same coordinates without intervening FadeOut
  - Too many Write/Create calls without cleanup
  - Objects left alive across section boundaries
  - Repeated move_to on same position for different objects

Returns a list of warnings/errors that can be fed back to the LLM review pass.
"""

import ast
import re
from typing import List, Tuple


def _extract_positions(code: str) -> List[Tuple[str, str, int]]:
    """Extract (variable_or_desc, position_expr, line_no) from move_to / to_edge / shift calls."""
    results = []
    for i, line in enumerate(code.splitlines(), 1):
        stripped = line.strip()
        # Pattern 1: var.move_to(...)  — variable-based
        m = re.search(r'(\w+)\.move_to\((.+?)\)', stripped)
        if m:
            results.append((m.group(1), m.group(2).strip(), i))
        # Pattern 2: ).move_to(...)  — chained after constructor, extract assignment target
        elif ').move_to(' in stripped:
            # Try to get the variable being assigned: eq1 = MathTex(...).move_to(ORIGIN)
            assign_m = re.match(r'\s*(\w+)\s*=\s*.+\.move_to\((.+?)\)', stripped)
            if assign_m:
                results.append((assign_m.group(1), assign_m.group(2).strip(), i))
        # Pattern 3: .to_edge(UP, ...)
        m = re.search(r'(\w+)\.to_edge\((\w+)', stripped)
        if m:
            results.append((m.group(1), f"edge:{m.group(2)}", i))
    return results


def _normalize_pos(expr: str) -> str:
    """Normalize position expressions for comparison."""
    expr = expr.replace(" ", "").replace("*", "*")
    # Collapse common equivalents
    expr = expr.replace("ORIGIN+UP*0.0", "ORIGIN")
    expr = expr.replace("np.array([0,0,0])", "ORIGIN")
    return expr


def detect_position_collisions(code: str) -> List[str]:
    """Find multiple objects placed at the same position without FadeOut between them."""
    warnings = []
    positions = _extract_positions(code)
    lines = code.splitlines()

    # Group by normalized position
    pos_map = {}  # normalized_pos -> [(var, line_no)]
    for var, pos_expr, line_no in positions:
        norm = _normalize_pos(pos_expr)
        if norm not in pos_map:
            pos_map[norm] = []
        pos_map[norm].append((var, line_no))

    for pos, placements in pos_map.items():
        if len(placements) < 2:
            continue
        # Check if there's a FadeOut between placements
        for i in range(len(placements) - 1):
            var_a, line_a = placements[i]
            var_b, line_b = placements[i + 1]
            if var_a == var_b:
                continue  # same object repositioned — fine

            # Check lines between for FadeOut of var_a
            between = "\n".join(lines[line_a:line_b - 1])
            if f"FadeOut({var_a}" not in between and f"FadeOut(*self.mobjects)" not in between:
                warnings.append(
                    f"[OVERLAP] Line {line_a} ({var_a}) and line {line_b} ({var_b}) "
                    f"both placed at {pos} with no FadeOut of {var_a} between them."
                )

    return warnings


def detect_object_accumulation(code: str) -> List[str]:
    """Detect too many Create/Write/FadeIn calls without corresponding FadeOut."""
    warnings = []
    creates = len(re.findall(r'self\.play\((Create|Write|FadeIn)\(', code))
    fadeouts = len(re.findall(r'self\.play\(FadeOut\(', code))
    clear_all = len(re.findall(r'FadeOut\(\*self\.mobjects\)', code))

    effective_cleanup = fadeouts + (clear_all * 5)  # each clear_all removes ~5 objects

    if creates > 6 and effective_cleanup < creates * 0.3:
        warnings.append(
            f"[ACCUMULATION] {creates} objects created but only ~{effective_cleanup} "
            f"cleaned up. Risk of cluttered screen. Add FadeOut calls between sections."
        )

    return warnings


def detect_missing_section_cleanup(code: str) -> List[str]:
    """Detect comment-based sections (# === SCENE/SECTION) without cleanup."""
    warnings = []
    lines = code.splitlines()
    section_starts = []

    for i, line in enumerate(lines):
        if re.match(r'\s*#\s*={3,}\s*(SCENE|SECTION|PART|STEP)\s', line, re.IGNORECASE):
            section_starts.append(i)

    for idx in range(1, len(section_starts)):
        prev_end = section_starts[idx]
        # Look at the 5 lines before this section header for cleanup
        window_start = max(section_starts[idx - 1], prev_end - 8)
        window = "\n".join(lines[window_start:prev_end])
        has_cleanup = (
            "FadeOut" in window
            or "self.remove" in window
            or "end_section" in window
        )
        if not has_cleanup:
            warnings.append(
                f"[NO_CLEANUP] Section at line {prev_end + 1} starts without "
                f"FadeOut/cleanup of previous section's objects."
            )

    return warnings


def detect_long_construct(code: str) -> List[str]:
    """Warn if construct() is excessively long without section helpers."""
    warnings = []
    # Count self.play calls as proxy for complexity
    play_count = len(re.findall(r'self\.play\(', code))
    has_helpers = "start_section" in code or "end_section" in code or "clear_except" in code

    if play_count > 25 and not has_helpers:
        warnings.append(
            f"[COMPLEXITY] construct() has {play_count} self.play() calls without "
            f"section lifecycle helpers. High risk of object accumulation."
        )

    return warnings


def detect_stale_copies(code: str) -> List[str]:
    """Detect .copy() usage where the original isn't removed."""
    warnings = []
    copy_matches = list(re.finditer(r'(\w+)\.copy\(\)', code))

    for m in copy_matches:
        original_var = m.group(1)
        after_copy = code[m.end():]
        # Check next 20 lines for FadeOut of original
        after_lines = after_copy.split("\n")[:20]
        after_text = "\n".join(after_lines)
        if f"FadeOut({original_var}" not in after_text and f"self.remove({original_var}" not in after_text:
            line_no = code[:m.start()].count("\n") + 1
            warnings.append(
                f"[STALE_COPY] Line {line_no}: {original_var}.copy() used but "
                f"original '{original_var}' is not removed. Both will render on screen."
            )

    return warnings


def run_all_checks(code: str) -> List[str]:
    """Run all overlap/hygiene checks. Returns list of warning strings."""
    warnings = []
    warnings.extend(detect_position_collisions(code))
    warnings.extend(detect_object_accumulation(code))
    warnings.extend(detect_missing_section_cleanup(code))
    warnings.extend(detect_long_construct(code))
    warnings.extend(detect_stale_copies(code))
    return warnings
