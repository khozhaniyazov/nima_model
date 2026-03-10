"""Deterministic layout engine for plan->Manim compilation.

The goal is not to be "smart" like an LLM; it's to be predictable:
- Assign each object a placement based on zone + simple packing.
- Ensure the top and bottom zones are reserved for title/caption.
- Provide a single function `apply_layout(mob, spec)` that the compiler can call.

This is a v1 layout engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional, Tuple


Zone = Literal["top", "center", "bottom", "full"]


@dataclass
class Frame:
    width: float
    height: float


@dataclass
class ZoneBox:
    # center position and max size
    cx: float
    cy: float
    w: float
    h: float


def zones(frame: Frame, margin: float = 0.6) -> Dict[Zone, ZoneBox]:
    """Return canonical zone boxes in Manim frame coordinates."""
    # Manim frame is centered at (0,0)
    w = frame.width
    h = frame.height

    top_h = 0.12 * h
    bottom_h = 0.16 * h
    center_h = h - top_h - bottom_h

    return {
        "top": ZoneBox(0.0, (h / 2) - (top_h / 2), w - margin, top_h - margin * 0.3),
        "bottom": ZoneBox(0.0, (-h / 2) + (bottom_h / 2), w - margin, bottom_h - margin * 0.3),
        "center": ZoneBox(0.0, 0.0, w - margin, center_h - margin),
        "full": ZoneBox(0.0, 0.0, w - margin, h - margin),
    }


def fit_into_box(mob, box: ZoneBox, pad: float = 0.0):
    """Scale mob down (never up) to fit within box."""
    max_w = max(0.1, box.w - pad)
    max_h = max(0.1, box.h - pad)
    if mob.width > max_w:
        mob.scale(max_w / mob.width)
    if mob.height > max_h:
        mob.scale(max_h / mob.height)
    return mob


def place_in_zone(mob, zone: Zone, frame: Frame):
    b = zones(frame)[zone]
    mob.move_to((b.cx, b.cy, 0))
    return mob


def apply_zone_layout(mob, zone: Zone, frame: Frame):
    """Fit and place a single mob into its zone."""
    b = zones(frame)[zone]
    fit_into_box(mob, b, pad=0.2)
    place_in_zone(mob, zone, frame)
    return mob


def apply_edge_layout(mob, edge: str, buff: float = 0.3):
    """Defer to Manim's to_edge at runtime (compiler emits this call)."""
    return mob


def point_to_manim(point: Tuple[float, float]):
    return (float(point[0]), float(point[1]), 0.0)
