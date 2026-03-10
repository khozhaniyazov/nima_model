"""Plan -> Manim deterministic compiler (v1).

This compiler intentionally supports a limited subset of objects and actions.
It is designed to be extended, but should remain deterministic.

Usage:
  code = compile_plan(plan_dict)

The output code:
- Uses a stable `objs` dict keyed by object id.
- Applies deterministic placement based on `zone`.
- Emits Manim animations for each beat action.

Security model:
- Plan is treated as data; compiler emits known-safe Manim code only.
- No arbitrary code strings are executed.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from algorithms.plan.schema import validate_plan_dict


def _py(s: str) -> str:
    """Return a Python string literal."""
    return json.dumps(s)


def _style_lines(style: Dict[str, Any], var: str) -> List[str]:
    out: List[str] = []
    if not style:
        return out
    color = style.get("color")
    if color:
        out.append(f"{var}.set_color({color})")
    # stroke/fill
    if style.get("stroke_width") is not None:
        out.append(f"{var}.set_stroke(width={float(style['stroke_width'])})")
    if style.get("stroke_opacity") is not None:
        out.append(f"{var}.set_stroke(opacity={float(style['stroke_opacity'])})")
    if style.get("fill_opacity") is not None:
        out.append(f"{var}.set_fill(opacity={float(style['fill_opacity'])})")
    return out


def _is_math_text(s: str) -> bool:
    if not s:
        return False
    math_tokens = ["^", "_", "\\", "ℝ", "→", "∈", "≅", "≤", "≥", "≠", "±", "×", "·", "√", "π"]
    return any(t in s for t in math_tokens)


def _ctor(obj: Dict[str, Any]) -> str:
    kind = obj["kind"]
    params = obj.get("params") or {}

    # Auto-upgrade Text to MathTex if it looks like math
    if kind == "Text":
        text = params.get("text", "")
        if _is_math_text(text):
            fs = obj.get("style", {}).get("font_size")
            if fs:
                return f"MathTex({_py(text)}, font_size={int(fs)})"
            return f"MathTex({_py(text)})"

    if kind == "Text":
        text = params.get("text", "")
        fs = obj.get("style", {}).get("font_size")
        if fs:
            return f"Text({_py(text)}, font_size={int(fs)})"
        return f"Text({_py(text)})"

    if kind == "MathTex":
        tex = params.get("tex", "")
        fs = obj.get("style", {}).get("font_size")
        if fs:
            return f"MathTex({_py(tex)}, font_size={int(fs)})"
        return f"MathTex({_py(tex)})"

    if kind == "VGroup":
        children = obj.get("children") or []
        args = ", ".join([f"objs[{_py(cid)}]" for cid in children])
        return f"VGroup({args})"

    if kind == "NumberPlane":
        # enforce subtle styling
        return (
            "NumberPlane(\n"
            "    x_range=[-5,5], y_range=[-4,4],\n"
            "    background_line_style={\"stroke_opacity\": 0.15},\n"
            "    faded_line_style={\"stroke_opacity\": 0.08},\n"
            "    faded_line_ratio=3,\n"
            ")"
        )

    if kind == "Axes":
        return "Axes(x_range=[-5,5,1], y_range=[-4,4,1])"

    if kind == "Dot":
        return "Dot()"

    if kind == "Line":
        return "Line(LEFT, RIGHT)"

    if kind == "Arrow":
        return "Arrow(LEFT, RIGHT)"

    if kind == "Rectangle":
        return "Rectangle()"

    if kind == "Circle":
        return "Circle()"

    if kind == "Square":
        return "Square()"

    if kind == "Polygon":
        return "Polygon(LEFT, RIGHT, UP)"

    raise ValueError(f"Unsupported kind: {kind}")


def compile_plan(plan: Dict[str, Any]) -> str:
    issues = validate_plan_dict(plan)
    if issues:
        raise ValueError("Invalid plan: " + "; ".join(issues))

    objects = plan["objects"]
    beats = plan["beats"]

    lines: List[str] = []
    a = lines.append

    a("from manim import *")
    a("import numpy as np")
    a("")
    a("# Auto-compiled from plan JSON (v1)")
    a("")
    a("class GeneratedScene(Scene):")
    a("    def construct(self):")
    a("        objs = {}  # id -> mobject")
    a("        # Frame dims (Manim config)")
    a("        fw = config.frame_width")
    a("        fh = config.frame_height")
    a("")

    # Instantiate objects
    for obj in objects:
        oid = obj["id"]
        var = f"o_{oid}".replace("-", "_")
        a(f"        {var} = {_ctor(obj)}")
        # style
        for sl in _style_lines(obj.get("style") or {}, var):
            a(f"        {sl}")
        # opacity for NumberPlane
        if obj["kind"] == "NumberPlane":
            a(f"        {var}.set_opacity(0.3)")
        # zone placement
        zone = obj.get("zone", "center")
        if zone == "top":
            a(f"        {var}.to_edge(UP, buff=0.3)")
        elif zone == "bottom":
            a(f"        {var}.to_edge(DOWN, buff=0.4)")
        elif zone == "center":
            a(f"        {var}.move_to(ORIGIN)")
        else:
            a(f"        {var}.move_to(ORIGIN)")
        a(f"        objs[{_py(oid)}] = {var}")
        a("")

    # Beats/actions
    for beat in beats:
        bid = beat.get("id", "")
        title = beat.get("title", "")
        a(f"        # === BEAT {bid}: {title} ===")
        actions = beat.get("actions") or []
        for act in actions:
            op = act.get("op")
            rt = act.get("run_time")
            rt_s = f", run_time={float(rt)}" if rt is not None else ""

            if op in ("create", "write", "fade_in"):
                tgt = act["target"]
                anim = {"create": "Create", "write": "Write", "fade_in": "FadeIn"}[op]
                a(f"        self.play({anim}(objs[{_py(tgt)}]){rt_s})")

            elif op == "fade_out":
                tgt = act["target"]
                a(f"        self.play(FadeOut(objs[{_py(tgt)}]){rt_s})")

            elif op == "transform":
                tgt = act["target"]
                src = act.get("source") or tgt
                a(f"        self.play(Transform(objs[{_py(tgt)}], objs[{_py(src)}]){rt_s})")

            elif op == "move_to":
                tgt = act["target"]
                place = act.get("place") or {}
                mode = place.get("mode", "zone")
                if mode == "edge":
                    edge = place.get("edge", "UP")
                    buff = float(place.get("buff", 0.3))
                    a(f"        self.play(objs[{_py(tgt)}].animate.to_edge({edge}, buff={buff}){rt_s})")
                elif mode == "point":
                    pt = place.get("point") or [0, 0]
                    a(f"        self.play(objs[{_py(tgt)}].animate.move_to(({float(pt[0])}, {float(pt[1])}, 0)){rt_s})")
                else:
                    a(f"        self.play(objs[{_py(tgt)}].animate.move_to(ORIGIN){rt_s})")

            elif op == "arrange":
                tgt = act["target"]
                d = act.get("arrange_dir", "DOWN")
                buff = float(act.get("arrange_buff", 0.4))
                a(f"        objs[{_py(tgt)}].arrange({d}, buff={buff})")

            elif op == "set_color":
                tgt = act["target"]
                color = act.get("color", "WHITE")
                a(f"        objs[{_py(tgt)}].set_color({color})")

            elif op == "wait":
                w = float(act.get("wait", 1.0))
                a(f"        self.wait({w})")

            else:
                raise ValueError(f"Unsupported action op: {op}")

        a("")

    # Ensure non-empty
    a("        self.wait(0.1)")
    a("")

    return "\n".join(lines)


def compile_plan_json(plan_json: str) -> str:
    return compile_plan(json.loads(plan_json))
