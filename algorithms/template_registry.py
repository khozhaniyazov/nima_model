"""Template registry derived from Figma exports.

These are *layout blueprints* used to guide plan-JSON generation.
The LLM fills the content slots, but the structure is fixed.
"""

from typing import Optional

TEMPLATES = {
    # ── MATH TEMPLATES ─────────────────────────────────────────────────────────
    "two_panel_comparison": {
        "name": "Two-Panel Comparison",
        "slots": [
            "title",
            "left_label",
            "left_items",
            "right_label",
            "right_items",
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
            "definition_label",
            "definition_text",
            "example_label",
            "example_text",
            "caption",
            "callout",
            "mode",
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
            "steps",
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
            "formula",
            "formula_note",
            "graph_points",
            "graph_color",
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
        "slots": ["title", "nodes", "edges", "caption", "callout"],
        "beats": 5,
        "notes": (
            "Layout: title top; center is node/edge diagram; caption bottom; optional callout. "
            "Use grouped columns (sets) and arrows."
        ),
    },
    "derivative_exploration": {
        "name": "Derivative Exploration",
        "slots": [
            "title",
            "function_tex",
            "derivative_tex",
            "tangent_point",
            "slope_value",
            "caption",
            "callout",
        ],
        "beats": 6,
        "notes": (
            "Layout: title top; center shows axes with graph; tangent line animates; slope value updates. "
            "Use ValueTracker for smooth tangent animation. Show secant→tangent transition."
        ),
    },
    "sequence_convergence": {
        "name": "Sequence Convergence",
        "slots": [
            "title",
            "sequence_formula",
            "limit_value",
            "nth_term",
            "caption",
            "callout",
        ],
        "beats": 5,
        "notes": (
            "Layout: title top; center shows number line with dot animating toward limit. "
            "Use ValueTracker for dot position. Show formula and nth term updating."
        ),
    },
    "matrix_transform": {
        "name": "Matrix Linear Transformation",
        "slots": [
            "title",
            "matrix_tex",
            "eigenvector_tex",
            "determinant_value",
            "caption",
            "callout",
        ],
        "beats": 7,
        "notes": (
            "Layout: title top; center shows NumberPlane with unit square and basis vectors i_hat, j_hat. "
            "FIRST: show basis vectors. SECOND: show unit square. THIRD: apply matrix transform to all three. "
            "Use subtle grid styling (stroke_opacity=0.15). Focus on vectors, not grid."
        ),
    },
    "area_under_curve": {
        "name": "Area Under Curve (Riemann Sums)",
        "slots": [
            "title",
            "function_tex",
            "integral_result",
            "n_rectangles",
            "caption",
            "callout",
        ],
        "beats": 6,
        "notes": (
            "Layout: title top; center shows axes with graph and shaded Riemann rectangles. "
            "Use ValueTracker for n (rectangle count). Show rectangles refining from 4 to 100."
        ),
    },
    "step_by_step_proof": {
        "name": "Step-by-Step Proof",
        "slots": [
            "title",
            "proof_steps",
            "current_step",
            "highlight_line",
            "caption",
            "callout",
        ],
        "beats": 8,
        "notes": (
            "Layout: title top; center shows equation with highlighted current step. "
            "Use TransformMatchingTex for elegant step transitions. Each beat shows one transformation."
        ),
    },
    # ── PHYSICS TEMPLATES (M2-TEMP-01) ──────────────────────────────────────────
    "wave_propagation": {
        "name": "Wave Propagation",
        "slots": [
            "title",
            "wave_type",
            "amplitude",
            "wavelength",
            "frequency",
            "caption",
            "callout",
        ],
        "beats": 6,
        "notes": (
            "Layout: title top; center shows axes with animated sine wave. "
            "Use ValueTracker for phase. Show wavelength and amplitude labels. "
            "Display wave equation and key parameters."
        ),
    },
    "field_visualization": {
        "name": "Field Visualization",
        "slots": ["title", "field_type", "charges", "caption", "callout"],
        "beats": 5,
        "notes": (
            "Layout: title top; center shows NumberPlane with ArrowVectorField. "
            "Use StreamLines for continuous fields. Show charge labels. "
            "Field arrows should scale with field strength."
        ),
    },
    "oscillation_motion": {
        "name": "Oscillation Motion",
        "slots": [
            "title",
            "oscillation_type",
            "amplitude",
            "period",
            "caption",
            "callout",
        ],
        "beats": 5,
        "notes": (
            "Layout: title top; center shows pendulum/spring with ValueTracker. "
            "Use always_redraw for smooth position updates. Show period and amplitude. "
            "Include energy bar chart showing KE/PE conversion."
        ),
    },
    # ── CS TEMPLATES (M2-TEMP-02) ──────────────────────────────────────────────
    "sorting_algorithm": {
        "name": "Sorting Algorithm",
        "slots": ["title", "algorithm_name", "data_items", "caption", "callout"],
        "beats": 8,
        "notes": (
            "Layout: title top; center shows array as VGroup of Rectangle+Text. "
            "Color YELLOW for active comparison, GREEN for sorted, RED for swap. "
            "Use Swap animation. Show pass number and comparison count."
        ),
    },
    "tree_traversal": {
        "name": "Tree Traversal",
        "slots": ["title", "traversal_type", "tree_structure", "caption", "callout"],
        "beats": 6,
        "notes": (
            "Layout: title top; center shows binary tree with Circle nodes and Line edges. "
            "Use Indicate for current node, color path GREEN. Build level-by-level. "
            "Show traversal order as list updating in real-time."
        ),
    },
    "graph_traversal": {
        "name": "Graph Traversal",
        "slots": [
            "title",
            "algorithm_name",
            "graph_structure",
            "start_node",
            "caption",
            "callout",
        ],
        "beats": 7,
        "notes": (
            "Layout: title top; center shows graph with Dot nodes and Line edges. "
            "Show visited set growing, frontier highlighted. Use color to show distance. "
            "Display queue/stack content as sidebar."
        ),
    },
    # ── CHEMISTRY TEMPLATES (M2-TEMP-03) ─────────────────────────────────────
    "reaction_mechanism": {
        "name": "Reaction Mechanism",
        "slots": [
            "title",
            "reaction_type",
            "reactants",
            "products",
            "caption",
            "callout",
        ],
        "beats": 7,
        "notes": (
            "Layout: title top; reactants LEFT, arrow CENTER, products RIGHT. "
            "Use CurvedArrow for electron movement. Animate bond breaking/forming. "
            "Show activation energy and reaction progress."
        ),
    },
    "orbital_visualization": {
        "name": "Electron Orbital",
        "slots": ["title", "element", "orbital_type", "caption", "callout"],
        "beats": 5,
        "notes": (
            "Layout: title top; center shows nucleus with concentric Circle shells. "
            "Place Dot electrons at correct positions. Show electron configuration. "
            "Animate shell filling order."
        ),
    },
    "molecule_building": {
        "name": "Molecule Building",
        "slots": ["title", "molecule_name", "atoms", "bonds", "caption", "callout"],
        "beats": 6,
        "notes": (
            "Layout: title top; build molecule step by step. "
            "Use CPK coloring: H=WHITE, C=GREY, O=RED, N=BLUE, S=YELLOW, Cl=GREEN. "
            "Use Dot for atoms, Line for bonds. Show molecular geometry."
        ),
    },
}


def choose_template(prompt: str, domain: str) -> Optional[str]:
    p = (prompt or "").lower()
    if domain == "math":
        if "derivative" in p or "tangent" in p or "slope" in p:
            return "derivative_exploration"
        if (
            "sequence" in p
            or "convergence" in p
            or "converge" in p
            or ("limit" in p and "n" in p)
        ):
            return "sequence_convergence"
        if (
            "matrix" in p
            or "transformation" in p
            or "linear algebra" in p
            or "eigenvector" in p
            or "determinant" in p
        ):
            return "matrix_transform"
        if (
            "area" in p
            and ("curve" in p or "graph" in p)
            or "integral" in p
            or "riemann" in p
        ):
            return "area_under_curve"
        if "isomorphism" in p or "mapping" in p or "bijection" in p:
            return "two_panel_comparison"
        if "composition" in p or ("function" in p and "map" in p):
            return "mapping_diagram"
        if "proof" in p:
            return "step_by_step_proof"
        if "derive" in p or "derivation" in p or "step" in p:
            return "step_by_step_derivation"
        if "graph" in p or "plot" in p or "function" in p:
            return "graph_and_formula"
        if "definition" in p or "example" in p:
            return "definition_to_example"

    elif domain == "physics":
        if "wave" in p or "sine" in p or "cosine" in p:
            return "wave_propagation"
        if "field" in p or "electric" in p or "magnetic" in p:
            return "field_visualization"
        if "oscillation" in p or "pendulum" in p or "spring" in p or "vibrate" in p:
            return "oscillation_motion"

    elif domain == "computer_science":
        if (
            "sort" in p
            or "bubble" in p
            or "quick" in p
            or "merge" in p
            or "selection" in p
        ):
            return "sorting_algorithm"
        if "tree" in p and (
            "traversal" in p or "bst" in p or "binary" in p or "node" in p
        ):
            return "tree_traversal"
        if "graph" in p and (
            "bfs" in p or "dfs" in p or "dijkstra" in p or "traversal" in p
        ):
            return "graph_traversal"

    elif domain == "chemistry":
        if "reaction" in p or "mechanism" in p or "organic" in p:
            return "reaction_mechanism"
        if "orbital" in p or "electron" in p or "shell" in p:
            return "orbital_visualization"
        if "molecule" in p or "bond" in p or "atom" in p or "cpk" in p:
            return "molecule_building"

    return None
