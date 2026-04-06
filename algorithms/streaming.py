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

import os
import json
import time
import uuid
import subprocess
import re
import threading
from pathlib import Path
from typing import Iterator, Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

load_dotenv(override=True)

from config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    GENERATION_MODEL,
    FAST_MODEL,
    MANIM_SCRIPTS,
    OUTPUTS,
    RENDER_TIMEOUT_SECONDS,
    MAX_RENDER_RETRIES,
)


# ═══════════════════════════════════════════════════════════════════════════════
# PROVIDER CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Multi-provider streaming LLM configuration
STREAM_PROVIDERS = {
    "zjuapi": {
        "base_url": os.getenv("ZJUBAPI_BASE_URL", "https://ai-cfs.zju.edu.cn"),
        "api_key": os.getenv("ZJUBAPI_API_KEY", ""),
        "model": os.getenv("ZJUBAPI_MODEL", "gpt-5.4"),
        "timeout": 45,
    },
    "wenwen": {
        "base_url": os.getenv("WENWEN_BASE_URL", "https://api.wenwen-ai.com"),
        "api_key": os.getenv("WENWEN_API_KEY", ""),
        "model": os.getenv("WENWEN_MODEL", "claude-opus-4-6"),
        "timeout": 45,
    },
    "openai": {
        "base_url": OPENAI_BASE_URL,
        "api_key": OPENAI_API_KEY,
        "model": GENERATION_MODEL,
        "timeout": 60,
    },
}

# Active provider (auto-select based on availability)
STREAM_PROVIDER = os.getenv("STREAM_PROVIDER", "auto")

# Scene generation settings
STREAM_SCENE_TIMEOUT = 45  # seconds per scene generation
STREAM_MAX_SCENES = 20  # max scenes per video
STREAM_SCENE_RETRIES = 3  # retries per scene on failure
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
}


def choose_visual_template(
    prompt: str, analysis: dict, explicit_template: str | None = None
) -> str:
    """Choose a render template by explicit request, domain, and concept keywords."""
    if explicit_template and explicit_template in VISUAL_TEMPLATES:
        return explicit_template

    text = f"{prompt} {analysis.get('domain', '')}".lower()
    domain = (analysis.get("domain") or "").lower()

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
    if any(
        k in text
        for k in [
            "subgroup",
            "set",
            "bijection",
            "pigeonhole",
            "combinatorics",
            "discrete",
        ]
    ):
        return "light-discrete"
    if domain == "physics":
        return "dark-physics"
    if domain in ("computer_science", "cs"):
        return "light-cs"
    if domain == "math":
        return "dark-blueprint"
    return "dark-blueprint"


def _select_provider() -> str:
    """Auto-select working provider based on availability."""
    if STREAM_PROVIDER != "auto":
        return STREAM_PROVIDER

    # Try providers in priority order
    for provider_name in ["zjuapi", "wenwen", "openai"]:
        cfg = STREAM_PROVIDERS[provider_name]
        if cfg.get("api_key"):
            return provider_name
    return "openai"


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

    # Try to extract scenes from plan structure
    if "scenes" in plan_data:
        raw_scenes = plan_data["scenes"]
    elif "beats" in plan_data:
        # Group beats into scenes (every 2-4 beats = 1 scene)
        beats = plan_data["beats"]
        scene_beats = []
        for i, beat in enumerate(beats):
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
        return scenes
    elif "segments" in plan_data:
        # Voiceover-style segments
        raw_scenes = plan_data["segments"]
    else:
        # Fallback: treat entire plan as one scene
        scenes.append(
            {
                "scene_id": "scene_0",
                "description": plan_data.get("description", "Main scene"),
                "objects": [],
                "duration_hint": plan_data.get("duration", 60),
                "animation_steps": [plan_data.get("plan", str(plan_data))],
            }
        )
        return scenes

    # Process raw scenes
    for i, raw in enumerate(raw_scenes[:max_scenes]):
        scene_id = raw.get("id", f"scene_{i}")
        scenes.append(
            {
                "scene_id": scene_id,
                "description": raw.get("description", raw.get("narration", "")),
                "objects": raw.get("objects", []),
                "duration_hint": raw.get("duration", raw.get("estimated_duration", 10)),
                "animation_steps": raw.get("animation", raw.get("beats", []))
                or [raw.get("visual_description", "")],
            }
        )

    scenes = _ensure_min_scene_count(scenes, plan_data)
    scenes = _dedupe_similar_scenes(scenes)
    return scenes


def _ensure_min_scene_count(scenes: List[dict], plan_data: dict) -> List[dict]:
    """Expand one long scene into 3 chunks for richer outputs."""
    if len(scenes) != 1:
        return scenes

    target_duration = int(plan_data.get("duration", 0) or 0)
    if target_duration < 120:
        return scenes

    scene = scenes[0]
    steps = scene.get("animation_steps", [])
    if not steps:
        steps = [scene.get("description", "")]

    chunk_count = 3
    chunk_size = max(1, len(steps) // chunk_count)
    expanded = []
    for i in range(chunk_count):
        start = i * chunk_size
        end = None if i == chunk_count - 1 else (i + 1) * chunk_size
        chunk_steps = steps[start:end]
        if not chunk_steps:
            continue
        expanded.append(
            {
                "scene_id": f"scene_{i}",
                "description": f"{scene.get('description', 'Scene')} (Part {i + 1}/{chunk_count})",
                "objects": scene.get("objects", []),
                "duration_hint": max(
                    15, int(scene.get("duration_hint", 45) / chunk_count)
                ),
                "animation_steps": chunk_steps,
            }
        )

    return expanded or scenes


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
    """Remove near-duplicate scenes from plan output to avoid repeated segments."""
    if len(scenes) <= 1:
        return scenes

    deduped = []
    seen_tokens: List[set] = []
    for s in scenes:
        desc = s.get("description", "")
        toks = _tokenize_for_similarity(desc)
        is_dup = any(_jaccard(toks, prev) >= threshold for prev in seen_tokens)
        if is_dup:
            continue
        deduped.append(s)
        seen_tokens.append(toks)

    # keep at least 1 scene
    return deduped or scenes[:1]


def _beats_to_scene(scene_id: str, beats: List[dict], plan_data: dict) -> dict:
    """Convert a group of beats into a scene dict."""
    descriptions = [b.get("description", b.get("narration", "")) for b in beats]
    return {
        "scene_id": scene_id,
        "description": " → ".join(descriptions[:2]),  # First two as summary
        "objects": _extract_objects_from_beats(beats),
        "duration_hint": sum(b.get("duration", 5) for b in beats),
        "animation_steps": [
            b.get("animation", b.get("description", "")) for b in beats
        ],
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
    if provider == "auto":
        provider = _select_provider()

    cfg = STREAM_PROVIDERS.get(provider, STREAM_PROVIDERS["openai"])

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            timeout=cfg.get("timeout", 60),
        )

        # Build messages
        messages = [
            {"role": "system", "content": _build_stream_system_msg(context)},
            {"role": "user", "content": prompt},
        ]

        # Use chat completions with streaming
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=messages,
            stream=True,
            max_tokens=3500,
        )

        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    except Exception as e:
        print(f"[STREAM] Provider {provider} failed: {e}")
        # Fallback to non-streaming
        yield from _generate_non_streaming(prompt, context)


def _generate_non_streaming(prompt: str, context: NarrativeContext) -> Iterator[str]:
    """Fallback non-streaming generation."""
    from openai import OpenAI

    provider_cfg = STREAM_PROVIDERS.get(_select_provider(), STREAM_PROVIDERS["openai"])

    client = OpenAI(
        api_key=provider_cfg["api_key"],
        base_url=provider_cfg["base_url"],
        timeout=provider_cfg.get("timeout", 60),
    )

    messages = [
        {"role": "system", "content": _build_stream_system_msg(context)},
        {"role": "user", "content": prompt},
    ]

    try:
        response = client.chat.completions.create(
            model=provider_cfg["model"],
            messages=messages,
            max_tokens=5000,
        )
        content = response.choices[0].message.content or ""
        # Yield in chunks to simulate streaming
        for i in range(0, len(content), 20):
            yield content[i : i + 20]
    except Exception as e:
        print(f"[STREAM] Non-streaming fallback failed: {e}")
        yield ""


def _build_stream_system_msg(context: NarrativeContext) -> str:
    """Build the system message for streaming generation."""
    base = """\
You are an expert Manim CE v0.18 code generator producing single scenes.
You generate ONE scene at a time with full narrative context.

CRITICAL RULES:
1. Return ONLY the complete, runnable Manim Python code. No prose, no markdown.
2. class Scene must be named GeneratedScene with def construct(self)
3. All imports: from manim import *
4. NEVER use: start_section(), begin_section(), end_section() — these don't exist in Manim CE
5. NEVER use: SVGMobject, ImageMobject, or emoji
6. Use MathTex for formulas, not Text
7. Include adequate self.wait() for pacing
8. Clean up objects before scene ends (FadeOut or remove)
9. Return code only — no comments, no explanations
10. NEVER repeat prior scenes or re-introduce already explained concepts unless explicitly asked
11. This is part of a continuous video: avoid hard resets, avoid "intro"/"summary" recaps in middle scenes
12. For scene_index > 0, continue from prior context state and focus only on NEW progression
13. ALL scenes in a job must use the SAME visual theme and SAME background color
14. Default to dark mode unless explicitly told otherwise

"""

    ctx_str = context.to_context_string()
    return base + "\n" + ctx_str


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE GENERATION
# ═══════════════════════════════════════════════════════════════════════════════


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

    scene_desc = scene_plan.get("description", "")
    duration_hint = scene_plan.get("duration_hint", 10)
    animation_steps = scene_plan.get("animation_steps", [])

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

            for token in stream_generate(prompt, context):
                code_chunks.append(token)

            full_code = "".join(code_chunks)
            elapsed = time.time() - start_time

            if not full_code or len(full_code) < 50:
                raise ValueError(
                    f"Empty or very short response ({len(full_code)} chars)"
                )

            # Extract code from markdown if present
            code = _extract_manim_code(full_code)

            # Validate syntax early to force retry before render
            from algorithms.code_digest import validate_python_syntax

            syntax_ok, syntax_err = validate_python_syntax(code)
            if not syntax_ok:
                raise ValueError(f"Syntax error: {syntax_err}")

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

            # Update narrative context with this scene's objects
            context = _update_context_from_scene(context, code, scene_desc)

            return code, context

        except Exception as e:
            last_error = e
            print(f"[STREAM] Scene {scene_num} attempt {attempt} failed: {e}")

            # Add error feedback to context for retry
            if attempt < max_retries:
                context.scene_history.append(f"[RETRY] {scene_desc}: {str(e)[:100]}")

    # All retries failed
    raise RuntimeError(
        f"Scene generation failed after {max_retries} attempts: {last_error}"
    )


def _build_scene_prompt(
    scene_plan: dict, context: NarrativeContext, duration_hint: int
) -> str:
    """Build the generation prompt for a single scene."""
    scene_desc = scene_plan.get("description", "")
    animation_steps = scene_plan.get("animation_steps", [])
    objects = scene_plan.get("objects", [])

    total_scenes = int(context.domain_state.get("total_scenes", 0) or 0)
    current_idx = int(context.scene_index)
    scene_position = (
        f"{current_idx + 1}/{total_scenes}" if total_scenes else str(current_idx + 1)
    )

    preamble_hint = generate_scene_preamble(context, scene_plan)

    prompt = f"""Create Manim CE scene for:

SCENE: {scene_desc}
SCENE POSITION: {scene_position}
DURATION HINT: ~{duration_hint} seconds

ANIMATION STEPS:
"""

    for i, step in enumerate(animation_steps, 1):
        prompt += f"  {i}. {step}\n"

    if objects:
        prompt += f"\nOBJECTS TO ANIMATE: {', '.join(objects)}\n"

    prompt += f"""
DOMAIN: {context.domain}
TARGET TOTAL DURATION: {context.duration_target}s

CONTINUITY REQUIREMENTS (CRITICAL):
- This is scene {scene_position} of one continuous video.
- Do NOT repeat explanation from previous scenes.
- Do NOT restart from introductory framing unless this is scene 1.
- Preserve narrative progression from prior scenes in context.
- Avoid full-screen resets and unnecessary redraw of same objects.

POSSIBLE CARRY-OVER HINTS:
{preamble_hint or "(none)"}

{context.to_context_string()}

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

    retry_prompt = f"""Fix this Manim scene that failed to render:

SCENE: {scene_desc}
DURATION HINT: ~{duration_hint} seconds

RENDER ERROR:
{error}

{context.to_context_string()}

Fix the code to resolve the render error. Return ONLY the corrected Python code.
"""

    code_chunks = []
    for token in stream_generate(retry_prompt, context):
        code_chunks.append(token)

    full_code = "".join(code_chunks)
    code = _extract_manim_code(full_code)

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
) -> Tuple[str, bool, str]:
    """
    Render a single scene's Manim code.

    Returns:
        Tuple of (video_path_or_error, success, error_message)
    """
    from algorithms.code_digest import validate_python_syntax, validate_manim_code

    script_path = MANIM_SCRIPTS / f"{filename}_scene{scene_num}.py"

    # Validate before writing
    syntax_ok, syntax_err = validate_python_syntax(code)
    if not syntax_ok:
        return "", False, f"Syntax error: {syntax_err}"

    # Write script
    with open(script_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(code)

    # Clean old files
    for old_file in OUTPUTS.rglob(f"{filename}_scene{scene_num}*.mp4"):
        try:
            old_file.unlink()
        except OSError:
            pass

    # Build render command
    cmd = [
        "manim",
        str(script_path),
        "GeneratedScene",
        "-ql",  # Low quality for speed during streaming
        "--format=mp4",
        "--media_dir",
        str(OUTPUTS),
        "--output_file",
        f"{filename}_scene{scene_num}.mp4",
        "--disable_caching",
        "--fps",
        "30",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=RENDER_TIMEOUT_SECONDS // 3,  # Per-scene timeout
        )

        if result.returncode == 0:
            # Find video file
            video_path = _find_scene_video(filename, scene_num)
            if video_path and video_path.exists():
                return str(video_path), True, ""
            return "", False, "Render succeeded but video file not found"

        return "", False, result.stderr[-500:]

    except subprocess.TimeoutExpired:
        return "", False, "Render timeout"
    except Exception as e:
        return "", False, str(e)


def _find_scene_video(filename: str, scene_num: int) -> Optional[Path]:
    """Find the rendered video file for a scene."""
    # Check common locations
    patterns = [
        OUTPUTS / f"{filename}_scene{scene_num}.mp4",
        OUTPUTS
        / "videos"
        / f"{filename}_scene{scene_num}"
        / "1080p60"
        / "GeneratedScene.mp4",
        OUTPUTS / "videos" / "1080p60" / "GeneratedScene.mp4",
    ]

    for p in patterns:
        if p.exists():
            return p

    # Glob fallback
    for mp4 in OUTPUTS.rglob(f"{filename}_scene{scene_num}*.mp4"):
        return mp4

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# PARALLEL RENDER-WHILE-GENERATE
# ═══════════════════════════════════════════════════════════════════════════════


def stream_render_scenes(
    scenes: List[dict],
    job_id: str,
    narrative_context: NarrativeContext,
    filename: str,
    max_scene_retries: int = 2,
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
    render_lock = threading.Lock()

    # Thread pool for parallel rendering
    render_executor = ThreadPoolExecutor(max_workers=2)

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
            errors.append({"scene": scene_num, "error": str(e), "type": "generation"})
            # Try retry with error feedback
            if max_scene_retries > 0:
                try:
                    code, context = retry_scene(scene_plan, context, scene_num, str(e))
                except Exception as retry_err:
                    errors.append(
                        {"scene": scene_num, "error": str(retry_err), "type": "retry"}
                    )
                    continue
            else:
                continue

        # ── Check if previous scene render is done, then start new render ──
        if scene_num > 0 and (scene_num - 1) in pending_renders:
            # Wait for previous scene's render to complete
            prev_future = pending_renders[scene_num - 1]
            try:
                video_path, success, error_msg = prev_future.result(
                    timeout=RENDER_TIMEOUT_SECONDS
                )
                completed_renders[scene_num - 1] = (video_path, success, error_msg)

                if not success:
                    errors.append(
                        {"scene": scene_num - 1, "error": error_msg, "type": "render"}
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
        )
        pending_renders[scene_num] = future

    # ── Wait for final scene render ─────────────────────────────────────
    for scene_num in range(len(scenes)):
        if scene_num in pending_renders:
            future = pending_renders[scene_num]
            try:
                video_path, success, error_msg = future.result(
                    timeout=RENDER_TIMEOUT_SECONDS
                )
                completed_renders[scene_num] = (video_path, success, error_msg)

                if not success:
                    errors.append(
                        {"scene": scene_num, "error": error_msg, "type": "render"}
                    )
            except Exception as e:
                errors.append(
                    {"scene": scene_num, "error": str(e), "type": "render_timeout"}
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


def stitch_scenes(scene_videos: List[str], output: str) -> str:
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

    if len(scene_videos) == 1:
        # Single scene — just copy
        import shutil

        shutil.copy2(scene_videos[0], output)
        return output

    # Build ffmpeg concat file
    concat_file = output + ".concat.txt"
    with open(concat_file, "w") as f:
        for video_path in scene_videos:
            if Path(video_path).exists():
                f.write(f"file '{video_path}'\n")

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_file,
                "-c",
                "copy",
                output,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-300:]}")

        print(f"[STITCH] Created {output} from {len(scene_videos)} scenes")

    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found — install ffmpeg to use scene stitching")
    finally:
        # Clean up concat file
        if Path(concat_file).exists():
            Path(concat_file).unlink()

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
