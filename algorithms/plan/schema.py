"""Plan JSON schema (v1) for scene-aware generation.

This module defines a minimal, explicit schema (as Python dataclasses + helpers)
for a *plan-first* animation pipeline.

Design goals:
- Stable object IDs: every object has an `id` that persists across beats.
- Explicit zones: top / center / bottom (frame regions) to reduce clutter.
- Deterministic compilation: plan -> Manim code without LLM creativity.
- Backward compatible: can adapt from existing narrated segments JSON.

NOTE: This is a pragmatic schema (not full JSON Schema draft). It is intended
for internal validation + compilation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple


Zone = Literal["top", "center", "bottom", "full"]


@dataclass
class Style:
    color: Optional[str] = None  # Manim color constant name: BLUE, YELLOW, etc.
    font_size: Optional[int] = None
    stroke_width: Optional[float] = None
    stroke_opacity: Optional[float] = None
    fill_opacity: Optional[float] = None
    weight: Optional[str] = None  # e.g., "BOLD" for Text, best-effort


@dataclass
class ObjectSpec:
    """A single scene object (mobject) spec.

    `kind` is compiled into a concrete Manim constructor.
    `params` is a restricted dict (compiler-controlled) to avoid arbitrary code.
    """

    id: str
    kind: Literal[
        "Text",
        "MathTex",
        "VGroup",
        "NumberPlane",
        "Axes",
        "Dot",
        "Line",
        "Arrow",
        "Rectangle",
        "Circle",
        "Square",
        "Polygon",
    ]
    zone: Zone = "center"
    style: Style = field(default_factory=Style)
    params: Dict[str, Any] = field(default_factory=dict)
    children: List[str] = field(default_factory=list)  # for VGroup


@dataclass
class PlaceSpec:
    """Placement instruction.

    anchor:
      - edge: UP/DOWN/LEFT/RIGHT
      - point: explicit frame coordinates
      - relative: relative to another object id
    """

    mode: Literal["zone", "edge", "point", "relative"] = "zone"
    edge: Optional[Literal["UP", "DOWN", "LEFT", "RIGHT"]] = None
    buff: float = 0.3
    point: Optional[Tuple[float, float]] = None
    relative_to: Optional[str] = None
    rel_dir: Optional[Literal["UP", "DOWN", "LEFT", "RIGHT"]] = None
    rel_buff: float = 0.3


@dataclass
class BeatAction:
    """A deterministic action on objects.

    Allowed actions are intentionally small and map to standard Manim animations.
    """

    op: Literal[
        "create",
        "write",
        "fade_in",
        "fade_out",
        "transform",
        "move_to",
        "arrange",
        "set_color",
        "wait",
    ]
    target: Optional[str] = None
    source: Optional[str] = None  # for transform
    run_time: Optional[float] = None
    wait: Optional[float] = None
    place: Optional[PlaceSpec] = None
    arrange_dir: Optional[Literal["DOWN", "UP", "LEFT", "RIGHT"]] = None
    arrange_buff: Optional[float] = None
    color: Optional[str] = None


@dataclass
class Beat:
    id: str
    title: str = ""
    actions: List[BeatAction] = field(default_factory=list)


@dataclass
class Plan:
    """Top-level plan."""

    version: str
    meta: Dict[str, Any] = field(default_factory=dict)
    objects: List[ObjectSpec] = field(default_factory=list)
    beats: List[Beat] = field(default_factory=list)


def as_dict(plan: Plan) -> Dict[str, Any]:
    """Serialize dataclasses to plain dict for JSON."""
    from dataclasses import asdict

    return asdict(plan)


def validate_plan_dict(data: Dict[str, Any]) -> List[str]:
    """Lightweight validation of required keys and object IDs."""
    issues: List[str] = []
    if not isinstance(data, dict):
        return ["Plan must be a JSON object"]

    if data.get("version") != "v1":
        issues.append("Missing/unsupported plan.version (expected 'v1')")

    objs = data.get("objects")
    if not isinstance(objs, list) or not objs:
        issues.append("Plan.objects must be a non-empty list")
        return issues

    ids = []
    for o in objs:
        if not isinstance(o, dict):
            issues.append("Each object must be an object")
            continue
        oid = o.get("id")
        if not oid or not isinstance(oid, str):
            issues.append("Object missing string id")
        else:
            ids.append(oid)

    if len(set(ids)) != len(ids):
        issues.append("Duplicate object ids")

    beats = data.get("beats")
    if not isinstance(beats, list) or not beats:
        issues.append("Plan.beats must be a non-empty list")

    return issues


def adapt_from_narrated_segments(narrated: Dict[str, Any]) -> Dict[str, Any]:
    """Backward-compat adapter.

    Existing `create_narrated_plan()` returns:
      {"segments": [{"id","title","narration","visual_description","estimated_duration"}, ...]}

    This adapter maps segments -> beats with placeholder actions.
    The new pipeline will eventually have the LLM emit full plan JSON directly.
    """
    segments = narrated.get("segments") or []
    objects: List[Dict[str, Any]] = [
        {
            "id": "title",
            "kind": "Text",
            "zone": "top",
            "style": {"font_size": 40, "color": "BLUE"},
            "params": {"text": ""},
        },
        {
            "id": "caption",
            "kind": "Text",
            "zone": "bottom",
            "style": {"font_size": 28, "color": "WHITE"},
            "params": {"text": ""},
        },
    ]

    beats: List[Dict[str, Any]] = []
    for seg in segments:
        sid = seg.get("id") or f"seg_{len(beats)+1}"
        title = seg.get("title") or sid
        narration = (seg.get("narration") or "").strip()
        est = seg.get("estimated_duration")
        wait = float(est) if est else 6.0
        beats.append(
            {
                "id": sid,
                "title": title,
                "actions": [
                    {"op": "transform", "target": "title", "source": "title", "run_time": 0.5},
                    {"op": "transform", "target": "caption", "source": "caption", "run_time": 0.5},
                    # Placeholder: keep narration for later sync; visuals not yet structured.
                    {"op": "wait", "wait": max(2.0, min(wait, 15.0))},
                ],
                "_legacy": {
                    "narration": narration,
                    "visual_description": seg.get("visual_description"),
                },
            }
        )

    return {
        "version": "v1",
        "meta": {"source": "legacy_narrated_segments"},
        "objects": objects,
        "beats": beats,
    }
