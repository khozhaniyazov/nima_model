"""
Real RAG system for NIMA.
Replaces the original 3-snippet static dict with a rich curated corpus
of ~30 proven Manim patterns drawn from 3b1b-style best practices.

Retrieval is keyword+domain matched, with DB fallback for accumulated
high-scoring examples.
"""
from __future__ import annotations
from typing import Optional
import json
import re
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════════
# CURATED CODE CORPUS
# Each entry: dict with keys:
#   tags     - list of topic/domain strings for matching
#   pattern  - concise, proven Manim CE snippet (no class boilerplate)
#   notes    - what this pattern teaches the LLM
# ═══════════════════════════════════════════════════════════════════════════════

CORPUS = [

    # ── FUNCTION GRAPHING ────────────────────────────────────────────────────
    {
        "tags": ["function", "graph", "plot", "curve", "math", "calculus"],
        "notes": "Plotting a function with labeled axes, color, and a dynamic tracker dot",
        "pattern": """\
axes = Axes(
    x_range=[-4, 4, 1],
    y_range=[-2, 10, 2],
    x_length=9,
    y_length=5,
    axis_config={"color": BLUE_D},
).add_coordinates()
axes_labels = axes.get_axis_labels(x_label="x", y_label="f(x)")

graph = axes.plot(lambda x: x**2, color=YELLOW)
graph_label = axes.get_graph_label(graph, label=MathTex("x^2"), x_val=3)

self.play(Create(axes), Write(axes_labels))
self.play(Create(graph), Write(graph_label), run_time=2)
self.wait(2)
""",
    },

    # ── VALUE TRACKER (LIVE PARAMETER ANIMATION) ─────────────────────────────
    {
        "tags": ["valuetracker", "dynamic", "parameter", "limit", "derivative", "live", "update"],
        "notes": "ValueTracker with always_redraw for continuously-updating objects — 3b1b signature pattern",
        "pattern": """\
axes = Axes(x_range=[-1, 5], y_range=[-1, 10], x_length=8, y_length=5)
graph = axes.plot(lambda x: x**2, color=BLUE)
self.add(axes, graph)

# Live dot that follows the curve
x_tracker = ValueTracker(1)
dot = always_redraw(
    lambda: Dot(axes.c2p(x_tracker.get_value(), x_tracker.get_value()**2), color=YELLOW)
)
x_label = always_redraw(
    lambda: MathTex(f"x = {x_tracker.get_value():.2f}", font_size=32)
    .next_to(dot, RIGHT, buff=0.2)
)
self.add(dot, x_label)
self.play(x_tracker.animate.set_value(4), run_time=4, rate_func=linear)
self.wait(1)
""",
    },

    # ── DERIVATIVE / TANGENT LINE ─────────────────────────────────────────────
    {
        "tags": ["derivative", "tangent", "slope", "secant", "limit", "calculus"],
        "notes": "Animate a secant line becoming a tangent as Δx → 0",
        "pattern": """\
axes = Axes(x_range=[-1, 5], y_range=[-1, 12], x_length=8, y_length=5)
graph = axes.plot(lambda x: x**2, color=BLUE)
self.play(Create(axes), Create(graph))

dx_tracker = ValueTracker(2.0)
x0 = 2.0

def get_secant():
    dx = dx_tracker.get_value()
    x1, x2 = x0, x0 + dx
    y1, y2 = x1**2, x2**2
    slope = (y2 - y1) / dx if dx != 0 else 2 * x0
    return axes.plot(lambda x: slope * (x - x0) + y1, color=YELLOW, x_range=[x0 - 1, x0 + dx + 1])

secant = always_redraw(get_secant)
slope_label = always_redraw(
    lambda: MathTex(
        r"\text{slope} = " + f"{((x0 + dx_tracker.get_value())**2 - x0**2) / dx_tracker.get_value():.2f}",
        font_size=32, color=YELLOW
    ).to_corner(UR).shift(DOWN * 0.5)
)
self.add(secant, slope_label)
self.play(dx_tracker.animate.set_value(0.01), run_time=5, rate_func=linear)
self.wait(2)
""",
    },

    # ── RIEMANN SUMS ──────────────────────────────────────────────────────────
    {
        "tags": ["integral", "riemann", "area", "sum", "approximation", "calculus"],
        "notes": "Riemann rectangles that refine as n increases",
        "pattern": """\
axes = Axes(x_range=[0, 4, 1], y_range=[0, 10, 2], x_length=8, y_length=5)
graph = axes.plot(lambda x: x**2, color=BLUE, x_range=[0, 3])
self.play(Create(axes), Create(graph))

n_tracker = ValueTracker(4)

def get_riemann():
    n = int(n_tracker.get_value())
    return axes.get_riemann_rectangles(
        graph, x_range=[0, 3], dx=3 / n,
        color=GREEN, stroke_width=0.5,
        fill_opacity=0.6
    )

rects = always_redraw(get_riemann)
n_label = always_redraw(
    lambda: MathTex(f"n = {int(n_tracker.get_value())}", font_size=36)
    .to_corner(UR)
)
self.add(rects, n_label)
self.play(n_tracker.animate.set_value(100), run_time=5, rate_func=smooth)
self.wait(2)
""",
    },

    # ── NUMBER LINE ───────────────────────────────────────────────────────────
    {
        "tags": ["number_line", "number line", "sequence", "convergence", "limit", "real numbers"],
        "notes": "Animated number line with movable dot — great for limits and sequences",
        "pattern": """\
nl = NumberLine(x_range=[-3, 3, 1], length=10, include_numbers=True)
dot = Dot(nl.n2p(0), color=YELLOW)
label = always_redraw(
    lambda: MathTex(f"{nl.p2n(dot.get_center()):.2f}", font_size=30).next_to(dot, UP)
)
self.play(Create(nl), FadeIn(dot), Write(label))
self.play(dot.animate.move_to(nl.n2p(2.718)), run_time=3)
self.wait(1)
""",
    },

    # ── NUMBER PLANE ──────────────────────────────────────────────────────────
    {
        "tags": ["number_plane", "numberplane", "grid", "vector", "linear algebra", "transformation"],
        "notes": "NumberPlane with vector arrows — essential for linear algebra topics",
        "pattern": """\
plane = NumberPlane(
    x_range=[-5, 5], y_range=[-4, 4],
    background_line_style={"stroke_color": TEAL, "stroke_opacity": 0.4},
)
self.play(Create(plane, lag_ratio=0.1), run_time=2)

v1 = Arrow(plane.c2p(0, 0), plane.c2p(2, 1), buff=0, color=RED)
v2 = Arrow(plane.c2p(0, 0), plane.c2p(1, 3), buff=0, color=GREEN)
labels = VGroup(
    MathTex(r"\vec{v}", color=RED).next_to(v1.get_end(), RIGHT),
    MathTex(r"\vec{w}", color=GREEN).next_to(v2.get_end(), UP),
)
self.play(GrowArrow(v1), GrowArrow(v2), Write(labels))
self.wait(2)
""",
    },

    # ── LINEAR TRANSFORMATION ──────────────────────────────────────────────────
    {
        "tags": ["linear transformation", "matrix", "transform", "linear algebra", "eigenvector", "determinant", "basis"],
        "notes": "Apply a 2D linear transformation with basis vectors and unit square — 3b1b classic",
        "pattern": """\
plane = NumberPlane(
    x_range=[-5, 5], y_range=[-4, 4],
    background_line_style={"stroke_opacity": 0.15},
    faded_line_style={"stroke_opacity": 0.08},
    faded_line_ratio=3,
).set_opacity(0.3)
self.play(Create(plane, lag_ratio=0.05), run_time=1.5)

# Basis vectors — show BEFORE transformation
i_hat = Arrow(ORIGIN, plane.c2p(1, 0), color=GREEN, buff=0, stroke_width=4)
j_hat = Arrow(ORIGIN, plane.c2p(0, 1), color=RED, buff=0, stroke_width=4)
i_label = MathTex(r"\\hat{i}", color=GREEN, font_size=28).next_to(i_hat.get_end(), DR, buff=0.1)
j_label = MathTex(r"\\hat{j}", color=RED, font_size=28).next_to(j_hat.get_end(), UL, buff=0.1)
self.play(GrowArrow(i_hat), GrowArrow(j_hat), Write(i_label), Write(j_label))
self.wait(1)

# Unit square formed by basis vectors
unit_square = Polygon(
    plane.c2p(0,0), plane.c2p(1,0), plane.c2p(1,1), plane.c2p(0,1),
    fill_color=YELLOW, fill_opacity=0.25, stroke_color=YELLOW, stroke_width=2,
)
self.play(Create(unit_square))
self.wait(1)

# Apply transformation: everything moves together
matrix = [[2, 1], [0, 2]]  # shear matrix
self.play(
    plane.animate.apply_matrix(matrix),
    i_hat.animate.put_start_and_end_on(ORIGIN, plane.c2p(2, 0)),
    j_hat.animate.put_start_and_end_on(ORIGIN, plane.c2p(1, 2)),
    unit_square.animate.apply_matrix(matrix),
    run_time=3,
)
self.wait(2)
""",
    },

    # ── STEP-BY-STEP EQUATIONS ────────────────────────────────────────────────
    {
        "tags": ["equation", "algebra", "step", "step-by-step", "proof", "derivation", "transform"],
        "notes": "Progressive equation reveal with TransformMatchingTex — elegant step-by-step math",
        "pattern": """\
eq1 = MathTex(r"x^2 - 5x + 6 = 0", font_size=52)
eq2 = MathTex(r"(x - 2)(x - 3) = 0", font_size=52)
eq3 = MathTex(r"x = 2 \\quad \\text{or} \\quad x = 3", font_size=52)

self.play(Write(eq1))
self.wait(1.5)
self.play(TransformMatchingTex(eq1, eq2), run_time=2)
self.wait(1.5)
self.play(TransformMatchingTex(eq2, eq3), run_time=2)
self.wait(2)
""",
    },

    # ── MATHTEX COLOR HIGHLIGHTING ────────────────────────────────────────────
    {
        "tags": ["mathtex", "color", "highlight", "equation", "formula", "math"],
        "notes": "Color-code specific parts of an equation for emphasis — key teaching technique",
        "pattern": """\
eq = MathTex(
    r"f", r"(", r"x", r")", r"=", r"x", r"^2", r"+", r"3", r"x", r"-", r"4",
    font_size=60,
)
# Highlight x terms in yellow
eq[2].set_color(YELLOW)
eq[5].set_color(YELLOW)
eq[9].set_color(YELLOW)
eq[6].set_color(YELLOW)

brace = Brace(VGroup(eq[5], eq[9]), DOWN, color=YELLOW)
brace_text = brace.get_text("x terms", font_size=28, color=YELLOW)

self.play(Write(eq))
self.wait(1)
self.play(GrowFromCenter(brace), Write(brace_text))
self.wait(2)
""",
    },

    # ── BAR CHART / DISTRIBUTION ──────────────────────────────────────────────
    {
        "tags": ["bar chart", "histogram", "distribution", "probability", "statistics", "chart", "frequency"],
        "notes": "Animated bar chart with updating values — great for probability/statistics",
        "pattern": """\
values = [0.1, 0.2, 0.4, 0.2, 0.1]
axes = Axes(
    x_range=[0, len(values), 1],
    y_range=[0, 0.6, 0.1],
    x_length=8,
    y_length=4,
    axis_config={"include_tip": False},
)
bars = VGroup()
for i, v in enumerate(values):
    bar = Rectangle(
        width=axes.x_axis.get_unit_size() * 0.8,
        height=axes.y_axis.get_unit_size() * v,
        fill_color=BLUE,
        fill_opacity=0.8,
        stroke_color=WHITE,
        stroke_width=1,
    )
    bar.align_to(axes.c2p(i + 0.1, 0), DL)
    bars.add(bar)

self.play(Create(axes))
self.play(LaggedStart(*[GrowFromEdge(b, DOWN) for b in bars], lag_ratio=0.1))
self.wait(2)
""",
    },

    # ── TRACED PATH ───────────────────────────────────────────────────────────
    {
        "tags": ["traced path", "parametric", "curve", "path", "locus", "motion"],
        "notes": "TracedPath that draws a curve as a dot moves — beautiful for parametric paths and loci",
        "pattern": """\
axes = Axes(x_range=[-4, 4], y_range=[-4, 4], x_length=7, y_length=7)
t = ValueTracker(0)

dot = always_redraw(lambda: Dot(
    axes.c2p(2 * np.cos(t.get_value()), 2 * np.sin(t.get_value())),
    color=YELLOW, radius=0.1
))
path = TracedPath(dot.get_center, stroke_color=BLUE, stroke_width=3)
self.add(axes, path, dot)
self.play(t.animate.set_value(TAU), run_time=4, rate_func=linear)
self.wait(1)
""",
    },

    # ── VECTOR FIELD ──────────────────────────────────────────────────────────
    {
        "tags": ["vector field", "flow", "differential equation", "gradient", "curl", "physics"],
        "notes": "Animated vector field — great for physics and differential equations",
        "pattern": """\
func = lambda pos: np.array([-pos[1], pos[0], 0]) * 0.5  # rotation field
field = ArrowVectorField(func, x_range=[-4, 4, 0.8], y_range=[-3, 3, 0.8])
stream = StreamLines(func, stroke_width=2, max_anchors_per_line=30)
self.play(Create(field, lag_ratio=0.05), run_time=2)
self.wait(1)
self.play(Create(stream, lag_ratio=0.01), run_time=3)
self.wait(2)
""",
    },

    # ── SORTING ALGORITHM ─────────────────────────────────────────────────────
    {
        "tags": ["sort", "bubble sort", "algorithm", "array", "comparison", "computer science", "cs"],
        "notes": "Animated array sorting with color-coded comparisons and swaps",
        "pattern": """\
data = [5, 3, 8, 1, 9, 2, 7, 4]
bar_width = 0.6
gap = 0.1
bars = VGroup()
for i, val in enumerate(data):
    bar = Rectangle(
        width=bar_width,
        height=val * 0.4,
        fill_color=BLUE,
        fill_opacity=0.85,
        stroke_color=WHITE,
        stroke_width=1,
    ).shift(RIGHT * i * (bar_width + gap))
    num = Text(str(val), font_size=20).next_to(bar, DOWN, buff=0.1)
    bars.add(VGroup(bar, num))

bars.center()
self.play(Create(bars))
self.wait(0.5)

# Bubble sort animation
arr = list(data)
for i in range(len(arr)):
    for j in range(len(arr) - i - 1):
        self.play(
            bars[j][0].animate.set_color(YELLOW),
            bars[j+1][0].animate.set_color(YELLOW),
            run_time=0.3
        )
        if arr[j] > arr[j+1]:
            arr[j], arr[j+1] = arr[j+1], arr[j]
            self.play(
                bars[j].animate.shift(RIGHT * (bar_width + gap)),
                bars[j+1].animate.shift(LEFT * (bar_width + gap)),
                run_time=0.4
            )
            bars[j], bars[j+1] = bars[j+1], bars[j]
        self.play(
            bars[j][0].animate.set_color(BLUE),
            bars[j+1][0].animate.set_color(BLUE),
            run_time=0.2
        )
    bars[len(arr) - i - 1][0].set_color(GREEN)
self.wait(1)
""",
    },

    # ── BINARY TREE ───────────────────────────────────────────────────────────
    {
        "tags": ["tree", "binary tree", "bst", "bfs", "dfs", "graph", "recursion", "computer science"],
        "notes": "Build a binary tree node-by-node with connecting edges",
        "pattern": """\
def make_node(val, color=BLUE):
    circle = Circle(radius=0.35, color=color, fill_opacity=0.8)
    label = Text(str(val), font_size=28, color=WHITE).move_to(circle.get_center())
    return VGroup(circle, label)

root = make_node(8).move_to(UP * 2)
left = make_node(4).move_to(UP * 0.5 + LEFT * 2)
right = make_node(12).move_to(UP * 0.5 + RIGHT * 2)
left_left = make_node(2).move_to(DOWN * 1 + LEFT * 3)
left_right = make_node(6).move_to(DOWN * 1 + LEFT * 1)

edges = VGroup(
    Line(root.get_bottom(), left.get_top(), stroke_width=2),
    Line(root.get_bottom(), right.get_top(), stroke_width=2),
    Line(left.get_bottom(), left_left.get_top(), stroke_width=2),
    Line(left.get_bottom(), left_right.get_top(), stroke_width=2),
)
self.play(FadeIn(root))
self.play(LaggedStart(
    AnimationGroup(GrowFromPoint(edges[0], root.get_bottom()), FadeIn(left)),
    AnimationGroup(GrowFromPoint(edges[1], root.get_bottom()), FadeIn(right)),
    lag_ratio=0.3
))
self.play(LaggedStart(
    AnimationGroup(GrowFromPoint(edges[2], left.get_bottom()), FadeIn(left_left)),
    AnimationGroup(GrowFromPoint(edges[3], left.get_bottom()), FadeIn(left_right)),
    lag_ratio=0.3
))
self.wait(2)
""",
    },

    # ── MATRIX MULTIPLICATION ─────────────────────────────────────────────────
    {
        "tags": ["matrix", "matrix multiplication", "linear algebra", "determinant"],
        "notes": "Display and animate matrices with MobjectMatrix, highlighting rows and columns",
        "pattern": """\
m1 = Matrix([[1, 2], [3, 4]], left_bracket="(", right_bracket=")")
m2 = Matrix([[5, 6], [7, 8]], left_bracket="(", right_bracket=")")
times = MathTex(r"\\times", font_size=48)
eq = MathTex(r"=", font_size=48)
result = Matrix([[19, 22], [43, 50]], left_bracket="(", right_bracket=")")

group = VGroup(m1, times, m2, eq, result).arrange(RIGHT, buff=0.4).scale(0.9)
self.play(Write(m1), Write(times), Write(m2), run_time=2)
self.wait(1)

# Highlight: row 0 of m1, col 0 of m2
self.play(
    m1.get_rows()[0].animate.set_color(YELLOW),
    m2.get_columns()[0].animate.set_color(RED),
)
self.wait(1)
self.play(Write(eq), Write(result))
self.wait(2)
""",
    },

    # ── PROBABILITY / PIE CHART ───────────────────────────────────────────────
    {
        "tags": ["probability", "conditional", "bayes", "pie", "pie chart", "proportion", "circle"],
        "notes": "Sector-based probability visualization with proportional areas",
        "pattern": """\
circle = Circle(radius=2, color=WHITE)
p = 0.3  # P(A) = 30%
sector_a = Sector(outer_radius=2, angle=p * TAU, start_angle=PI/2, color=BLUE, fill_opacity=0.8)
sector_b = Sector(outer_radius=2, angle=(1-p) * TAU, start_angle=PI/2 + p*TAU, color=RED, fill_opacity=0.6)

label_a = MathTex(r"P(A) = 30\\%", color=BLUE, font_size=32).shift(LEFT * 1.5 + UP * 0.5)
label_b = MathTex(r"P(A^c) = 70\\%", color=RED, font_size=32).shift(RIGHT * 1.2 + DOWN * 0.5)

self.play(Create(circle))
self.play(FadeIn(sector_a), FadeIn(sector_b))
self.play(Write(label_a), Write(label_b))
self.wait(2)
""",
    },

    # ── TAYLOR SERIES ─────────────────────────────────────────────────────────
    {
        "tags": ["taylor", "maclaurin", "series", "approximation", "polynomial", "calculus"],
        "notes": "Show Taylor polynomial approximations of increasing degree converging to a function",
        "pattern": """\
import numpy as np

axes = Axes(x_range=[-3.5, 3.5, 1], y_range=[-2, 8, 1], x_length=8, y_length=5)
true_graph = axes.plot(np.exp, color=WHITE, x_range=[-3, 3])
self.play(Create(axes), Create(true_graph))

colors = [BLUE, GREEN, YELLOW, ORANGE, RED]
approx_label = Text("", font_size=28).to_corner(UR)

for n, color in enumerate(colors):
    # Taylor polynomial for e^x up to degree n
    def poly(x, deg=n):
        return sum(x**k / np.math.factorial(k) for k in range(deg + 1))
    graph = axes.plot(poly, color=color, x_range=[-3, 3])
    new_label = MathTex(
        r"T_{" + str(n) + r"}(x)", font_size=28, color=color
    ).to_corner(UR).shift(DOWN * 0.5 * n)
    self.play(Create(graph), Write(new_label), run_time=1)
    self.wait(0.8)
self.wait(2)
""",
    },

    # ── EIGENVALUE / EIGENVECTOR ──────────────────────────────────────────────
    {
        "tags": ["eigenvalue", "eigenvector", "matrix", "linear algebra", "transformation"],
        "notes": "Show that eigenvectors only scale under a matrix transformation — visual intuition",
        "pattern": """\
plane = NumberPlane(
    x_range=[-4, 4], y_range=[-4, 4],
    background_line_style={"stroke_opacity": 0.15},
    faded_line_style={"stroke_opacity": 0.08},
).set_opacity(0.3)
self.play(Create(plane, lag_ratio=0.05), run_time=1.5)

# Eigenvectors for [[3,1],[0,2]]: (1,0) with λ=3, (1,1) with λ=2
v1 = Arrow(ORIGIN, plane.c2p(1.5, 0), buff=0, color=YELLOW, stroke_width=4)
v2 = Arrow(ORIGIN, plane.c2p(1, 1), buff=0, color=RED, stroke_width=4)
l1 = MathTex(r"\\lambda=3", color=YELLOW, font_size=28).next_to(v1.get_end(), RIGHT)
l2 = MathTex(r"\\lambda=2", color=RED, font_size=28).next_to(v2.get_end(), UP)

self.play(GrowArrow(v1), GrowArrow(v2), Write(l1), Write(l2))
self.wait(1)

# Apply [[3,1],[0,2]] transformation
A = np.array([[3, 1], [0, 2]])
self.play(
    plane.animate.apply_matrix(A),
    v1.animate.apply_matrix(A),
    v2.animate.apply_matrix(A),
    run_time=3
)
self.wait(2)
""",
    },

    # ── GRAPH / NETWORK ───────────────────────────────────────────────────────
    {
        "tags": ["graph", "network", "node", "edge", "dijkstra", "bfs", "dfs", "path", "shortest path"],
        "notes": "Animated graph/network with highlighted traversal path",
        "pattern": """\
# Build a small weighted graph
vertices = {
    "A": LEFT * 3,
    "B": LEFT * 1 + UP * 1.5,
    "C": RIGHT * 1 + UP * 1.5,
    "D": RIGHT * 3,
    "E": ORIGIN + DOWN * 1,
}
dots = {k: Dot(v, radius=0.18, color=BLUE).set_z_index(1) for k, v in vertices.items()}
labels = {k: Text(k, font_size=24).next_to(dots[k], UP, buff=0.1) for k in dots}

edges_list = [("A","B"), ("A","E"), ("B","C"), ("B","E"), ("C","D"), ("E","D")]
edges = {
    (u, v): Line(vertices[u], vertices[v], stroke_width=2.5, color=GREY)
    for u, v in edges_list
}

self.play(LaggedStart(*[Create(e) for e in edges.values()], lag_ratio=0.05))
self.play(LaggedStart(*[FadeIn(d) for d in dots.values()], *[Write(l) for l in labels.values()], lag_ratio=0.05))
self.wait(0.5)

# Highlight a path A → B → C → D
path_nodes = ["A", "B", "C", "D"]
self.play(*[dots[n].animate.set_color(YELLOW) for n in path_nodes], run_time=1)
path_edges = [(path_nodes[i], path_nodes[i+1]) for i in range(len(path_nodes)-1)]
self.play(*[edges[e].animate.set_color(YELLOW).set_stroke(width=4) for e in path_edges if e in edges], run_time=1)
self.wait(2)
""",
    },

    # ── FOURIER SERIES ────────────────────────────────────────────────────────
    {
        "tags": ["fourier", "series", "frequency", "sine", "cosine", "wave", "signal", "spectrum"],
        "notes": "Build a Fourier approximation by layering sine waves",
        "pattern": """\
import numpy as np
axes = Axes(x_range=[0, TAU, 1], y_range=[-2, 2, 0.5], x_length=10, y_length=4)
self.play(Create(axes))

def square_wave_approx(x, n_terms):
    return sum(
        (4 / (np.pi * k)) * np.sin(k * x)
        for k in range(1, n_terms * 2, 2)
    )

colors = [BLUE, GREEN, YELLOW, ORANGE]
for n, color in enumerate([1, 3, 5, 11]):
    graph = axes.plot(lambda x, n=n: square_wave_approx(x, [1,3,5,11][n]), color=color, x_range=[0, TAU])
    label = Text(f"{[1,3,5,11][n]} terms", font_size=24, color=color).to_edge(RIGHT).shift(UP * (1.5 - n * 0.8))
    self.play(Create(graph), Write(label), run_time=1)
    self.wait(0.5)
self.wait(2)
""",
    },

    # ── COMPLEX NUMBER / ARGAND PLANE ──────────────────────────────────────────
    {
        "tags": ["complex", "argand", "imaginary", "modulus", "argument", "euler", "roots"],
        "notes": "Show complex numbers on the Argand plane with polar representation",
        "pattern": """\
plane = ComplexPlane(x_range=[-3, 3], y_range=[-3, 3]).add_coordinates()
self.play(Create(plane, lag_ratio=0.05))

# z = 1 + 2i
z_dot = Dot(plane.n2p(1 + 2j), color=YELLOW, radius=0.1)
z_label = MathTex(r"z = 1 + 2i", font_size=32).next_to(z_dot, UR, buff=0.1)
arrow = Arrow(ORIGIN, plane.n2p(1 + 2j), buff=0, color=YELLOW)
modulus_line = Line(plane.n2p(1 + 2j), plane.n2p(1), stroke_width=1.5, color=GREY, stroke_style=DASHED)
real_line = Line(ORIGIN, plane.n2p(1), stroke_width=1.5, color=RED)

self.play(GrowArrow(arrow), FadeIn(z_dot), Write(z_label))
self.play(Create(real_line), Create(modulus_line))
self.wait(2)
""",
    },

    # ── GEOMETRY PROOF ────────────────────────────────────────────────────────
    {
        "tags": ["geometry", "proof", "triangle", "circle", "angle", "theorem", "pythagorean"],
        "notes": "Rigorous geometric construction with labeled angles and sides",
        "pattern": """\
triangle = Polygon(
    ORIGIN, RIGHT * 4, UP * 3,
    color=WHITE, stroke_width=2,
    fill_color=BLUE_E, fill_opacity=0.3
)
# Label sides
side_a = MathTex("a").next_to(Line(ORIGIN, RIGHT * 4), DOWN)
side_b = MathTex("b").next_to(Line(ORIGIN, UP * 3), LEFT)
side_c = MathTex("c").next_to(Line(RIGHT * 4, UP * 3), RIGHT)

right_angle_mark = RightAngle(
    Line(ORIGIN, RIGHT), Line(ORIGIN, UP),
    length=0.25, color=YELLOW
)
self.play(Create(triangle))
self.play(Create(right_angle_mark))
self.play(Write(side_a), Write(side_b), Write(side_c))
self.wait(1)

# Show a^2 + b^2 = c^2
theorem = MathTex(r"a^2 + b^2 = c^2", font_size=52).to_edge(DOWN)
self.play(Write(theorem))
self.wait(2)
""",
    },

    # ── RECURSIVE / FRACTAL ────────────────────────────────────────────────────
    {
        "tags": ["recursion", "fractal", "self-similar", "sierpinski", "tree fractal", "fibonacci"],
        "notes": "Animated recursive structure — shown level by level",
        "pattern": """\
def sierpinski(n, pos, size):
    if n == 0:
        return [Triangle(fill_color=BLUE, fill_opacity=0.8, color=WHITE).scale(size).move_to(pos)]
    s = size / 2
    h = s * np.sqrt(3) / 2
    c = [pos + LEFT * s + DOWN * h / 3,
         pos + RIGHT * s + DOWN * h / 3,
         pos + UP * (2 * h / 3)]
    return sierpinski(n-1, c[0], s) + sierpinski(n-1, c[1], s) + sierpinski(n-1, c[2], s)

for level in range(4):
    triangles = sierpinski(level, ORIGIN, 2.5)
    group = VGroup(*triangles)
    if level == 0:
        self.play(FadeIn(group))
    else:
        self.play(ReplacementTransform(prev_group, group), run_time=1)
    prev_group = group
    self.wait(0.8)
self.wait(2)
""",
    },

    # ── POPULATION / LOGISTIC GROWTH ──────────────────────────────────────────
    {
        "tags": ["logistic", "population", "growth", "differential equation", "equilibrium", "dynamics"],
        "notes": "Phase portrait and solution curve for logistic growth ODE",
        "pattern": """\
import numpy as np
axes = Axes(x_range=[0, 10, 1], y_range=[0, 1.2, 0.2], x_length=9, y_length=5)
axes_labels = axes.get_axis_labels("t", "P(t)")

r, K = 1.0, 1.0
def logistic(t, P0=0.1):
    return K / (1 + ((K - P0) / P0) * np.exp(-r * t))

curves = VGroup()
for P0, col in [(0.05, BLUE), (0.5, GREEN), (0.9, YELLOW)]:
    curve = axes.plot(lambda t, p=P0: logistic(t, p), color=col, x_range=[0, 10])
    curves.add(curve)

equilibrium = axes.plot(lambda t: 1.0, color=RED, stroke_style=DASHED)
eq_label = MathTex(r"K = 1", color=RED, font_size=28).next_to(axes.c2p(9, 1), UP)

self.play(Create(axes), Write(axes_labels))
self.play(LaggedStart(*[Create(c) for c in curves], lag_ratio=0.3), run_time=3)
self.play(Create(equilibrium), Write(eq_label))
self.wait(2)
""",
    },

    # ── CENTRAL LIMIT THEOREM / SAMPLING ─────────────────────────────────────
    {
        "tags": ["central limit theorem", "clt", "normal distribution", "gaussian", "statistics", "sampling"],
        "notes": "3b1b-inspired: show sample means converging to a normal distribution",
        "pattern": """\
import numpy as np
axes = Axes(x_range=[0, 10, 1], y_range=[0, 0.5, 0.1], x_length=9, y_length=4)
np.random.seed(42)
samples = [np.mean(np.random.exponential(scale=2, size=30)) for _ in range(1000)]

def get_histogram(sample_means, n_bins=40):
    hist, edges = np.histogram(sample_means, bins=n_bins, range=(0, 10), density=True)
    bars = VGroup()
    for i, h in enumerate(hist):
        x_left = edges[i]
        bar = Rectangle(
            width=axes.x_axis.get_unit_size() * (edges[1] - edges[0]),
            height=axes.y_axis.get_unit_size() * h,
            fill_color=BLUE, fill_opacity=0.6, stroke_width=0.5
        ).align_to(axes.c2p(x_left, 0), DL)
        bars.add(bar)
    return bars

hist = get_histogram(samples)
self.play(Create(axes))
self.play(LaggedStart(*[GrowFromEdge(b, DOWN) for b in hist], lag_ratio=0.01), run_time=2)

# Overlay normal curve
mu, sigma = np.mean(samples), np.std(samples)
normal = axes.plot(
    lambda x: (1/(sigma * np.sqrt(2*np.pi))) * np.exp(-0.5*((x-mu)/sigma)**2),
    color=YELLOW, stroke_width=3
)
self.play(Create(normal), run_time=2)
self.wait(2)
""",
    },

    # ── PI ESTIMATION / MONTE CARLO ───────────────────────────────────────────
    {
        "tags": ["monte carlo", "simulation", "random", "pi", "probability", "estimation"],
        "notes": "Monte Carlo π estimation — dots scatter inside/outside circle with a live count",
        "pattern": """\
import numpy as np
np.random.seed(0)
square = Square(side_length=4, color=WHITE)
circle = Circle(radius=2, color=YELLOW)
self.play(Create(square), Create(circle))

inside_count, total_count = 0, 0
pi_display = always_redraw(
    lambda: MathTex(
        r"\\pi \\approx " + f"{4 * inside_count / max(total_count, 1):.4f}",
        font_size=36
    ).to_corner(UR)
)
self.add(pi_display)

inside_dots, outside_dots = VGroup(), VGroup()
for _ in range(200):
    x, y = np.random.uniform(-2, 2), np.random.uniform(-2, 2)
    total_count += 1
    in_circle = x**2 + y**2 <= 4
    if in_circle:
        inside_count += 1
    dot = Dot([x, y, 0], radius=0.04, color=GREEN if in_circle else RED)
    (inside_dots if in_circle else outside_dots).add(dot)
    self.add(dot)

self.play(Write(MathTex(r"\\pi \\approx " + f"{4*inside_count/total_count:.4f}", font_size=36).to_corner(UR)))
self.wait(2)
""",
    },

    # ── NUMBER SIEVE / NUMBER THEORY ─────────────────────────────────────────
    {
        "tags": ["prime", "sieve", "number theory", "divisibility", "factor", "modular"],
        "notes": "Sieve of Eratosthenes — animate elimination of multiples on a number grid",
        "pattern": """\
from manim import *
import numpy as np

class GeneratedScene(Scene):
    def construct(self):
        title = Text("Sieve of Eratosthenes", font_size=40, color=BLUE).to_edge(UP, buff=0.3)
        self.play(Write(title))

        n = 30
        # Build grid of number squares
        cols = 10
        rows = 3
        cells = VGroup()
        nums = list(range(2, n + 2))
        for i, num in enumerate(nums):
            sq = Square(side_length=0.55, color=WHITE, fill_opacity=0.1)
            lbl = Text(str(num), font_size=20).move_to(sq.get_center())
            cell = VGroup(sq, lbl)
            cell.move_to(RIGHT * (i % cols) * 0.6 + DOWN * (i // cols) * 0.65)
            cells.add(cell)
        cells.center().shift(DOWN * 0.4)
        self.play(FadeIn(cells), run_time=1.5)
        self.wait(1)

        is_prime = [True] * len(nums)
        for pi, p in enumerate(nums):
            if not is_prime[pi]:
                continue
            # Highlight p
            self.play(cells[pi][0].animate.set_fill(YELLOW, opacity=0.7), run_time=0.3)
            # Cross out multiples
            anims = []
            for qi in range(pi + p, len(nums), p):
                if is_prime[qi]:
                    is_prime[qi] = False
                    anims.append(cells[qi][0].animate.set_fill(RED, opacity=0.6))
            if anims:
                self.play(*anims, run_time=0.4)

        self.wait(2)
        summary = Text("Yellow = Prime", font_size=28, color=YELLOW).to_edge(DOWN, buff=0.3)
        self.play(Write(summary))
        self.wait(2)
""",
    },

    # ── PENDULUM / PHYSICS SIMULATION ─────────────────────────────────────────
    {
        "tags": ["pendulum", "oscillation", "spring", "simple harmonic", "physics", "mechanics"],
        "notes": "Animated pendulum with ValueTracker controlling angle — clean physics pattern",
        "pattern": """\
axes = Axes(x_range=[0, 10, 1], y_range=[-1.2, 1.2, 0.5], x_length=9, y_length=4)
axes_labels = axes.get_axis_labels(x_label="t", y_label=r"\\theta(t)")
self.play(Create(axes), Write(axes_labels))

omega = 2 * PI / 3   # angular frequency
graph = axes.plot(lambda t: np.cos(omega * t), color=BLUE, x_range=[0, 10])
self.play(Create(graph), run_time=3)
self.wait(1)

# Pendulum diagram
pivot = Dot(UP * 2, color=WHITE)
ghostline = DashedLine(UP * 2, UP * 2 + DOWN * 1.8, color=GREY)
t = ValueTracker(0)
rod = always_redraw(lambda: Line(
    UP * 2,
    UP * 2 + 1.8 * np.array([np.sin(np.cos(omega * t.get_value())), -np.sqrt(1 - np.sin(np.cos(omega * t.get_value()))**2), 0]),
    color=WHITE, stroke_width=3
))
bob = always_redraw(lambda: Dot(
    UP * 2 + 1.8 * np.array([np.sin(1.0 * np.cos(omega * t.get_value())), -np.cos(1.0 * np.cos(omega * t.get_value())), 0]),
    radius=0.18, color=ORANGE
))
self.add(pivot, ghostline, rod, bob)
self.play(t.animate.set_value(6), run_time=6, rate_func=linear)
self.wait(1)
""",
    },

    # ── SUPPLY AND DEMAND / ECONOMICS ─────────────────────────────────────────
    {
        "tags": ["supply", "demand", "economics", "equilibrium", "price", "market", "intersection"],
        "notes": "Supply and demand curves meeting at equilibrium — classic economics visual",
        "pattern": """\
axes = Axes(
    x_range=[0, 10, 2], y_range=[0, 10, 2],
    x_length=7, y_length=5,
    axis_config={"include_tip": True},
).add_coordinates()
x_label = axes.get_x_axis_label(Text("Quantity", font_size=24), edge=RIGHT, direction=DOWN)
y_label = axes.get_y_axis_label(Text("Price", font_size=24), edge=UP, direction=LEFT)

demand = axes.plot(lambda q: 9 - 0.8 * q, color=BLUE, x_range=[0, 9], stroke_width=3)
supply = axes.plot(lambda q: 1 + 0.8 * q, color=RED,  x_range=[0, 9], stroke_width=3)

d_label = Text("Demand", font_size=24, color=BLUE).next_to(axes.c2p(1, 9 - 0.8), LEFT, buff=0.1)
s_label = Text("Supply", font_size=24, color=RED).next_to(axes.c2p(1, 1.8), LEFT, buff=0.1)

self.play(Create(axes), Write(x_label), Write(y_label))
self.play(Create(demand), Write(d_label), Create(supply), Write(s_label), run_time=2)
self.wait(1)

# Equilibrium point: 9 - 0.8q = 1 + 0.8q  =>  q = 5, p = 5
eq_dot = Dot(axes.c2p(5, 5), color=YELLOW, radius=0.12)
eq_label = MathTex(r"P^* = 5, Q^* = 5", font_size=30, color=YELLOW).next_to(eq_dot, UR)
self.play(FadeIn(eq_dot), Write(eq_label))

# Dashed lines to axes
v_line = DashedLine(axes.c2p(5, 0), axes.c2p(5, 5), color=GREY)
h_line = DashedLine(axes.c2p(0, 5), axes.c2p(5, 5), color=GREY)
self.play(Create(v_line), Create(h_line))
self.wait(2)
""",
    },

    # ── GENERAL PROCESS FLOW / TIMELINE ───────────────────────────────────────
    {
        "tags": ["process", "flow", "timeline", "steps", "stages", "sequence", "general", "comparison"],
        "notes": "Animated step-by-step process flow with arrows — works for any sequential topic",
        "pattern": """\
steps = ["Input", "Process", "Output"]
colors = [BLUE, GREEN, YELLOW]
boxes = VGroup()
for i, (label, color) in enumerate(zip(steps, colors)):
    box = RoundedRectangle(width=2.2, height=1.0, corner_radius=0.2,
                           color=color, fill_opacity=0.3, stroke_width=2)
    txt = Text(label, font_size=28).move_to(box.get_center())
    boxes.add(VGroup(box, txt))

boxes.arrange(RIGHT, buff=1.2).center()
arrows = VGroup(*[
    Arrow(boxes[i].get_right(), boxes[i+1].get_left(), buff=0.1)
    for i in range(len(boxes) - 1)
])

self.play(LaggedStart(*[FadeIn(b) for b in boxes], lag_ratio=0.4), run_time=1.5)
self.play(LaggedStart(*[GrowArrow(a) for a in arrows], lag_ratio=0.3))
self.wait(2)
""",
    },

    # ── COMPLETE MINI-SCENE EXAMPLE — PYTHAGOREAN THEOREM PROOF ──────────────
    {
        "tags": ["complete scene", "template", "pythagorean", "geometry", "proof", "example"],
        "notes": "COMPLETE SCENE EXAMPLE: full 3-act structure with title, visual proof, and summary",
        "pattern": """\
from manim import *

class GeneratedScene(Scene):
    def construct(self):
        # === ACT 1: TITLE (0–8s) ===
        title = Text("Pythagorean Theorem", font_size=44, color=BLUE)
        subtitle = Text("a\u00b2 + b\u00b2 = c\u00b2", font_size=32, color=WHITE)
        title_group = VGroup(title, subtitle).arrange(DOWN, buff=0.4).center()
        self.play(Write(title))
        self.play(FadeIn(subtitle, shift=UP * 0.3))
        self.wait(2)
        self.play(FadeOut(title_group))

        # === ACT 2: VISUAL CONSTRUCTION (8–40s) ===
        section_title = Text("The Right Triangle", font_size=36, color=BLUE_C).to_edge(UP, buff=0.3)
        self.play(Write(section_title))

        triangle = Polygon(ORIGIN, RIGHT * 3, UP * 4,
                           color=WHITE, stroke_width=2, fill_color=BLUE_E, fill_opacity=0.25)
        triangle.center().shift(DOWN * 0.5)

        side_a = MathTex("a", font_size=32).next_to(triangle, DOWN)
        side_b = MathTex("b", font_size=32).next_to(triangle, LEFT)
        side_c = MathTex("c", font_size=32).next_to(triangle, RIGHT)
        right_mark = RightAngle(
            Line(triangle.get_vertices()[0], triangle.get_vertices()[1]),
            Line(triangle.get_vertices()[0], triangle.get_vertices()[2]),
            length=0.25, color=YELLOW
        )

        self.play(Create(triangle), run_time=1.5)
        self.play(Create(right_mark), Write(side_a), Write(side_b), Write(side_c))
        self.wait(2)

        # === ACT 3: EQUATION (40–60s) ===
        self.play(FadeOut(triangle, right_mark, side_a, side_b, side_c, section_title))
        eq_title = Text("The Theorem", font_size=36, color=BLUE_C).to_edge(UP, buff=0.3)
        self.play(Write(eq_title))

        eq1 = MathTex(r"a^2", r"+", r"b^2", r"=", r"c^2", font_size=60)
        eq1[0].set_color(RED)
        eq1[2].set_color(GREEN)
        eq1[4].set_color(YELLOW)
        self.play(Write(eq1))
        self.wait(3)
""",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# LOAD CURATED EXAMPLES FROM manim_examples_raw.json
# ═══════════════════════════════════════════════════════════════════════════════

_UNSAFE_PATTERNS = {"ImageMobject", "ThreeDScene", "MovingCameraScene"}


def _load_json_examples():
    """Load curated examples from the training directory and append to CORPUS."""
    json_path = Path(__file__).parent.parent / "training" / "manim_examples_raw.json"
    if not json_path.exists():
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            examples = json.load(f)
    except Exception:
        return

    for ex in examples:
        code = ex.get("code", "")
        scene = ex.get("scene", "")

        # Skip unsafe patterns
        if any(pat in code for pat in _UNSAFE_PATTERNS):
            continue

        # Auto-generate tags from scene name (split camelCase)
        words = re.sub(r"([a-z])([A-Z])", r"\1 \2", scene).lower().split()
        tags = list(set(words))

        # Add extra tags based on code content
        if "ValueTracker" in code:
            tags.append("valuetracker")
            tags.append("dynamic")
        if "NumberPlane" in code:
            tags.append("numberplane")
            tags.append("grid")
        if "Axes" in code or "axes" in code:
            tags.append("graph")
            tags.append("plot")
        if "MathTex" in code:
            tags.append("equation")
            tags.append("math")
        if "always_redraw" in code or "add_updater" in code:
            tags.append("updater")
            tags.append("dynamic")
        if "TracedPath" in code or "update_path" in code:
            tags.append("traced path")
            tags.append("path")
        if "Rotating" in code or "rotate" in code.lower():
            tags.append("rotation")
        if "Transform" in code:
            tags.append("transform")

        tags = list(set(tags))  # deduplicate

        CORPUS.append({
            "tags": tags,
            "notes": f"Official Manim CE example: {scene}",
            "pattern": code,
        })


# Load at module import time
_load_json_examples()


# ═══════════════════════════════════════════════════════════════════════════════
# RETRIEVAL FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def retrieve_patterns(domain: str, topic: str, subtopics: list[str] = None, limit: int = 3) -> list[dict]:
    """
    Return up to `limit` relevant patterns from the corpus.
    Scoring:
      - +1 for each individual keyword match
      - +2 bonus for each multi-word tag phrase that appears verbatim in the query
    Falls back to generic domain patterns if nothing matches.
    """
    subtopics = subtopics or []
    query_text = " ".join([domain, topic] + subtopics).lower().replace("_", " ")
    query_tokens = set(query_text.split())

    scored = []
    for entry in CORPUS:
        score = 0
        for tag in entry["tags"]:
            tag_lower = tag.lower()
            tag_words = set(tag_lower.split())
            # Single keyword match
            token_overlap = len(query_tokens & tag_words)
            score += token_overlap
            # Bonus for whole multi-word phrase match
            if " " in tag_lower and tag_lower in query_text:
                score += 5
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: -x[0])
    if scored:
        return [e for _, e in scored[:limit]]

    # fallback: return first matching domain entries
    fallback = [e for e in CORPUS if domain.lower() in " ".join(e["tags"]).lower()]
    return fallback[:limit] if fallback else CORPUS[:2]


def retrieve_golden_example(domain: str, topic: str, subtopics: list[str] = None, db=None) -> str:
    """
    Build a formatted string of golden patterns to inject into the generation prompt.
    Also queries DB for real high-scoring examples.
    """
    sections = []

    # 1. DB examples (real battle-tested code)
    if db and db.available:
        try:
            examples = db.get_best_examples(domain=domain, limit=2)
            for ex in examples:
                sections.append(
                    f"# [OK] HIGH-SCORING EXAMPLE FROM DATABASE (score: {ex['overall_score']}/100)\n"
                    f"# Topic: {ex.get('topic', 'N/A')}\n"
                    f"{ex['final_code'][:1500]}\n# ... (truncated)\n"
                )
        except Exception:
            pass

    # 2. Curated corpus patterns
    patterns = retrieve_patterns(domain, topic, subtopics, limit=3)
    for p in patterns:
        sections.append(
            f"# [OK] PROVEN PATTERN: {p['notes']}\n"
            f"{p['pattern']}"
        )

    if not sections:
        return "# No domain-specific patterns found. Use standard Manim CE best practices."

    return "\n\n".join(sections)