"""
Streaming Generation Pipeline for NIMA.

Eliminates bulk generation timeouts by streaming scene-by-scene with
parallel render-while-generate pipeline.

Architecture:
  Prompt → Storyboard Plan → Scene Splitter → [For each scene]
      ├── Generate scene code (with narrative context)
      ├── Validate scene code
      ├── Render scene (in parallel while next scene generates)
      └── On scene fail → retry scene only, not full video
                                      ↓
                              Scene Concatenation → Final Video

Components:
  1. NarrativeContext     — tracks object/camera state across scenes
  2. split_plan_into_scenes() — split storyboard into individual scenes
  3. generate_scene()     — single scene with narrative context
  4. stream_render_scenes() — parallel render-while-generate
  5. retry_scene()        — scene-level retry with error feedback
  6. generate_scene_preamble() — recreates needed objects for scene
  7. stitch_scenes()      — ffmpeg concat of scene MP4s
  8. stream_generate()    — streaming LLM wrapper (multi-provider)
  9. estimate_scene_cost() — token budget estimation
"""

import json
import os
import sys
import time
import uuid
import subprocess
import re
import threading
import tempfile
from pathlib import Path
from typing import Iterator, Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_TIMEOUT,
    ZJUBAPI_BASE_URL,
    ZJUBAPI_API_KEY,
    ZJUBAPI_MODEL,
    ZJUBAPI_TIMEOUT,
    WENWEN_BASE_URL,
    WENWEN_API_KEY,
    WENWEN_MODEL,
    WENWEN_TIMEOUT,
    GENERATION_MODEL,
    FAST_MODEL,
    MANIM_SCRIPTS,
    OUTPUTS,
    RENDER_TIMEOUT_SECONDS,
    MAX_RENDER_RETRIES,
    STREAM_PARALLEL_RENDERS,
    STREAM_PROVIDER as CONFIG_STREAM_PROVIDER,
    STREAM_PROVIDER_FAILURE_COOLDOWN,
    STREAM_PROVIDER_TOTAL_TIMEOUT,
    STREAM_PROVIDER_USE_SUBPROCESS,
    STREAM_SCENE_TIMEOUT as CONFIG_STREAM_SCENE_TIMEOUT,
    STREAM_MAX_SCENES as CONFIG_STREAM_MAX_SCENES,
    STREAM_SCENE_RETRIES as CONFIG_STREAM_SCENE_RETRIES,
)
from algorithms.media_tools import (
    ffmpeg_command as _ffmpeg_command,
    manim_command as _manim_command,
    probe_media_duration_seconds,
    validate_video_file,
)
from algorithms.i18n import localize_scene_code
from algorithms.overlap_detector import run_all_checks as detect_static_layout_risks
from algorithms.rendering import cleanup_manim_partials, inject_manim_frame_config
from algorithms.video_quality import (
    analyze_video_frames,
    short_video_quality_requires_fallback,
    video_quality_requires_hard_failure,
    video_quality_requires_mode_recovery,
)
from RAG.RAG_system import retrieve_golden_example, retrieve_patterns


# ═══════════════════════════════════════════════════════════════════════════════
# PROVIDER CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Multi-provider streaming LLM configuration
PROVIDER_PRIORITY = ("zjuapi", "wenwen", "openai")
PROVIDER_FAILURE_COOLDOWN_SECONDS = STREAM_PROVIDER_FAILURE_COOLDOWN
PROVIDER_TOTAL_TIMEOUT_SECONDS = STREAM_PROVIDER_TOTAL_TIMEOUT
_PROVIDER_COOLDOWNS: Dict[str, float] = {}

STREAM_PROVIDERS = {
    "zjuapi": {
        "base_url": ZJUBAPI_BASE_URL,
        "api_key": ZJUBAPI_API_KEY,
        "model": ZJUBAPI_MODEL,
        "timeout": ZJUBAPI_TIMEOUT,
    },
    "wenwen": {
        "base_url": WENWEN_BASE_URL,
        "api_key": WENWEN_API_KEY,
        "model": WENWEN_MODEL,
        "timeout": WENWEN_TIMEOUT,
    },
    "openai": {
        "base_url": OPENAI_BASE_URL,
        "api_key": OPENAI_API_KEY,
        "model": GENERATION_MODEL,
        "timeout": OPENAI_TIMEOUT,
    },
}

# Active provider (auto-select based on availability)
STREAM_PROVIDER = CONFIG_STREAM_PROVIDER

# Scene generation settings
STREAM_SCENE_TIMEOUT = CONFIG_STREAM_SCENE_TIMEOUT
STREAM_MAX_SCENES = CONFIG_STREAM_MAX_SCENES
STREAM_SCENE_RETRIES = CONFIG_STREAM_SCENE_RETRIES
STREAM_MIN_SCENES = 2  # minimum scenes for long outputs
STREAM_RAG_CONTEXT_CHARS = 5000

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

SHORT_VERTICAL_RAG_REFERENCE = """\
# [OK] SHORT VERTICAL MANIM PATTERN: kinetic phone-safe explainer
config.frame_width = 8
config.frame_height = 14.222222
self.camera.background_color = "#0F1117"
title = Text("Fast hook", font_size=46, color="#F5F7FA", weight=BOLD).to_edge(UP, buff=0.65)
nodes = VGroup(*[
    Circle(radius=0.28, color="#58C4DD", fill_opacity=0.9).move_to(p)
    for p in [LEFT * 2 + UP * 2, RIGHT * 1.7 + UP * 1.2, LEFT * 1 + DOWN * 1.4, RIGHT * 2 + DOWN * 2]
])
edges = VGroup(
    Line(nodes[0].get_center(), nodes[1].get_center(), color="#334155", stroke_width=5),
    Line(nodes[0].get_center(), nodes[2].get_center(), color="#334155", stroke_width=5),
    Line(nodes[2].get_center(), nodes[3].get_center(), color="#334155", stroke_width=5),
    Line(nodes[1].get_center(), nodes[3].get_center(), color="#334155", stroke_width=5),
)
token = Dot(nodes[0].get_center(), radius=0.12, color="#F2C94C")
caption = Text("move the idea, not text", font_size=34, color="#F5F7FA").to_edge(DOWN, buff=0.8)
self.add(title, edges, nodes, token, caption)
self.play(Indicate(nodes[0], color="#F2C94C"), run_time=0.45)
self.play(MoveAlongPath(token, edges[0]), edges[0].animate.set_color("#F2C94C").set_stroke(width=9), run_time=0.9)
self.play(Transform(caption, Text("numbers change live", font_size=34, color="#F5F7FA").to_edge(DOWN, buff=0.8)), run_time=0.35)
self.play(MoveAlongPath(token, edges[3]), edges[3].animate.set_color("#22C55E").set_stroke(width=9), run_time=0.9)
self.wait(0.4)
"""

STANDARD_YOUTUBE_RAG_REFERENCE = """\
# [OK] STANDARD 16:9 MANIM PATTERN: retention-first YouTube explainer
self.camera.background_color = "#0F1117"
accent = "#58C4DD"
warm = "#F2C94C"
fg = "#F5F7FA"
title = Text("Why the obvious path fails", font_size=38, color=fg, weight=BOLD).to_edge(UP, buff=0.35)
axis = NumberLine(x_range=[0, 16, 2], length=9, color="#64748B").shift(DOWN * 1.6)
window = Rectangle(width=8.8, height=1.2, stroke_color=accent, stroke_width=4).move_to(axis)
mid = Dot(axis.n2p(8), radius=0.12, color=warm)
left_half = Rectangle(width=4.4, height=1.2, stroke_color="#EF4444", fill_color="#EF4444", fill_opacity=0.12).move_to(axis.n2p(4))
label = Text("Cut the search space", font_size=30, color=fg).next_to(axis, DOWN, buff=0.45)
self.add(title, axis, window, mid, label)
self.play(Create(axis), FadeIn(title, shift=DOWN * 0.2), run_time=0.8)
self.play(GrowFromCenter(window), Flash(mid, color=warm), run_time=0.9)
self.play(FadeIn(left_half), Indicate(left_half, color="#EF4444"), run_time=0.9)
self.play(left_half.animate.set_opacity(0.04), window.animate.set_width(4.4).move_to(axis.n2p(12)), mid.animate.move_to(axis.n2p(12)), run_time=1.1)
self.play(Transform(label, Text("Same rule, half the work", font_size=30, color=fg).next_to(axis, DOWN, buff=0.45)), run_time=0.6)
self.wait(1.2)
"""

COURSE_LESSON_RAG_REFERENCE = """\
# [OK] COURSE 16:9 MANIM PATTERN: modular lesson with checkpoint rail
self.camera.background_color = "#F9FAFB"
fg = "#111827"
muted = "#64748B"
accent = "#2563EB"
warm = "#F59E0B"
module = Text("Module 3 / 7", font_size=22, color=muted).to_corner(UL, buff=0.35)
rail = VGroup(*[
    Circle(radius=0.07, stroke_color=accent, fill_color=accent, fill_opacity=0.25)
    for _ in range(7)
]).arrange(RIGHT, buff=0.18).next_to(module, DOWN, aligned_edge=LEFT, buff=0.18)
title = Text("Invariant: the safe part stays safe", font_size=34, color=fg, weight=BOLD).to_edge(UP, buff=0.45)
boxes = VGroup(*[
    Rectangle(width=0.72, height=0.62, stroke_color=muted, fill_color="#E0F2FE", fill_opacity=0.45)
    for _ in range(9)
]).arrange(RIGHT, buff=0.08).shift(DOWN * 0.35)
window = Rectangle(width=4.2, height=0.86, stroke_color=accent, stroke_width=4).move_to(boxes[4])
invariant = Text("Everything outside the window is already ruled out", font_size=26, color=fg).next_to(boxes, DOWN, buff=0.55)
marker = Triangle(color=warm, fill_opacity=0.9).scale(0.18).next_to(boxes[4], UP, buff=0.2)
self.add(module, rail, title)
self.play(LaggedStart(*[FadeIn(b, shift=UP * 0.08) for b in boxes], lag_ratio=0.08), run_time=1.0)
self.play(GrowFromCenter(window), FadeIn(marker), run_time=0.8)
self.play(Write(invariant), rail[2].animate.set_fill(accent, opacity=1), run_time=0.8)
self.play(window.animate.set_width(2.0).move_to(boxes[6]), marker.animate.next_to(boxes[6], UP, buff=0.2), run_time=1.0)
self.play(Indicate(invariant, color=warm), run_time=0.8)
self.wait(1.2)
"""

LECTURE_ACADEMIC_RAG_REFERENCE = """\
# [OK] LECTURE 16:9 MANIM PATTERN: academic board with derivation focus
self.camera.background_color = "#F8FAFC"
fg = "#0F172A"
muted = "#64748B"
accent = "#1D4ED8"
warm = "#B45309"
section = Text("Section 4 - Main Proof", font_size=24, color=muted).to_corner(UL, buff=0.55)
claim = Text("Claim", font_size=28, color=fg, weight=BOLD).to_edge(UP, buff=0.62)
proof_map = VGroup(
    Text("assumptions", font_size=24, color=muted),
    Arrow(LEFT, RIGHT, color=accent),
    Text("lemma", font_size=24, color=accent),
    Arrow(LEFT, RIGHT, color=accent),
    Text("result", font_size=24, color=warm),
).arrange(RIGHT, buff=0.22).next_to(claim, DOWN, buff=0.32)
line_1 = Text("1. Start from the assumption", font_size=28, color=fg).shift(UP * 0.05)
line_2 = Text("2. Substitute the lemma result", font_size=28, color=fg).next_to(line_1, DOWN, aligned_edge=LEFT, buff=0.3)
old_layer = VGroup(proof_map, line_1)
self.add(section, claim)
self.play(FadeIn(proof_map, shift=DOWN * 0.08), Write(line_1), run_time=1.0)
focus_transition(self, old_layer, line_2, run_time=0.8)
self.play(Circumscribe(line_2, color=warm), run_time=0.7)
self.wait(1.0)
"""

FOCUS_LAYER_RAG_REFERENCE = """\
# [OK] FOCUS LAYER PATTERN: simulated depth without fragile blur filters
# Do not use Blur(...), GaussianBlur(...), PIL image filters, or camera post-processing.
# In Manim, readability is more reliable when older layers are dimmed and the
# active idea receives a translucent plate plus a higher z-index.
# The renderer injects fit_to_safe_frame(...), focus_plate(...), and
# focus_transition(scene, old_layer, active_layer) into every generated scene.

old_layer = VGroup(previous_diagram, previous_labels)
new_label = Text("new idea", font_size=28, color="#111827").move_to(RIGHT * 2 + UP * 0.8)
focus_transition(self, old_layer, new_label)
# Later, either keep the old layer dimmed as context or fade it out before the next dense panel.
"""

VISUAL_TEMPLATES = {
    "dark-blueprint": {
        "label": "Dark Blueprint",
        "mode": "dark",
        "background_color": "#0F1117",
        "foreground_color": "#F5F7FA",
        "accent": "#58C4DD",
        "style_notes": "technical, blueprint-like, neon cyan accents, high contrast, cinematic dark UI",
    },
    "dark-cinema": {
        "label": "Dark Cinema",
        "mode": "dark",
        "background_color": "#101418",
        "foreground_color": "#F6F1E9",
        "accent": "#FFB86C",
        "style_notes": "dramatic dark mode, warm highlights, elegant math presentation, minimal HUD",
    },
    "light-notebook": {
        "label": "Light Notebook",
        "mode": "light",
        "background_color": "#FAF7F0",
        "foreground_color": "#202124",
        "accent": "#2563EB",
        "style_notes": "clean academic notebook style, paper-like background, blue emphasis, readable annotations",
    },
    "light-minimal": {
        "label": "Light Minimal",
        "mode": "light",
        "background_color": "#FFFFFF",
        "foreground_color": "#111827",
        "accent": "#14B8A6",
        "style_notes": "minimal bright presentation, sparse layout, clean geometry, modern explainer aesthetic",
    },
    "dark-linalg": {
        "label": "Dark Linear Algebra",
        "mode": "dark",
        "background_color": "#0B1020",
        "foreground_color": "#E5EEF8",
        "accent": "#8B5CF6",
        "style_notes": "precise linear algebra style, dark indigo background, matrix-focused, vectors and transforms glow subtly",
    },
    "dark-graph": {
        "label": "Dark Graph Theory",
        "mode": "dark",
        "background_color": "#0E141B",
        "foreground_color": "#F3F4F6",
        "accent": "#22C55E",
        "style_notes": "network/graph aesthetic, dark slate background, nodes and edges with strong green highlights, algorithmic feel",
    },
    "light-calculus": {
        "label": "Light Calculus",
        "mode": "light",
        "background_color": "#FFFDF7",
        "foreground_color": "#1F2937",
        "accent": "#DC2626",
        "style_notes": "clean calculus whiteboard, warm paper background, red highlights for tangents, areas, limits and derivatives",
    },
    "light-discrete": {
        "label": "Light Discrete",
        "mode": "light",
        "background_color": "#F8FAFC",
        "foreground_color": "#0F172A",
        "accent": "#7C3AED",
        "style_notes": "clear discrete math style, structured boxes/arrows, crisp labels, ideal for proofs, graphs, sets, and combinatorics",
    },
    "dark-physics": {
        "label": "Dark Physics",
        "mode": "dark",
        "background_color": "#050816",
        "foreground_color": "#E0F2FE",
        "accent": "#38BDF8",
        "style_notes": "deep-space physics aesthetic, dark cosmic background, luminous vectors/fields/waves, cinematic scientific style",
    },
    "light-cs": {
        "label": "Light Computer Science",
        "mode": "light",
        "background_color": "#F9FAFB",
        "foreground_color": "#111827",
        "accent": "#2563EB",
        "style_notes": "clean CS explainer style, code/data-structure friendly, blue algorithm highlights, organized and readable",
    },
    "dark-game-theory": {
        "label": "Dark Game Theory",
        "mode": "dark",
        "background_color": "#111827",
        "foreground_color": "#F9FAFB",
        "accent": "#F59E0B",
        "style_notes": "strategic decision-board aesthetic, payoff matrices, highlighted choices, tension between options, elegant dark presentation",
    },
    "light-proof": {
        "label": "Light Proof",
        "mode": "light",
        "background_color": "#FFFBF5",
        "foreground_color": "#1F2937",
        "accent": "#7C3AED",
        "style_notes": "clean proof-oriented layout, theorem/proof structure, boxes, arrows, and highlighted contradictions or logical steps",
    },
}


def choose_visual_template(
    prompt: str, analysis: dict, explicit_template: str | None = None
) -> str:
    """Choose a render template by explicit request, domain, and concept keywords."""
    if explicit_template and explicit_template in VISUAL_TEMPLATES:
        return explicit_template

    text = f"{prompt} {analysis.get('domain', '')}".lower()
    domain = (analysis.get("domain") or "").lower()
    mode = (analysis.get("video_mode") or "").lower()
    aspect = str(analysis.get("aspect") or "")

    if mode == "lecture":
        return "light-notebook"

    if any(
        k in text
        for k in [
            "prisoner",
            "dilemma",
            "nash",
            "payoff",
            "game theory",
            "strategy",
            "equilibrium",
        ]
    ):
        return "dark-game-theory"
    if any(
        k in text
        for k in ["matrix", "eigen", "vector", "linear transformation", "svd", "basis"]
    ):
        return "dark-linalg"
    if any(
        k in text
        for k in ["graph", "adjacency", "bfs", "dfs", "hamiltonian", "eulerian", "tree"]
    ):
        return "dark-graph"
    if any(
        k in text
        for k in [
            "integral",
            "derivative",
            "limit",
            "laplace",
            "taylor",
            "epsilon",
            "delta",
        ]
    ):
        return "light-calculus"

    if mode == "short" or aspect == "9:16":
        # Vertical shorts are usually viewed on small screens. Prefer high contrast
        # dark themes and large central visuals instead of proof/notebook layouts.
        if domain == "physics":
            return "dark-physics"
        return "dark-blueprint"

    if any(
        k in text
        for k in [
            "subgroup",
            "set",
            "bijection",
            "pigeonhole",
            "combinatorics",
            "discrete",
            "proof",
            "contradiction",
            "theorem",
        ]
    ):
        return "light-proof"
    if domain == "physics":
        return "dark-physics"
    if domain in ("computer_science", "cs"):
        return "light-cs"
    if domain == "math":
        return "dark-blueprint"
    return "dark-blueprint"


def _provider_has_credentials(provider_name: str) -> bool:
    cfg = STREAM_PROVIDERS.get(provider_name) or {}
    return bool(cfg.get("api_key"))


def _provider_is_cooled_down(provider_name: str) -> bool:
    until = _PROVIDER_COOLDOWNS.get(provider_name)
    if not until:
        return False
    if until <= time.time():
        _PROVIDER_COOLDOWNS.pop(provider_name, None)
        return False
    return True


def _generation_error_is_timeout(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "timeout" in text
        or "timed out" in text
        or exc.__class__.__name__.lower() in {"timeout", "timeouterror"}
    )


def _mark_provider_failure(provider_name: str, exc: Exception) -> None:
    if provider_name not in STREAM_PROVIDERS:
        return
    if PROVIDER_FAILURE_COOLDOWN_SECONDS <= 0:
        return
    _PROVIDER_COOLDOWNS[provider_name] = (
        time.time() + PROVIDER_FAILURE_COOLDOWN_SECONDS
    )


def _clear_provider_failure(provider_name: str) -> None:
    _PROVIDER_COOLDOWNS.pop(provider_name, None)


def _provider_attempt_order(provider: str = "auto") -> List[str]:
    """Return providers to try, preserving forced-provider behavior."""
    requested = provider if provider != "auto" else STREAM_PROVIDER
    if requested != "auto":
        return [requested] if requested in STREAM_PROVIDERS else ["openai"]

    configured = [
        name for name in PROVIDER_PRIORITY if _provider_has_credentials(name)
    ]
    if not configured:
        return ["openai"]

    active = [name for name in configured if not _provider_is_cooled_down(name)]
    return active or configured


def _select_provider() -> str:
    """Auto-select the first configured provider that is not in cooldown."""
    order = _provider_attempt_order("auto")
    return order[0] if order else "openai"


# ═══════════════════════════════════════════════════════════════════════════════
# NARRATIVE CONTEXT
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class NarrativeContext:
    """
    Tracks narrative state across scenes to maintain coherence.

    Each scene receives this context so the LLM knows what's been created,
    where the camera is, and what domain-specific state exists.
    """

    prompt: str
    domain: str
    duration_target: int = 60
    scene_index: int = 0

    # Object state — tracks what's been created and is available
    # Maps object_name -> {"type": "Circle|Text|... ", "state": "description"}
    object_state: Dict[str, dict] = field(default_factory=dict)

    # Camera state — current position/zoom
    camera_state: Dict[str, Any] = field(default_factory=dict)

    # Scene history — completed scene summaries for context
    scene_history: List[str] = field(default_factory=list)

    # Domain-specific state
    domain_state: Dict[str, Any] = field(default_factory=dict)

    def add_object(self, name: str, obj_type: str, description: str):
        """Register an object created in a scene."""
        self.object_state[name] = {"type": obj_type, "description": description}

    def remove_object(self, name: str):
        """Mark an object as no longer in scene."""
        if name in self.object_state:
            del self.object_state[name]

    def update_camera(self, **kwargs):
        """Update camera state."""
        self.camera_state.update(kwargs)

    def add_scene_history(self, scene_summary: str):
        """Record a scene for context in future scenes."""
        self.scene_history.append(scene_summary)
        # Keep last 5 scenes for context window
        if len(self.scene_history) > 5:
            self.scene_history = self.scene_history[-5:]

    def to_context_string(self) -> str:
        """Render this context as a string for LLM prompt injection."""
        lines = ["=== NARRATIVE CONTEXT ==="]

        if self.scene_history:
            lines.append("\nPrevious scenes:")
            for i, summary in enumerate(self.scene_history, 1):
                lines.append(f"  Scene {i}: {summary}")

        if self.object_state:
            lines.append("\nObjects in scene:")
            for name, info in self.object_state.items():
                lines.append(f"  {name} ({info['type']}): {info['description']}")

        if self.camera_state:
            lines.append("\nCamera state:")
            for k, v in self.camera_state.items():
                lines.append(f"  {k}: {v}")

        if self.domain_state:
            lines.append(f"\nDomain state ({self.domain}):")
            for k, v in self.domain_state.items():
                lines.append(f"  {k}: {v}")

        lines.append(f"\nTarget duration: {self.duration_target}s total")
        return "\n".join(lines)

    @classmethod
    def from_analysis(cls, prompt: str, analysis: dict) -> "NarrativeContext":
        """Create initial context from request analysis."""
        domain = analysis.get("domain", "general")
        duration = analysis.get("duration", 60)

        ctx = cls(prompt=prompt, domain=domain, duration_target=duration)

        # Domain-specific initial state
        if domain == "math":
            ctx.domain_state = {
                "coordinate_system": "2d",
                "has_axes": False,
                "latex_mode": True,
                "background_color": "#0F1117",
                "foreground_color": "#F5F7FA",
                "theme_mode": "dark",
            }
        elif domain == "physics":
            ctx.domain_state = {
                "has_planes": False,
                "unit_system": "SI",
                "background_color": "#0F1117",
                "foreground_color": "#F5F7FA",
                "theme_mode": "dark",
            }
        elif domain == "computer_science":
            ctx.domain_state = {
                "has_diagram": False,
                "code_highlighting": True,
                "background_color": "#0F1117",
                "foreground_color": "#F5F7FA",
                "theme_mode": "dark",
            }

        return ctx


def apply_visual_template(
    context: NarrativeContext, template_id: str | None
) -> NarrativeContext:
    """Apply a curated visual template to the whole streaming job."""
    template_id = template_id or "dark-blueprint"
    tpl = VISUAL_TEMPLATES.get(template_id, VISUAL_TEMPLATES["dark-blueprint"])
    context.domain_state.update(
        {
            "template_id": template_id,
            "template_label": tpl["label"],
            "theme_mode": tpl["mode"],
            "background_color": tpl["background_color"],
            "foreground_color": tpl["foreground_color"],
            "accent_color": tpl["accent"],
            "style_notes": tpl["style_notes"],
        }
    )
    return context


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE SPLITTER
# ═══════════════════════════════════════════════════════════════════════════════


def split_plan_into_scenes(plan_data: dict, max_scenes: int = 20) -> List[dict]:
    """
    Split a storyboard plan into individual scenes.

    Each scene is one animation unit. The split is based on:
    - Scene/beats in the plan JSON
    - Natural break points (concept transitions)
    - Max scene count to prevent over-fragmentation

    Returns list of scene dicts with keys:
      scene_id, description, objects, duration_hint, animation_steps
    """
    scenes = []
    mode = (plan_data.get("video_mode") or "").lower()

    # Try to extract scenes from plan structure
    if "scenes" in plan_data:
        raw_scenes = _coerce_plan_items(plan_data["scenes"])
    elif "beats" in plan_data:
        # Group beats into scenes (every 2-4 beats = 1 scene)
        beats = _coerce_plan_items(plan_data["beats"])
        scene_beats = []
        for beat in beats:
            scene_beats.append(beat)
            # Split every 3 beats or on major transition markers
            if len(scene_beats) >= 3 or beat.get("is_transition"):
                scene_id = f"scene_{len(scenes)}"
                scenes.append(_beats_to_scene(scene_id, scene_beats, plan_data))
                scene_beats = []
        if scene_beats:
            scenes.append(
                _beats_to_scene(f"scene_{len(scenes)}", scene_beats, plan_data)
            )
        return _finalize_split_scenes(scenes, plan_data, max_scenes)
    elif "segments" in plan_data:
        # Voiceover-style segments
        raw_scenes = _coerce_plan_items(plan_data["segments"])
    else:
        # Fallback: treat entire plan as one scene
        scenes.append(
            {
                "scene_id": "scene_0",
                "description": _clean_plan_text(
                    plan_data.get("description", "Main scene")
                ),
                "objects": [],
                "duration_hint": _safe_positive_int(plan_data.get("duration"), 60),
                "animation_steps": _clean_plan_text_list(
                    [plan_data.get("plan", str(plan_data))]
                ),
            }
        )
        return _finalize_split_scenes(scenes, plan_data, max_scenes)

    if not raw_scenes:
        scenes.append(
            {
                "scene_id": "scene_0",
                "description": _clean_plan_text(
                    plan_data.get("description", "Main scene")
                ),
                "objects": [],
                "duration_hint": _safe_positive_int(plan_data.get("duration"), 60),
                "animation_steps": _clean_plan_text_list(
                    [plan_data.get("plan", str(plan_data))]
                ),
            }
        )
        return _finalize_split_scenes(scenes, plan_data, max_scenes)

    # Process raw scenes. Short mode needs to preserve the final question even
    # when the model over-produces content segments.
    selected_raw = raw_scenes
    if len(raw_scenes) > max_scenes:
        question_indices = [
            idx for idx, raw in enumerate(raw_scenes) if raw.get("type") == "question"
        ]
        if mode == "short" and question_indices:
            selected_raw = [
                *[
                    raw
                    for idx, raw in enumerate(raw_scenes)
                    if idx != question_indices[-1]
                ][: max_scenes - 1],
                raw_scenes[question_indices[-1]],
            ]
        else:
            selected_raw = raw_scenes[:max_scenes]

    for i, raw in enumerate(selected_raw):
        scene_id = raw.get("id", f"scene_{i}")
        description = _clean_plan_text(raw.get("description", raw.get("narration", "")))
        narration = _clean_plan_text(raw.get("narration", ""))
        animation_steps = _clean_plan_text_list(
            raw.get("animation", raw.get("beats", []))
            or [raw.get("visual_description", "")]
        )
        scene = {
            "scene_id": scene_id,
            "description": description,
            "objects": raw.get("objects", []),
            "duration_hint": _safe_positive_int(
                raw.get("duration", raw.get("estimated_duration", 10)), 10
            ),
            "animation_steps": animation_steps or [description],
        }
        # Preserve segment metadata for downstream use (question scenes, narration, etc.)
        if raw.get("type"):
            scene["type"] = raw["type"]
        if narration:
            scene["narration"] = narration
        if raw.get("title"):
            scene["title"] = raw["title"]
        for key in (
            "visual_description",
            "scene_role",
            "required_motions",
            "short_directives",
            "standard_directives",
            "course_directives",
            "forbidden_visuals",
            "beat_intensity",
            "retention_hook",
            "module",
            "lecture_section",
            "lecture_directives",
            "learning_objective",
            "checkpoint_id",
        ):
            if key in raw:
                scene[key] = raw[key]
        scenes.append(scene)

    return _finalize_split_scenes(scenes, plan_data, max_scenes)


def _coerce_plan_items(value: Any) -> List[dict]:
    """Return only dict items from an LLM-provided list-like plan field."""
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = int(default)
    return max(1, parsed)


def _clean_plan_text(value: Any) -> str:
    """Normalize LLM plan text and drop obvious dangling sentence fragments."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""

    # Split into sentence-like chunks while preserving terminal punctuation.
    chunks = re.findall(r"[^.!?]+[.!?]?", text)
    chunks = [chunk.strip() for chunk in chunks if chunk.strip()]
    if not chunks:
        return text

    dangling_starters = {
        "if",
        "when",
        "while",
        "because",
        "but",
        "and",
        "or",
        "so",
        "then",
        "the",
        "this",
        "that",
    }
    dangling_enders = {
        "and",
        "or",
        "but",
        "the",
        "a",
        "an",
        "to",
        "of",
        "for",
        "with",
        "from",
        "at",
        "in",
        "on",
        "by",
        "into",
        "onto",
        "than",
        "as",
    }
    preposition_starters = {"at", "in", "on", "from", "to", "for", "with", "by"}
    cleaned_chunks = list(chunks)
    last = cleaned_chunks[-1].strip()
    last_words = re.findall(r"[A-Za-z0-9']+", last)
    first_word = last_words[0].lower() if last_words else ""
    final_word = last_words[-1].lower() if last_words else ""
    has_terminal = last.endswith((".", "?", "!"))
    ends_as_article_phrase = bool(
        re.search(r"\b(the|a|an)\s+[A-Za-z0-9']+[.!?]?$", last, flags=re.I)
    )
    short_dangling = len(last_words) <= 7 and (
        first_word in dangling_starters or final_word in dangling_enders
    )
    preposition_fragment = (
        len(last_words) <= 8
        and first_word in preposition_starters
        and ends_as_article_phrase
    )
    unterminated_fragment = not has_terminal and len(last_words) <= 8
    if len(cleaned_chunks) > 1 and (
        short_dangling or preposition_fragment or unterminated_fragment
    ):
        cleaned_chunks.pop()

    cleaned = " ".join(cleaned_chunks).strip()
    if not cleaned:
        cleaned = text
    if cleaned and cleaned[-1] not in ".!?":
        cleaned = cleaned.rstrip(",;:") + "."
    return cleaned


def _clean_plan_text_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [_clean_plan_text(value)] if value.strip() else []
    if isinstance(value, (list, tuple)):
        cleaned = []
        for item in value:
            if isinstance(item, dict):
                text = (
                    item.get("animation")
                    or item.get("description")
                    or item.get("narration")
                    or item.get("visual_description")
                    or ""
                )
            else:
                text = item
            cleaned_text = _clean_plan_text(text)
            if cleaned_text:
                cleaned.append(cleaned_text)
        return cleaned
    return []


def _finalize_split_scenes(
    scenes: List[dict], plan_data: dict, max_scenes: int
) -> List[dict]:
    """Apply mode-aware bounds and dedupe to every supported plan shape."""
    mode = (plan_data.get("video_mode") or "").lower()
    if mode in ("course", "lecture"):
        # Preserve long-form structure: skip dedupe in course/lecture mode.
        # Repetition is handled by reporting instead of destructive collapse.
        pass
    else:
        scenes = _dedupe_similar_scenes(scenes)

    return _ensure_scene_bounds(scenes, plan_data, max_scenes)


def _scene_bounds(plan_data: dict, max_scenes: int) -> tuple[int, int]:
    """Resolve mode scene limits from plan metadata with config fallback."""
    try:
        from algorithms.video_modes import build_video_mode_profile

        profile = build_video_mode_profile(plan_data.get("video_mode"))
        mode_min = profile.min_scenes
        mode_max = profile.max_scenes
    except Exception:
        mode_min = 1
        mode_max = max_scenes

    hard_max = _safe_positive_int(max_scenes, mode_max or 1)
    min_scenes = _safe_positive_int(plan_data.get("min_scenes"), mode_min or 1)
    resolved_max = _safe_positive_int(
        plan_data.get("max_scenes"), mode_max or hard_max
    )
    resolved_max = max(1, min(hard_max, resolved_max))
    min_scenes = max(1, min(min_scenes, resolved_max))
    return min_scenes, resolved_max


def _ensure_scene_bounds(
    scenes: List[dict], plan_data: dict, max_scenes: int
) -> List[dict]:
    """Expand sparse plans toward the mode's minimum scene count."""
    if not scenes:
        return scenes

    min_scenes, resolved_max = _scene_bounds(plan_data, max_scenes)
    if len(scenes) >= min_scenes:
        return scenes[:resolved_max]

    expanded = list(scenes)
    while len(expanded) < min_scenes and len(expanded) < resolved_max:
        split_idx = _choose_scene_to_split(expanded)
        if split_idx is None:
            break
        parts = _split_scene(expanded[split_idx])
        if len(parts) < 2:
            break
        expanded = expanded[:split_idx] + parts + expanded[split_idx + 1 :]

    for i, scene in enumerate(expanded):
        scene["scene_id"] = scene.get("scene_id") or f"scene_{i}"

    return expanded[:resolved_max]


def _choose_scene_to_split(scenes: List[dict]) -> Optional[int]:
    candidates = [
        (idx, scene)
        for idx, scene in enumerate(scenes)
        if scene.get("type") != "question"
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            len(item[1].get("animation_steps", []) or []),
            len(item[1].get("description", "") or ""),
        ),
    )[0]


def _split_scene(scene: dict) -> List[dict]:
    if scene.get("type") == "question":
        return [scene]

    steps = _clean_plan_text_list(scene.get("animation_steps", []) or [])
    description = _clean_plan_text(
        scene.get("description", "") or scene.get("narration", "")
    )
    duration = max(2, _safe_positive_int(scene.get("duration_hint"), 20))

    if len(steps) >= 2:
        mid = max(1, len(steps) // 2)
        step_groups = [steps[:mid], steps[mid:]]
    else:
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+", description)
            if s.strip()
        ]
        if len(sentences) < 2:
            return [scene]
        mid = max(1, len(sentences) // 2)
        step_groups = [
            [" ".join(sentences[:mid])],
            [" ".join(sentences[mid:])],
        ]

    parts = []
    base_id = scene.get("scene_id", "scene")
    for idx, group in enumerate(step_groups):
        desc = group[0] if group else description
        part = dict(scene)
        part["scene_id"] = f"{base_id}_{idx + 1}"
        part["description"] = _clean_plan_text(desc)
        part["animation_steps"] = _clean_plan_text_list(group)
        part["duration_hint"] = max(4, duration // 2)
        if "narration" in part:
            part["narration"] = _clean_plan_text(desc)
        parts.append(part)

    return parts


def _tokenize_for_similarity(text: str) -> set:
    words = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    stop = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "scene",
        "part",
    }
    return {w for w in words if w not in stop and len(w) > 2}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _dedupe_similar_scenes(scenes: List[dict], threshold: float = 0.78) -> List[dict]:
    """Remove near-duplicate scenes from plan output to avoid repeated segments.

    Never removes scenes with type='question' — those are intentional pedagogical pauses.
    """
    if len(scenes) <= 1:
        return scenes

    deduped = []
    seen_tokens: List[set] = []
    for s in scenes:
        # Never dedupe question scenes
        if s.get("type") == "question":
            deduped.append(s)
            continue

        desc = s.get("description", "")
        toks = _tokenize_for_similarity(desc)
        if not toks:
            deduped.append(s)
            continue
        is_dup = any(_jaccard(toks, prev) >= threshold for prev in seen_tokens)
        if is_dup:
            continue
        deduped.append(s)
        seen_tokens.append(toks)

    # keep at least 1 scene
    return deduped or scenes[:1]


def _beats_to_scene(scene_id: str, beats: List[dict], plan_data: dict) -> dict:
    """Convert a group of beats into a scene dict."""
    descriptions = [
        _clean_plan_text(b.get("description", b.get("narration", ""))) for b in beats
    ]
    return {
        "scene_id": scene_id,
        "description": _clean_plan_text(" -> ".join(descriptions[:2])),
        "objects": _extract_objects_from_beats(beats),
        "duration_hint": sum(_safe_positive_int(b.get("duration"), 5) for b in beats),
        "animation_steps": _clean_plan_text_list(
            [b.get("animation", b.get("description", "")) for b in beats]
        ),
    }


def _extract_objects_from_beats(beats: List[dict]) -> List[str]:
    """Extract mentioned objects from beats."""
    objects = []
    seen = set()
    for beat in beats:
        for obj in beat.get("objects", []):
            if obj not in seen:
                objects.append(obj)
                seen.add(obj)
    return objects


# ═══════════════════════════════════════════════════════════════════════════════
# STREAMING LLM WRAPPER
# ═══════════════════════════════════════════════════════════════════════════════


def stream_generate(
    prompt: str,
    context: NarrativeContext,
    provider: str = "auto",
) -> Iterator[str]:
    """
    Stream tokens from LLM provider.

    Yields tokens as they arrive for real-time processing.

    Args:
        prompt: The full prompt to send
        context: NarrativeContext for provider routing
        provider: Provider name or "auto"

    Yields:
        str: Tokens as they arrive
    """
    providers = _provider_attempt_order(provider)
    if len(providers) == 1 and providers[0] != "openai":
        yield from _generate_non_streaming(prompt, context, providers=providers)
        return

    stream_failures: List[Tuple[str, Exception]] = []

    for provider_name in providers:
        try:
            content = _generate_with_provider(
                prompt, context, provider_name, stream=True
            )
            if content.strip():
                _clear_provider_failure(provider_name)
                print(
                    f"[STREAM] Provider {provider_name} succeeded "
                    f"({len(content)} chars)"
                )
                yield from _yield_llm_chunks(content)
                return
            raise ValueError("empty provider response")
        except Exception as e:
            _mark_provider_failure(provider_name, e)
            stream_failures.append((provider_name, e))
            print(f"[STREAM] Provider {provider_name} failed: {e}")

    non_streaming_candidates = [
        provider_name
        for provider_name, exc in stream_failures
        if not _generation_error_is_timeout(exc)
    ]
    if not non_streaming_candidates:
        yield ""
        return

    yield from _generate_non_streaming(
        prompt, context, providers=non_streaming_candidates
    )


def _build_llm_messages(prompt: str, context: NarrativeContext) -> List[dict]:
    return [
        {"role": "system", "content": _build_stream_system_msg(context)},
        {"role": "user", "content": prompt},
    ]


def _yield_llm_chunks(content: str, chunk_size: int = 20) -> Iterator[str]:
    for i in range(0, len(content), chunk_size):
        yield content[i : i + chunk_size]


def _provider_request_timeout(cfg: dict) -> int:
    configured = int(cfg.get("timeout") or 60)
    cap = int(PROVIDER_TOTAL_TIMEOUT_SECONDS or 0)
    if cap <= 0:
        return configured
    return max(10, min(configured, cap))


def _provider_max_tokens(context: NarrativeContext, *, stream: bool) -> int:
    mode = str(context.domain_state.get("video_mode") or "").lower()
    if mode == "short":
        return 2200 if stream else 2800
    if mode == "standard":
        return 2200 if stream else 2800
    if mode in {"course", "lecture"}:
        return 2400 if stream else 3200
    return 2600 if stream else 3400


# Some upstream proxies (e.g. third-party gpt-5.x relays) reject the legacy
# `max_tokens` field — and the openai SDK 2.x silently rewrites it to either
# `max_completion_tokens` (chat) or `max_output_tokens` (responses) depending
# on the detected model family. When that rewritten field comes back as a 400
# "Unsupported parameter", we retry once without any token cap.
_MAX_TOKEN_PARAM_HINTS = (
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
)


_MAX_TOKEN_REJECT_PHRASES = (
    "unsupported parameter",
    "unrecognized",
    "is not supported",
    "not allowed",
    "is not allowed",
    "not permitted",
)


def _is_max_tokens_unsupported_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if not any(p in msg for p in _MAX_TOKEN_REJECT_PHRASES):
        return False
    return any(hint in msg for hint in _MAX_TOKEN_PARAM_HINTS)


def _create_chat_completion(client, *, stream: bool, **kwargs):
    """Call chat.completions.create with a retry that drops max_tokens.

    Returns the response object as-is. Raises whatever the SDK raises when
    the retry path is not applicable.
    """
    try:
        return client.chat.completions.create(stream=stream, **kwargs)
    except Exception as exc:
        if "max_tokens" in kwargs and _is_max_tokens_unsupported_error(exc):
            kwargs.pop("max_tokens", None)
            print(
                "[STREAM] Provider rejected max_tokens parameter; "
                "retrying without a token cap"
            )
            return client.chat.completions.create(stream=stream, **kwargs)
        raise


def _partial_scene_content_is_usable(content: str) -> bool:
    lowered = (content or "").lower()
    return (
        len(content or "") >= 1200
        and "from manim import" in lowered
        and "class generatedscene" in lowered
        and "def construct" in lowered
    )


def _generate_with_provider(
    prompt: str,
    context: NarrativeContext,
    provider_name: str,
    *,
    stream: bool,
) -> str:
    if STREAM_PROVIDER_USE_SUBPROCESS:
        return _generate_with_provider_subprocess(
            prompt, context, provider_name, stream=stream
        )
    return _generate_with_provider_in_process(
        prompt, context, provider_name, stream=stream
    )


def _generate_with_provider_in_process(
    prompt: str,
    context: NarrativeContext,
    provider_name: str,
    *,
    stream: bool,
) -> str:
    cfg = STREAM_PROVIDERS.get(provider_name, STREAM_PROVIDERS["openai"])
    request_timeout = _provider_request_timeout(cfg)
    started = time.time()
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            timeout=request_timeout,
        )

        messages = _build_llm_messages(prompt, context)

        response = _create_chat_completion(
            client,
            model=cfg["model"],
            messages=messages,
            stream=stream,
            max_tokens=_provider_max_tokens(context, stream=stream),
        )

        if not stream:
            return response.choices[0].message.content or ""

        chunks = []
        for chunk in response:
            if time.time() - started > request_timeout:
                partial = "".join(chunks)
                if _partial_scene_content_is_usable(partial):
                    print(
                        f"[STREAM] Provider {provider_name} hit {request_timeout}s; "
                        f"using partial candidate ({len(partial)} chars)"
                    )
                    return partial
                raise TimeoutError(
                    f"{provider_name} streaming exceeded {request_timeout}s"
                )
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
        return "".join(chunks)

    except Exception as e:
        raise e


def _generate_with_provider_subprocess(
    prompt: str,
    context: NarrativeContext,
    provider_name: str,
    *,
    stream: bool,
) -> str:
    """Run provider generation in a child process so timeout kills are real."""
    cfg = STREAM_PROVIDERS.get(provider_name, STREAM_PROVIDERS["openai"])
    request_timeout = _provider_request_timeout(cfg)
    payload = {
        "api_key": cfg.get("api_key") or "",
        "base_url": cfg.get("base_url"),
        "model": cfg.get("model"),
        "timeout": request_timeout,
        "stream": bool(stream),
        "max_tokens": _provider_max_tokens(context, stream=stream),
        "messages": _build_llm_messages(prompt, context),
    }

    tmp_dir = Path(tempfile.mkdtemp(prefix="nima-llm-"))
    payload_path = tmp_dir / "payload.json"
    output_path = tmp_dir / "output.txt"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    output_path.write_text("", encoding="utf-8")
    # Resolve to the project root (parent of `algorithms/`) so `python -m
    # algorithms._streaming_child` can import the module regardless of the
    # parent process's cwd.
    project_root = Path(__file__).resolve().parent.parent
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "algorithms._streaming_child",
                str(payload_path),
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=request_timeout + 5,
            cwd=str(project_root),
        )
        content = output_path.read_text(encoding="utf-8", errors="replace")
        # Surface any [STREAM] telemetry the child emitted to stdout (e.g.,
        # the max_tokens-fallback log line) so it lands in operator logs
        # alongside the parent's [STREAM] lines.
        if result.stdout:
            for line in result.stdout.splitlines():
                if line.startswith("[STREAM]"):
                    print(line)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "provider subprocess failed")[-1200:])
        return content
    except subprocess.TimeoutExpired as exc:
        content = output_path.read_text(encoding="utf-8", errors="replace")
        # Surface child telemetry the kill captured before SIGKILL — e.g. a
        # successful max_tokens fallback log from the *first* call where the
        # *retry* is what timed out. Both bytes and str payloads are possible
        # depending on platform.
        partial_stdout = exc.stdout
        if isinstance(partial_stdout, bytes):
            partial_stdout = partial_stdout.decode("utf-8", errors="replace")
        if partial_stdout:
            for line in partial_stdout.splitlines():
                if line.startswith("[STREAM]"):
                    print(line)
        if stream and _partial_scene_content_is_usable(content):
            print(
                f"[STREAM] Provider {provider_name} subprocess hit {request_timeout}s; "
                f"using partial candidate ({len(content)} chars)"
            )
            return content
        raise TimeoutError(f"{provider_name} generation exceeded {request_timeout}s") from exc
    finally:
        try:
            payload_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass


def _generate_non_streaming(
    prompt: str,
    context: NarrativeContext,
    providers: Optional[List[str]] = None,
) -> Iterator[str]:
    """Fallback non-streaming generation."""
    candidate_providers = providers or _provider_attempt_order("auto")

    for provider_name in candidate_providers:
        try:
            content = _generate_with_provider(
                prompt, context, provider_name, stream=False
            )
            if content.strip():
                _clear_provider_failure(provider_name)
                print(
                    f"[STREAM] Non-streaming provider {provider_name} succeeded "
                    f"({len(content)} chars)"
                )
                yield from _yield_llm_chunks(content)
                return
            raise ValueError("empty provider response")
        except Exception as e:
            _mark_provider_failure(provider_name, e)
            print(f"[STREAM] Non-streaming provider {provider_name} failed: {e}")

    yield ""


def _build_stream_system_msg(context: NarrativeContext) -> str:
    """Build the system message for streaming generation."""
    language_lock = os.environ.get("NIMA_LANGUAGE_LOCK", "").strip()
    language_block = ""
    if language_lock:
        language_block = (
            f"LANGUAGE LOCK (NON-NEGOTIABLE, OVERRIDES EVERY OTHER RULE):\n"
            f"- Every Text(), Tex(), MathTex() string in the generated code "
            f"MUST be written in {language_lock}.\n"
            f"- Every title, label, hint, summary, takeaway, and chapter marker "
            f"MUST be in {language_lock}.\n"
            f"- DO NOT output English captions like 'Cold Open', 'The Setup', "
            f"'ray', 'straight angle', 'summary', 'rewind', 'looks settled', "
            f"'locked anyway', etc. Translate them into {language_lock}.\n"
            f"- The ONLY allowed non-{language_lock} tokens on screen are:\n"
            f"    * single-letter math/geometry vertex names (A, B, C, D, E, "
            f"O, P, Q, x, y, z), \n"
            f"    * digits and degree/percent/math symbols (e.g. 60°, 180°, "
            f"+, -, =, ÷, ×).\n"
            f"- If a label name was historically English in the model's "
            f"training data, REWRITE IT in {language_lock} before emitting.\n\n"
        )

    base = language_block + """\
You are an expert Manim CE v0.18 code generator producing single scenes.
You generate ONE scene at a time with full narrative context.

CRITICAL RULES:
1. Return ONLY the complete, runnable Manim Python code. No prose, no markdown.
2. class Scene must be named GeneratedScene with def construct(self)
3. All imports: from manim import *
4. NEVER use: start_section(), begin_section(), end_section() — these don't exist in Manim CE
5. NEVER use: SVGMobject, ImageMobject, or emoji
6. Use MathTex for formulas only if LaTeX commands are necessary; otherwise prefer readable Text with plain ASCII math
7. Include adequate self.wait() for pacing
8. Clean up only distracting construction artifacts; keep the final explanatory visual alive when the mode contract asks for a payoff frame.
9. Return code only — no comments, no explanations
10. NEVER repeat prior scenes or re-introduce already explained concepts unless explicitly asked
11. This is part of a continuous video: avoid hard resets, avoid "intro"/"summary" recaps in middle scenes
12. For scene_index > 0, continue from prior context state and focus only on NEW progression
13. ALL scenes in a job must use the SAME visual theme and SAME background color
14. Default to dark mode unless explicitly told otherwise
15. NEVER use self.camera.frame or camera.frame unless the scene explicitly subclasses MovingCameraScene (it does not here)
16. Do not call average_color() with raw string hex values; use explicit Manim colors only
17. Never prefix labels with literal words like "text", "label", or "title". Use Text("Prime pieces"), not Text("textPrime pieces").
18. Keep each scene concise: use loops, VGroups, and transforms instead of huge duplicated object lists; target 90-180 lines of code.
19. Dynamic labels created with always_redraw must position themselves inside the lambda, e.g. Text(...).next_to(anchor, UP); do not position them once afterward in a VGroup.

"""

    try:
        from algorithms.code_digest import latex_toolchain_available

        latex_available = latex_toolchain_available()
    except Exception:
        latex_available = False
    if not latex_available:
        base += """\
LOCAL RENDERER NOTE:
- LaTeX is not available in this environment. Do not use MathTex or Tex unless absolutely unavoidable.
- Use Text with plain ASCII math instead: =>, <=, >=, x, ^, and simple parentheses.
- Do not use LaTeX-only symbols such as \\Rightarrow, \\checkmark, \\cdots, or \\text{...}.

"""

    if context.domain_state.get("video_mode") == "short" or context.domain_state.get(
        "aspect"
    ) == "9:16":
        base += """\
SHORT VERTICAL QUALITY RULES:
- Design for a 9:16 phone screen: big central objects, high contrast, minimal text.
- Use font_size >= 34 for labels and >= 44 for titles; never use .scale() to shrink text below readability.
- Keep all important objects within x = -3.2..3.2 and y = -6.5..6.5.
- Avoid wide side-by-side layouts; stack vertically or use one central diagram.
- Fill the center of the screen: the main visual group should span at least half the phone width or height.
- Use at most 4 short text labels on screen at once.
- Keep each Text string under 28 visible characters per line; use "\\n" line breaks for anything longer.
- For probability, tables, tests, or comparisons, animate one stacked table/card at a time; do not place two dense tables side by side on a phone screen.
- Keep labels outside cell borders and dividers with visible padding; never draw text across a line or rectangle edge.
- Prefer dark high-contrast background with bright foreground text.

SHORT SOCIAL CREATIVE CONTRACT:
- This is a high-retention 55-60 second social short, not a compressed lecture.
- Never make a static title card, static bullet list, or text-only explainer scene.
- Every scene must have a moving central object within the first 0.5 seconds.
- Every scene must contain at least three distinct visual events: move, pulse, transform, trace, collide, overwrite, reveal, or highlight.
- Text is a HUD layer only: short hook, one live label, or one challenge. The concept must be carried by motion.
- Prefer concrete domain objects: graph nodes and edge weights, molecules and bonds, cars and velocity arrows, arrays and search windows, curves and moving points.
- Use fast beat pacing: many short animations with brief waits, not one slow Write followed by a long wait.
- Override the normal cleanup habit for shorts: do not FadeOut every object before the last wait.
- End by holding the final graph/object/challenge frame on screen; scene stitching can cut from that living frame.

"""

    if context.domain_state.get("video_mode") == "standard":
        base += """\
STANDARD YOUTUBE EXPLAINER RULES:
- This is a 16:9, 2-5 minute YouTube explainer chapter, not a classroom lecture.
- Use a cold-open/setup/tension/mechanism/example/misconception/payoff/takeaway arc across the full video.
- Keep one recurring anchor visual that evolves; do not rebuild unrelated title cards scene after scene.
- No quizzes, question pauses, comment CTAs, or static bullet/title cards.
- Every scene needs concrete objects, visible state changes, and at least one pattern interrupt: compare, zoom, transform, reveal, simulate, or show a mistake.
- Text is for labels, equations, and short chapter markers. Motion and object state must carry the explanation.
- When adding a new dense label, panel, or branch over existing material, dim the older layer and put a translucent focus plate behind the new layer. Do not use literal blur filters; do not let crisp text overlap crisp old text.
- Scale the main visual group into a safe inner frame when labels, arrows, or panels approach the edge.
- End each chapter on a living visual payoff or open loop; do not FadeOut every object before the final wait.

"""

    if context.domain_state.get("video_mode") == "course":
        base += """\
COURSE LESSON RULES:
- This is a 16:9 modular course lesson, not a viral short or a fast YouTube explainer.
- Structure matters: show chapter/module labels, progress rail, learning objectives, worked examples, checkpoints, recap maps, and transfer examples.
- A course is made from short scenelets inside chapters. Keep each scene focused on one 10-30 second teaching move instead of one long board that accumulates objects.
- Question scenes are intentional thinking pauses. Keep each question to one prompt, a faint prior anchor visual, and a subtle timer or progress pulse.
- Content scenes must teach with diagrams, state changes, examples, and reusable visual vocabulary, not paragraph boards.
- Keep text readable and sparse: short labels, definitions, checklist rows, and one-sentence takeaways only.
- Return to the same course map or anchor visual between modules so the learner sees progress.
- Use slower deliberate pacing than standard mode, but every scene still needs visible visual progress.
- Keep important text and objects inside x=-5.7..5.7 and y=-2.9..2.9; scale the main visual group into a safe inner frame before animations.
- Use focus layering instead of accidental overlap: do not use literal blur filters; dim older groups to about 20-30 percent opacity, add a translucent focus plate behind the new label/panel, and raise the active layer with z-index.

"""

    if context.domain_state.get("video_mode") == "lecture":
        base += """\
ACADEMIC LECTURE RULES:
- This is a formal 16:9 academic lecture, not a viral short and not a YouTube retention chapter.
- Build definitions, theorem statements, lemmas, proof steps, worked examples, pitfalls, and recap maps as separate scenelets.
- Keep each scene focused on one derivation or proof move. Do not create a giant board that carries stale text for minutes.
- Use a small section label, proof map, equation ladder, or assumption ledger so the viewer knows where they are in the argument.
- Use focus layering for derivation steps: dim older proof context, put a translucent plate behind the active line, and raise active z-index.
- Use font_size >= 24 for every label, justification, and equation line. Do not use tiny 18-23px labels.
- Keep important notation inside x=-5.4..5.4 and y=-2.65..2.65; scale the main board into width 10.8 and height 5.3.
- Keep at most five active proof lines visible at once; dim older material into a proof map instead of stacking a proof wall.
- Questions are quiet thinking pauses, not quizzes or social CTAs. Do not reveal the answer inside a question scene.

"""

    ctx_str = context.to_context_string()
    return base + "\n" + ctx_str


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE GENERATION
# ═══════════════════════════════════════════════════════════════════════════════


# Retry-prompt helpers were extracted to algorithms.streaming_prompts in
# the issue-#11 split. Re-imported here so existing call sites and tests that
# patch e.g. `streaming._classify_retry_error` continue to work unchanged.
from algorithms.streaming_prompts import (  # noqa: E402,F401  (re-export for back-compat)
    _OVERLAP_PATTERN,
    _build_retry_addendum,
    _classify_retry_error,
    _extract_overlap_pair,
    _surgical_repair_tips,
)


def generate_scene(
    scene_plan: dict,
    narrative_context: NarrativeContext,
    scene_num: int,
    max_retries: int = 2,
) -> Tuple[str, NarrativeContext]:
    """
    Generate single scene code with full narrative context.

    Args:
        scene_plan: Scene data from split_plan_into_scenes
        narrative_context: Current narrative state
        scene_num: Scene number for naming
        max_retries: Max generation retries

    Returns:
        Tuple of (generated_code, updated_context)
    """
    context = narrative_context
    context.scene_index = scene_num
    _mark_scene_generation(scene_plan, "pending")

    scene_desc = scene_plan.get("description", "")
    duration_hint = scene_plan.get("duration_hint", 10)

    # Build generation prompt
    prompt = _build_scene_prompt(scene_plan, context, duration_hint)

    # Anti-repeat guard: don't let scene regenerate near-identical recent content
    recent_ctx = "\n".join(context.scene_history[-3:])
    if recent_ctx:
        prompt += (
            "\n\nANTI-REPEAT CHECK:\n"
            "- Your scene must add NEW conceptual progress compared to recent scenes.\n"
            "- Do not restate the same explanation in different words.\n"
            "- If similar to prior content, skip recap and move to the next logical step.\n"
            f"Recent scene summaries:\n{recent_ctx}\n"
        )

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            # Stream the generation with timeout
            code_chunks = []
            start_time = time.time()

            attempt_prompt = prompt
            if last_error is not None:
                attempt_prompt += _build_retry_addendum(
                    last_error, attempt=attempt, scene_plan=scene_plan
                )

            for token in stream_generate(attempt_prompt, context):
                code_chunks.append(token)

            full_code = "".join(code_chunks)
            elapsed = time.time() - start_time

            if not full_code or len(full_code) < 50:
                raise ValueError(
                    f"Empty or very short response ({len(full_code)} chars)"
                )

            # Extract code from markdown if present
            code = _extract_manim_code(full_code)
            code = _sanitize_generated_code(code)
            if context.domain_state.get("video_mode") == "lecture":
                code = _enforce_minimum_font_size(
                    code,
                    int(context.domain_state.get("minimum_label_font_size") or 24),
                )

            # Validate syntax and known bad patterns early to force retry before render
            from algorithms.code_digest import (
                validate_python_syntax,
                validate_manim_code,
                validate_names_and_imports,
                check_code_quality,
            )

            syntax_ok, syntax_err = validate_python_syntax(code)
            if not syntax_ok:
                raise ValueError(f"Syntax error: {syntax_err}")

            structure_ok, structure_err = validate_manim_code(code)
            if not structure_ok:
                raise ValueError(structure_err)

            imports_ok, import_issues = validate_names_and_imports(code)
            if not imports_ok:
                raise ValueError("; ".join(import_issues[:3]))

            quality_ok, quality_messages = check_code_quality(code)
            blocking_quality = [
                msg for msg in quality_messages if msg.startswith("[ERR]")
            ]
            if blocking_quality:
                raise ValueError("; ".join(blocking_quality[:3]))

            pattern_err = _reject_known_bad_patterns(code)
            if pattern_err:
                raise ValueError(pattern_err)
            layout_hygiene_err = _reject_layout_hygiene_code(
                code, context, scene_plan
            )
            if layout_hygiene_err:
                raise ValueError(layout_hygiene_err)
            long_text_err = _reject_unbounded_long_text_code(
                code, context, scene_plan
            )
            if long_text_err:
                raise ValueError(long_text_err)
            short_static_err = _reject_static_short_code(code, context)
            if short_static_err:
                raise ValueError(short_static_err)
            short_duration_err = _reject_short_duration_code(
                code, context, scene_plan
            )
            if short_duration_err:
                raise ValueError(short_duration_err)
            standard_engagement_err = _reject_standard_engagement_code(
                code, context, scene_plan
            )
            if standard_engagement_err:
                raise ValueError(standard_engagement_err)
            course_instruction_err = _reject_course_instructional_code(
                code, context, scene_plan
            )
            if course_instruction_err:
                raise ValueError(course_instruction_err)
            lecture_academic_err = _reject_lecture_academic_code(
                code, context, scene_plan
            )
            if lecture_academic_err:
                raise ValueError(lecture_academic_err)

            if "self.camera.frame" in code or ".camera.frame" in code:
                raise ValueError(
                    "Invalid camera.frame usage in Scene; regenerate without MovingCameraScene APIs"
                )

            # Validate basic structure
            if "class GeneratedScene" not in code and "class Scene" not in code:
                raise ValueError("No Scene class found in generated code")

            # Reject obvious recap/repeat patterns in non-first scenes
            if scene_num > 0:
                lowered = code.lower()
                repeat_markers = [
                    "let's start",
                    "in this video",
                    "we begin",
                    "introduction",
                    "recap",
                    "summary of what we saw",
                ]
                if any(m in lowered for m in repeat_markers):
                    raise ValueError(
                        "Detected recap/intro pattern in mid-scene; forcing regenerate"
                    )

            print(
                f"[STREAM] Scene {scene_num} generated in {elapsed:.1f}s ({len(code)} chars)"
            )
            _mark_scene_generation(scene_plan, "llm")

            # Update narrative context with this scene's objects
            context = _update_context_from_scene(context, code, scene_desc)

            return code, context

        except Exception as e:
            last_error = e
            print(f"[STREAM] Scene {scene_num} attempt {attempt} failed: {e}")
            error_text = str(e).lower()
            mode = context.domain_state.get("video_mode")
            provider_failure = (
                "generation exceeded" in error_text
                or "empty or very short response" in error_text
            )
            if mode == "standard" and provider_failure:
                code = _make_standard_fallback_scene_code(scene_plan, context)
                _mark_scene_generation(scene_plan, "deterministic_standard_fallback", e)
                context = _update_context_from_scene(context, code, scene_desc)
                print(
                    f"[STREAM] Scene {scene_num} using deterministic standard fallback "
                    f"after provider failure: {e}"
                )
                return code, context
            if mode == "lecture" and provider_failure:
                code = _make_lecture_fallback_scene_code(scene_plan, context)
                _mark_scene_generation(scene_plan, "deterministic_lecture_fallback", e)
                context = _update_context_from_scene(context, code, scene_desc)
                print(
                    f"[STREAM] Scene {scene_num} using deterministic lecture fallback "
                    f"after provider failure: {e}"
                )
                return code, context
            if mode == "course" and provider_failure:
                code = _make_course_fallback_scene_code(scene_plan, context)
                _mark_scene_generation(scene_plan, "deterministic_course_fallback", e)
                context = _update_context_from_scene(context, code, scene_desc)
                print(
                    f"[STREAM] Scene {scene_num} using deterministic course fallback "
                    f"after provider failure: {e}"
                )
                return code, context
            if mode == "short" and provider_failure:
                code = _make_short_fallback_scene_code(scene_plan, context)
                _mark_scene_generation(scene_plan, "deterministic_short_fallback", e)
                context = _update_context_from_scene(context, code, scene_desc)
                print(
                    f"[STREAM] Scene {scene_num} using deterministic short fallback "
                    f"after provider failure: {e}"
                )
                return code, context

            # Add error feedback to context for retry
            if attempt < max_retries:
                context.scene_history.append(f"[RETRY] {scene_desc}: {str(e)[:100]}")

    # Issue #20: in speed_mode (DRAFT/FAST), `max_retries == 1`, so the loop
    # above fires exactly once — the gate-aware surgical retry that PR #7
    # added is therefore *never* given a chance and the deterministic
    # fallback overrides the scene on every classifiable layout error.
    # Guarantee one surgical retry whenever the failure is classifiable
    # (overlap / accumulation / leftover / edge_crowding / text_overlap),
    # regardless of the speed-mode budget. The cost is one extra LLM call
    # per affected scene — tiny compared to permanently discarding the
    # LLM render and shipping a deterministic template.
    if (
        last_error is not None
        and max_retries < 2
        and _classify_retry_error(str(last_error)) != "generic"
    ):
        try:
            print(
                f"[STREAM] Scene {scene_num} attempting surgical retry before "
                f"deterministic fallback (gate={_classify_retry_error(str(last_error))})"
            )
            surgical_prompt = prompt + _build_retry_addendum(
                last_error, attempt=2, scene_plan=scene_plan
            )
            code_chunks = []
            for token in stream_generate(surgical_prompt, context):
                code_chunks.append(token)
            full_code = "".join(code_chunks)
            if not full_code or len(full_code) < 50:
                raise ValueError(
                    f"Empty surgical response ({len(full_code)} chars)"
                )
            code = _extract_manim_code(full_code)
            code = _sanitize_generated_code(code)
            if context.domain_state.get("video_mode") == "lecture":
                code = _enforce_minimum_font_size(
                    code,
                    int(context.domain_state.get("minimum_label_font_size") or 24),
                )

            from algorithms.code_digest import (
                validate_python_syntax,
                validate_manim_code,
                validate_names_and_imports,
                check_code_quality,
            )

            ok, err = validate_python_syntax(code)
            if not ok:
                raise ValueError(f"Syntax error: {err}")
            ok, err = validate_manim_code(code)
            if not ok:
                raise ValueError(err)
            ok, issues = validate_names_and_imports(code)
            if not ok:
                raise ValueError("; ".join(issues[:3]))
            quality_ok, quality_messages = check_code_quality(code)
            blocking = [m for m in quality_messages if m.startswith("[ERR]")]
            if blocking:
                raise ValueError("; ".join(blocking[:3]))
            pattern_err = _reject_known_bad_patterns(code)
            if pattern_err:
                raise ValueError(pattern_err)
            layout_err = _reject_layout_hygiene_code(code, context, scene_plan)
            if layout_err:
                raise ValueError(layout_err)

            print(
                f"[STREAM] Scene {scene_num} surgical retry succeeded "
                f"({len(code)} chars); using LLM render instead of deterministic fallback"
            )
            _mark_scene_generation(scene_plan, "llm_surgical_retry")
            context = _update_context_from_scene(context, code, scene_desc)
            return code, context
        except Exception as surgical_error:
            print(
                f"[STREAM] Scene {scene_num} surgical retry also failed: "
                f"{surgical_error}"
            )
            last_error = surgical_error

    # All retries (including the surgical retry above when it ran) failed —
    # fall back to a deterministic scene where one is available for this
    # mode. Short mode previously had no per-scene fallback, which meant a
    # single failing scene aborted the whole short video; the job-level
    # short-fallback retry that re-renders every scene is far more expensive
    # than just dropping a deterministic last-resort scene here.
    mode = context.domain_state.get("video_mode")
    if mode == "standard":
        code = _make_standard_fallback_scene_code(scene_plan, context)
        _mark_scene_generation(scene_plan, "deterministic_standard_fallback", last_error)
        context = _update_context_from_scene(context, code, scene_desc)
        print(
            f"[STREAM] Scene {scene_num} using deterministic standard fallback "
            f"after generation failure: {last_error}"
        )
        return code, context

    if mode == "lecture":
        code = _make_lecture_fallback_scene_code(scene_plan, context)
        _mark_scene_generation(scene_plan, "deterministic_lecture_fallback", last_error)
        context = _update_context_from_scene(context, code, scene_desc)
        print(
            f"[STREAM] Scene {scene_num} using deterministic lecture fallback "
            f"after generation failure: {last_error}"
        )
        return code, context

    if mode == "course":
        code = _make_course_fallback_scene_code(scene_plan, context)
        _mark_scene_generation(scene_plan, "deterministic_course_fallback", last_error)
        context = _update_context_from_scene(context, code, scene_desc)
        print(
            f"[STREAM] Scene {scene_num} using deterministic course fallback "
            f"after generation failure: {last_error}"
        )
        return code, context

    if mode == "short":
        code = _make_short_fallback_scene_code(scene_plan, context)
        _mark_scene_generation(scene_plan, "deterministic_short_fallback", last_error)
        context = _update_context_from_scene(context, code, scene_desc)
        print(
            f"[STREAM] Scene {scene_num} using deterministic short fallback "
            f"after generation failure: {last_error}"
        )
        return code, context

    raise RuntimeError(
        f"Scene generation failed after {max_retries} attempts: {last_error}"
    )


def _mark_scene_generation(scene_plan: dict, source: str, error: Exception | None = None) -> None:
    """Attach lightweight generation provenance directly to the mutable scene plan."""
    try:
        scene_plan["_generation_source"] = source
        if error is not None:
            detail = re.sub(r"\s+", " ", str(error)).strip()
            scene_plan["_generation_error"] = detail[:260]
    except Exception:
        return


def _coerce_scene_terms(value: Any) -> List[str]:
    """Return compact retrieval terms from scene plan values."""
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, (list, tuple, set)):
        terms: List[str] = []
        for item in value:
            terms.extend(_coerce_scene_terms(item))
        return terms
    if isinstance(value, dict):
        terms = []
        for key in ("topic", "title", "description", "narration", "name"):
            terms.extend(_coerce_scene_terms(value.get(key)))
        return terms
    return []


def _retrieve_streaming_rag_context(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """
    Fetch relevant Manim patterns for a single streaming scene.

    RAG is an optimization layer, not a reliability dependency. If retrieval fails
    for any reason, scene generation should continue with the normal prompt.
    """
    topic = (
        scene_plan.get("topic")
        or scene_plan.get("title")
        or scene_plan.get("description")
        or context.prompt
        or context.domain
    )
    terms: List[str] = []
    for key in ("objects", "animation_steps", "subtopics", "narration"):
        terms.extend(_coerce_scene_terms(scene_plan.get(key)))

    # Keep the query useful without stuffing full scene text into the cache key.
    seen = set()
    subtopics = []
    for term in terms:
        lowered = term.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        subtopics.append(term[:120])
        if len(subtopics) >= 8:
            break

    short_mode = context.domain_state.get("video_mode") == "short" or (
        context.domain_state.get("aspect") == "9:16"
    )
    if short_mode:
        sections = [SHORT_VERTICAL_RAG_REFERENCE]
        try:
            patterns = retrieve_patterns(
                context.domain, str(topic), tuple(subtopics), limit=2
            )
        except Exception as exc:
            print(f"[STREAM] short RAG retrieval skipped: {exc}")
            patterns = []

        for pattern in patterns:
            notes = str(pattern.get("notes") or "").strip()
            tags = ", ".join(str(tag) for tag in pattern.get("tags", [])[:8])
            if notes:
                sections.append(
                    "# [OK] RELEVANT TECHNIQUE REFERENCE\n"
                    f"# Notes: {notes}\n"
                    f"# Tags: {tags}\n"
                    "# Short-mode adaptation: use the technique only; keep a "
                    "stacked 9:16 layout, large text, and safe frame bounds."
                )
        return "\n\n".join(sections)[:STREAM_RAG_CONTEXT_CHARS]

    standard_mode = context.domain_state.get("video_mode") == "standard"
    course_mode = context.domain_state.get("video_mode") == "course"
    lecture_mode = context.domain_state.get("video_mode") == "lecture"
    reference_sections = []
    if standard_mode:
        reference_sections.append(STANDARD_YOUTUBE_RAG_REFERENCE)
    if course_mode:
        reference_sections.append(COURSE_LESSON_RAG_REFERENCE)
    if lecture_mode:
        reference_sections.append(LECTURE_ACADEMIC_RAG_REFERENCE)
    if standard_mode or course_mode or lecture_mode:
        reference_sections.append(FOCUS_LAYER_RAG_REFERENCE)

    try:
        rag_context = retrieve_golden_example(context.domain, str(topic), subtopics)
    except Exception as exc:
        print(f"[STREAM] RAG retrieval skipped: {exc}")
        return "\n\n".join(reference_sections)[:STREAM_RAG_CONTEXT_CHARS]

    rag_context = (rag_context or "").strip()
    if rag_context:
        reference_sections.append(rag_context)
    if not reference_sections:
        return ""
    return "\n\n".join(reference_sections)[:STREAM_RAG_CONTEXT_CHARS]


def _build_scene_prompt(
    scene_plan: dict, context: NarrativeContext, duration_hint: int
) -> str:
    """Build the generation prompt for a single scene."""
    scene_desc = scene_plan.get("description", "")
    scene_title = scene_plan.get("title", "")
    narration = scene_plan.get("narration", "")
    visual_description = scene_plan.get("visual_description", "")
    scene_role = scene_plan.get("scene_role", "")
    animation_steps = scene_plan.get("animation_steps", [])
    objects = scene_plan.get("objects", [])
    required_motions = scene_plan.get("required_motions", []) or []
    short_directives = scene_plan.get("short_directives", []) or []
    standard_directives = scene_plan.get("standard_directives", []) or []
    course_directives = scene_plan.get("course_directives", []) or []
    lecture_directives = scene_plan.get("lecture_directives", []) or []
    course_module = scene_plan.get("module", "")
    lecture_section = scene_plan.get("lecture_section", "")
    learning_objective = scene_plan.get("learning_objective", "")
    checkpoint_id = scene_plan.get("checkpoint_id", "")
    forbidden_visuals = scene_plan.get("forbidden_visuals", []) or []

    total_scenes = int(context.domain_state.get("total_scenes", 0) or 0)
    current_idx = int(context.scene_index)
    scene_position = (
        f"{current_idx + 1}/{total_scenes}" if total_scenes else str(current_idx + 1)
    )

    preamble_hint = generate_scene_preamble(context, scene_plan)
    rag_context = _retrieve_streaming_rag_context(scene_plan, context)

    prompt = f"""Create Manim CE scene for:

SCENE: {scene_desc}
SCENE POSITION: {scene_position}
DURATION HINT: ~{duration_hint} seconds
TITLE: {scene_title or "(none)"}
NARRATION TO MATCH: {narration or "(none)"}
VISUAL DESCRIPTION: {visual_description or "(none)"}
SCENE ROLE: {scene_role or "(unspecified)"}
MODULE: {course_module or "(none)"}
LECTURE SECTION: {lecture_section or "(none)"}
LEARNING OBJECTIVE: {learning_objective or "(none)"}
CHECKPOINT ID: {checkpoint_id or "(none)"}

ANIMATION STEPS:
"""

    for i, step in enumerate(animation_steps, 1):
        prompt += f"  {i}. {step}\n"

    if objects:
        prompt += f"\nOBJECTS TO ANIMATE: {', '.join(objects)}\n"
    if required_motions:
        prompt += "\nREQUIRED MOTIONS:\n"
        for i, motion in enumerate(required_motions, 1):
            prompt += f"  {i}. {motion}\n"

    short_mode = context.domain_state.get("video_mode") == "short" or (
        context.domain_state.get("aspect") == "9:16"
    )
    if short_mode:
        prompt += """
SHORT SOCIAL SCENE CONTRACT (MANDATORY):
- Treat this scene as one beat in a fast 9:16 social short.
- Do not build a title slide, bullet slide, text card, or lecture board.
- Start with a visible moving object before any long text.
- Use at least three distinct visual events before the final wait.
- Reuse or transform the central visual instead of clearing to another text layout.
- Keep all text as short HUD labels. The animation, not text, must explain the idea.
- End on a visual change, reveal, or challenge frame.
- Keep the final frame alive. Do not FadeOut the full graph/diagram/title before the scene ends.
- The code runtime must land near the duration hint; add active visual holds, pulses, route glows, or challenge pulses instead of dead air.
"""
        if short_directives:
            prompt += "\nEXTRA SHORT DIRECTIVES:\n"
            for i, directive in enumerate(short_directives, 1):
                prompt += f"  {i}. {directive}\n"
        if forbidden_visuals:
            prompt += "\nFORBIDDEN VISUALS:\n"
            for i, forbidden in enumerate(forbidden_visuals, 1):
                prompt += f"  {i}. {forbidden}\n"

    standard_mode = context.domain_state.get("video_mode") == "standard"
    if standard_mode:
        prompt += """
STANDARD YOUTUBE EXPLAINER CONTRACT (MANDATORY):
- Treat this as one chapter in a 2-5 minute YouTube explainer, not a lecture.
- No question pauses, no quizzes, no comment CTA, and no text-only chapter cards.
- Start with motion or a concrete visual within the first second.
- Keep a recurring anchor visual that evolves across the scene.
- Use pattern interrupts every 8-12 seconds: compare, zoom, transform, reveal, simulate, or show a common mistake.
- Explain with visual cause and effect. Text may label objects, equations, or chapter beats, but cannot carry the whole scene.
- When adding a new dense label, panel, or branch over existing material, do not use literal blur filters; dim the older layer and put a translucent focus plate behind the new layer.
- After building the main visual group, scale it into a safe inner frame around width 10.6 and height 5.1 so labels do not crowd the edges.
- Only the main title may use to_edge(UP). Put counters, arrows, labels, and beat markers next_to the anchor visual with at least 0.25 buff.
- Use distinct vertical lanes for labels above and below rows/graphs; never stack two labels on the same point or over cells.
- End on a living visual payoff or open loop. Do not FadeOut the full diagram before the scene ends.
- The code runtime must land near the duration hint; add active visual holds, replays, comparison pulses, or state updates instead of dead air.
"""
        if standard_directives:
            prompt += "\nEXTRA STANDARD DIRECTIVES:\n"
            for i, directive in enumerate(standard_directives, 1):
                prompt += f"  {i}. {directive}\n"
        if scene_plan.get("retention_hook"):
            prompt += (
                "\nRETENTION BEAT: This scene must contain a visible tension, "
                "misconception, reveal, or payoff moment.\n"
            )
        if forbidden_visuals:
            prompt += "\nFORBIDDEN VISUALS:\n"
            for i, forbidden in enumerate(forbidden_visuals, 1):
                prompt += f"  {i}. {forbidden}\n"

    course_mode = context.domain_state.get("video_mode") == "course"
    if course_mode:
        if scene_plan.get("type") == "question":
            prompt += """
COURSE CHECKPOINT CONTRACT (MANDATORY):
- Treat this as an intentional learner thinking pause, not a content lecture.
- Show exactly one question prompt with a faint reminder of the prior anchor visual.
- Add a small timer/progress pulse and hold near the duration hint.
- Do not reveal the answer during the pause, do not ask for comments, and do not add multiple quiz questions.
- Keep text readable: one prompt plus at most two short option/path labels.
"""
        else:
            prompt += """
COURSE CONTENT SCENE CONTRACT (MANDATORY):
- Treat this as one 10-30 second scenelet inside a chapter of a longer course lesson.
- Keep a module label or progress rail visible without making it the main content.
- Teach through a diagram, worked example, state table, graph, array, or concrete object that changes on screen.
- Avoid paragraph boards. Use short labels attached to objects and reveal definitions only when used.
- Use deliberate pacing: at least two visual teaching moves before any recap or takeaway.
- When introducing a new panel or label over existing material, do not use literal blur filters; first dim or fade the old group, then add a BackgroundRectangle/focus plate behind the new group and set the active group above it with z-index.
- End with a state that can carry into a checkpoint, recap map, or next module.
- Keep all important text and objects inside x=-5.7..5.7 and y=-2.9..2.9; scale the main visual group into a safe inner frame before playing animations.
- The code runtime must land near the duration hint and must not exceed 30 seconds; use example steps, state updates, checklist routing, or timer pulses instead of dead air.
"""
        if course_directives:
            prompt += "\nEXTRA COURSE DIRECTIVES:\n"
            for i, directive in enumerate(course_directives, 1):
                prompt += f"  {i}. {directive}\n"
        if learning_objective:
            prompt += (
                "\nLEARNING OBJECTIVE: The visual must make this objective "
                f"observable: {learning_objective}\n"
            )
        if forbidden_visuals:
            prompt += "\nFORBIDDEN VISUALS:\n"
            for i, forbidden in enumerate(forbidden_visuals, 1):
                prompt += f"  {i}. {forbidden}\n"

    lecture_mode = context.domain_state.get("video_mode") == "lecture"
    if lecture_mode:
        if scene_plan.get("type") == "question":
            prompt += """
LECTURE THINKING PAUSE CONTRACT (MANDATORY):
- Treat this as a quiet academic pause, not a quiz card or social prompt.
- Show exactly one proof/derivation question over a faint prior proof map.
- Add a subtle timer/progress pulse and hold near the duration hint.
- Do not reveal the answer during the pause and do not add multiple questions.
- Keep text sparse: one prompt plus at most one short reminder label.
"""
        else:
            prompt += """
LECTURE CONTENT SCENE CONTRACT (MANDATORY):
- Treat this as one academic scenelet inside a longer lecture.
- Build one formal move: definition expansion, lemma proof step, theorem implication, worked example step, pitfall repair, or recap map.
- Keep a section label, proof map, equation ladder, or assumption ledger visible without letting it dominate the frame.
- Use focus layering for new derivation lines: do not use literal blur filters; dim old proof context, add a BackgroundRectangle/focus plate behind the active line, and set active z-index above old context.
- Avoid paragraph proof walls. Use short lines attached to justifications, arrows, diagrams, or equation steps.
- Use font_size >= 24 for every label, justification, and equation line. Do not create tiny 18-23px proof labels.
- Keep all important notation inside x=-5.4..5.4 and y=-2.65..2.65; scale the main board into width 10.8 and height 5.3 before animations.
- Keep at most five active proof lines visible at once. Older context should become a dim proof map, not another crisp text stack.
- The code runtime must land near the duration hint and must not exceed 50 seconds; use derivation steps, proof-map pulses, and active holds instead of dead air.
"""
        if lecture_directives:
            prompt += "\nEXTRA LECTURE DIRECTIVES:\n"
            for i, directive in enumerate(lecture_directives, 1):
                prompt += f"  {i}. {directive}\n"
        if learning_objective:
            prompt += (
                "\nLEARNING OBJECTIVE: The academic board must make this objective "
                f"observable: {learning_objective}\n"
            )
        if forbidden_visuals:
            prompt += "\nFORBIDDEN VISUALS:\n"
            for i, forbidden in enumerate(forbidden_visuals, 1):
                prompt += f"  {i}. {forbidden}\n"

    prompt += f"""
DOMAIN: {context.domain}
TARGET TOTAL DURATION: {context.duration_target}s

CONTINUITY REQUIREMENTS (CRITICAL):
- This is scene {scene_position} of one continuous video.
- Do NOT repeat explanation from previous scenes.
- Do NOT restart from introductory framing unless this is scene 1.
- Preserve narrative progression from prior scenes in context.
- Avoid full-screen resets and unnecessary redraw of same objects.
- Use the theme colors from context exactly; do not choose a different background.
- Do not emit labels that start with literal prefixes such as "text", "label", or "title".

POSSIBLE CARRY-OVER HINTS:
{preamble_hint or "(none)"}

{context.to_context_string()}
"""

    if rag_context:
        prompt += f"""
RELEVANT PROVEN MANIM PATTERNS:
- Use these as technique references, not as copy-paste scene boilerplate.
- Preserve this scene's storyboard, duration, theme, and continuity rules.

{rag_context}
"""

    prompt += """
Generate the complete Python code for this single scene only.
"""

    return prompt


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
    warnings = detect_static_layout_risks(check_code)
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


def _update_context_from_scene(
    context: NarrativeContext,
    code: str,
    scene_desc: str,
) -> NarrativeContext:
    """Update narrative context based on generated scene code."""
    import re

    # Extract MathTex/Text objects mentioned in code
    math_objects = re.findall(r"MathTex\((.*?)\)", code)
    text_objects = re.findall(r"Text\((.*?)\)", code)
    shapes = re.findall(r"(Circle|Line|Arrow|Square|Triangle|Polygon)\(", code)

    # Register created objects
    for tex in math_objects[:5]:
        clean = tex.strip()[:30]
        context.add_object(f"tex_{clean[:10]}", "MathTex", clean)

    for txt in text_objects[:3]:
        clean = txt.strip()[:20]
        context.add_object(f"text_{clean[:10]}", "Text", clean)

    for shape in shapes[:5]:
        context.add_object(f"shape_{shape.lower()}", shape, f"{shape} shape")

    context.add_scene_history(scene_desc)

    return context


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE-LEVEL RETRY
# ═══════════════════════════════════════════════════════════════════════════════


def retry_scene(
    scene_plan: dict,
    context: NarrativeContext,
    scene_num: int,
    error: str,
) -> Tuple[str, NarrativeContext]:
    """
    Retry single scene generation with error feedback.

    Unlike full pipeline restart, this only retries the failed scene,
    preserving all previously generated and rendered scenes.

    Args:
        scene_plan: Original scene plan
        context: Current narrative context
        scene_num: Scene index
        error: Error message from failed render

    Returns:
        Tuple of (fixed_code, updated_context)
    """
    print(f"[STREAM] Retrying scene {scene_num} after error: {error[:200]}")

    # Add error context for targeted fix
    context.scene_history.append(
        f"[ERROR] {scene_plan.get('description', '')}: {error[:150]}"
    )

    # Build retry prompt with error context
    scene_desc = scene_plan.get("description", "")
    duration_hint = scene_plan.get("duration_hint", 10)

    mode_contract_prompt = _build_scene_prompt(scene_plan, context, duration_hint)
    mode = str(context.domain_state.get("video_mode") or "").lower()
    # Render-failure retries reuse the same surgical-addendum dispatcher used
    # by generate_scene's in-loop retry; if no specific gate matches we keep
    # the old layout-recovery requirements as the generic fallback so
    # render-time failures (manim runtime errors etc.) still get layout
    # advice when the error mentions overlap/edges.
    layout_recovery = ""
    if _classify_retry_error(error) == "generic" and any(
        marker in error.lower()
        for marker in ("overlap", "crowd frame edges", "ocr", "layout")
    ):
        layout_recovery = """
LAYOUT RECOVERY REQUIREMENTS:
- Rebuild the layout from scratch; do not patch the previous object positions.
- Keep one main anchor VGroup at ORIGIN and scale it to max width 10.4 and max height 5.0.
- Only the main title may sit near the top edge; all other labels must be next_to visible objects with buff >= 0.25.
- Use separate vertical lanes for arrows, captions, and counters so text never lands over cells, lines, or markers.
- Prefer fewer, larger labels over many small labels; no paragraph blocks.
"""
        if mode == "standard":
            layout_recovery += (
                "- For standard mode, keep the YouTube pacing but use a clean "
                "three-lane composition: title lane, animation lane, payoff lane.\n"
            )

    surgical = _surgical_repair_tips(error)

    retry_prompt = f"""{mode_contract_prompt}

The previous generated code failed validation or rendering. Regenerate the full scene under the same storyboard and mode contract.

SCENE: {scene_desc}
DURATION HINT: ~{duration_hint} seconds

RENDER ERROR:
{error}
{layout_recovery}{surgical}
Return ONLY the corrected Python code.
"""

    code_chunks = []
    for token in stream_generate(retry_prompt, context):
        code_chunks.append(token)

    full_code = "".join(code_chunks)
    code = _extract_manim_code(full_code)
    code = _sanitize_generated_code(code)
    if context.domain_state.get("video_mode") == "lecture":
        code = _enforce_minimum_font_size(
            code,
            int(context.domain_state.get("minimum_label_font_size") or 24),
        )

    if "self.camera.frame" in code or ".camera.frame" in code:
        raise ValueError("Retry still used invalid camera.frame API")

    from algorithms.code_digest import (
        check_code_quality,
        validate_manim_code,
        validate_names_and_imports,
        validate_python_syntax,
    )

    syntax_ok, syntax_err = validate_python_syntax(code)
    if not syntax_ok:
        raise ValueError(f"Retry produced syntax error: {syntax_err}")
    structure_ok, structure_err = validate_manim_code(code)
    if not structure_ok:
        raise ValueError(f"Retry produced invalid Manim code: {structure_err}")
    imports_ok, import_issues = validate_names_and_imports(code)
    if not imports_ok:
        raise ValueError(
            "Retry produced invalid imports/names: " + "; ".join(import_issues[:3])
        )
    quality_ok, quality_messages = check_code_quality(code)
    blocking_quality = [msg for msg in quality_messages if msg.startswith("[ERR]")]
    if blocking_quality:
        raise ValueError(
            "Retry produced blocked quality issue: " + "; ".join(blocking_quality[:3])
        )
    pattern_err = _reject_known_bad_patterns(code)
    if pattern_err:
        raise ValueError(f"Retry produced known bad pattern: {pattern_err}")
    layout_hygiene_err = _reject_layout_hygiene_code(code, context, scene_plan)
    if layout_hygiene_err:
        raise ValueError(f"Retry produced layout hygiene issue: {layout_hygiene_err}")
    long_text_err = _reject_unbounded_long_text_code(code, context, scene_plan)
    if long_text_err:
        raise ValueError(f"Retry produced unbounded long text: {long_text_err}")
    short_static_err = _reject_static_short_code(code, context)
    if short_static_err:
        raise ValueError(f"Retry produced static short issue: {short_static_err}")
    short_duration_err = _reject_short_duration_code(code, context, scene_plan)
    if short_duration_err:
        raise ValueError(f"Retry produced short duration issue: {short_duration_err}")
    standard_engagement_err = _reject_standard_engagement_code(
        code, context, scene_plan
    )
    if standard_engagement_err:
        raise ValueError(
            f"Retry produced standard engagement issue: {standard_engagement_err}"
        )
    course_instruction_err = _reject_course_instructional_code(
        code, context, scene_plan
    )
    if course_instruction_err:
        raise ValueError(
            f"Retry produced course instructional issue: {course_instruction_err}"
        )
    lecture_academic_err = _reject_lecture_academic_code(code, context, scene_plan)
    if lecture_academic_err:
        raise ValueError(
            f"Retry produced lecture academic issue: {lecture_academic_err}"
        )

    # Update context
    context = _update_context_from_scene(context, code, f"[RETRY] {scene_desc}")

    return code, context


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE PREAMBLE GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════


def generate_scene_preamble(context: NarrativeContext, scene_plan: dict) -> str:
    """
    Generate scene opening: recreates needed objects for continuity.

    For scenes that need objects from previous scenes, this generates
    the setup code to recreate those objects at the scene's start.
    """
    bg = context.domain_state.get("background_color", "#0F1117")
    preamble = f'# Scene preamble: keep visual theme consistent\nself.camera.background_color = "{bg}"\n'

    # Domain-specific setup
    if context.domain == "math":
        if not context.object_state:
            # First scene: set up axes
            preamble += (
                """
# Scene preamble: set up coordinate system
self.camera.background_color = "%s"
"""
                % bg
            )

    elif context.domain == "physics":
        preamble += """
# Scene preamble: physics domain setup
"""

    # Object recreation for continuity
    if context.object_state and len(context.scene_history) > 0:
        # This is NOT the first scene — recreate key objects
        recreations = []
        for name, info in list(context.object_state.items())[:5]:
            recreations.append(f"# Recreate {name}: {info['description']}")

        if recreations:
            preamble += "\n" + "\n".join(recreations) + "\n"

    return preamble


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE RENDERING (parallel)
# ═══════════════════════════════════════════════════════════════════════════════


def _render_single_scene(
    code: str,
    filename: str,
    job_id: str,
    scene_num: int,
    render_resolution: Optional[Tuple[int, int]] = None,
    quality_flag: str = "-ql",
    fps: int = 30,
    timeout_seconds: Optional[int] = None,
) -> Tuple[str, bool, str]:
    """
    Render a single scene's Manim code.

    Returns:
        Tuple of (video_path_or_error, success, error_message)
    """
    from algorithms.code_digest import (
        downgrade_tex_to_text_if_needed,
        validate_python_syntax,
        validate_manim_code,
        validate_names_and_imports,
        check_code_quality,
    )

    script_path = MANIM_SCRIPTS / f"{filename}_scene{scene_num}.py"
    code = _sanitize_generated_code(downgrade_tex_to_text_if_needed(code))
    code = inject_manim_frame_config(code, render_resolution)

    # Validate before writing
    syntax_ok, syntax_err = validate_python_syntax(code)
    if not syntax_ok:
        return "", False, f"Syntax error: {syntax_err}"

    structure_ok, structure_err = validate_manim_code(code)
    if not structure_ok:
        return "", False, structure_err

    imports_ok, import_issues = validate_names_and_imports(code)
    if not imports_ok:
        return "", False, "; ".join(import_issues[:3])

    quality_ok, quality_messages = check_code_quality(code)
    blocking_quality = [msg for msg in quality_messages if msg.startswith("[ERR]")]
    if blocking_quality:
        return "", False, "; ".join(blocking_quality[:3])

    pattern_err = _reject_known_bad_patterns(code)
    if pattern_err:
        return "", False, pattern_err

    # Write script
    with open(script_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(code)

    # Clean old files for THIS exact scene only.
    # IMPORTANT: avoid prefix collisions like scene1 matching scene10/scene11.
    scene_prefix = f"{filename}_scene{scene_num}"
    for old_file in OUTPUTS.rglob(f"{scene_prefix}*.mp4"):
        name = old_file.name
        if not name.startswith(scene_prefix):
            continue
        suffix = name[len(scene_prefix) :]
        # Allow only exact scene or scene-specific suffixes that begin with non-digit
        # (e.g. _tts.mp4). Reject names where next char is a digit (scene10 collision).
        if suffix and suffix[0].isdigit():
            continue
        try:
            old_file.unlink()
        except OSError:
            pass

    # Build render command
    cmd = [
        *_manim_command(),
        str(script_path),
        "GeneratedScene",
        quality_flag,
        "--format=mp4",
        "--media_dir",
        str(OUTPUTS),
        "--output_file",
        f"{filename}_scene{scene_num}.mp4",
        "--disable_caching",
        "--fps",
        str(fps),
    ]

    if render_resolution and len(render_resolution) == 2:
        w, h = render_resolution
        cmd.extend(["--resolution", f"{w},{h}"])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds or (RENDER_TIMEOUT_SECONDS // 3),
        )

        if result.returncode == 0:
            # Find video file
            video_path = _find_scene_video(filename, scene_num)
            if video_path and video_path.exists():
                cleanup_manim_partials(video_path)
                return str(video_path), True, ""
            return "", False, "Render succeeded but video file not found"

        return "", False, result.stderr[-500:]

    except subprocess.TimeoutExpired:
        return "", False, "Render timeout"
    except Exception as e:
        return "", False, str(e)


def _find_scene_video(filename: str, scene_num: int) -> Optional[Path]:
    """Find the rendered video file for a scene."""
    scene_prefix = f"{filename}_scene{scene_num}"
    patterns = [OUTPUTS / f"{scene_prefix}.mp4"]

    for p in patterns:
        if p.exists():
            return p

    # Glob fallback with exact scene prefix guard
    candidates = []
    for mp4 in OUTPUTS.rglob(f"{scene_prefix}*.mp4"):
        name = mp4.name
        if not name.startswith(scene_prefix):
            continue
        suffix = name[len(scene_prefix) :]
        # Reject scene3 -> scene30/scene31 collisions
        if suffix and suffix[0].isdigit():
            continue
        candidates.append(mp4)

    if candidates:
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        # Prefer TTS merged outputs when available
        for c in candidates:
            if c.name.endswith("_tts.mp4"):
                return c
        return candidates[0]

    return None


def _safe_text_literal(value: str, max_chars: int = 44) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars].rsplit(" ", 1)[0].strip()
    return cut or cleaned[:max_chars].strip()


def _factorization_line(number: int) -> str:
    n = max(2, int(number))
    factors: list[int] = []
    divisor = 2
    while divisor * divisor <= n:
        while n % divisor == 0:
            factors.append(divisor)
            n //= divisor
        divisor += 1
    if n > 1:
        factors.append(n)
    return " x ".join(str(factor) for factor in factors)


def _is_final_short_scene(scene_plan: dict, context: NarrativeContext) -> bool:
    if scene_plan.get("type") == "question":
        return True
    if context.domain_state.get("video_mode") != "short":
        return False
    try:
        total = int(context.domain_state.get("total_scenes") or 0)
    except (TypeError, ValueError):
        total = 0
    return bool(total and int(context.scene_index or 0) >= total - 1)


def _short_fallback_lines(scene_plan: dict, context: NarrativeContext) -> list[str]:
    prompt = (context.prompt or "").lower()
    scene_desc = scene_plan.get("description") or scene_plan.get("narration") or ""
    scene_num = max(0, int(context.scene_index or 0))
    final_short_scene = _is_final_short_scene(scene_plan, context)

    if "bayes" in prompt or "false positive" in prompt:
        if final_short_scene:
            return ["Your turn", "false alarms double", "does 8% go up?"]
        variants = [
            ["1,000 tested", "10 sick", "990 healthy"],
            ["Positive tests mix", "9 true positives", "99 false alarms"],
            ["Result", "9 / 108", "about 8%"],
            ["Bayes asks", "sick among positives", "part / whole"],
        ]
        return variants[min(scene_num, len(variants) - 1)]

    if "dijkstra" in prompt:
        if final_short_scene:
            return ["Your turn", "which node is next?", "smallest distance wins"]
        variants = [
            ["Start at A", "distance A = 0", "others = infinity"],
            ["Pick smallest", "relax neighbors", "keep shorter paths"],
            ["A to C costs 2", "C to D costs 3", "total path = 5"],
            ["Final path", "settled nodes stay", "best distance wins"],
        ]
        return variants[min(scene_num, len(variants) - 1)]

    numbers = [int(match) for match in re.findall(r"\b\d{2,4}\b", context.prompt or "")]
    if ("factor" in prompt or "prime" in prompt) and numbers:
        if final_short_scene:
            target = numbers[-1]
            return ["Your turn", f"factor {target}", "which primes appear?"]
        first = numbers[0]
        second = numbers[1] if len(numbers) > 1 else numbers[0]
        variants = [
            [
                f"{first} = {_factorization_line(first)}",
                f"{second} = {_factorization_line(second)}",
                "prime pieces only",
            ],
            [
                "order can change",
                "prime pieces stay",
                "counts stay fixed",
            ],
            [
                f"{first}: {_factorization_line(first).replace(' x ', ', ')}",
                f"{second}: {_factorization_line(second).replace(' x ', ', ')}",
                "unique prime list",
            ],
            [
                "one prime recipe",
                "same counts",
                "order does not matter",
            ],
        ]
        return variants[min(scene_num, len(variants) - 1)]

    sentences = re.split(r"(?<=[.!?])\s+", scene_desc)
    lines = [_safe_text_literal(sentence, 34) for sentence in sentences if sentence.strip()]
    return (lines or [_safe_text_literal(context.prompt or "Key idea", 34)])[:3]


def _short_fallback_title(scene_plan: dict, context: NarrativeContext) -> str:
    if _is_final_short_scene(scene_plan, context):
        return "Your turn"

    prompt = (context.prompt or "").lower()
    if "bayes" in prompt or "false positive" in prompt:
        return "Bayes theorem"
    if "dijkstra" in prompt:
        return "Dijkstra path"
    if "factor" in prompt or "prime" in prompt:
        return "Prime factors"

    title = scene_plan.get("title") or context.prompt or scene_plan.get("description") or "Key idea"
    return _safe_text_literal(title, 22)


def _standard_fallback_title(scene_plan: dict) -> str:
    title = str(
        scene_plan.get("title")
        or scene_plan.get("description")
        or scene_plan.get("narration")
        or "Binary search cuts the problem"
    )
    title = _clean_plan_text(title) or "Binary search cuts the problem"
    if len(title) > 48:
        title = title[:45].rstrip(" ,.;:-") + "..."
    return title


def _make_standard_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Deterministic 16:9 fallback for standard-mode continuity.

    This is a provider safety net, not the preferred creative path. It rotates
    through distinct storyboards so a provider outage does not collapse a full
    standard video into repeated text changes.
    """
    scene_index = int(context.scene_index or 0)
    plan_text = " ".join(
        str(scene_plan.get(key) or "")
        for key in ("title", "description", "narration", "visual_description")
    ).lower()
    if "linear" in plan_text and any(token in plan_text for token in ("scan", "obvious", "one by one")):
        code = _make_standard_fallback_linear_scan_scene_code(scene_plan, context)
    elif any(token in plan_text for token in ("sorted", "order", "needs order")):
        code = _make_standard_fallback_sorted_order_scene_code(scene_plan, context)
    elif any(token in plan_text for token in ("payoff", "gap", "grow", "larger", "comparison count")):
        code = _make_standard_fallback_payoff_scene_code(scene_plan, context)
    elif any(token in plan_text for token in ("takeaway", "best use", "mental model", "end")):
        code = _make_standard_fallback_takeaway_scene_code(scene_plan, context)
    elif any(token in plan_text for token in ("race", "side by side", "together")):
        code = _make_standard_fallback_race_scene_code(scene_plan, context)
    elif any(token in plan_text for token in ("middle", "midpoint", "mechanism", "half")):
        code = _make_standard_fallback_window_scene_code(scene_plan, context)
    else:
        variant = scene_index % 3
        if variant == 1:
            code = _make_standard_fallback_race_scene_code(scene_plan, context)
        elif variant == 2:
            code = _make_standard_fallback_ladder_scene_code(scene_plan, context)
        else:
            code = _make_standard_fallback_window_scene_code(scene_plan, context)
    return localize_scene_code(code)


def _make_standard_fallback_window_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated shrinking-window fallback for standard-mode continuity."""
    title = _standard_fallback_title(scene_plan)
    scene_index = int(context.scene_index or 0)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")
    target_index = min(14, max(2, 11 + (scene_index % 3)))
    target_value = target_index + 1
    first_mid = 7
    second_left = 8 if target_index > first_mid else 0
    second_right = 15 if target_index > first_mid else 6
    second_mid = (second_left + second_right) // 2
    relation = "<" if first_mid < target_index else ">"
    direction = "keep right half" if target_index > first_mid else "keep left half"

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")
        danger = ManimColor("#EF4444")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        values = list(range(1, 17))
        cells = VGroup()
        for value in values:
            box = RoundedRectangle(
                width=0.58,
                height=0.62,
                corner_radius=0.08,
                stroke_color=muted,
                stroke_width=1.4,
                fill_color=ManimColor("#1F2937"),
                fill_opacity=0.92,
            )
            label = Text(str(value), font_size=24, color=fg, weight=BOLD).move_to(box)
            cells.add(VGroup(box, label))
        cells.arrange(RIGHT, buff=0.08).move_to(DOWN * 0.15)

        target = SurroundingRectangle(cells[{target_index}], color=good, buff=0.06, stroke_width=3)
        target_label = Text("target = {target_value}", font_size=24, color=good, weight=BOLD).next_to(target, DOWN, buff=0.25)

        window = SurroundingRectangle(VGroup(*[cells[i] for i in range(16)]), color=accent, buff=0.11, stroke_width=3)
        mid_marker = Triangle(fill_color=secondary, fill_opacity=1, stroke_color=secondary).scale(0.13).rotate(PI)
        mid_marker.next_to(cells[{first_mid}], UP, buff=0.18)
        mid_label = Text("mid = {first_mid + 1}", font_size=23, color=secondary, weight=BOLD).next_to(mid_marker, UP, buff=0.08)

        compare_plate = RoundedRectangle(width=4.8, height=0.75, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.8)
        compare_plate.next_to(cells, UP, buff=1.05)
        compare_text = Text("{first_mid + 1} {relation} {target_value}  ->  {direction}", font_size=27, color=fg, weight=BOLD)
        compare_text.move_to(compare_plate)
        compare_text.set_z_index(2)

        counter = Text("comparisons: 1    remaining: 16", font_size=24, color=muted)
        counter.next_to(cells, DOWN, buff=0.82)

        self.play(FadeIn(title, shift=DOWN * 0.15), LaggedStart(*[FadeIn(c, shift=UP * 0.05) for c in cells], lag_ratio=0.025), run_time=1.5)
        self.play(Create(window), FadeIn(target), FadeIn(target_label), run_time=0.8)
        self.play(FadeIn(mid_marker, shift=DOWN * 0.08), FadeIn(mid_label), FadeIn(compare_plate), FadeIn(compare_text), FadeIn(counter), run_time=0.9)
        self.play(Flash(cells[{first_mid}].get_center(), color=secondary, flash_radius=0.45, line_length=0.16), Indicate(cells[{first_mid}], color=secondary), run_time=0.9)

        discard = VGroup(*[cells[i] for i in range({second_left})]) if {target_index} > {first_mid} else VGroup(*[cells[i] for i in range({second_right + 1}, 16)])
        keep = VGroup(*[cells[i] for i in range({second_left}, {second_right + 1})])
        next_window = SurroundingRectangle(keep, color=accent, buff=0.11, stroke_width=3)
        next_marker = Triangle(fill_color=secondary, fill_opacity=1, stroke_color=secondary).scale(0.13).rotate(PI)
        next_marker.next_to(cells[{second_mid}], UP, buff=0.18)
        next_mid_label = Text("mid = {second_mid + 1}", font_size=23, color=secondary, weight=BOLD).next_to(next_marker, UP, buff=0.08)
        next_counter = Text("comparisons: 2    remaining: {second_right - second_left + 1}", font_size=24, color=muted).next_to(cells, DOWN, buff=0.82)

        self.play(discard.animate.set_opacity(0.25), Transform(window, next_window), Transform(mid_marker, next_marker), Transform(mid_label, next_mid_label), Transform(counter, next_counter), run_time=1.3)
        self.play(Indicate(keep, color=accent), run_time=0.8)

        payoff_plate = RoundedRectangle(width=5.6, height=1.0, corner_radius=0.14, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        payoff_plate.to_edge(DOWN, buff=0.42)
        payoff_plate.set_z_index(0)
        payoff = Text("One comparison deletes half the map", font_size=28, color=fg, weight=BOLD).move_to(payoff_plate)
        payoff.set_z_index(2)
        self.play(FadeOut(compare_plate), FadeIn(payoff_plate), Transform(compare_text, payoff), run_time=0.9)
        self.play(Flash(target, color=good, flash_radius=0.55, line_length=0.16), target.animate.set_stroke(width=5), run_time=0.9)
        self.wait(7.5)
'''


def _make_standard_fallback_linear_scan_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated linear-scan fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        row = VGroup()
        for value in range(1, 17):
            box = RoundedRectangle(width=0.55, height=0.58, corner_radius=0.07, stroke_color=muted, stroke_width=1.3, fill_color=ManimColor("#1F2937"), fill_opacity=0.92)
            label = Text(str(value), font_size=22, color=fg, weight=BOLD).move_to(box)
            row.add(VGroup(box, label))
        row.arrange(RIGHT, buff=0.065).move_to(UP * 0.15)

        marker = Triangle(fill_color=secondary, fill_opacity=1, stroke_color=secondary).scale(0.13).rotate(PI)
        marker.next_to(row[0], UP, buff=0.18)
        target = SurroundingRectangle(row[11], color=good, buff=0.06, stroke_width=3)
        counter = Text("comparisons: 1", font_size=27, color=accent, weight=BOLD).next_to(row, DOWN, buff=0.45)
        rule = Text("linear search earns certainty one cell at a time", font_size=28, color=fg, weight=BOLD)
        if rule.width > 9.8:
            rule.scale_to_fit_width(9.8)
        rule.next_to(title, DOWN, buff=0.35)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(rule), FadeIn(row), run_time=1.0)
        self.play(FadeIn(marker), FadeIn(counter), FadeIn(target), run_time=0.7)
        scanned_a = VGroup(*[row[i] for i in range(0, 4)])
        counter_a = Text("comparisons: 4", font_size=27, color=accent, weight=BOLD).move_to(counter)
        self.play(marker.animate.next_to(row[3], UP, buff=0.18), scanned_a.animate.set_opacity(0.35), Transform(counter, counter_a), run_time=1.0)
        scanned_b = VGroup(*[row[i] for i in range(4, 8)])
        counter_b = Text("comparisons: 8", font_size=27, color=accent, weight=BOLD).move_to(counter)
        self.play(marker.animate.next_to(row[7], UP, buff=0.18), scanned_b.animate.set_opacity(0.35), Transform(counter, counter_b), run_time=1.0)
        scanned_c = VGroup(*[row[i] for i in range(8, 12)])
        counter_c = Text("comparisons: 12", font_size=27, color=good, weight=BOLD).move_to(counter)
        self.play(marker.animate.next_to(row[11], UP, buff=0.18), scanned_c.animate.set_opacity(0.55), Transform(counter, counter_c), target.animate.set_stroke(width=5), run_time=1.0)

        plate = RoundedRectangle(width=6.9, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        plate.to_edge(DOWN, buff=0.42)
        payoff = Text("easy to trust, expensive to repeat", font_size=28, color=fg, weight=BOLD).move_to(plate)
        self.play(FadeIn(plate), FadeIn(payoff), Flash(target, color=good, flash_radius=0.55, line_length=0.16), run_time=1.0)
        self.wait(9.0)
'''


def _make_standard_fallback_sorted_order_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated sorted-order requirement fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")
        danger = ManimColor("#EF4444")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        def make_row(values, fill):
            row = VGroup()
            for value in values:
                box = RoundedRectangle(width=0.52, height=0.54, corner_radius=0.07, stroke_color=muted, stroke_width=1.2, fill_color=ManimColor(fill), fill_opacity=0.92)
                label = Text(str(value), font_size=20, color=fg, weight=BOLD).move_to(box)
                row.add(VGroup(box, label))
            row.arrange(RIGHT, buff=0.055)
            return row

        unsorted = make_row([8, 1, 13, 4, 10, 2, 16, 7, 3, 12, 5, 15, 6, 11, 9, 14], "#1F2937").scale(0.92).shift(UP * 0.72)
        sorted_row = make_row(list(range(1, 17)), "#111827").scale(0.92).shift(DOWN * 0.88)
        top_label = Text("unsorted: no safe half", font_size=23, color=danger, weight=BOLD).next_to(unsorted, UP, buff=0.16)
        bottom_label = Text("sorted: halves mean something", font_size=23, color=secondary, weight=BOLD).next_to(sorted_row, UP, buff=0.16)

        slash = Cross(unsorted, stroke_color=danger, stroke_width=5)
        window = SurroundingRectangle(VGroup(*[sorted_row[i] for i in range(8, 16)]), color=accent, buff=0.10, stroke_width=3)
        mid = SurroundingRectangle(sorted_row[7], color=secondary, buff=0.06, stroke_width=3)
        target = SurroundingRectangle(sorted_row[11], color=good, buff=0.06, stroke_width=3)

        rule = Text("binary search buys speed with order", font_size=29, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.35)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(rule), run_time=0.8)
        self.play(FadeIn(top_label), FadeIn(unsorted), run_time=0.8)
        self.play(Wiggle(unsorted), Create(slash), run_time=0.9)
        self.play(FadeIn(bottom_label), FadeIn(sorted_row), run_time=0.8)
        self.play(Create(mid), Flash(sorted_row[7].get_center(), color=secondary, flash_radius=0.42, line_length=0.15), run_time=0.8)
        self.play(Create(window), FadeOut(slash), unsorted.animate.set_opacity(0.22), run_time=1.0)
        self.play(Create(target), Indicate(VGroup(*[sorted_row[i] for i in range(8, 16)]), color=accent), run_time=0.9)

        plate = RoundedRectangle(width=6.6, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        plate.to_edge(DOWN, buff=0.42)
        payoff = Text("without order, the jump is a guess", font_size=28, color=fg, weight=BOLD).move_to(plate)
        self.play(FadeIn(plate), FadeIn(payoff), run_time=0.8)
        self.wait(9.2)
'''


def _make_standard_fallback_payoff_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated comparison-count payoff fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        danger = ManimColor("#EF4444")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)
        note = Text("the gap gets bigger as the list grows", font_size=28, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.30)

        labels = ["16", "64", "1024"]
        linear = [16, 64, 1024]
        binary = [4, 6, 10]
        groups = VGroup()
        for idx, label in enumerate(labels):
            base = LEFT * 3.1 + RIGHT * (idx * 3.1) + DOWN * 1.2
            x_label = Text("n=" + label, font_size=23, color=muted).move_to(base + DOWN * 0.45)
            lin_bar = Rectangle(width=0.42, height=2.45, stroke_width=0, fill_color=danger, fill_opacity=0.85).move_to(base + LEFT * 0.25 + UP * 0.05)
            bin_bar = Rectangle(width=0.42, height=0.45 + idx * 0.20, stroke_width=0, fill_color=secondary, fill_opacity=0.92).align_to(lin_bar, DOWN).shift(RIGHT * 0.55)
            lin_count = Text(str(linear[idx]), font_size=22, color=danger, weight=BOLD).next_to(lin_bar, UP, buff=0.08)
            bin_count = Text(str(binary[idx]), font_size=22, color=secondary, weight=BOLD).next_to(bin_bar, UP, buff=0.08)
            groups.add(VGroup(lin_bar, bin_bar, lin_count, bin_count, x_label))

        legend = VGroup(
            Text("linear checks", font_size=23, color=danger, weight=BOLD),
            Text("binary checks", font_size=23, color=secondary, weight=BOLD),
        ).arrange(RIGHT, buff=0.55).to_edge(DOWN, buff=0.45)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(note), run_time=0.8)
        for idx, group in enumerate(groups):
            self.play(GrowFromEdge(group[0], DOWN), GrowFromEdge(group[1], DOWN), FadeIn(group[2]), FadeIn(group[3]), FadeIn(group[4]), run_time=0.75)
        self.play(FadeIn(legend), run_time=0.5)
        self.play(Indicate(groups[-1][1], color=good), Flash(groups[-1][1].get_top(), color=good, flash_radius=0.5, line_length=0.16), run_time=0.9)

        plate = RoundedRectangle(width=6.8, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        plate.next_to(note, DOWN, buff=0.35)
        payoff = Text("cutting beats counting", font_size=29, color=fg, weight=BOLD).move_to(plate)
        self.play(FadeIn(plate), FadeIn(payoff), run_time=0.8)
        self.wait(11.0)
'''


def _make_standard_fallback_takeaway_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated decision-rule takeaway fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        question = RoundedRectangle(width=3.9, height=1.0, corner_radius=0.12, stroke_color=accent, stroke_width=3, fill_color=ManimColor("#1F2937"), fill_opacity=0.92)
        q_text = Text("is the data sorted?", font_size=25, color=fg, weight=BOLD).move_to(question)
        question_group = VGroup(question, q_text).shift(UP * 1.15)

        yes = RoundedRectangle(width=3.2, height=0.92, corner_radius=0.12, stroke_color=good, stroke_width=3, fill_color=ManimColor("#064E3B"), fill_opacity=0.86)
        yes_text = Text("use binary search", font_size=23, color=good, weight=BOLD).move_to(yes)
        yes_group = VGroup(yes, yes_text).shift(LEFT * 2.35 + DOWN * 0.45)

        no = RoundedRectangle(width=3.2, height=0.92, corner_radius=0.12, stroke_color=secondary, stroke_width=3, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        no_text = Text("linear still works", font_size=23, color=secondary, weight=BOLD).move_to(no)
        no_group = VGroup(no, no_text).shift(RIGHT * 2.35 + DOWN * 0.45)

        yes_arrow = Arrow(question_group.get_bottom(), yes_group.get_top(), color=good, buff=0.10, stroke_width=4)
        no_arrow = Arrow(question_group.get_bottom(), no_group.get_top(), color=secondary, buff=0.10, stroke_width=4)
        yes_label = Text("yes", font_size=22, color=good, weight=BOLD).next_to(yes_arrow, LEFT, buff=0.08)
        no_label = Text("no", font_size=22, color=secondary, weight=BOLD).next_to(no_arrow, RIGHT, buff=0.08)

        bottom = Text("same problem, different promise", font_size=29, color=accent, weight=BOLD)
        bottom.to_edge(DOWN, buff=0.55)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(question_group), run_time=0.8)
        self.play(Create(yes_arrow), Create(no_arrow), FadeIn(yes_label), FadeIn(no_label), run_time=0.8)
        self.play(FadeIn(yes_group, shift=UP * 0.12), FadeIn(no_group, shift=UP * 0.12), run_time=0.8)
        self.play(Indicate(yes_group, color=good), Indicate(no_group, color=secondary), run_time=0.9)
        self.play(FadeIn(bottom), run_time=0.7)
        self.play(question_group.animate.scale(1.04), rate_func=there_and_back, run_time=0.8)
        self.wait(9.6)
'''


def _make_standard_fallback_race_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated linear-vs-binary race fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    scene_index = int(context.scene_index or 0)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")
    target_index = min(14, max(8, 10 + (scene_index % 5)))
    target_value = target_index + 1

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")
        danger = ManimColor("#EF4444")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        values = list(range(1, 17))
        target_index = {target_index}
        target_value = {target_value}

        def make_row(fill_color):
            row = VGroup()
            for value in values:
                box = RoundedRectangle(
                    width=0.52,
                    height=0.52,
                    corner_radius=0.07,
                    stroke_color=muted,
                    stroke_width=1.2,
                    fill_color=ManimColor(fill_color),
                    fill_opacity=0.94,
                )
                label = Text(str(value), font_size=20, color=fg, weight=BOLD).move_to(box)
                row.add(VGroup(box, label))
            row.arrange(RIGHT, buff=0.055)
            return row

        linear_cells = make_row("#1F2937").shift(UP * 0.72 + RIGHT * 0.45)
        binary_cells = make_row("#111827").shift(DOWN * 0.85 + RIGHT * 0.45)
        linear_label = Text("linear scan", font_size=24, color=muted, weight=BOLD).next_to(linear_cells, LEFT, buff=0.35)
        binary_label = Text("binary split", font_size=24, color=secondary, weight=BOLD).next_to(binary_cells, LEFT, buff=0.35)

        target_box = SurroundingRectangle(linear_cells[target_index], color=good, buff=0.055, stroke_width=3)
        target_text = Text("target = " + str(target_value), font_size=25, color=good, weight=BOLD).to_edge(DOWN, buff=0.43)

        scan_marker = Triangle(fill_color=danger, fill_opacity=1, stroke_color=danger).scale(0.12).rotate(PI)
        scan_marker.next_to(linear_cells[0], UP, buff=0.16)
        jump_marker = Triangle(fill_color=secondary, fill_opacity=1, stroke_color=secondary).scale(0.12).rotate(PI)
        jump_marker.next_to(binary_cells[7], UP, buff=0.16)

        binary_window = SurroundingRectangle(binary_cells, color=accent, buff=0.10, stroke_width=3)
        right_keep = VGroup(*[binary_cells[i] for i in range(8, 16)])
        narrow_window = SurroundingRectangle(right_keep, color=accent, buff=0.10, stroke_width=3)
        second_marker = Triangle(fill_color=secondary, fill_opacity=1, stroke_color=secondary).scale(0.12).rotate(PI)
        second_marker.next_to(binary_cells[11], UP, buff=0.16)

        verdict_plate = RoundedRectangle(width=6.4, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.84)
        verdict_plate.next_to(title, DOWN, buff=0.32)
        verdict = Text("same target, different tempo", font_size=27, color=fg, weight=BOLD).move_to(verdict_plate)

        self.play(FadeIn(title, shift=DOWN * 0.15), FadeIn(verdict_plate), FadeIn(verdict), run_time=0.9)
        self.play(FadeIn(linear_label), FadeIn(binary_label), FadeIn(linear_cells), FadeIn(binary_cells), run_time=1.0)
        self.play(FadeIn(scan_marker), FadeIn(jump_marker), Create(binary_window), FadeIn(target_box), FadeIn(target_text), run_time=0.9)

        linear_scanned = VGroup(*[linear_cells[i] for i in range(target_index + 1)])
        self.play(
            scan_marker.animate.next_to(linear_cells[target_index], UP, buff=0.16),
            linear_scanned.animate.set_opacity(0.42),
            Transform(binary_window, narrow_window),
            Transform(jump_marker, second_marker),
            run_time=1.45,
        )
        self.play(Indicate(right_keep, color=accent), Flash(binary_cells[11].get_center(), color=secondary, flash_radius=0.45, line_length=0.16), run_time=0.85)

        binary_win = Text("binary: 4 jumps", font_size=28, color=secondary, weight=BOLD)
        linear_cost = Text("linear: " + str(target_value) + " checks", font_size=28, color=danger, weight=BOLD)
        result = VGroup(binary_win, linear_cost).arrange(RIGHT, buff=0.55).next_to(binary_cells, DOWN, buff=0.55)
        self.play(Transform(verdict, binary_win.copy().move_to(verdict)), FadeIn(result), run_time=0.9)
        self.play(Flash(target_box, color=good, flash_radius=0.55, line_length=0.16), target_box.animate.set_stroke(width=5), run_time=0.9)
        self.wait(8.2)
'''


def _make_standard_fallback_ladder_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Animated decision-ladder fallback for standard explainers."""
    title = _standard_fallback_title(scene_plan)
    bg = context.domain_state.get("background_color", "#111827")
    fg = context.domain_state.get("foreground_color", "#F9FAFB")
    accent = context.domain_state.get("accent_color", "#F59E0B")
    secondary = context.domain_state.get("secondary_color", "#38BDF8")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=34, color=fg, weight=BOLD)
        if title.width > 10.4:
            title.scale_to_fit_width(10.4)
        title.to_edge(UP, buff=0.35)

        note = Text("every question halves the uncertainty", font_size=27, color=accent, weight=BOLD)
        note.next_to(title, DOWN, buff=0.26)

        labels = ["16 candidates", "8 remain", "4 remain", "2 remain", "1 answer"]
        levels = VGroup()
        for idx, label in enumerate(labels):
            fill = "#1F2937" if idx < len(labels) - 1 else "#064E3B"
            stroke = accent if idx < len(labels) - 1 else good
            plate = RoundedRectangle(
                width=3.0,
                height=0.58,
                corner_radius=0.09,
                stroke_color=stroke,
                stroke_width=2.2,
                fill_color=ManimColor(fill),
                fill_opacity=0.94,
            )
            text = Text(label, font_size=23, color=fg if idx < len(labels) - 1 else good, weight=BOLD).move_to(plate)
            levels.add(VGroup(plate, text))
        levels.arrange(DOWN, buff=0.20).shift(RIGHT * 2.15 + DOWN * 0.18)

        arrows = VGroup()
        for idx in range(len(levels) - 1):
            arrows.add(Arrow(levels[idx].get_bottom(), levels[idx + 1].get_top(), buff=0.05, color=secondary, stroke_width=3))

        left_panel = VGroup(
            Text("bad version:", font_size=25, color=muted, weight=BOLD),
            Text("check one item", font_size=23, color=muted),
            Text("then another", font_size=23, color=muted),
            Text("then another...", font_size=23, color=muted),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.18)
        left_panel.shift(LEFT * 3.25 + DOWN * 0.08)

        fast_panel = VGroup(
            Text("good version:", font_size=25, color=secondary, weight=BOLD),
            Text("ask the midpoint", font_size=23, color=fg),
            Text("throw away half", font_size=23, color=fg),
            Text("repeat with focus", font_size=23, color=fg),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.18)
        fast_panel.next_to(left_panel, DOWN, buff=0.56, aligned_edge=LEFT)

        formula_plate = RoundedRectangle(width=5.6, height=0.78, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.86)
        formula_plate.to_edge(DOWN, buff=0.42)
        formula = Text("16 items need only 4 clean cuts", font_size=28, color=fg, weight=BOLD).move_to(formula_plate)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(note), run_time=0.8)
        self.play(FadeIn(left_panel, shift=RIGHT * 0.12), run_time=0.8)
        self.play(FadeIn(fast_panel, shift=RIGHT * 0.12), run_time=0.8)
        self.play(LaggedStart(*[FadeIn(level) for level in levels], lag_ratio=0.14), run_time=1.2)
        self.play(LaggedStart(*[Create(arrow) for arrow in arrows], lag_ratio=0.18), run_time=0.9)
        self.play(Indicate(levels[-1], color=good), FadeIn(formula_plate), FadeIn(formula), run_time=1.0)
        earlier_levels = VGroup(*[levels[i] for i in range(len(levels) - 1)])
        self.play(earlier_levels.animate.set_opacity(0.55), levels[-1].animate.scale(1.08), run_time=0.8)
        self.wait(8.4)
'''


def _course_fallback_title(scene_plan: dict, context: NarrativeContext) -> str:
    title = str(
        scene_plan.get("title")
        or scene_plan.get("module")
        or scene_plan.get("description")
        or context.prompt
        or "Lesson scene"
    )
    title = _clean_plan_text(title) or "Lesson scene"
    if len(title) > 54:
        title = title[:51].rstrip(" ,.;:-") + "..."
    return title


def _make_course_question_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _course_fallback_title(scene_plan, context)
    prompt = _clean_plan_text(
        scene_plan.get("narration")
        or scene_plan.get("description")
        or "Which path matches the idea we just built?"
    )
    if len(prompt) > 104:
        prompt = prompt[:101].rstrip(" ,.;:-") + "..."
    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    secondary = context.domain_state.get("secondary_color", "#F2C94C")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")

        title = Text({title!r}, font_size=30, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        module = Text("checkpoint", font_size=20, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.22)

        question = Text({prompt!r}, font_size=29, color=fg, weight=BOLD)
        if question.width > 9.8:
            question.scale_to_fit_width(9.8)
        question.move_to(UP * 0.55)

        left = RoundedRectangle(width=3.3, height=0.9, corner_radius=0.1, stroke_color=accent, stroke_width=2.5, fill_color=ManimColor("#111827"), fill_opacity=0.72).shift(LEFT * 2.25 + DOWN * 0.8)
        right = RoundedRectangle(width=3.3, height=0.9, corner_radius=0.1, stroke_color=secondary, stroke_width=2.5, fill_color=ManimColor("#111827"), fill_opacity=0.72).shift(RIGHT * 2.25 + DOWN * 0.8)
        left_text = Text("use the rule", font_size=23, color=accent, weight=BOLD).move_to(left)
        right_text = Text("test an example", font_size=23, color=secondary, weight=BOLD).move_to(right)
        timer = Line(LEFT * 2.0, RIGHT * 2.0, color=muted, stroke_width=5).to_edge(DOWN, buff=0.75)
        tick = Dot(color=secondary, radius=0.08).move_to(timer.get_left())

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(module), run_time=0.8)
        self.play(FadeIn(question), run_time=0.8)
        self.play(FadeIn(left), FadeIn(right), FadeIn(left_text), FadeIn(right_text), run_time=0.8)
        self.play(Create(timer), GrowFromCenter(tick), run_time=0.7)
        self.play(tick.animate.move_to(timer.get_right()), rate_func=linear, run_time=1.2)
        self.wait(6.3)
'''


def _make_course_map_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _course_fallback_title(scene_plan, context)
    module = _clean_plan_text(scene_plan.get("module") or "Course Map")
    if len(module) > 36:
        module = module[:33].rstrip(" ,.;:-") + "..."
    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    secondary = context.domain_state.get("secondary_color", "#F2C94C")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=30, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        module = Text({module!r}, font_size=19, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.22)

        milestones = VGroup()
        labels = ["anchor", "rule", "practice", "transfer"]
        for idx, label in enumerate(labels):
            box = RoundedRectangle(width=2.0, height=0.68, corner_radius=0.09, stroke_color=accent if idx < 2 else muted, stroke_width=2.2, fill_color=ManimColor("#111827"), fill_opacity=0.82)
            text = Text(label, font_size=21, color=fg if idx < 2 else muted, weight=BOLD).move_to(box)
            milestones.add(VGroup(box, text))
        milestones.arrange(DOWN, buff=0.28).shift(LEFT * 3.25 + DOWN * 0.18)

        path = VMobject(color=secondary, stroke_width=5)
        points = [m.get_center() for m in milestones]
        path.set_points_as_corners(points)
        learner = Dot(color=secondary, radius=0.12).move_to(points[0])

        board = RoundedRectangle(width=4.7, height=2.6, corner_radius=0.14, stroke_color=accent, stroke_width=3, fill_color=ManimColor("#111827"), fill_opacity=0.82).shift(RIGHT * 1.8 + DOWN * 0.05)
        board_title = Text("course route", font_size=24, color=fg, weight=BOLD).move_to(board.get_top() + DOWN * 0.45)
        route_a = Line(board.get_left() + RIGHT * 0.55 + UP * 0.25, board.get_center() + LEFT * 0.2, color=secondary, stroke_width=5)
        route_b = Line(board.get_center() + LEFT * 0.2, board.get_right() + LEFT * 0.65 + DOWN * 0.35, color=good, stroke_width=5)
        final_dot = Dot(color=good, radius=0.12).move_to(route_b.get_end())

        plate = RoundedRectangle(width=6.2, height=0.78, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.88)
        plate.to_edge(DOWN, buff=0.42)
        objective = Text("keep the lesson route visible", font_size=27, color=fg, weight=BOLD).move_to(plate)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(module), run_time=0.8)
        self.play(LaggedStart(*[FadeIn(m, shift=RIGHT * 0.12) for m in milestones], lag_ratio=0.12), run_time=1.1)
        self.play(Create(path), GrowFromCenter(learner), run_time=0.9)
        self.play(learner.animate.move_to(points[1]), Indicate(milestones[1], color=secondary), run_time=1.0)
        self.play(FadeIn(board), FadeIn(board_title), run_time=0.8)
        self.play(Create(route_a), learner.animate.move_to(points[2]), run_time=1.0)
        self.play(Create(route_b), GrowFromCenter(final_dot), Indicate(milestones[-1], color=good), run_time=1.0)
        self.play(FadeIn(plate), FadeIn(objective), Flash(final_dot.get_center(), color=good, flash_radius=0.5, line_length=0.16), run_time=0.9)
        self.wait(14.2)
'''


def _make_course_mechanism_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _course_fallback_title(scene_plan, context)
    module = _clean_plan_text(scene_plan.get("module") or "Mechanism")
    if len(module) > 36:
        module = module[:33].rstrip(" ,.;:-") + "..."
    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    secondary = context.domain_state.get("secondary_color", "#F2C94C")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=30, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        module = Text({module!r}, font_size=19, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.22)

        labels = ["current", "rule", "next"]
        panels = VGroup()
        for idx, label in enumerate(labels):
            color = accent if idx != 2 else good
            panel = RoundedRectangle(width=2.55, height=1.18, corner_radius=0.1, stroke_color=color, stroke_width=2.5, fill_color=ManimColor("#111827"), fill_opacity=0.82)
            text = Text(label, font_size=24, color=fg, weight=BOLD).move_to(panel)
            panels.add(VGroup(panel, text))
        panels.arrange(RIGHT, buff=0.52).shift(UP * 0.25)

        arrows = VGroup(
            Arrow(panels[0].get_right(), panels[1].get_left(), color=secondary, stroke_width=4, buff=0.12),
            Arrow(panels[1].get_right(), panels[2].get_left(), color=secondary, stroke_width=4, buff=0.12),
        )
        token = Dot(color=secondary, radius=0.13).move_to(panels[0].get_center() + DOWN * 0.34)

        invariant = RoundedRectangle(width=7.4, height=0.64, corner_radius=0.1, stroke_color=good, stroke_width=2.5, fill_color=ManimColor("#052E16"), fill_opacity=0.72)
        invariant.shift(DOWN * 1.55)
        invariant_text = Text("invariant stays true while state changes", font_size=24, color=good, weight=BOLD)
        if invariant_text.width > 6.9:
            invariant_text.scale_to_fit_width(6.9)
        invariant_text.move_to(invariant)

        counter_line = NumberLine(x_range=[0, 4, 1], length=4.6, color=muted, include_numbers=False).to_edge(DOWN, buff=0.72)
        low_dot = Dot(color=accent, radius=0.09).move_to(counter_line.n2p(0))
        high_dot = Dot(color=good, radius=0.09).move_to(counter_line.n2p(4))
        scan = Dot(color=secondary, radius=0.1).move_to(counter_line.n2p(0))

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(module), run_time=0.8)
        self.play(LaggedStart(*[FadeIn(panel, shift=DOWN * 0.1) for panel in panels], lag_ratio=0.15), GrowFromCenter(token), run_time=1.1)
        self.play(Create(arrows[0]), token.animate.move_to(panels[1].get_center() + DOWN * 0.34), run_time=0.9)
        self.play(Create(invariant), FadeIn(invariant_text), Indicate(panels[1], color=secondary), run_time=1.0)
        self.play(Create(arrows[1]), token.animate.move_to(panels[2].get_center() + DOWN * 0.34), run_time=0.9)
        self.play(Create(counter_line), GrowFromCenter(low_dot), GrowFromCenter(high_dot), GrowFromCenter(scan), run_time=0.9)
        self.play(scan.animate.move_to(counter_line.n2p(2.5)), low_dot.animate.move_to(counter_line.n2p(1)), Indicate(invariant, color=good), run_time=1.1)
        self.play(Flash(token.get_center(), color=good, flash_radius=0.48, line_length=0.16), run_time=0.8)
        self.wait(14.4)
'''


def _make_course_compare_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _course_fallback_title(scene_plan, context)
    module = _clean_plan_text(scene_plan.get("module") or "Compare")
    if len(module) > 36:
        module = module[:33].rstrip(" ,.;:-") + "..."
    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    secondary = context.domain_state.get("secondary_color", "#F2C94C")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        bad = ManimColor("#EF4444")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=30, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        module = Text({module!r}, font_size=19, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.22)

        left = RoundedRectangle(width=3.35, height=2.05, corner_radius=0.12, stroke_color=bad, stroke_width=3, fill_color=ManimColor("#111827"), fill_opacity=0.82).shift(LEFT * 2.35 + DOWN * 0.15)
        right = RoundedRectangle(width=3.35, height=2.05, corner_radius=0.12, stroke_color=good, stroke_width=3, fill_color=ManimColor("#111827"), fill_opacity=0.82).shift(RIGHT * 2.35 + DOWN * 0.15)
        wrong_label = Text("near miss", font_size=24, color=bad, weight=BOLD).move_to(left.get_top() + DOWN * 0.42)
        right_label = Text("valid move", font_size=24, color=good, weight=BOLD).move_to(right.get_top() + DOWN * 0.42)

        wrong_path = VGroup(
            Line(left.get_left() + RIGHT * 0.55 + DOWN * 0.2, left.get_center() + RIGHT * 0.2 + UP * 0.25, color=bad, stroke_width=5),
            Line(left.get_center() + RIGHT * 0.2 + UP * 0.25, left.get_right() + LEFT * 0.55 + DOWN * 0.4, color=bad, stroke_width=5),
        )
        right_path = VGroup(
            Line(right.get_left() + RIGHT * 0.55 + DOWN * 0.35, right.get_center() + LEFT * 0.1, color=secondary, stroke_width=5),
            Line(right.get_center() + LEFT * 0.1, right.get_right() + LEFT * 0.55 + UP * 0.25, color=good, stroke_width=5),
        )
        fail = Text("X", font_size=42, color=bad, weight=BOLD).move_to(left.get_bottom() + UP * 0.44)
        ok = Text("OK", font_size=34, color=good, weight=BOLD).move_to(right.get_bottom() + UP * 0.44)

        bridge = Arrow(left.get_right() + RIGHT * 0.2, right.get_left() + LEFT * 0.2, color=accent, stroke_width=4, buff=0.12)
        repair = Text("repair the assumption", font_size=25, color=fg, weight=BOLD).next_to(bridge, UP, buff=0.25)
        if repair.width > 4.4:
            repair.scale_to_fit_width(4.4)

        plate = RoundedRectangle(width=6.4, height=0.78, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.88)
        plate.to_edge(DOWN, buff=0.42)
        takeaway = Text("compare, mark, then repair", font_size=27, color=fg, weight=BOLD).move_to(plate)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(module), run_time=0.8)
        self.play(FadeIn(left), FadeIn(right), FadeIn(wrong_label), FadeIn(right_label), run_time=0.9)
        self.play(LaggedStart(*[Create(line) for line in wrong_path], lag_ratio=0.15), run_time=0.9)
        self.play(Write(fail), Wiggle(left), run_time=0.9)
        self.play(Create(bridge), FadeIn(repair), run_time=0.8)
        self.play(LaggedStart(*[Create(line) for line in right_path], lag_ratio=0.15), run_time=0.9)
        self.play(Write(ok), Indicate(right, color=good), wrong_path.animate.set_opacity(0.35), run_time=1.0)
        self.play(FadeIn(plate), FadeIn(takeaway), Flash(ok.get_center(), color=good, flash_radius=0.48, line_length=0.16), run_time=0.9)
        self.wait(14.6)
'''


def _make_course_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Deterministic lesson scenelet for course-mode reliability."""
    return localize_scene_code(_make_course_fallback_scene_code_raw(scene_plan, context))


def _make_course_fallback_scene_code_raw(
    scene_plan: dict, context: NarrativeContext
) -> str:
    if scene_plan.get("type") == "question" or "question" in _clean_plan_text(scene_plan.get("scene_role")).lower():
        return _make_course_question_fallback_scene_code(scene_plan, context)

    title = _course_fallback_title(scene_plan, context)
    module = _clean_plan_text(scene_plan.get("module") or "Course Module")
    if len(module) > 36:
        module = module[:33].rstrip(" ,.;:-") + "..."
    role = _clean_plan_text(scene_plan.get("scene_role") or scene_plan.get("type")).lower()
    plan_text = " ".join(
        _clean_plan_text(scene_plan.get(key)).lower()
        for key in ("title", "description", "narration", "visual_description", "module", "scene_role")
    )
    if any(token in plan_text for token in ("map", "orientation", "recap", "summary", "takeaway", "synthesis")):
        return _make_course_map_fallback_scene_code(scene_plan, context)
    if any(token in plan_text for token in ("mechanism", "rule", "invariant", "state", "cost", "tradeoff", "complexity", "counter")):
        return _make_course_mechanism_fallback_scene_code(scene_plan, context)
    if any(token in plan_text for token in ("mistake", "edge", "boundary", "break", "repair", "non-example", "near miss", "wrong")):
        return _make_course_compare_fallback_scene_code(scene_plan, context)
    if "example" in role or "practice" in role:
        steps = ["set up toy case", "run the rule", "read the result"]
        objective = "practice turns the rule into a move"
    elif "definition" in role or "vocabulary" in role:
        steps = ["name the object", "attach the label", "test the definition"]
        objective = "attach a name, then test it"
    else:
        steps = ["build the anchor", "change one state", "keep the useful rule"]
        objective = "one lesson beat, one durable idea"

    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    secondary = context.domain_state.get("secondary_color", "#F2C94C")
    steps_literal = repr(steps)

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=30, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        module = Text({module!r}, font_size=19, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.22)

        rail = VGroup()
        for idx in range(4):
            dot = Circle(radius=0.11, stroke_color=accent, stroke_width=2, fill_color=accent if idx <= 1 else muted, fill_opacity=0.85 if idx <= 1 else 0.2)
            rail.add(dot)
        rail.arrange(RIGHT, buff=0.22).to_edge(LEFT, buff=0.78).shift(UP * 2.08)

        anchor = RoundedRectangle(width=3.0, height=2.1, corner_radius=0.14, stroke_color=accent, stroke_width=3, fill_color=ManimColor("#111827"), fill_opacity=0.82).shift(LEFT * 3.25 + DOWN * 0.15)
        anchor_label = Text("anchor visual", font_size=23, color=fg, weight=BOLD).move_to(anchor.get_center() + UP * 0.45)
        start_point = anchor.get_center() + DOWN * 0.25 + LEFT * 0.75
        end_point = anchor.get_center() + DOWN * 0.25 + RIGHT * 0.75
        state = Dot(color=secondary, radius=0.11).move_to(start_point)
        target = Dot(color=good, radius=0.11).move_to(end_point)
        path = Arrow(start_point, end_point, color=secondary, stroke_width=4, buff=0.12)
        practice_marker = Dot(color=accent, radius=0.08).move_to(start_point + UP * 0.36)

        steps = {steps_literal}
        cards = VGroup()
        for idx, label in enumerate(steps):
            card = RoundedRectangle(width=4.7, height=0.62, corner_radius=0.09, stroke_color=accent if idx < len(steps) - 1 else good, stroke_width=2.0, fill_color=ManimColor("#111827"), fill_opacity=0.82)
            text = Text(label, font_size=22, color=fg if idx < len(steps) - 1 else good, weight=BOLD)
            if text.width > 4.25:
                text.scale_to_fit_width(4.25)
            text.move_to(card)
            cards.add(VGroup(card, text))
        cards.arrange(DOWN, buff=0.22).shift(RIGHT * 2.15 + DOWN * 0.1)

        self.play(FadeIn(title, shift=DOWN * 0.12), FadeIn(module), FadeIn(rail), run_time=0.8)
        self.play(FadeIn(anchor), FadeIn(anchor_label), GrowFromCenter(state), GrowFromCenter(target), run_time=0.9)
        self.play(Create(path), state.animate.move_to(target.get_center()), run_time=1.0)
        self.play(GrowFromCenter(practice_marker), run_time=0.4)
        self.play(practice_marker.animate.move_to(end_point + UP * 0.36), Indicate(target, color=good), run_time=0.9)
        self.play(LaggedStart(*[FadeIn(card, shift=LEFT * 0.10) for card in cards], lag_ratio=0.15), run_time=1.1)
        focus = SurroundingRectangle(cards[0], color=secondary, buff=0.07, stroke_width=3)
        self.play(Create(focus), Indicate(cards[0], color=secondary), run_time=0.8)
        next_focus = SurroundingRectangle(cards[-1], color=good, buff=0.07, stroke_width=3)
        self.play(Transform(focus, next_focus), cards[0].animate.set_opacity(0.55), Indicate(cards[-1], color=good), run_time=1.0)

        plate = RoundedRectangle(width=6.7, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.88)
        plate.to_edge(DOWN, buff=0.42)
        objective = Text({objective!r}, font_size=27, color=fg, weight=BOLD).move_to(plate)
        if objective.width > 6.2:
            objective.scale_to_fit_width(6.2)
            objective.move_to(plate)
        self.play(FadeIn(plate), FadeIn(objective), Flash(cards[-1].get_center(), color=good, flash_radius=0.5, line_length=0.16), run_time=0.9)
        self.wait(14.2)
'''


def _lecture_fallback_title(scene_plan: dict, context: NarrativeContext) -> str:
    title = str(
        scene_plan.get("title")
        or scene_plan.get("lecture_section")
        or scene_plan.get("description")
        or context.prompt
        or "Lecture board"
    )
    title = _clean_plan_text(title) or "Lecture board"
    if len(title) > 54:
        title = title[:51].rstrip(" ,.;:-") + "..."
    return title


def _lecture_fallback_steps(scene_plan: dict) -> tuple[list[str], list[str], str]:
    role = _clean_plan_text(scene_plan.get("scene_role") or scene_plan.get("type")).lower()
    if "example" in role:
        return (
            ["instantiate symbols", "run the calculation", "interpret the result"],
            ["given values", "theorem rule", "computed target"],
            "the example follows the proof map",
        )
    if any(token in role for token in ("pitfall", "repair", "edge")):
        return (
            ["test the tempting step", "mark the missing assumption", "repair the route"],
            ["naive line", "failure point", "valid condition"],
            "the bad proof fails at one visible step",
        )
    if "definition" in role or "statement" in role:
        return (
            ["separate assumptions", "name the conclusion", "connect the implication"],
            ["assumption", "definition", "target claim"],
            "the statement is a map, not a paragraph",
        )
    return (
        ["start from the assumption", "apply the lemma", "arrive at the target"],
        ["assumption", "lemma", "target"],
        "one proof move stays active at a time",
    )


def _make_lecture_question_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _lecture_fallback_title(scene_plan, context)
    question = _clean_plan_text(
        scene_plan.get("narration")
        or scene_plan.get("description")
        or "Which assumption is doing the work here?"
    )
    if len(question) > 105:
        question = question[:102].rstrip(" ,.;:-") + "..."
    bg = context.domain_state.get("background_color", "#0B1020")
    fg = context.domain_state.get("foreground_color", "#F8FAFC")
    accent = context.domain_state.get("accent_color", "#93C5FD")
    secondary = context.domain_state.get("secondary_color", "#FBBF24")

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")

        title = Text({title!r}, font_size=32, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        section = Text("thinking pause", font_size=22, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.14)

        prompt = Text({question!r}, font_size=29, color=fg, weight=BOLD)
        if prompt.width > 9.8:
            prompt.scale_to_fit_width(9.8)
        prompt.move_to(UP * 0.45)

        map_nodes = VGroup()
        for label in ["statement", "lemma", "target"]:
            box = RoundedRectangle(width=2.35, height=0.54, corner_radius=0.08, stroke_color=muted, stroke_width=1.8, fill_color=ManimColor("#111827"), fill_opacity=0.45)
            text = Text(label, font_size=20, color=muted).move_to(box)
            map_nodes.add(VGroup(box, text))
        map_nodes.arrange(RIGHT, buff=0.35).next_to(prompt, DOWN, buff=0.75)
        map_nodes.set_opacity(0.42)
        timer = Circle(radius=0.42, stroke_color=secondary, stroke_width=5).next_to(map_nodes, DOWN, buff=0.55)
        timer_label = Text("pause", font_size=21, color=secondary, weight=BOLD).move_to(timer)

        self.play(FadeIn(section), FadeIn(title, shift=DOWN * 0.12), run_time=0.8)
        self.play(FadeIn(prompt), FadeIn(map_nodes), run_time=0.9)
        self.play(Create(timer), FadeIn(timer_label), run_time=0.8)
        self.play(timer.animate.scale(1.12), rate_func=there_and_back, run_time=1.0)
        self.wait(6.4)
'''


def _make_lecture_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Deterministic academic scenelet for lecture-mode reliability."""
    return localize_scene_code(_make_lecture_fallback_scene_code_raw(scene_plan, context))


def _make_lecture_fallback_scene_code_raw(
    scene_plan: dict, context: NarrativeContext
) -> str:
    if scene_plan.get("type") == "question" or "question" in _clean_plan_text(scene_plan.get("scene_role")).lower():
        return _make_lecture_question_fallback_scene_code(scene_plan, context)

    title = _lecture_fallback_title(scene_plan, context)
    section = _clean_plan_text(scene_plan.get("lecture_section") or "Academic Board")
    if len(section) > 38:
        section = section[:35].rstrip(" ,.;:-") + "..."
    steps, assumptions, payoff_line = _lecture_fallback_steps(scene_plan)
    bg = context.domain_state.get("background_color", "#0B1020")
    fg = context.domain_state.get("foreground_color", "#F8FAFC")
    accent = context.domain_state.get("accent_color", "#93C5FD")
    secondary = context.domain_state.get("secondary_color", "#FBBF24")
    steps_literal = repr(steps)
    assumptions_literal = repr(assumptions)

    return f'''from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        secondary = ManimColor({secondary!r})
        muted = ManimColor("#94A3B8")
        good = ManimColor("#22C55E")

        title = Text({title!r}, font_size=32, color=fg, weight=BOLD)
        if title.width > 10.2:
            title.scale_to_fit_width(10.2)
        title.to_edge(UP, buff=0.42)
        section = Text({section!r}, font_size=21, color=accent, weight=BOLD).next_to(title, DOWN, buff=0.14)

        assumptions = {assumptions_literal}
        ledger = VGroup()
        for label in assumptions:
            box = RoundedRectangle(width=2.75, height=0.58, corner_radius=0.08, stroke_color=muted, stroke_width=1.6, fill_color=ManimColor("#111827"), fill_opacity=0.75)
            text = Text(label, font_size=19, color=fg)
            if text.width > 2.35:
                text.scale_to_fit_width(2.35)
            text.move_to(box)
            ledger.add(VGroup(box, text))
        ledger.arrange(DOWN, buff=0.18).move_to(LEFT * 4.45 + DOWN * 0.18)
        ledger_title = Text("assumption ledger", font_size=20, color=muted, weight=BOLD).next_to(ledger, UP, buff=0.18)

        steps = {steps_literal}
        ladder = VGroup()
        for idx, label in enumerate(steps):
            plate = RoundedRectangle(width=5.55, height=0.64, corner_radius=0.09, stroke_color=accent if idx < len(steps) - 1 else good, stroke_width=2.0, fill_color=ManimColor("#111827"), fill_opacity=0.82)
            text = Text(label, font_size=22, color=fg if idx < len(steps) - 1 else good, weight=BOLD)
            if text.width > 5.05:
                text.scale_to_fit_width(5.05)
            text.move_to(plate)
            ladder.add(VGroup(plate, text))
        ladder.arrange(DOWN, buff=0.24).move_to(DOWN * 0.18)

        proof_map = VGroup()
        for label in ["statement", "lemma", "target"]:
            node = RoundedRectangle(width=2.15, height=0.52, corner_radius=0.08, stroke_color=secondary, stroke_width=1.8, fill_color=ManimColor("#1F2937"), fill_opacity=0.72)
            text = Text(label, font_size=18, color=secondary).move_to(node)
            proof_map.add(VGroup(node, text))
        proof_map.arrange(DOWN, buff=0.22).move_to(RIGHT * 4.45 + DOWN * 0.12)
        map_title = Text("proof map", font_size=20, color=muted, weight=BOLD).next_to(proof_map, UP, buff=0.18)
        arrows = VGroup()
        for idx in range(len(proof_map) - 1):
            arrows.add(Arrow(proof_map[idx].get_bottom(), proof_map[idx + 1].get_top(), buff=0.05, color=secondary, stroke_width=2.5))

        self.play(FadeIn(section), FadeIn(title, shift=DOWN * 0.12), run_time=0.8)
        self.play(FadeIn(ledger_title), LaggedStart(*[FadeIn(card, shift=RIGHT * 0.10) for card in ledger], lag_ratio=0.10), run_time=1.0)
        self.play(FadeIn(map_title), LaggedStart(*[FadeIn(node) for node in proof_map], lag_ratio=0.10), LaggedStart(*[Create(arrow) for arrow in arrows], lag_ratio=0.12), run_time=1.1)
        self.play(LaggedStart(*[FadeIn(line, shift=UP * 0.08) for line in ladder], lag_ratio=0.16), run_time=1.2)

        active = SurroundingRectangle(ladder[0], color=secondary, buff=0.08, stroke_width=3)
        self.play(Create(active), Indicate(ledger[0], color=secondary), run_time=0.9)
        next_active = SurroundingRectangle(ladder[1], color=secondary, buff=0.08, stroke_width=3)
        self.play(Transform(active, next_active), ledger[0].animate.set_opacity(0.45), Indicate(ladder[1], color=secondary), run_time=1.0)
        final_active = SurroundingRectangle(ladder[2], color=good, buff=0.08, stroke_width=3.5)
        self.play(Transform(active, final_active), proof_map[-1].animate.set_stroke(color=good, width=3), Indicate(ladder[2], color=good), run_time=1.0)

        plate = RoundedRectangle(width=6.7, height=0.82, corner_radius=0.12, stroke_width=0, fill_color=ManimColor("#0F172A"), fill_opacity=0.88)
        plate.to_edge(DOWN, buff=0.42)
        payoff = Text({payoff_line!r}, font_size=27, color=fg, weight=BOLD).move_to(plate)
        if payoff.width > 6.2:
            payoff.scale_to_fit_width(6.2)
            payoff.move_to(plate)
        self.play(FadeIn(plate), FadeIn(payoff), Flash(ladder[-1].get_center(), color=good, flash_radius=0.55, line_length=0.16), run_time=0.9)
        self.wait(15.0)
'''


def _make_short_dijkstra_scene_code(
    scene_plan: dict,
    context: NarrativeContext,
    *,
    title: str,
    bg: str,
    fg: str,
    accent: str,
    warm: str,
) -> str:
    scene_index = int(context.scene_index or 0)
    final_scene = _is_final_short_scene(scene_plan, context)
    caption = "which node is next?" if final_scene else _short_fallback_lines(scene_plan, context)[0]
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        muted = ManimColor("#6B7280")
        title = Text({"Your turn" if final_scene else title!r}, font_size=38, color=fg, weight=BOLD)
        if title.width > 5.7:
            title.scale(5.7 / title.width)
        title.to_edge(UP, buff=0.82)
        caption = Text({caption!r}, font_size=28, color=warm if {final_scene!r} else fg)
        if caption.width > 5.6:
            caption.scale(5.6 / caption.width)
        caption.next_to(title, DOWN, buff=0.22)

        pos = {{
            "A": LEFT * 2.15 + UP * 1.55,
            "B": RIGHT * 1.35 + UP * 1.85,
            "C": LEFT * 1.45 + DOWN * 1.35,
            "D": RIGHT * 2.0 + DOWN * 1.05,
        }}
        weights = [("A", "B", "2"), ("A", "C", "5"), ("B", "C", "1"), ("B", "D", "4"), ("C", "D", "2")]
        edges = VGroup()
        edge_lookup = {{}}
        weight_labels = VGroup()
        for a, b, w in weights:
            line = Line(pos[a], pos[b], color=muted, stroke_width=4)
            edge_lookup[(a, b)] = line
            edge_lookup[(b, a)] = line
            label = Text(w, font_size=23, color=fg)
            label.move_to((pos[a] + pos[b]) / 2)
            label.set_z_index(5)
            weight_labels.add(label)
            edges.add(line)

        def node(label):
            circle = Circle(radius=0.34, stroke_color=accent, stroke_width=4, fill_color=ManimColor("#111824"), fill_opacity=0.95)
            circle.move_to(pos[label])
            text = Text(label, font_size=27, color=fg, weight=BOLD).move_to(circle)
            group = VGroup(circle, text)
            group.set_z_index(10)
            return group

        nodes = VGroup(node("A"), node("B"), node("C"), node("D"))
        dist = VGroup(
            Text("d(A)=0", font_size=24, color=warm),
            Text("d(B)=2", font_size=24, color=warm),
            Text("d(C)=3", font_size=24, color=warm),
            Text("d(D)=6", font_size=24, color=warm),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.16)
        dist.to_edge(DOWN, buff=0.78)
        dist_box = SurroundingRectangle(dist, color=accent, buff=0.2, corner_radius=0.12)

        self.play(FadeIn(title, shift=DOWN * 0.2), FadeIn(caption, shift=DOWN * 0.15), run_time=0.55)
        self.play(Create(edges), LaggedStart(*[GrowFromCenter(n) for n in nodes], lag_ratio=0.12), FadeIn(weight_labels), run_time=1.2)

        scene_index = {scene_index}
        if scene_index == 0:
            pulse_path = [("A", "B"), ("A", "C")]
            note = Text("start at A", font_size=30, color=warm).next_to(nodes[0], LEFT, buff=0.2)
            self.play(Indicate(nodes[0], color=warm), FadeIn(note), run_time=0.9)
        elif scene_index == 1:
            pulse_path = [("A", "B"), ("B", "C")]
            note = Text("relax neighbors", font_size=30, color=warm).move_to(DOWN * 2.75)
            self.play(FadeIn(note, shift=UP * 0.2), run_time=0.35)
        elif scene_index == 2:
            pulse_path = [("A", "B"), ("B", "D")]
            note = Text("best path so far", font_size=30, color=warm).move_to(DOWN * 2.75)
            self.play(FadeIn(note, shift=UP * 0.2), run_time=0.35)
        else:
            pulse_path = [("A", "B"), ("B", "C"), ("C", "D")]
            note = Text("smallest distance wins", font_size=29, color=warm).move_to(DOWN * 2.75)
            self.play(FadeIn(note, shift=UP * 0.2), run_time=0.35)

        for a, b in pulse_path:
            line = edge_lookup[(a, b)]
            glow = line.copy().set_color(warm).set_stroke(width=9, opacity=0.85)
            traveler = Dot(color=warm, radius=0.08).move_to(line.get_start())
            self.play(ShowPassingFlash(glow, time_width=0.5), MoveAlongPath(traveler, line), run_time=0.85)
            self.remove(traveler)
            line.set_color(warm)
            line.set_stroke(width=6)
        self.play(FadeIn(dist_box), LaggedStart(*[FadeIn(d, shift=RIGHT * 0.2) for d in dist], lag_ratio=0.1), run_time=0.8)
        self.play(Indicate(dist[min(scene_index, 3)], color=warm), run_time=0.8)
        self.play(Indicate(note, color=warm), run_time=0.75)
        self.wait(2.5)
"""


def _make_short_binary_search_scene_code(
    scene_plan: dict,
    context: NarrativeContext,
    *,
    title: str,
    bg: str,
    fg: str,
    accent: str,
    warm: str,
) -> str:
    scene_index = int(context.scene_index or 0)
    final_scene = _is_final_short_scene(scene_plan, context)
    headline = "Your turn" if final_scene else "Binary search"
    note = "which half survives?" if final_scene else _short_fallback_lines(scene_plan, context)[0]
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        title = Text({headline!r}, font_size=38, color=fg, weight=BOLD).to_edge(UP, buff=0.82)
        subtitle = Text({note!r}, font_size=27, color=warm if {final_scene!r} else fg)
        if subtitle.width > 5.6:
            subtitle.scale(5.6 / subtitle.width)
        subtitle.next_to(title, DOWN, buff=0.25)
        values = [1, 3, 5, 7, 9, 11, 13, 15]
        cells = VGroup()
        for value in values:
            box = RoundedRectangle(width=1.25, height=0.9, corner_radius=0.1, stroke_color=accent, stroke_width=3, fill_color=ManimColor("#111824"), fill_opacity=0.82)
            label = Text(str(value), font_size=28, color=fg, weight=BOLD).move_to(box)
            cells.add(VGroup(box, label))
        cells.arrange_in_grid(rows=2, cols=4, buff=0.22).move_to(DOWN * 0.05)
        target = Text("target = 7", font_size=31, color=warm).next_to(subtitle, DOWN, buff=0.42)
        pointer = Triangle(color=warm, fill_color=warm, fill_opacity=1).scale(0.17).rotate(PI)
        pointer.next_to(cells[3], UP, buff=0.16)
        window = SurroundingRectangle(cells, color=warm, buff=0.14, corner_radius=0.12)
        low_high = Text("low ........ high", font_size=24, color=fg).next_to(cells, DOWN, buff=0.42)

        self.play(FadeIn(title, shift=DOWN * 0.2), FadeIn(subtitle), FadeIn(target), run_time=0.55)
        self.play(LaggedStart(*[GrowFromCenter(cell) for cell in cells], lag_ratio=0.06), Create(window), FadeIn(low_high), run_time=1.2)
        scene_index = {scene_index}
        steps = [
            (3, 0, 7, "mid = 7"),
            (5, 4, 7, "7 is left of 11"),
            (3, 0, 3, "match found"),
            (2, 0, 3, "try the next mid"),
        ]
        mid, lo, hi, label = steps[min(scene_index, len(steps) - 1)]
        new_window = SurroundingRectangle(VGroup(*[cells[i] for i in range(lo, hi + 1)]), color=warm, buff=0.14, corner_radius=0.12)
        mid_label = Text(label, font_size=30, color=warm).to_edge(DOWN, buff=0.82)
        self.play(Transform(window, new_window), pointer.animate.next_to(cells[mid], UP, buff=0.16), FadeIn(mid_label, shift=UP * 0.25), run_time=1.0)
        self.play(cells[mid][0].animate.set_fill(warm, opacity=0.35), Indicate(cells[mid], color=warm), run_time=0.85)
        faded = [cells[i] for i in range(len(cells)) if i < lo or i > hi]
        if faded:
            self.play(*[cell.animate.set_opacity(0.25) for cell in faded], run_time=0.55)
        self.play(pointer.animate.shift(DOWN * 0.12), rate_func=there_and_back, run_time=0.75)
        self.play(Indicate(mid_label, color=warm), run_time=0.75)
        self.wait(2.6)
"""


def _make_short_molecule_scene_code(
    scene_plan: dict,
    context: NarrativeContext,
    *,
    title: str,
    bg: str,
    fg: str,
    accent: str,
    warm: str,
) -> str:
    scene_index = int(context.scene_index or 0)
    final_scene = _is_final_short_scene(scene_plan, context)
    caption = "which bond changes first?" if final_scene else _short_fallback_lines(scene_plan, context)[0]
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        title = Text({"Your turn" if final_scene else title!r}, font_size=37, color=fg, weight=BOLD).to_edge(UP, buff=0.82)
        caption = Text({caption!r}, font_size=27, color=warm if {final_scene!r} else fg)
        if caption.width > 5.6:
            caption.scale(5.6 / caption.width)
        caption.next_to(title, DOWN, buff=0.24)

        center = ORIGIN + DOWN * 0.25
        atom_specs = [
            ("C", center, 0.46, accent),
            ("O", center + LEFT * 1.75 + UP * 0.95, 0.38, warm),
            ("O", center + RIGHT * 1.75 + UP * 0.95, 0.38, warm),
            ("H", center + LEFT * 1.8 + DOWN * 1.05, 0.31, fg),
            ("H", center + RIGHT * 1.8 + DOWN * 1.05, 0.31, fg),
        ]
        atoms = VGroup()
        for label, pos, radius, color in atom_specs:
            circle = Circle(radius=radius, stroke_color=color, stroke_width=4, fill_color=color, fill_opacity=0.18).move_to(pos)
            text = Text(label, font_size=24, color=fg, weight=BOLD).move_to(circle)
            atoms.add(VGroup(circle, text))
        bonds = VGroup(
            Line(atom_specs[0][1], atom_specs[1][1], color=fg, stroke_width=7),
            Line(atom_specs[0][1], atom_specs[2][1], color=fg, stroke_width=7),
            Line(atom_specs[0][1], atom_specs[3][1], color=fg, stroke_width=5),
            Line(atom_specs[0][1], atom_specs[4][1], color=fg, stroke_width=5),
        )
        molecule = VGroup(bonds, atoms)
        label = Text("bonds store shape", font_size=29, color=warm).to_edge(DOWN, buff=0.84)
        scene_index = {scene_index}
        self.play(FadeIn(title, shift=DOWN * 0.2), FadeIn(caption), run_time=0.5)
        self.play(LaggedStart(*[GrowFromCenter(atom) for atom in atoms], lag_ratio=0.12), run_time=1.0)
        self.play(LaggedStart(*[Create(bond) for bond in bonds], lag_ratio=0.12), FadeIn(label, shift=UP * 0.2), run_time=1.1)
        if scene_index == 0:
            self.play(molecule.animate.rotate(PI / 10), rate_func=there_and_back, run_time=1.2)
        elif scene_index == 1:
            self.play(Indicate(bonds[0], color=warm), Indicate(bonds[1], color=warm), run_time=1.0)
        elif scene_index == 2:
            electron = Dot(color=warm, radius=0.08).move_to(bonds[0].get_start())
            self.play(MoveAlongPath(electron, bonds[0]), MoveAlongPath(Dot(color=warm, radius=0.08).move_to(bonds[1].get_start()), bonds[1]), run_time=1.2)
        else:
            self.play(molecule.animate.scale(1.08), Indicate(label, color=warm), rate_func=there_and_back, run_time=1.1)
        self.play(molecule.animate.rotate(-PI / 12), rate_func=there_and_back, run_time=1.05)
        self.play(Indicate(label, color=warm), run_time=0.75)
        self.wait(2.4)
"""


def _make_short_car_scene_code(
    scene_plan: dict,
    context: NarrativeContext,
    *,
    title: str,
    bg: str,
    fg: str,
    accent: str,
    warm: str,
) -> str:
    scene_index = int(context.scene_index or 0)
    final_scene = _is_final_short_scene(scene_plan, context)
    caption = "what changes after impact?" if final_scene else _short_fallback_lines(scene_plan, context)[0]
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        title = Text({"Your turn" if final_scene else title!r}, font_size=37, color=fg, weight=BOLD).to_edge(UP, buff=0.82)
        caption = Text({caption!r}, font_size=27, color=warm if {final_scene!r} else fg)
        if caption.width > 5.6:
            caption.scale(5.6 / caption.width)
        caption.next_to(title, DOWN, buff=0.24)
        track = Line(LEFT * 3.0 + DOWN * 1.0, RIGHT * 3.0 + DOWN * 1.0, color=fg, stroke_width=5)
        car_body = RoundedRectangle(width=1.35, height=0.55, corner_radius=0.12, stroke_color=accent, stroke_width=3, fill_color=accent, fill_opacity=0.22)
        roof = Polygon(LEFT * 0.38 + UP * 0.28, RIGHT * 0.38 + UP * 0.28, RIGHT * 0.2 + UP * 0.62, LEFT * 0.1 + UP * 0.62, color=accent, fill_color=accent, fill_opacity=0.16)
        wheels = VGroup(Circle(radius=0.13, color=warm, fill_color=warm, fill_opacity=0.8).shift(LEFT * 0.43 + DOWN * 0.32), Circle(radius=0.13, color=warm, fill_color=warm, fill_opacity=0.8).shift(RIGHT * 0.43 + DOWN * 0.32))
        car = VGroup(car_body, roof, wheels).move_to(LEFT * 2.4 + DOWN * 0.52)
        block = Square(side_length=0.72, color=warm, fill_color=warm, fill_opacity=0.16).move_to(RIGHT * 2.25 + DOWN * 0.58)
        velocity = Arrow(car.get_right(), car.get_right() + RIGHT * 0.95, color=warm, buff=0.05, stroke_width=6)
        label = Text("momentum moves", font_size=29, color=warm).to_edge(DOWN, buff=0.84)
        self.play(FadeIn(title, shift=DOWN * 0.2), FadeIn(caption), Create(track), FadeIn(label), run_time=0.65)
        self.play(FadeIn(car, shift=RIGHT * 0.4), FadeIn(block), GrowArrow(velocity), run_time=0.9)
        scene_index = {scene_index}
        if scene_index == 0:
            self.play(car.animate.shift(RIGHT * 1.5), velocity.animate.shift(RIGHT * 1.5), run_time=1.1)
        elif scene_index == 1:
            self.play(car.animate.shift(RIGHT * 2.45), velocity.animate.shift(RIGHT * 2.45), block.animate.shift(RIGHT * 0.35), run_time=1.2)
            self.play(Indicate(block, color=warm), run_time=0.6)
        elif scene_index == 2:
            self.play(car.animate.shift(RIGHT * 2.2), block.animate.shift(RIGHT * 1.2), velocity.animate.scale(0.65).shift(RIGHT * 2.0), run_time=1.25)
        else:
            self.play(car.animate.shift(RIGHT * 1.8), block.animate.shift(RIGHT * 0.8), Indicate(label, color=warm), run_time=1.15)
        self.play(wheels.animate.rotate(TAU), Indicate(label, color=warm), run_time=0.85)
        self.wait(2.5)
"""


def _make_short_generic_motion_scene_code(
    scene_plan: dict,
    context: NarrativeContext,
    *,
    title: str,
    bg: str,
    fg: str,
    accent: str,
    warm: str,
) -> str:
    scene_index = int(context.scene_index or 0)
    final_scene = _is_final_short_scene(scene_plan, context)
    lines = _short_fallback_lines(scene_plan, context)
    caption = lines[0] if lines else "watch the change"
    return f"""from manim import *
import numpy as np

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        title = Text({"Your turn" if final_scene else title!r}, font_size=37, color=fg, weight=BOLD)
        if title.width > 5.7:
            title.scale(5.7 / title.width)
        title.to_edge(UP, buff=0.82)
        caption = Text({caption!r}, font_size=27, color=warm if {final_scene!r} else fg)
        if caption.width > 5.6:
            caption.scale(5.6 / caption.width)
        caption.next_to(title, DOWN, buff=0.24)
        curve = ParametricFunction(lambda t: np.array([2.25 * np.cos(t), 1.05 * np.sin(2 * t) - 0.2, 0]), t_range=[0, TAU], color=accent, stroke_width=5)
        dot = Dot(color=warm, radius=0.1).move_to(curve.get_start())
        cards = VGroup()
        for label in {repr(lines[:3])}:
            text = Text(label, font_size=25, color=fg)
            if text.width > 4.9:
                text.scale(4.9 / text.width)
            box = RoundedRectangle(width=5.4, height=0.72, corner_radius=0.1, stroke_color=accent, stroke_width=2, fill_color=ManimColor("#111824"), fill_opacity=0.6)
            cards.add(VGroup(box, text))
        cards.arrange(DOWN, buff=0.18).to_edge(DOWN, buff=0.62)
        self.play(FadeIn(title, shift=DOWN * 0.2), FadeIn(caption), run_time=0.5)
        self.play(Create(curve), GrowFromCenter(dot), run_time=0.9)
        self.play(MoveAlongPath(dot, curve), LaggedStart(*[FadeIn(card, shift=UP * 0.18) for card in cards], lag_ratio=0.15), run_time=1.8)
        self.play(Indicate(cards[min({scene_index}, len(cards) - 1)], color=warm), run_time=0.75)
        self.play(dot.animate.scale(1.4), rate_func=there_and_back, run_time=0.75)
        self.wait(2.5)
"""


def _make_short_fallback_scene_code(
    scene_plan: dict, context: NarrativeContext
) -> str:
    """Deterministic last-resort scene for strict short-mode reliability."""
    return localize_scene_code(_make_short_fallback_scene_code_raw(scene_plan, context))


def _make_short_fallback_scene_code_raw(
    scene_plan: dict, context: NarrativeContext
) -> str:
    title = _short_fallback_title(scene_plan, context)
    lines = _short_fallback_lines(scene_plan, context)
    bg = context.domain_state.get("background_color", "#0F1117")
    fg = context.domain_state.get("foreground_color", "#F5F7FA")
    accent = context.domain_state.get("accent_color", "#58C4DD")
    warm = context.domain_state.get("secondary_color", "#F2C94C")
    prompt = (context.prompt or "").lower()

    if "dijkstra" in prompt or "shortest path" in prompt or "weighted graph" in prompt:
        return _make_short_dijkstra_scene_code(
            scene_plan, context, title=title, bg=bg, fg=fg, accent=accent, warm=warm
        )
    if "binary search" in prompt or ("sorted" in prompt and "target" in prompt):
        return _make_short_binary_search_scene_code(
            scene_plan, context, title=title, bg=bg, fg=fg, accent=accent, warm=warm
        )
    if any(token in prompt for token in ["molecule", "bond", "atom", "chemical", "chemistry", "hybrid"]):
        return _make_short_molecule_scene_code(
            scene_plan, context, title=title, bg=bg, fg=fg, accent=accent, warm=warm
        )
    if any(token in prompt for token in ["car", "cart", "collision", "momentum", "velocity", "acceleration"]):
        return _make_short_car_scene_code(
            scene_plan, context, title=title, bg=bg, fg=fg, accent=accent, warm=warm
        )
    if "bayes" not in prompt and "false positive" not in prompt and "factor" not in prompt and "prime" not in prompt:
        return _make_short_generic_motion_scene_code(
            scene_plan, context, title=title, bg=bg, fg=fg, accent=accent, warm=warm
        )

    line_literals = ", ".join(repr(line) for line in lines[:3])
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = {bg!r}
        fg = ManimColor({fg!r})
        accent = ManimColor({accent!r})
        warm = ManimColor({warm!r})
        title = Text({title!r}, font_size=40, color=fg, weight=BOLD)
        if title.width > 5.4:
            title.scale(5.4 / title.width)
        title.to_edge(UP, buff=0.95)
        underline = Line(LEFT * 2.55, RIGHT * 2.55, color=accent, stroke_width=3)
        underline.next_to(title, DOWN, buff=0.25)
        panel = RoundedRectangle(
            width=5.8,
            height=6.8,
            corner_radius=0.18,
            stroke_color=accent,
            stroke_width=3,
            fill_color=ManimColor("#111824"),
            fill_opacity=0.55,
        ).move_to(ORIGIN + DOWN * 0.25)
        labels = [{line_literals}]
        rows = VGroup()
        for i, label in enumerate(labels):
            row = RoundedRectangle(
                width=5.0,
                height=1.25,
                corner_radius=0.14,
                stroke_color=accent if i != len(labels) - 1 else warm,
                stroke_width=2.5,
                fill_color=accent if i != len(labels) - 1 else warm,
                fill_opacity=0.08,
            )
            text = Text(label, font_size=35, color=fg if i != len(labels) - 1 else warm)
            if text.width > 4.5:
                text.scale(4.5 / text.width)
            row_group = VGroup(row, text)
            rows.add(row_group)
        rows.arrange(DOWN, buff=0.45).move_to(panel.get_center())
        self.add(title, underline, panel, rows)
        self.wait(1.0)
        self.play(Indicate(rows[-1], color=warm, scale_factor=1.03), run_time=1.0)
        self.wait(7.0)
"""


def _render_short_fallback_scene(
    scene_plan: dict,
    context: NarrativeContext,
    scene_num: int,
    filename: str,
    job_id: str,
    render_resolution: Optional[Tuple[int, int]],
    quality_flag: str,
    fps: int,
    timeout_seconds: Optional[int],
) -> Tuple[Optional[str], bool, str, NarrativeContext]:
    code = _make_short_fallback_scene_code(scene_plan, context)
    video_path, success, error = _render_single_scene(
        code,
        filename,
        job_id,
        scene_num,
        render_resolution,
        quality_flag,
        fps,
        timeout_seconds,
    )
    if not success or not video_path:
        return None, False, error, context
    valid, validation_error = _validate_scene_video(scene_num, video_path)
    if not valid:
        return video_path, False, validation_error, context
    if context.domain_state.get("video_mode") == "short":
        video_path = _pad_scene_to_min_duration(
            video_path,
            float(scene_plan.get("duration_hint") or 0),
            fps=fps,
            scene_num=scene_num,
        )
    new_context = _update_context_from_scene(
        context, code, f"[FALLBACK] {scene_plan.get('description', '')}"
    )
    return video_path, True, "", new_context


def _recover_render_failure(
    scene_plan: dict,
    context: NarrativeContext,
    scene_num: int,
    error_msg: str,
    filename: str,
    job_id: str,
    render_resolution: Optional[Tuple[int, int]] = None,
    quality_flag: str = "-ql",
    fps: int = 30,
    timeout_seconds: Optional[int] = None,
) -> Tuple[Optional[str], bool, str, NarrativeContext]:
    """Retry a failed render once using the targeted scene retry path."""
    try:
        fixed_code, new_context = retry_scene(scene_plan, context, scene_num, error_msg)
        video_path, success, retry_error = _render_single_scene(
            fixed_code,
            filename,
            job_id,
            scene_num,
            render_resolution,
            quality_flag,
            fps,
            timeout_seconds,
        )
        return video_path if success else None, success, retry_error, new_context
    except Exception as e:
        return None, False, str(e), context


def _validate_scene_video(
    scene_num: int,
    video_path: str,
    *,
    mode: str | None = None,
    allow_quality_recovery: bool = False,
) -> Tuple[bool, str]:
    """Run local integrity and severe frame-quality checks for one scene."""
    validation = validate_video_file(video_path)
    if not validation.ok:
        return (
            False,
            f"scene {scene_num} video failed integrity check: {validation.error}",
        )

    quality = analyze_video_frames(video_path, max_frames=4)
    warnings = quality.get("warnings") or []
    if warnings:
        print(f"[STREAM] Scene {scene_num} frame-quality warnings: {warnings}")
    if not quality.get("ok", False) and video_quality_requires_hard_failure(quality):
        return (
            False,
            f"scene {scene_num} failed frame-quality check: {'; '.join(warnings)}",
        )
    if allow_quality_recovery and video_quality_requires_mode_recovery(quality, mode):
        return (
            False,
            f"scene {scene_num} needs mode-aware layout recovery: "
            + "; ".join(warnings or [f"quality score {quality.get('score')}"]),
        )
    return True, ""


def _pad_scene_to_min_duration(
    video_path: str,
    min_duration_seconds: float,
    *,
    fps: int,
    scene_num: int,
) -> str:
    """Clone the final frame when a short beat renders under its planned length."""
    try:
        target = float(min_duration_seconds)
    except (TypeError, ValueError):
        return video_path
    if target <= 0:
        return video_path

    current = probe_media_duration_seconds(video_path)
    if current is None or current + 0.2 >= target:
        return video_path

    pad_by = max(0.0, target - current)
    source = Path(video_path)
    padded = source.with_name(f"{source.stem}_padded.mp4")
    cmd = [
        *_ffmpeg_command(),
        "-y",
        "-i",
        str(source),
        "-vf",
        f"tpad=stop_mode=clone:stop_duration={pad_by:.3f},fps={int(fps or 10)}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(padded),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(60, int(pad_by * 8) + 30),
        )
    except Exception as exc:
        print(f"[STREAM] Scene {scene_num} duration pad skipped: {exc}")
        return video_path

    if result.returncode != 0:
        print(
            f"[STREAM] Scene {scene_num} duration pad failed: "
            f"{(result.stderr or result.stdout)[-300:]}"
        )
        return video_path

    validation = validate_video_file(str(padded), min_duration_seconds=target - 0.2)
    if not validation.ok:
        print(
            f"[STREAM] Scene {scene_num} padded output failed validation: "
            f"{validation.error}"
        )
        return video_path

    print(
        f"[STREAM] Scene {scene_num} padded from {current:.2f}s "
        f"to {validation.duration_seconds or target:.2f}s"
    )
    return str(padded)


def _should_pad_scene_duration(context: NarrativeContext) -> bool:
    return bool(
        context.domain_state.get("video_mode") == "short"
        or context.domain_state.get("duration_padding_enabled")
    )


def _accept_or_recover_scene_render(
    *,
    scene_num: int,
    scene_plan: dict,
    context: NarrativeContext,
    video_path: str,
    success: bool,
    error_msg: str,
    filename: str,
    job_id: str,
    render_resolution: Optional[Tuple[int, int]],
    quality_flag: str,
    fps: int,
    scene_timeout_seconds: Optional[int],
) -> Tuple[Optional[str], bool, str, NarrativeContext]:
    """Validate a scene render and recover once on render or quality failure."""
    mode = str(context.domain_state.get("video_mode") or "").lower()
    recoverable_original_path = ""
    recoverable_original_reason = ""
    if success and video_path:
        valid, validation_error = _validate_scene_video(
            scene_num,
            video_path,
            mode=mode,
            allow_quality_recovery=mode in {"standard", "course", "lecture"},
        )
        if valid:
            if context.domain_state.get("video_mode") == "short":
                quality = analyze_video_frames(video_path, max_frames=4)
                if short_video_quality_requires_fallback(quality):
                    error_msg = (
                        "short scene failed strict phone-quality gate: "
                        + "; ".join(quality.get("warnings") or ["low short score"])
                    )
                    print(f"[STREAM] Scene {scene_num} strict short gate: {error_msg}")
                else:
                    video_path = _pad_scene_to_min_duration(
                        video_path,
                        float(scene_plan.get("duration_hint") or 0),
                        fps=fps,
                        scene_num=scene_num,
                    )
                    return video_path, True, "", context
            else:
                if _should_pad_scene_duration(context):
                    video_path = _pad_scene_to_min_duration(
                        video_path,
                        float(scene_plan.get("duration_hint") or 0),
                        fps=fps,
                        scene_num=scene_num,
                    )
                return video_path, True, "", context
        else:
            if mode in {"standard", "course", "lecture"}:
                original_validation = validate_video_file(video_path)
                if original_validation.ok:
                    original_quality = analyze_video_frames(video_path, max_frames=4)
                    if not video_quality_requires_hard_failure(original_quality):
                        recoverable_original_path = video_path
                        recoverable_original_reason = validation_error
            error_msg = validation_error
        success = False

    recovered_path, recovered_ok, recovered_err, context = _recover_render_failure(
        scene_plan,
        context,
        scene_num,
        error_msg,
        filename,
        job_id,
        render_resolution,
        quality_flag,
        fps,
        scene_timeout_seconds,
    )
    if recovered_ok and recovered_path:
        valid, validation_error = _validate_scene_video(
            scene_num,
            recovered_path,
            mode=mode,
            allow_quality_recovery=False,
        )
        if valid:
            if context.domain_state.get("video_mode") == "short":
                quality = analyze_video_frames(recovered_path, max_frames=4)
                if not short_video_quality_requires_fallback(quality):
                    recovered_path = _pad_scene_to_min_duration(
                        recovered_path,
                        float(scene_plan.get("duration_hint") or 0),
                        fps=fps,
                        scene_num=scene_num,
                    )
                    return recovered_path, True, "", context
                error_msg = (
                    "recovered short scene failed strict phone-quality gate: "
                    + "; ".join(quality.get("warnings") or ["low short score"])
                )
                print(f"[STREAM] Scene {scene_num} strict short gate: {error_msg}")
            else:
                if _should_pad_scene_duration(context):
                    recovered_path = _pad_scene_to_min_duration(
                        recovered_path,
                        float(scene_plan.get("duration_hint") or 0),
                        fps=fps,
                        scene_num=scene_num,
                    )
                return recovered_path, True, "", context
        else:
            error_msg = validation_error
    else:
        error_msg = recovered_err or error_msg

    if recoverable_original_path and mode in {"standard", "course", "lecture"}:
        accepted_path = recoverable_original_path
        if _should_pad_scene_duration(context):
            accepted_path = _pad_scene_to_min_duration(
                accepted_path,
                float(scene_plan.get("duration_hint") or 0),
                fps=fps,
                scene_num=scene_num,
            )
        detail = (
            "accepted original render after failed mode-aware recovery: "
            + (error_msg or recoverable_original_reason)
        )
        scene_plan["_render_recovery_note"] = re.sub(r"\s+", " ", detail).strip()[:260]
        print(f"[STREAM] Scene {scene_num} {scene_plan['_render_recovery_note']}")
        return accepted_path, True, "", context

    if context.domain_state.get("video_mode") == "short":
        fallback_path, fallback_ok, fallback_err, context = _render_short_fallback_scene(
            scene_plan,
            context,
            scene_num,
            filename,
            job_id,
            render_resolution,
            quality_flag,
            fps,
            scene_timeout_seconds,
        )
        if fallback_ok:
            fallback_path = _pad_scene_to_min_duration(
                fallback_path,
                float(scene_plan.get("duration_hint") or 0),
                fps=fps,
                scene_num=scene_num,
            )
            return fallback_path, True, "", context
        return fallback_path, False, fallback_err or error_msg, context
    return None, False, error_msg, context


# ═══════════════════════════════════════════════════════════════════════════════
# PARALLEL RENDER-WHILE-GENERATE
# ═══════════════════════════════════════════════════════════════════════════════


def stream_render_scenes(
    scenes: List[dict],
    job_id: str,
    narrative_context: NarrativeContext,
    filename: str,
    max_scene_retries: int = 2,
    render_resolution: Optional[Tuple[int, int]] = None,
    quality_flag: str = "-ql",
    fps: int = 30,
    scene_timeout_seconds: Optional[int] = None,
) -> Tuple[List[str], NarrativeContext, List[dict], Dict[int, Tuple[str, bool, str]]]:
    """
    Render scenes in parallel while generating the next scene.

    Algorithm:
    1. Generate scene 0
    2. Start rendering scene 0 in background thread
    3. While scene 0 renders, generate scene 1
    4. When scene 0 render completes, start scene 1 render
    5. Continue until all scenes are generated and rendered

    This achieves overlap: scene N is rendering while scene N+1 is being generated.

    Args:
        scenes: List of scene plans from split_plan_into_scenes
        job_id: Job identifier for tracking
        narrative_context: Initial narrative context
        filename: Base filename for output
        max_scene_retries: Max retries per scene

    Returns:
        Tuple of (video_paths, final_context, errors, completed_renders)
    """
    video_paths = []
    errors = []
    context = narrative_context
    # Thread pool for parallel rendering
    render_executor = ThreadPoolExecutor(max_workers=max(1, STREAM_PARALLEL_RENDERS))

    # Track pending renders
    pending_renders = {}  # scene_num -> future
    completed_renders = {}  # scene_num -> (video_path, success, error)

    context.domain_state["total_scenes"] = len(scenes)
    print(f"[STREAM] Starting streaming pipeline for {len(scenes)} scenes")

    for scene_num, scene_plan in enumerate(scenes):
        print(f"[STREAM] === Scene {scene_num + 1}/{len(scenes)} ===")

        # ── Generate this scene ───────────────────────────────────────
        try:
            code, context = generate_scene(
                scene_plan, context, scene_num, max_scene_retries
            )
        except Exception as e:
            print(f"[STREAM] Scene {scene_num} generation failed: {e}")
            # Try retry with error feedback
            if max_scene_retries > 0:
                try:
                    code, context = retry_scene(scene_plan, context, scene_num, str(e))
                    _mark_scene_generation(scene_plan, "llm_retry", e)
                except Exception as retry_err:
                    _mark_scene_generation(scene_plan, "generation_failed", retry_err)
                    errors.append(
                        {
                            "scene": scene_num,
                            "error": str(retry_err),
                            "type": "generation_retry",
                            "initial_error": str(e),
                        }
                    )
                continue
            else:
                _mark_scene_generation(scene_plan, "generation_failed", e)
                errors.append(
                    {"scene": scene_num, "error": str(e), "type": "generation"}
                )
                continue

        # ── Check if previous scene render is done, then start new render ──
        if scene_num > 0 and (scene_num - 1) in pending_renders:
            # Wait for previous scene's render to complete
            prev_future = pending_renders.pop(scene_num - 1)
            try:
                video_path, success, error_msg = prev_future.result(
                    timeout=RENDER_TIMEOUT_SECONDS
                )
                accepted_path, accepted_ok, accepted_err, context = (
                    _accept_or_recover_scene_render(
                        scene_num=scene_num - 1,
                        scene_plan=scenes[scene_num - 1],
                        context=context,
                        video_path=video_path,
                        success=success,
                        error_msg=error_msg,
                        filename=filename,
                        job_id=job_id,
                        render_resolution=render_resolution,
                        quality_flag=quality_flag,
                        fps=fps,
                        scene_timeout_seconds=scene_timeout_seconds,
                    )
                )
                completed_renders[scene_num - 1] = (
                    accepted_path or "",
                    accepted_ok,
                    accepted_err,
                )
                if not accepted_ok:
                    errors.append(
                        {
                            "scene": scene_num - 1,
                            "error": accepted_err,
                            "type": classify_render_error(accepted_err),
                        }
                    )
            except Exception as e:
                errors.append(
                    {"scene": scene_num - 1, "error": str(e), "type": "render_timeout"}
                )

        # ── Start rendering this scene in background ───────────────────
        print(f"[STREAM] Starting render for scene {scene_num} in background")
        future = render_executor.submit(
            _render_single_scene,
            code,
            filename,
            job_id,
            scene_num,
            render_resolution,
            quality_flag,
            fps,
            scene_timeout_seconds,
        )
        pending_renders[scene_num] = future

    # ── Wait for final scene render ─────────────────────────────────────
    for scene_num in list(pending_renders.keys()):
        if scene_num in pending_renders:
            future = pending_renders.pop(scene_num)
            try:
                video_path, success, error_msg = future.result(
                    timeout=RENDER_TIMEOUT_SECONDS
                )
                accepted_path, accepted_ok, accepted_err, context = (
                    _accept_or_recover_scene_render(
                        scene_num=scene_num,
                        scene_plan=scenes[scene_num],
                        context=context,
                        video_path=video_path,
                        success=success,
                        error_msg=error_msg,
                        filename=filename,
                        job_id=job_id,
                        render_resolution=render_resolution,
                        quality_flag=quality_flag,
                        fps=fps,
                        scene_timeout_seconds=scene_timeout_seconds,
                    )
                )
                completed_renders[scene_num] = (
                    accepted_path or "",
                    accepted_ok,
                    accepted_err,
                )
                if not accepted_ok:
                    errors.append(
                        {
                            "scene": scene_num,
                            "error": accepted_err,
                            "type": classify_render_error(accepted_err),
                        }
                    )
            except Exception as e:
                errors.append(
                    {
                        "scene": scene_num,
                        "error": str(e),
                        "type": classify_render_error(str(e)),
                    }
                )

    render_executor.shutdown(wait=True)

    # Build ordered, de-duplicated list of successful scene videos.
    video_paths = []
    for scene_num in sorted(completed_renders.keys()):
        video_path, success, _ = completed_renders[scene_num]
        if success and video_path:
            video_paths.append(video_path)

    print(
        f"[STREAM] Pipeline complete: {len(video_paths)} scenes rendered, {len(errors)} errors"
    )

    return video_paths, context, errors, completed_renders


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE STITCHING
# ═══════════════════════════════════════════════════════════════════════════════


def stitch_scenes(scene_videos: List[str], output: str, fps: int = 30) -> str:
    """
    Concatenate scene videos using ffmpeg.

    Args:
        scene_videos: List of video file paths in order
        output: Output file path

    Returns:
        Path to stitched video
    """
    if not scene_videos:
        raise ValueError("No scene videos to stitch")

    fps = max(1, int(fps or 30))

    if len(scene_videos) == 1:
        # Single scene — just copy
        import shutil

        shutil.copy2(scene_videos[0], output)
        return output

    normalized_dir = Path(
        tempfile.mkdtemp(prefix="nima-stitch-", dir=str(Path(output).parent))
    )
    concat_file = str(normalized_dir / "concat.txt")
    normalized_paths = []

    try:
        for idx, video_path in enumerate(scene_videos):
            source = Path(video_path)
            if not source.exists():
                continue

            normalized_path = normalized_dir / f"clip_{idx:03d}.mp4"
            result = subprocess.run(
                [
                    *_ffmpeg_command(),
                    "-y",
                    "-i",
                    str(source),
                    "-vf",
                    f"scale=trunc(iw/2)*2:trunc(ih/2)*2,fps={fps},format=yuv420p",
                    "-r",
                    str(fps),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-af",
                    "aresample=44100",
                    str(normalized_path),
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0 or not normalized_path.exists():
                raise RuntimeError(
                    f"ffmpeg normalize failed for {source.name}: {result.stderr[-300:]}"
                )
            normalized_paths.append(str(normalized_path))

        if not normalized_paths:
            raise RuntimeError("No normalized scene videos available for stitching")

        with open(concat_file, "w", encoding="utf-8") as f:
            for video_path in normalized_paths:
                safe_path = video_path.replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        result = subprocess.run(
            [
                *_ffmpeg_command(),
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_file,
                "-fflags",
                "+genpts",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-r",
                str(fps),
                output,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-300:]}")

        print(f"[STITCH] Created {output} from {len(scene_videos)} scenes")

    except FileNotFoundError as err:
        raise RuntimeError("ffmpeg not found — install ffmpeg to use scene stitching") from err
    finally:
        for normalized_path in normalized_paths:
            path = Path(normalized_path)
            if path.exists():
                path.unlink()
        if Path(concat_file).exists():
            Path(concat_file).unlink()
        if normalized_dir.exists():
            normalized_dir.rmdir()

    return output


# ═══════════════════════════════════════════════════════════════════════════════
# TOKEN BUDGET ESTIMATION
# ═══════════════════════════════════════════════════════════════════════════════


def estimate_scene_cost(scene_plan: dict) -> int:
    """
    Estimate tokens needed for a scene.

    Used for token budget tracking and provider selection.
    Returns estimated token count.
    """
    desc = scene_plan.get("description", "")
    animation_steps = scene_plan.get("animation_steps", [])
    objects = scene_plan.get("objects", [])

    # Rough estimation: ~4 chars per token average
    base_tokens = len(desc) // 4
    step_tokens = sum(len(str(s)) // 4 for s in animation_steps)
    object_tokens = sum(len(o) // 4 for o in objects)

    # Add overhead for context and system prompt (~500 tokens)
    overhead = 500

    return base_tokens + step_tokens + object_tokens + overhead


def select_provider_for_budget(token_estimate: int) -> str:
    """
    Select appropriate provider based on token budget.

    Higher token estimates need more reliable/slower providers.
    """
    if token_estimate < 500:
        return "zjuapi"  # Fast, good for simple scenes
    elif token_estimate < 1500:
        return "wenwen"  # Balanced
    else:
        return "openai"  # Most reliable for complex scenes
