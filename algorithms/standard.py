"""Standard-mode planning helpers.

Standard videos are the YouTube-explainer lane: longer than a short, tighter
than a lecture, and built around retention beats. They should keep a recurring
visual anchor, alternate explanation with payoff, and avoid question pauses.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any


STANDARD_TARGET_SCENES = 8
STANDARD_MIN_SCENE_SECONDS = 22
STANDARD_MAX_SCENE_SECONDS = 38

GENERIC_STANDARD_PHRASES = {
    "simple visual setup",
    "main idea",
    "key takeaway",
    "formal details",
    "explain the concept",
    "introduce the concept",
    "show a title",
    "summary",
    "simple picture",
    "concrete situation",
    "what-if scenario",
    "what stays invariant",
    "connecting symbols to geometry",
    "practical rule",
    "let's zoom in",
    "feels natural before any formal details",
}

VISUAL_MOTION_WORDS = {
    "animate",
    "move",
    "transform",
    "trace",
    "highlight",
    "compare",
    "reveal",
    "zoom",
    "morph",
    "build",
    "derive",
    "plot",
    "draw",
    "sweep",
    "slide",
    "simulate",
    "update",
    "collapse",
    "expand",
}


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = int(default)
    return max(1, parsed)


def _text_blob(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True).lower()
    except TypeError:
        return str(value or "").lower()


def _topic_from(prompt: str, analysis: dict | None) -> str:
    analysis = analysis or {}
    prompt_topic = ""
    prompt_match = re.search(
        r"\b(?:for|about|on)\s+(.+?)(?:\s+using\b|\s+with\b|[.,;:]|$)",
        prompt or "",
        flags=re.I,
    )
    if prompt_match:
        prompt_topic = _clean_text(prompt_match.group(1))

    topic = (
        analysis.get("topic")
        or analysis.get("concept")
        or analysis.get("subject")
        or prompt
        or "the concept"
    )
    topic = _clean_text(topic)
    contaminated = bool(
        re.search(r"\b(youtube|explainer|standard|video|minute|moving)\b", topic, re.I)
    )
    if prompt_topic and (contaminated or len(topic.split()) > 7):
        topic = prompt_topic
    topic = re.sub(
        r"\b(make|create|explain|explaining|video|youtube|standard|minutes?|minute|animation)\b",
        "",
        topic,
        flags=re.I,
    )
    return _clean_text(topic).strip(" .,:;-") or "the concept"


def _has_visual_motion(segment: dict) -> bool:
    blob = _text_blob(
        [
            segment.get("visual_description"),
            segment.get("animation"),
            segment.get("animation_steps"),
            segment.get("description"),
        ]
    )
    return sum(1 for word in VISUAL_MOTION_WORDS if word in blob) >= 2


def _looks_generic(segment: dict) -> bool:
    blob = _text_blob(segment)
    return any(phrase in blob for phrase in GENERIC_STANDARD_PHRASES)


def _raw_plan_segments(plan_data: dict) -> list[dict]:
    for key in ("segments", "scenes", "beats"):
        items = [item for item in plan_data.get(key, []) if isinstance(item, dict)]
        if items:
            return items
    return []


def standard_plan_is_thin(plan_data: dict) -> bool:
    segments = _raw_plan_segments(plan_data)
    if len(segments) < 5:
        return True
    content = [seg for seg in segments if seg.get("type") != "question"]
    if len(content) < 5:
        return True
    motionful = sum(1 for seg in content if _has_visual_motion(seg))
    generic = sum(1 for seg in content if _looks_generic(seg))
    questions = sum(1 for seg in segments if seg.get("type") == "question")
    return questions > 0 or motionful < max(3, len(content) // 2) or generic >= 3


def build_standard_youtube_segments(
    prompt: str,
    topic: str | None = None,
    duration: int = 240,
) -> list[dict]:
    """Build a strong 8-chapter YouTube explainer spine."""
    topic = _clean_text(topic) or _topic_from(prompt, {})
    per_seg = max(22, min(36, int(duration or 240) // STANDARD_TARGET_SCENES))

    common_directives = [
        "Use a recurring anchor visual that returns or evolves in this scene.",
        "Use motion, comparison, or transformation as the main explanation layer.",
        "Keep text as labels, captions, equations, or chapter markers; avoid paragraph slides.",
        "End with a small payoff or open loop that naturally leads to the next scene.",
    ]

    beat_specs = [
        (
            "Cold Open",
            f"Start with the surprising failure case or visual paradox behind {topic}.",
            "Show the final-looking result first, mark the part that feels wrong, then rewind into the setup.",
            "hook",
            ["surprising example", "anchor diagram", "mystery marker"],
            ["flash final result", "mark the contradiction", "rewind into setup"],
        ),
        (
            "The Setup",
            f"Define the concrete objects for {topic} without turning it into a lecture.",
            "Build the anchor visual from primitive objects, one piece at a time, with labels attached to the objects.",
            "setup",
            ["anchor diagram", "primitive objects", "labels"],
            ["build primitives", "attach labels", "group the anchor visual"],
        ),
        (
            "Naive Attempt",
            "Try the obvious method first so the viewer has something to beat.",
            "Animate the naive path or calculation, then visibly show where it wastes work or gives the wrong intuition.",
            "tension",
            ["naive path", "wasted work marker", "comparison badge"],
            ["run naive attempt", "highlight waste", "freeze comparison"],
        ),
        (
            "Core Mechanism",
            f"Reveal the mechanism that makes {topic} actually work.",
            "Transform the naive visual into the correct mechanism, preserving positions so the viewer can track what changed.",
            "mechanism",
            ["correct mechanism", "transformed anchor", "change marker"],
            ["transform anchor", "highlight changed part", "trace the mechanism"],
        ),
        (
            "Worked Example",
            "Run a compact example with live numbers or states.",
            "Step through a real example using the anchor visual, updating labels as the objects move.",
            "example",
            ["worked example", "live labels", "state updates"],
            ["step through example", "update labels", "move state marker"],
        ),
        (
            "Pattern Break",
            "Show the common mistake and why the mechanism avoids it.",
            "Split the screen into a wrong path and a correct path, then collapse the wrong path away.",
            "misconception",
            ["wrong path", "correct path", "mistake marker"],
            ["compare paths", "shake wrong path", "collapse wrong path"],
        ),
        (
            "Payoff",
            f"Compress the whole idea of {topic} into one reusable mental model.",
            "Morph the worked example into a reusable rule diagram, keeping the same colors and anchor objects.",
            "payoff",
            ["rule diagram", "anchor colors", "compressed model"],
            ["morph example into rule", "highlight reusable pieces", "show payoff"],
        ),
        (
            "Clean Takeaway",
            "End with the mental model, not a quiz.",
            "Hold the final anchor visual, replay the key transformation quickly, and leave a single takeaway sentence.",
            "takeaway",
            ["final anchor", "key transformation", "takeaway caption"],
            ["replay transformation", "lock final diagram", "fade in takeaway caption"],
        ),
    ]

    return [
        {
            "id": f"scene_{idx}",
            "title": title,
            "narration": narration,
            "visual_description": visual,
            "estimated_duration": per_seg,
            "type": "content",
            "scene_role": role,
            "objects": objects,
            "required_motions": motions,
            "standard_directives": common_directives,
            "retention_hook": role in {"hook", "tension", "misconception", "payoff"},
            "forbidden_visuals": [
                "static bullet slide",
                "text-only chapter card",
                "question pause",
                "lecture chalkboard wall of text",
            ],
        }
        for idx, (title, narration, visual, role, objects, motions) in enumerate(
            beat_specs
        )
    ]


def _select_standard_segments(
    raw_segments: list[dict], blueprint: list[dict]
) -> list[dict]:
    content = [seg for seg in raw_segments if seg.get("type") != "question"]
    selected = content[:STANDARD_TARGET_SCENES]
    if len(selected) < STANDARD_TARGET_SCENES:
        for filler in copy.deepcopy(blueprint):
            if len(selected) >= STANDARD_TARGET_SCENES:
                break
            selected.append(filler)
    return selected[:STANDARD_TARGET_SCENES]


def _attach_standard_contract(segment: dict, blueprint: dict, idx: int) -> dict:
    seg = copy.deepcopy(segment)
    bp = copy.deepcopy(blueprint)

    seg.setdefault("id", f"scene_{idx}")
    seg.setdefault("title", bp.get("title", f"Chapter {idx + 1}"))
    seg["type"] = "content"
    raw_duration = _positive_int(
        seg.get("duration") or seg.get("estimated_duration"),
        _positive_int(bp.get("estimated_duration"), 30),
    )
    blueprint_duration = _positive_int(bp.get("estimated_duration"), 30)
    seg["estimated_duration"] = max(
        STANDARD_MIN_SCENE_SECONDS,
        min(max(raw_duration, blueprint_duration), STANDARD_MAX_SCENE_SECONDS),
    )

    if not _has_visual_motion(seg) or _looks_generic(seg):
        seg["visual_description"] = bp["visual_description"]
        if not seg.get("narration"):
            seg["narration"] = bp["narration"]

    seg["scene_role"] = seg.get("scene_role") or bp.get("scene_role")
    seg["objects"] = list(dict.fromkeys([*(seg.get("objects") or []), *bp.get("objects", [])]))
    seg["required_motions"] = list(
        dict.fromkeys([*(seg.get("required_motions") or []), *bp.get("required_motions", [])])
    )[:5]
    seg["standard_directives"] = list(
        dict.fromkeys([*(seg.get("standard_directives") or []), *bp.get("standard_directives", [])])
    )
    seg["forbidden_visuals"] = list(
        dict.fromkeys([*(seg.get("forbidden_visuals") or []), *bp.get("forbidden_visuals", [])])
    )
    seg["retention_hook"] = bool(seg.get("retention_hook") or bp.get("retention_hook"))
    return seg


def upgrade_standard_plan_data(
    plan_data: dict,
    prompt: str,
    analysis: dict | None,
    profile: Any,
) -> dict:
    """Make standard mode chaptered, visual, and retention-aware."""
    requested_mode = str(getattr(profile, "mode", "") or "").strip().lower()
    plan_mode = str(plan_data.get("video_mode") or "").strip().lower()
    if requested_mode != "standard" and plan_mode != "standard":
        return plan_data

    upgraded = copy.deepcopy(plan_data)
    upgraded["video_mode"] = "standard"
    topic = _topic_from(prompt, analysis)
    duration = int(
        upgraded.get("target_duration")
        or getattr(profile, "target_duration", 240)
        or 240
    )
    blueprint = build_standard_youtube_segments(prompt, topic, duration)
    raw_segments = _raw_plan_segments(upgraded)

    if standard_plan_is_thin({"segments": raw_segments}):
        segments = copy.deepcopy(blueprint)
        strategy = "replaced_thin_plan_with_youtube_chapters"
    else:
        selected = _select_standard_segments(raw_segments, blueprint)
        segments = [
            _attach_standard_contract(seg, blueprint[min(idx, len(blueprint) - 1)], idx)
            for idx, seg in enumerate(selected)
        ]
        strategy = "enriched_existing_plan_with_youtube_contract"

    for idx, seg in enumerate(segments):
        seg["id"] = f"scene_{idx}"
        seg["type"] = "content"

    upgraded["segments"] = segments
    upgraded.pop("scenes", None)
    upgraded.pop("beats", None)
    upgraded["min_scenes"] = STANDARD_TARGET_SCENES
    upgraded["max_scenes"] = max(STANDARD_TARGET_SCENES, int(getattr(profile, "max_scenes", 12)))
    upgraded["standard_strategy"] = strategy
    upgraded["standard_contract"] = {
        "format": "youtube_explainer",
        "target_scenes": STANDARD_TARGET_SCENES,
        "retention_first": True,
        "questions_allowed": False,
        "recurring_anchor_visual": True,
    }
    return upgraded
