"""Short-form video planning helpers.

Shorts need their own contract. A vertical 60 second render should not inherit
lecture pacing, static bullet cards, or vague "explain the concept" scenes.
This module upgrades short plans into dense, motion-first social beats while
keeping the general streaming renderer reusable.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from algorithms.mode_helpers import (
    clean_text as _clean_text,
    has_motion,
    looks_generic,
    text_blob as _text_blob,
)


SHORT_TARGET_SCENES = 5

MOTION_WORDS = {
    "animate",
    "move",
    "moving",
    "pulse",
    "snap",
    "flash",
    "transform",
    "morph",
    "highlight",
    "trace",
    "sweep",
    "slide",
    "shrink",
    "grow",
    "rotate",
    "collide",
    "compress",
    "reveal",
    "fade",
    "draw",
    "create",
    "travel",
    "jump",
    "zoom",
    "thicken",
    "overwrite",
    "drop",
}

GENERIC_SHORT_PHRASES = {
    "simple picture",
    "main idea",
    "feels natural",
    "formal details",
    "quick what-if",
    "what changes and what stays",
    "key takeaway",
    "explain visually",
    "introduce the concept",
}


def _topic_from(prompt: str, analysis: dict | None) -> str:
    analysis = analysis or {}
    topic = (
        analysis.get("topic")
        or analysis.get("concept")
        or analysis.get("subject")
        or prompt
        or "the idea"
    )
    topic = _clean_text(topic)
    topic = re.sub(
        r"\b(viral|tiktok|instagram|reel|short|vertical|social|media|network|video|make|create|explain|explaining)\b",
        "",
        topic,
        flags=re.I,
    )
    topic = _clean_text(topic).strip(" .,:;-")
    return topic or "the idea"


def _segment(
    idx: int,
    *,
    title: str,
    narration: str,
    visual: str,
    seg_type: str,
    duration: int,
    objects: list[str],
    motions: list[str],
    role: str,
) -> dict:
    return {
        "id": f"scene_{idx}",
        "title": title,
        "narration": narration,
        "visual_description": visual,
        "estimated_duration": duration,
        "type": seg_type,
        "scene_role": role,
        "objects": objects,
        "required_motions": motions,
        "short_directives": [
            "Start with visible motion in the first half second.",
            "Use text only as captions or labels; the main explanation must be moving objects.",
            "Show at least three distinct visual changes before the scene ends.",
            "Keep the central diagram alive; transform it instead of replacing it with a text card.",
        ],
        "forbidden_visuals": [
            "static title card",
            "bullet list",
            "paragraph of text",
            "wide lecture layout",
        ],
        "beat_intensity": "high",
    }


def build_short_social_segments(
    prompt: str,
    topic: str | None = None,
    duration: int = 58,
) -> list[dict]:
    """Return five dense short-form beats for common visual domains."""
    text = (prompt or "").lower()
    topic = _clean_text(topic) or _topic_from(prompt, {})
    per_seg = max(9, min(13, int(duration or 58) // SHORT_TARGET_SCENES))

    if "dijkstra" in text or "shortest path" in text or "weighted graph" in text:
        beats = [
            (
                "Hook: the obvious path lies",
                "Two routes look close. Dijkstra wins by refusing to guess.",
                "Open on a vertical weighted graph. Pulse two tempting routes, then snap attention to start node A.",
                "content",
                ["weighted graph", "nodes", "edges", "route"],
                ["pulse two routes", "snap camera focus to node A", "flash competing edge weights"],
                "hook",
            ),
            (
                "Distances go live",
                "Start at A. Zero is locked. Every neighbor gets a temporary price tag.",
                "Glow node A, draw distance badges d(A)=0, d(B)=2, d(C)=5, and make each badge pop as its edge lights up.",
                "content",
                ["start node", "distance badges", "edge weights"],
                ["glow start node", "pop distance badges", "draw highlighted edges"],
                "setup",
            ),
            (
                "Relax the graph",
                "Pick the smallest unlocked number. Relax its edges. If a cheaper route appears, overwrite the label.",
                "Move a bright token from A to B to C. Transform an old distance label into a smaller one while rejected labels shake.",
                "content",
                ["moving token", "unlocked nodes", "distance labels"],
                ["move token along edges", "overwrite a label", "shake rejected labels"],
                "mechanism",
            ),
            (
                "Path reveal",
                "When a node is locked, its number is final. The shortest path appears one edge at a time.",
                "Freeze the distance table, thicken the winning path, and fade losing edges behind the bright route.",
                "content",
                ["distance table", "winning path", "losing edges"],
                ["freeze table", "thicken winning path", "fade losing edges"],
                "payoff",
            ),
            (
                "Your turn",
                "Your turn: if one edge gets cheaper, which node changes first? Type your answer in the comments!",
                "Keep the graph alive, drop one edge weight, and pulse the next candidate nodes as the challenge.",
                "question",
                ["graph", "changed edge", "candidate nodes"],
                ["drop edge weight", "pulse candidate nodes", "hold challenge frame"],
                "challenge",
            ),
        ]
    elif "binary search" in text:
        beats = [
            (
                "Hook: delete half",
                "Binary search feels like cheating: every guess deletes half the world.",
                "Show eight sorted boxes. Smash-cut a search window around all boxes and flash the target.",
                "content",
                ["sorted boxes", "target", "search window"],
                ["flash target", "draw search window", "shake all boxes"],
                "hook",
            ),
            (
                "Middle first",
                "Never start at the edge. Jump to the middle and ask one brutal question.",
                "Drop a pointer onto the middle box, compare target versus middle, then split the row into yes and no halves.",
                "content",
                ["middle pointer", "target", "comparison"],
                ["drop pointer", "flash comparison", "split row"],
                "setup",
            ),
            (
                "Half disappears",
                "If the middle is too small, the entire left side is dead. Not maybe. Dead.",
                "Fade the rejected half to gray, shrink the active window, and keep the target badge glowing.",
                "content",
                ["rejected half", "active window", "target badge"],
                ["fade rejected half", "shrink window", "pulse target badge"],
                "mechanism",
            ),
            (
                "Repeat fast",
                "Do it again. Eight boxes become four, then two, then one.",
                "Animate three rapid window transforms with a counter: 8 to 4 to 2 to 1.",
                "content",
                ["window", "counter", "remaining boxes"],
                ["transform window", "count down", "snap to final box"],
                "payoff",
            ),
            (
                "Your turn",
                "Your turn: target is eleven. Which half survives the first guess? Type your answer in the comments!",
                "Freeze the first midpoint and pulse the two possible halves as the challenge.",
                "question",
                ["midpoint", "left half", "right half"],
                ["freeze midpoint", "pulse possible halves", "hold challenge frame"],
                "challenge",
            ),
        ]
    elif any(
        k in text for k in ["bond", "molecule", "atom", "chemical", "chemistry", "hybrid"]
    ):
        beats = [
            (
                "Hook: atoms snap together",
                "A chemical bond is not a stick. It is shared attraction locking atoms into shape.",
                "Throw atoms into frame, pull them into a molecule, then ignite glowing bond lines.",
                "content",
                ["atoms", "bond lines", "molecule"],
                ["throw atoms into frame", "pull atoms together", "ignite bond lines"],
                "hook",
            ),
            (
                "Electrons choose the shape",
                "Electron clouds repel. That invisible push decides the angle you actually see.",
                "Orbit electron dots around atoms, then push bond arms apart into a visible geometry.",
                "content",
                ["electron dots", "bond arms", "angle"],
                ["orbit electrons", "push bond arms", "open angle label"],
                "setup",
            ),
            (
                "Bond forms",
                "When sharing wins, the bond brightens. When repulsion wins, atoms spread out.",
                "Create a bond line between atoms, thicken it as distance stabilizes, then bounce atoms into equilibrium.",
                "content",
                ["bond line", "atoms", "equilibrium"],
                ["create bond", "thicken bond", "bounce atoms into equilibrium"],
                "mechanism",
            ),
            (
                "Geometry reveal",
                "The molecule is the receipt: bond count, angle, and lone pairs all show up in one shape.",
                "Rotate the finished molecule slightly, label the bond angle, and pulse lone-pair pressure.",
                "content",
                ["molecule", "bond angle", "lone pair"],
                ["rotate molecule", "label angle", "pulse lone pair"],
                "payoff",
            ),
            (
                "Your turn",
                "Your turn: add one lone pair. Does the bond angle open or squeeze? Type your answer in the comments!",
                "Keep the molecule visible and pulse two possible angle outcomes.",
                "question",
                ["molecule", "open angle", "squeezed angle"],
                ["add lone pair", "pulse two angle outcomes", "hold challenge frame"],
                "challenge",
            ),
        ]
    elif any(
        k in text
        for k in ["car", "cart", "collision", "momentum", "velocity", "acceleration"]
    ):
        beats = [
            (
                "Hook: crash math",
                "A collision looks chaotic, but momentum keeps the receipt.",
                "Launch a car across a vertical track toward a block, with a bright velocity arrow attached.",
                "content",
                ["car", "block", "velocity arrow"],
                ["launch car", "stretch velocity arrow", "flash impact target"],
                "hook",
            ),
            (
                "Before impact",
                "Mass times velocity is the number to watch before anything hits.",
                "Scale a momentum arrow as speed increases and show m times v as a compact badge.",
                "content",
                ["momentum arrow", "speed badge", "car"],
                ["scale momentum arrow", "increase speed ticks", "pop m times v badge"],
                "setup",
            ),
            (
                "Impact",
                "At contact, force spikes. Momentum transfers through the collision.",
                "Animate the car hitting the block, compress a spring shape, then flash the contact point.",
                "content",
                ["car", "block", "spring", "contact point"],
                ["collide car and block", "compress spring", "flash contact point"],
                "mechanism",
            ),
            (
                "After impact",
                "The motion changes bodies, but the total momentum has to balance.",
                "Move both objects after collision with shorter arrows and a total-momentum meter.",
                "content",
                ["car", "block", "momentum meter"],
                ["move both objects", "shorten arrows", "balance momentum meter"],
                "payoff",
            ),
            (
                "Your turn",
                "Your turn: double the mass, same speed. What happens after impact? Type your answer in the comments!",
                "Freeze two mass options and pulse the expected outcome as a challenge.",
                "question",
                ["mass options", "outcome arrows", "challenge frame"],
                ["double mass badge", "pulse outcome arrows", "hold challenge frame"],
                "challenge",
            ),
        ]
    else:
        beats = [
            (
                "Hook",
                f"Here is the part of {topic} that people usually miss.",
                "Open with one surprising visual contrast, then zoom into the object that changes.",
                "content",
                ["contrast", "main object", "change marker"],
                ["flash contrast", "zoom into object", "pulse change marker"],
                "hook",
            ),
            (
                "Moving pieces",
                "Track the object that changes. Ignore everything else for three seconds.",
                "Animate the main object moving along a curve while secondary labels fade behind it.",
                "content",
                ["main object", "curve", "secondary labels"],
                ["move object on curve", "fade secondary labels", "trace path"],
                "setup",
            ),
            (
                "Rule",
                "The rule is simple: one input changes, one output reacts, and the pattern repeats.",
                "Transform input and output badges while a bright path traces the relationship.",
                "content",
                ["input badge", "output badge", "relationship path"],
                ["transform input badge", "transform output badge", "trace relationship path"],
                "mechanism",
            ),
            (
                "Payoff",
                "Once you see the pattern, the formula stops being decoration.",
                "Snap the visual pattern into a compact rule card without clearing the moving diagram.",
                "content",
                ["pattern", "rule card", "moving diagram"],
                ["snap pattern into rule", "keep diagram moving", "highlight formula meaning"],
                "payoff",
            ),
            (
                "Your turn",
                "Your turn: change the input. What moves first? Type your answer in the comments!",
                "Keep the final visual alive and pulse two possible next moves.",
                "question",
                ["final visual", "option A", "option B"],
                ["change input", "pulse two options", "hold challenge frame"],
                "challenge",
            ),
        ]

    return [
        _segment(
            idx,
            title=title,
            narration=narration,
            visual=visual,
            seg_type=seg_type,
            duration=per_seg,
            objects=objects,
            motions=motions,
            role=role,
        )
        for idx, (title, narration, visual, seg_type, objects, motions, role) in enumerate(
            beats
        )
    ]


_SHORT_MOTION_FIELDS = (
    "visual_description",
    "animation",
    "animation_steps",
    "beats",
    "description",
)


def _has_motion_language(segment: dict) -> bool:
    return has_motion(segment, fields=_SHORT_MOTION_FIELDS, words=MOTION_WORDS)


def _looks_generic(segment: dict) -> bool:
    return looks_generic(segment, GENERIC_SHORT_PHRASES)


def _select_short_segments(raw_segments: list[dict], social_segments: list[dict]) -> list[dict]:
    if not raw_segments:
        return copy.deepcopy(social_segments)

    question_segments = [seg for seg in raw_segments if seg.get("type") == "question"]
    content_segments = [seg for seg in raw_segments if seg.get("type") != "question"]
    selected = content_segments[: SHORT_TARGET_SCENES - 1]
    if question_segments:
        selected.append(question_segments[-1])
    else:
        selected.append(copy.deepcopy(social_segments[-1]))

    if len(selected) < SHORT_TARGET_SCENES:
        fillers = copy.deepcopy(social_segments)
        for filler in fillers:
            if len(selected) >= SHORT_TARGET_SCENES:
                break
            selected.insert(max(0, len(selected) - 1), filler)

    return selected[:SHORT_TARGET_SCENES]


def short_plan_is_visually_thin(plan_data: dict) -> bool:
    """Heuristic signal for static/generic short plans."""
    segments = [seg for seg in plan_data.get("segments", []) if isinstance(seg, dict)]
    if len(segments) < 4:
        return True

    content = [seg for seg in segments if seg.get("type") != "question"]
    if not content:
        return True

    motionful = sum(1 for seg in content if _has_motion_language(seg))
    generic = sum(1 for seg in content if _looks_generic(seg))
    text_only = sum(
        1
        for seg in content
        if "text" in _text_blob(seg) and not _has_motion_language(seg)
    )

    return motionful < max(2, len(content) - 1) or generic >= 2 or text_only >= 2


def _attach_short_contract(segment: dict, blueprint: dict, idx: int) -> dict:
    seg = copy.deepcopy(segment)
    bp = copy.deepcopy(blueprint)

    seg.setdefault("id", f"scene_{idx}")
    seg.setdefault("title", bp.get("title", f"Beat {idx + 1}"))
    seg.setdefault("type", bp.get("type", "content"))
    seg.setdefault("estimated_duration", bp.get("estimated_duration", 11))

    if not _has_motion_language(seg) or _looks_generic(seg):
        seg["visual_description"] = bp["visual_description"]
        if not seg.get("narration"):
            seg["narration"] = bp["narration"]

    seg["scene_role"] = seg.get("scene_role") or bp.get("scene_role")
    seg["objects"] = list(dict.fromkeys([*(seg.get("objects") or []), *bp.get("objects", [])]))
    seg["required_motions"] = list(
        dict.fromkeys([*(seg.get("required_motions") or []), *bp.get("required_motions", [])])
    )[:5]
    seg["short_directives"] = list(
        dict.fromkeys([*(seg.get("short_directives") or []), *bp.get("short_directives", [])])
    )
    seg["forbidden_visuals"] = list(
        dict.fromkeys([*(seg.get("forbidden_visuals") or []), *bp.get("forbidden_visuals", [])])
    )
    seg["beat_intensity"] = "high"
    return seg


def upgrade_short_plan_data(
    plan_data: dict,
    prompt: str,
    analysis: dict | None,
    profile: Any,
) -> dict:
    """Make a short plan motion-first and exactly five social beats."""
    requested_mode = str(getattr(profile, "mode", "") or "").strip().lower()
    plan_mode = str(plan_data.get("video_mode") or "").strip().lower()
    if requested_mode != "short" and plan_mode != "short":
        return plan_data

    upgraded = copy.deepcopy(plan_data)
    upgraded["video_mode"] = "short"
    topic = _topic_from(prompt, analysis)
    duration = int(
        upgraded.get("target_duration")
        or getattr(profile, "target_duration", 58)
        or 58
    )
    social_segments = build_short_social_segments(prompt, topic, duration)

    raw_segments = [
        seg for seg in upgraded.get("segments", []) if isinstance(seg, dict)
    ]
    if short_plan_is_visually_thin({"segments": raw_segments}):
        segments = copy.deepcopy(social_segments)
        strategy = "replaced_thin_plan_with_social_beats"
    else:
        selected = _select_short_segments(raw_segments, social_segments)
        segments = [
            _attach_short_contract(seg, social_segments[min(idx, len(social_segments) - 1)], idx)
            for idx, seg in enumerate(selected)
        ]
        strategy = "enriched_existing_plan_with_motion_contract"

    # The final segment is always the challenge beat.
    if segments:
        segments[-1]["type"] = "question"
        cta = "Type your answer in the comments!"
        narration = _clean_text(segments[-1].get("narration"))
        if cta not in narration:
            narration = narration.rstrip(". ") + f". {cta}" if narration else cta
        segments[-1]["narration"] = narration
        segments[-1]["scene_role"] = "challenge"

    for idx, seg in enumerate(segments):
        seg["id"] = f"scene_{idx}"

    upgraded["segments"] = segments[:SHORT_TARGET_SCENES]
    upgraded["min_scenes"] = SHORT_TARGET_SCENES
    upgraded["max_scenes"] = SHORT_TARGET_SCENES
    upgraded["short_strategy"] = strategy
    upgraded["short_contract"] = {
        "format": "vertical_social_short",
        "pacing": "high_density",
        "motion_first": True,
        "target_scenes": SHORT_TARGET_SCENES,
        "forbid_text_only_scenes": True,
    }
    return upgraded
