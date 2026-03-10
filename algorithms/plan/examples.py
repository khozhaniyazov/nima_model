"""Example plan JSON documents (v1).

These are meant for unit/manual testing of the compiler.
"""

from __future__ import annotations

from typing import Dict, Any


def minimal_title_and_caption() -> Dict[str, Any]:
    return {
        "version": "v1",
        "meta": {"name": "minimal_title_and_caption"},
        "objects": [
            {
                "id": "title",
                "kind": "Text",
                "zone": "top",
                "style": {"font_size": 44, "color": "BLUE"},
                "params": {"text": "System Operational"},
            },
            {
                "id": "caption",
                "kind": "Text",
                "zone": "bottom",
                "style": {"font_size": 28, "color": "WHITE"},
                "params": {"text": "A plan-first Manim pipeline."},
            },
            {
                "id": "plane",
                "kind": "NumberPlane",
                "zone": "center",
                "style": {},
                "params": {},
            },
        ],
        "beats": [
            {
                "id": "beat_1",
                "title": "Intro",
                "actions": [
                    {"op": "create", "target": "plane", "run_time": 1.0},
                    {"op": "write", "target": "title", "run_time": 0.8},
                    {"op": "fade_in", "target": "caption", "run_time": 0.6},
                    {"op": "wait", "wait": 2.0},
                ],
            }
        ],
    }
