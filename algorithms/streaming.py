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

# FOCUS helper constants live in algorithms.streaming_validation; see
# the re-export block below.


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


# Code post-processing, quality gates and classify_render_error were
# extracted to algorithms.streaming_validation in the PR for #11.
# Re-exported here so tests and internal callers can still reach them
# via streaming.<name>.
from algorithms.streaming_validation import (  # noqa: E402,F401  (re-export for back-compat)
    FOCUS_HELPERS_CODE,
    FOCUS_HELPERS_SENTINEL,
    _enforce_minimum_font_size,
    _estimate_manim_code_duration,
    _extract_manim_code,
    _inject_focus_helpers,
    _iter_call_blocks,
    _parse_first_number,
    _reject_course_instructional_code,
    _reject_known_bad_patterns,
    _reject_layout_hygiene_code,
    _reject_lecture_academic_code,
    _reject_short_duration_code,
    _reject_standard_engagement_code,
    _reject_static_short_code,
    _reject_unbounded_long_text_code,
    _sanitize_generated_code,
    _short_ends_with_full_fadeout,
    _strip_injected_focus_helpers,
    classify_render_error,
)

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


# Deterministic fallback scene generators were extracted to
# algorithms.streaming_fallbacks in the PR for #11. Re-exported here for
# back-compat: tests and internal callers access them via streaming.<name>.
from algorithms.streaming_fallbacks import (  # noqa: E402,F401  (re-export for back-compat)
    _course_fallback_title,
    _factorization_line,
    _is_final_short_scene,
    _lecture_fallback_steps,
    _lecture_fallback_title,
    _make_course_compare_fallback_scene_code,
    _make_course_fallback_scene_code,
    _make_course_fallback_scene_code_raw,
    _make_course_map_fallback_scene_code,
    _make_course_mechanism_fallback_scene_code,
    _make_course_question_fallback_scene_code,
    _make_lecture_fallback_scene_code,
    _make_lecture_fallback_scene_code_raw,
    _make_lecture_question_fallback_scene_code,
    _make_short_binary_search_scene_code,
    _make_short_car_scene_code,
    _make_short_dijkstra_scene_code,
    _make_short_fallback_scene_code,
    _make_short_fallback_scene_code_raw,
    _make_short_generic_motion_scene_code,
    _make_short_molecule_scene_code,
    _make_standard_fallback_ladder_scene_code,
    _make_standard_fallback_linear_scan_scene_code,
    _make_standard_fallback_payoff_scene_code,
    _make_standard_fallback_race_scene_code,
    _make_standard_fallback_scene_code,
    _make_standard_fallback_sorted_order_scene_code,
    _make_standard_fallback_takeaway_scene_code,
    _make_standard_fallback_window_scene_code,
    _safe_text_literal,
    _short_fallback_lines,
    _short_fallback_title,
    _standard_fallback_title,
)


def _render_mode_fallback_scene(
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
    """Last-resort deterministic render for a non-short mode.

    Invoked when the LLM retry itself also fails (hygiene reject, syntax error,
    or render error on the retried code). The deterministic helpers already
    honour ``NIMA_LANGUAGE_LOCK`` via ``localize_scene_code``, so a recovered
    scene still matches the target language.
    """
    mode = str(context.domain_state.get("video_mode") or "").lower()
    if mode == "standard":
        code = _make_standard_fallback_scene_code(scene_plan, context)
    elif mode == "course":
        code = _make_course_fallback_scene_code(scene_plan, context)
    elif mode == "lecture":
        code = _make_lecture_fallback_scene_code(scene_plan, context)
    else:
        return None, False, f"no deterministic fallback for mode {mode!r}", context

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
    valid, validation_error = _validate_scene_video(scene_num, video_path, mode=mode)
    if not valid:
        return video_path, False, validation_error, context
    new_context = _update_context_from_scene(
        context, code, f"[FALLBACK] {scene_plan.get('description', '')}"
    )
    _mark_scene_generation(
        scene_plan,
        f"deterministic_{mode}_fallback_render_recovery",
        None,
    )
    return video_path, True, "", new_context


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

    current_mode = str(context.domain_state.get("video_mode") or "").lower()
    if current_mode == "short":
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
    if current_mode in {"standard", "course", "lecture"}:
        fallback_path, fallback_ok, fallback_err, context = _render_mode_fallback_scene(
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
        if fallback_ok and fallback_path:
            if _should_pad_scene_duration(context):
                fallback_path = _pad_scene_to_min_duration(
                    fallback_path,
                    float(scene_plan.get("duration_hint") or 0),
                    fps=fps,
                    scene_num=scene_num,
                )
            detail = (
                f"accepted deterministic {current_mode} fallback after failed "
                f"mode-aware recovery: " + (error_msg or "unknown")
            )
            scene_plan["_render_recovery_note"] = re.sub(r"\s+", " ", detail).strip()[:260]
            print(f"[STREAM] Scene {scene_num} {scene_plan['_render_recovery_note']}")
            return fallback_path, True, "", context
        return None, False, fallback_err or error_msg, context
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
