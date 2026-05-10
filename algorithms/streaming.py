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

# Scene orchestration extracted to algorithms.streaming_orchestration in
# the third PR for #59. Re-exported here so tests and call sites still
# reach them via streaming.<name>.
from algorithms.streaming_orchestration import (  # noqa: E402,F401  (re-export for back-compat)
    _accept_or_recover_scene_render,
    _recover_render_failure,
    estimate_scene_cost,
    generate_scene,
    retry_scene,
    select_provider_for_budget,
    stitch_scenes,
    stream_render_scenes,
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


