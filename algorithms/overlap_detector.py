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

import re
from typing import Dict, List, Tuple


EDGE_POSITION_TOKENS = [
    "edge:UP",
    "edge:DOWN",
    "edge:LEFT",
    "edge:RIGHT",
    "edge:ORIGIN",
]


def _extract_vgroup_children(code: str) -> Dict[str, List[str]]:
    """Extract VGroup variable -> direct child variable names."""
    vgroup_children: Dict[str, List[str]] = {}
    lines = code.splitlines()

    vgroup_pattern = re.compile(r"(\w+)\s*=\s*VGroup\(([^)]+)\)")
    for i, line in enumerate(lines, 1):
        vm = vgroup_pattern.search(line)
        if vm:
            vg_var = vm.group(1)
            children_str = vm.group(2)
            children = [c.strip() for c in children_str.split(",")]
            vgroup_children[vg_var] = children

    return vgroup_children


def _extract_positions(code: str) -> List[Tuple[str, str, int]]:
    """Extract (variable_or_desc, position_expr, line_no) from move_to / to_edge calls."""
    results = []
    vgroup_children = _extract_vgroup_children(code)

    for i, line in enumerate(code.splitlines(), 1):
        stripped = line.strip()
        m = re.search(r"(\w+)\.move_to\((.+?)\)", stripped)
        if m:
            var_name, pos_expr = m.group(1), m.group(2).strip()
            if var_name in vgroup_children:
                for child in vgroup_children[var_name]:
                    norm_pos = _normalize_pos(pos_expr)
                    results.append((f"{var_name}.{child}", f"{norm_pos}@child", i))
            else:
                results.append((var_name, _normalize_pos(pos_expr), i))
        elif ").move_to(" in stripped:
            assign_m = re.match(r"\s*(\w+)\s*=\s*.+\.move_to\((.+?)\)", stripped)
            if assign_m:
                var_name, pos_expr = assign_m.group(1), assign_m.group(2).strip()
                if var_name in vgroup_children:
                    for child in vgroup_children[var_name]:
                        norm_pos = _normalize_pos(pos_expr)
                        results.append((f"{var_name}.{child}", f"{norm_pos}@child", i))
                else:
                    results.append((var_name, _normalize_pos(pos_expr), i))
        m = re.search(r"(\w+)\.to_edge\(([^,)]+)", stripped)
        if m:
            var_name, edge_expr = m.group(1), m.group(2).strip()
            if var_name in vgroup_children:
                for child in vgroup_children[var_name]:
                    results.append(
                        (f"{var_name}.{child}", _normalize_edge_pos(edge_expr), i)
                    )
            else:
                results.append((var_name, _normalize_edge_pos(edge_expr), i))

    return results


def _normalize_pos(expr: str) -> str:
    """Normalize position expressions for comparison."""
    expr = expr.replace(" ", "")
    if expr.startswith("np.array([") and not expr.endswith("])"):
        expr = expr + ")"
    if expr.startswith("(") and not expr.endswith(")"):
        expr = expr + ")"
    expr = expr.replace("ORIGIN+UP*0.0", "ORIGIN")
    expr = expr.replace("np.array([0,0,0])", "ORIGIN")
    np_m = re.search(
        r"np\.array\(\[([+-]?[0-9.]+\s*,\s*[+-]?[0-9.]+(?:\s*,\s*[+-]?[0-9.]+)?)\]\)",
        expr,
    )
    if np_m:
        return f"tup:{np_m.group(1).replace(' ', '')}"
    tup_m = re.fullmatch(
        r"\(([+-]?[0-9.]+)\s*,\s*([+-]?[0-9.]+)(?:\s*,\s*([+-]?[0-9.]+))?\)",
        expr,
    )
    if tup_m:
        coords = ",".join([g for g in tup_m.groups() if g is not None])
        return f"tup:{coords}"
    return _normalize_edge_pos(expr)


def _normalize_edge_pos(expr: str) -> str:
    """Normalize edge position expressions (UP, DOWN, LEFT, RIGHT, ORIGIN)."""
    clean = expr.replace(" ", "")

    to_edge_m = re.search(r"to_edge\(([^,)]+)", clean)
    if to_edge_m:
        clean = to_edge_m.group(1)

    edge_tokens = [
        t for t in re.findall(r"\b(UP|DOWN|LEFT|RIGHT|ORIGIN)\b", clean) if t
    ]
    if not edge_tokens:
        return clean

    unique_tokens = []
    for token in edge_tokens:
        if token not in unique_tokens:
            unique_tokens.append(token)

    if len(unique_tokens) == 1:
        return f"edge:{unique_tokens[0]}"

    ordered = [
        t for t in ["UP", "DOWN", "LEFT", "RIGHT", "ORIGIN"] if t in unique_tokens
    ]
    return "edge:" + "+".join(ordered)


def _has_removal_between(between: str, var_name: str) -> bool:
    """Best-effort detection that an object is removed/hidden between placements."""
    base_var = var_name.split(".")[0]
    patterns = [
        rf"FadeOut\(\s*{re.escape(var_name)}\s*\)",
        rf"FadeOut\(\s*{re.escape(base_var)}\s*\)",
        rf"self\.remove\(\s*{re.escape(var_name)}\s*\)",
        rf"self\.remove\(\s*{re.escape(base_var)}\s*\)",
        rf"FadeOut\(\*self\.mobjects\)",
        rf"(?:ReplacementTransform|Transform|FadeTransform|TransformMatching\w*)\(\s*{re.escape(base_var)}\s*,",
        rf"{re.escape(base_var)}\.animate\.[^\n]*set_opacity\(\s*0(?:\.0+)?\s*\)",
        rf"{re.escape(base_var)}\.set_opacity\(\s*0(?:\.0+)?\s*\)",
        rf"{re.escape(base_var)}\.animate\.[^\n]*fade\(\s*1(?:\.0+)?\s*\)",
    ]
    return any(re.search(pattern, between) for pattern in patterns)


def detect_position_collisions(code: str) -> List[str]:
    """Find multiple objects placed at the same position without FadeOut between them."""
    warnings = []
    positions = _extract_positions(code)
    lines = code.splitlines()

    pos_map = {}
    for var, pos_expr, line_no in positions:
        norm = _normalize_pos(pos_expr)
        if norm not in pos_map:
            pos_map[norm] = []
        pos_map[norm].append((var, line_no))

    for pos, placements in pos_map.items():
        if len(placements) < 2:
            continue
        sorted_placements = sorted(placements, key=lambda x: x[1])
        for i in range(len(sorted_placements) - 1):
            var_a, line_a = sorted_placements[i]
            var_b, line_b = sorted_placements[i + 1]
            if var_a.startswith("_"):
                continue
            if var_b.startswith("_"):
                continue
            if var_a == var_b:
                continue

            between = "\n".join(lines[line_a : line_b - 1])
            has_removal = _has_removal_between(between, var_a)
            if not has_removal:
                warnings.append(
                    f"[OVERLAP] Line {line_a} ({var_a}) and line {line_b} ({var_b}) "
                    f"both placed at {pos} with no FadeOut of {var_a} between them."
                )

    return warnings


def detect_object_accumulation(code: str) -> List[str]:
    """Detect too many Create/Write/FadeIn calls without corresponding FadeOut."""
    warnings = []
    creates = len(re.findall(r"self\.play\((Create|Write|FadeIn)\(", code))
    fadeouts = len(re.findall(r"self\.play\(FadeOut\(", code))
    clear_all = len(re.findall(r"FadeOut\(\*self\.mobjects\)", code))

    helpers_present = "def start_section" in code and "def end_section" in code
    start_count = len(re.findall(r"start_section\(self", code))
    end_count = len(re.findall(r"end_section\(", code))
    helpers_used = start_count >= 2 and end_count >= 1

    size_weights = {
        "NumberPlane": 5,
        "ComplexPlane": 5,
        "MathTex": 3,
        "Axes": 2,
    }
    weighted_creates = creates
    for obj_type, weight in size_weights.items():
        count = len(re.findall(rf"({obj_type})\(", code))
        weighted_creates += count * (weight - 1)

    effective_cleanup = fadeouts + (clear_all * 5)

    if helpers_present and start_count > 0 and end_count == 0:
        warnings.append(
            "[SECTION_HELPERS_UNUSED] start_section called but no end_section found. "
            "For multi-step scenes you MUST wrap steps in start_section()/end_section() "
            "and add created objects to the returned `section` group."
        )

    if helpers_present and not helpers_used:
        warnings.append(
            "[SECTION_HELPERS_UNUSED] Helpers are injected but not used. "
            "For multi-step scenes you MUST wrap steps in start_section()/end_section() "
            "and add created objects to the returned `section` group."
        )

    if creates > 10 and effective_cleanup < creates * 0.4:
        warnings.append(
            f"[ACCUMULATION] {creates} objects created but only ~{effective_cleanup} "
            f"cleaned up. Risk of cluttered screen. Use section lifecycle helpers or add FadeOut between steps."
        )

    return warnings


def detect_missing_section_cleanup(code: str) -> List[str]:
    """Detect comment-based sections and section helper misuse without cleanup."""
    warnings = []
    lines = code.splitlines()
    section_starts = []

    for i, line in enumerate(lines):
        if re.match(r"\s*#\s*={3,}\s*(SCENE|SECTION|PART|STEP)\s", line, re.IGNORECASE):
            section_starts.append(i)

    start_section_stacks = []
    section_add_objects = {}

    for i, line in enumerate(lines):
        start_m = re.search(r"(\w+)\s*=\s*start_section\(self", line)
        if start_m:
            section_var = start_m.group(1)
            start_section_stacks.append((section_var, i))
            section_add_objects[section_var] = []
        end_m = re.search(r"(\w+)\.end\(", line)
        if end_m and start_section_stacks:
            section_var, start_line = start_section_stacks.pop()
        add_m = re.search(r"(\w+)\.add\(([^)]+)\)", line)
        if add_m and start_section_stacks:
            section_var, _ = start_section_stacks[-1]
            section_add_objects.setdefault(section_var, []).append(add_m.group(2))

    if start_section_stacks:
        warnings.append(
            f"[SECTION_LEAK] start_section at line {start_section_stacks[-1][1] + 1} "
            f"has no end_section. Objects may persist across section boundaries."
        )

    for idx in range(1, len(section_starts)):
        prev_end = section_starts[idx]
        window_start = max(section_starts[idx - 1], prev_end - 15)
        window = "\n".join(lines[window_start:prev_end])
        has_cleanup = (
            "FadeOut" in window
            or "self.remove" in window
            or "end_section" in window
            or "*self.mobjects" in window
        )
        if not has_cleanup:
            warnings.append(
                f"[NO_CLEANUP] Section at line {prev_end + 1} starts without "
                f"FadeOut/cleanup of previous section's objects."
            )

    return warnings


def detect_section_leak(code: str) -> List[str]:
    """Detect objects that persist across section boundaries without being in a section group."""
    warnings = []
    lines = code.splitlines()

    section_ranges = []
    in_section = False
    section_start = 0
    section_var = None
    section_vars = set()

    for i, line in enumerate(lines):
        start_m = re.search(r"(\w+)\s*=\s*start_section\(self", line)
        if start_m:
            in_section = True
            section_start = i
            section_var = start_m.group(1)
            section_vars.add(section_var)
        end_m = re.search(r"(\w+)\.end\(", line)
        if end_m and in_section:
            section_ranges.append((section_start, i, section_var))
            in_section = False
            section_var = None

    if in_section and section_start > 0:
        section_ranges.append((section_start, len(lines) - 1, section_var))

    created_objects = {}
    for i, line in enumerate(lines):
        assign_m = re.match(r"\s*(\w+)\s*=\s*(.+?)\(", line)
        if assign_m and "self.play" not in line and "def " not in line:
            var_name = assign_m.group(1)
            obj_type = assign_m.group(2).strip()
            if var_name not in created_objects:
                created_objects[var_name] = (i, obj_type)

    for start, end, sec_var in section_ranges:
        section_content = "\n".join(lines[start:end])
        section_creates = re.findall(
            r"(\w+)\s*=\s*(?:VGroup|NumberPlane|ComplexPlane|Axes|MathTex|Text|Circle|Square|Dot|Line|Arrow)\(",
            section_content,
        )
        if not section_creates:
            continue
        after_section_start = end + 1
        if after_section_start >= len(lines):
            continue
        after_section = "\n".join(
            lines[after_section_start : min(after_section_start + 30, len(lines))]
        )
        next_section_m = re.search(
            r"start_section\(", "\n".join(lines[after_section_start:])
        )
        next_section_line = (
            next_section_m.start() + after_section_start
            if next_section_m
            else len(lines)
        )
        after_section_window = "\n".join(lines[after_section_start:next_section_line])
        for obj in section_creates:
            if obj not in section_vars and obj in created_objects:
                obj_line, _ = created_objects[obj]
                if (
                    f"FadeOut({obj})" not in after_section_window
                    and f"self.remove({obj})" not in after_section_window
                ):
                    warnings.append(
                        f"[SECTION_LEAK] Object '{obj}' created in section at line {obj_line + 1} "
                        f"appears in next section without cleanup. Use FadeOut({obj}) or add to section group."
                    )

    return warnings


def detect_long_construct(code: str) -> List[str]:
    """Warn if construct() is excessively long without section lifecycle helpers."""
    warnings = []
    play_count = len(re.findall(r"self\.play\(", code))

    # "has helpers" means the INJECTED helpers are actually used in the code.
    # The model sometimes defines its own start_section/end_section wrappers;
    # that doesn't guarantee tracking/cleanup.
    uses_injected_section = (
        re.search(r"\bsec\s*=\s*start_section\(", code) is not None
        or re.search(r"\bsec\.end\(\)", code) is not None
    )

    if play_count > 25 and not uses_injected_section:
        warnings.append(
            f"[SECTION_HELPERS_UNUSED] Helpers are injected but not used. "
            f"For multi-step scenes you MUST wrap steps in start_section()/end_section() "
            f"and add created objects to the returned `section` group."
        )
        warnings.append(
            f"[COMPLEXITY] construct() has {play_count} self.play() calls without "
            f"tracked section lifecycle. High risk of object accumulation."
        )

    return warnings


def detect_stale_copies(code: str) -> List[str]:
    """Detect .copy() usage where the original isn't removed."""
    warnings = []
    copy_matches = list(re.finditer(r"(\w+)\.copy\(\)", code))

    for m in copy_matches:
        original_var = m.group(1)
        after_copy = code[m.end() :]
        # Check next 20 lines for FadeOut of original
        after_lines = after_copy.split("\n")[:20]
        after_text = "\n".join(after_lines)
        if (
            f"FadeOut({original_var}" not in after_text
            and f"self.remove({original_var}" not in after_text
        ):
            line_no = code[: m.start()].count("\n") + 1
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
    warnings.extend(detect_section_leak(code))
    warnings.extend(detect_long_construct(code))
    warnings.extend(detect_stale_copies(code))
    return warnings
