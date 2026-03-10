"""Template registry derived from Figma exports.

These are *layout blueprints* used to guide plan-JSON generation.
The LLM fills the content slots, but the structure is fixed.
"""
from typing import Optional

TEMPLATES = {
    "two_panel_comparison": {
        "name": "Two-Panel Comparison",
        "slots": [
            "title",
            "left_label", "left_items",
            "right_label", "right_items",
            "arrow_label",
            "caption",
            "callout",
            "highlight_side",
        ],
        "beats": 5,
        "palette": ["#58c4dd", "#ff6b6b", "#83c167", "#1a1a2e"],
        "notes": (
            "Layout: title top; center has left panel, arrow, right panel; caption bottom; optional callout. "
            "Use consistent left/right panels across beats; change highlight_side per beat. "
            "Use palette colors for accents and keep background dark."
        ),
    },
    "definition_to_example": {
        "name": "Definition → Example",
        "slots": [
            "title",
            "definition_label", "definition_text",
            "example_label", "example_text",
            "caption",
            "callout",
            "mode",  # definition | example | both
        ],
        "beats": 6,
        "notes": (
            "Layout: top title; center has definition block and/or example block; caption bottom; optional callout. "
            "Start with definition-only, then both, then example-only."
        ),
    },
    "step_by_step_derivation": {
        "name": "Step-by-Step Derivation",
        "slots": [
            "title",
            "steps",  # list of equations
            "visible_steps",
            "highlight_line",
            "caption",
            "callout",
        ],
        "beats": 5,
        "notes": (
            "Layout: title top; center is vertical list of equations; caption bottom; optional callout. "
            "Each beat reveals one more step; highlight latest or specified line."
        ),
    },
    "graph_and_formula": {
        "name": "Graph + Formula",
        "slots": [
            "title",
            "formula", "formula_note",
            "graph_points", "graph_color",
            "side_notes",
            "caption",
            "highlight_point",
            "callout",
        ],
        "beats": 5,
        "notes": (
            "Layout: title top; center has graph; right/side notes; formula near bottom-center; caption bottom."
        ),
    },
    "mapping_diagram": {
        "name": "Mapping Diagram",
        "slots": [
            "title",
            "nodes", "edges",
            "caption",
            "callout",
        ],
        "beats": 5,
        "notes": (
            "Layout: title top; center is node/edge diagram; caption bottom; optional callout. "
            "Use grouped columns (sets) and arrows."
        ),
    },
}


def choose_template(prompt: str, domain: str) -> Optional[str]:
    p = (prompt or "").lower()
    if domain == "math":
        if "isomorphism" in p or "mapping" in p or "bijection" in p:
            return "two_panel_comparison"
        if "composition" in p or "function" in p or "map" in p:
            return "mapping_diagram"
        if "derive" in p or "derivation" in p or "step" in p:
            return "step_by_step_derivation"
        if "graph" in p or "function" in p and "plot" in p:
            return "graph_and_formula"
        if "definition" in p or "example" in p:
            return "definition_to_example"
    return None
