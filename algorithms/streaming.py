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
# Imported for two reasons: (a) tests monkeypatch `streaming.retrieve_*` to
# stub RAG retrieval, and (b) `streaming_prompts._retrieve_streaming_rag_context`
# does a lazy `getattr(_streaming, "retrieve_*", ...)` dispatch to observe
# those monkeypatches. Both require the names to exist on this module.
from RAG.RAG_system import retrieve_golden_example, retrieve_patterns  # noqa: F401


# ═══════════════════════════════════════════════════════════════════════════════
# PROVIDER CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Multi-provider streaming LLM configuration
# LLM streaming-provider layer extracted to algorithms.streaming_providers
# in the PR for #11. Re-exported here so tests and call sites still reach
# them via streaming.<name>.
from algorithms.streaming_providers import (  # noqa: E402,F401  (re-export for back-compat)
    PROVIDER_FAILURE_COOLDOWN_SECONDS,
    PROVIDER_PRIORITY,
    PROVIDER_TOTAL_TIMEOUT_SECONDS,
    STREAM_PROVIDER,
    STREAM_PROVIDERS,
    _MAX_TOKEN_PARAM_HINTS,
    _MAX_TOKEN_REJECT_PHRASES,
    _PROVIDER_COOLDOWNS,
    _build_llm_messages,
    _build_stream_system_msg,
    _clear_provider_failure,
    _create_chat_completion,
    _generate_non_streaming,
    _generate_with_provider,
    _generate_with_provider_in_process,
    _generate_with_provider_subprocess,
    _generation_error_is_timeout,
    _is_max_tokens_unsupported_error,
    _mark_provider_failure,
    _partial_scene_content_is_usable,
    _provider_attempt_order,
    _provider_has_credentials,
    _provider_is_cooled_down,
    _provider_max_tokens,
    _provider_request_timeout,
    _select_provider,
    _yield_llm_chunks,
    stream_generate,
)

STREAM_SCENE_TIMEOUT = CONFIG_STREAM_SCENE_TIMEOUT
STREAM_MAX_SCENES = CONFIG_STREAM_MAX_SCENES
STREAM_SCENE_RETRIES = CONFIG_STREAM_SCENE_RETRIES
STREAM_MIN_SCENES = 2  # minimum scenes for long outputs
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


from algorithms.streaming_prompts import (  # noqa: E402,F401  (re-export for back-compat)
    _OVERLAP_PATTERN,
    _build_retry_addendum,
    _classify_retry_error,
    _extract_overlap_pair,
    _surgical_repair_tips,
)

# Per-scene render helpers extracted to algorithms.streaming_render in the
# second PR for #59. Re-exported here so tests and call sites still reach
# them via streaming.<name>.
from algorithms.streaming_render import (  # noqa: E402,F401  (re-export for back-compat)
    _find_scene_video,
    _pad_scene_to_min_duration,
    _render_mode_fallback_scene,
    _render_short_fallback_scene,
    _render_single_scene,
    _should_pad_scene_duration,
    _validate_scene_video,
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

# Scene-prompt + RAG-reference helpers extracted to algorithms.streaming_prompts
# in the PR for #59. Re-exported here so tests and call sites still reach
# them via streaming.<name>.
from algorithms.streaming_prompts import (  # noqa: E402,F401  (re-export for back-compat)
    COURSE_LESSON_RAG_REFERENCE,
    FOCUS_LAYER_RAG_REFERENCE,
    LECTURE_ACADEMIC_RAG_REFERENCE,
    SHORT_VERTICAL_RAG_REFERENCE,
    STANDARD_YOUTUBE_RAG_REFERENCE,
    STREAM_RAG_CONTEXT_CHARS,
    _build_scene_prompt,
    _coerce_scene_terms,
    _mark_scene_generation,
    _retrieve_streaming_rag_context,
    _update_context_from_scene,
    generate_scene_preamble,
)


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
