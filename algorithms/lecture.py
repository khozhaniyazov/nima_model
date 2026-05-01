"""Lecture-mode planning helpers.

Lecture videos are the academic lane: formal, derivation-heavy, and paced like
an instructor building a board argument. They still use scenelets so one bad
long board does not accumulate unreadable stale objects.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any


LECTURE_TARGET_CONTENT_SCENES = 24
LECTURE_TARGET_QUESTIONS = 6
LECTURE_MIN_SCENE_SECONDS = 24
LECTURE_MAX_SCENE_SECONDS = 35

GENERIC_LECTURE_PHRASES = {
    "simple visual setup",
    "main idea",
    "key takeaway",
    "formal details",
    "explain the concept",
    "introduce the concept",
    "show a title",
    "summary",
    "take a moment to think about it",
    "thorough derivation",
}

ACADEMIC_MOTION_WORDS = {
    "derive",
    "prove",
    "transform",
    "trace",
    "highlight",
    "compare",
    "reveal",
    "draw",
    "plot",
    "update",
    "substitute",
    "isolate",
    "evaluate",
    "annotate",
    "step",
    "connect",
    "map",
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
        r"\b(?:for|about|on|explaining|explain|teaching|teach|lecture\s+about)\s+(.+?)"
        r"(?:\s+using\b|\s+with\b|\s+via\b|\s+through\b|[.,;:]|$)",
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
        re.search(
            r"\b(lecture|course|lesson|video|minute|minutes|teach|teaching|"
            r"academic|derivation|proof)\b",
            topic,
            re.I,
        )
    )
    if prompt_topic and (contaminated or len(topic.split()) > 8):
        topic = prompt_topic
    topic = re.sub(
        r"\b(make|create|explain|explaining|teach|teaching|lecture|course|"
        r"lesson|video|minutes?|animation)\b",
        "",
        topic,
        flags=re.I,
    )
    return _clean_text(topic).strip(" .,:;-") or "the concept"


def _raw_plan_segments(plan_data: dict) -> list[dict]:
    for key in ("segments", "scenes", "beats"):
        items = [item for item in plan_data.get(key, []) if isinstance(item, dict)]
        if items:
            return items
    return []


def _has_academic_motion(segment: dict) -> bool:
    blob = _text_blob(
        [
            segment.get("visual_description"),
            segment.get("animation"),
            segment.get("animation_steps"),
            segment.get("description"),
            segment.get("required_motions"),
            segment.get("lecture_directives"),
        ]
    )
    return sum(1 for word in ACADEMIC_MOTION_WORDS if word in blob) >= 2


def _looks_generic(segment: dict) -> bool:
    blob = _text_blob(segment)
    return any(phrase in blob for phrase in GENERIC_LECTURE_PHRASES)


def _section_count(segments: list[dict]) -> int:
    sections = {
        _clean_text(seg.get("lecture_section") or seg.get("section")).lower()
        for seg in segments
        if _clean_text(seg.get("lecture_section") or seg.get("section"))
    }
    if sections:
        return len(sections)

    titles = " ".join(_clean_text(seg.get("title")) for seg in segments).lower()
    return sum(
        1
        for marker in ("definition", "theorem", "proof", "example", "application")
        if marker in titles
    )


def lecture_plan_is_thin(plan_data: dict) -> bool:
    segments = _raw_plan_segments(plan_data)
    if len(segments) < 18:
        return True

    content = [seg for seg in segments if seg.get("type") != "question"]
    questions = [seg for seg in segments if seg.get("type") == "question"]
    if len(content) < 14:
        return True
    if not (4 <= len(questions) <= 12):
        return True

    motionful = sum(1 for seg in content if _has_academic_motion(seg))
    generic = sum(1 for seg in content if _looks_generic(seg))
    sections = _section_count(segments)
    return (
        motionful < max(9, len(content) // 2)
        or generic >= 5
        or sections < 4
    )


def _content_blueprint(topic: str, content_duration: int) -> list[dict]:
    common_directives = [
        "Use a lecture board style: section label, equation ladder, proof map, or diagram ledger.",
        "Build one formal step at a time; do not accumulate a full unreadable board.",
        "Use focus_transition or focus plates when new derivation lines appear over old board context.",
        "Keep notation sparse and readable; attach symbols to the diagram or equation step that uses them.",
        "Use font_size >= 24 for every label and equation line; never shrink proof groups below readability.",
        "Keep the active derivation board below the top title band and inside width 10.8, height 5.3.",
        "Keep at most five active proof lines visible; move older lines into a dim proof map instead of stacking them.",
    ]

    specs = [
        ("Lecture Map", "Section 1 - Roadmap", "roadmap", f"State the academic goal of the lecture on {topic}.", "Build a theorem/example/proof/application roadmap.", "identify the lecture path", ["roadmap", "section markers", "goal statement"], ["draw roadmap", "mark proof destination", "connect sections"]),
        ("Notation Contract", "Section 1 - Roadmap", "notation", f"Define the notation that will be used for {topic}.", "Introduce only the symbols needed for the first derivation and pin them to a small legend.", "read the notation", ["notation legend", "symbol anchors", "first example"], ["reveal symbols", "attach to example", "dim unused terms"]),
        ("Motivating Counterexample", "Section 1 - Roadmap", "motivation", f"Show why {topic} needs a formal argument.", "Animate a naive argument failing and leave a question mark over the broken step.", "see the gap", ["naive argument", "gap marker", "counterexample"], ["run naive argument", "mark invalid step", "freeze gap"]),
        ("Formal Statement", "Section 2 - Statement", "definition", f"Write the formal statement for {topic}.", "Reveal the statement in clauses, each clause tied to a visual object.", "parse the statement", ["statement clauses", "object labels", "condition markers"], ["reveal clauses", "map clauses", "highlight assumptions"]),
        ("Assumption Audit", "Section 2 - Statement", "assumption", f"Separate assumptions from conclusions in {topic}.", "Move assumptions to the left ledger and conclusions to the right target box.", "separate assumptions and conclusions", ["assumption ledger", "target box", "arrows"], ["sort clauses", "draw implication arrow", "highlight target"]),
        ("Definition Expansion", "Section 2 - Statement", "definition", f"Expand the definition needed for {topic}.", "Unfold the definition into two or three usable tests, not a paragraph.", "use the definition", ["definition box", "usable tests", "check marks"], ["unfold definition", "apply tests", "mark usable form"]),
        ("Lemma Preview", "Section 3 - Proof Machinery", "lemma", f"Preview the first lemma that supports {topic}.", "Show where the lemma plugs into the proof map before proving it.", "know why the lemma matters", ["proof map", "lemma tile", "plug-in arrow"], ["place lemma", "connect proof map", "dim future steps"]),
        ("Lemma Proof Step 1", "Section 3 - Proof Machinery", "proof", f"Prove the first move in the lemma for {topic}.", "Derive one line from the assumptions and put a plate behind the active line.", "follow the first proof move", ["equation ladder", "active line", "assumption tag"], ["copy assumption", "transform line", "tag justification"]),
        ("Lemma Proof Step 2", "Section 3 - Proof Machinery", "proof", f"Complete the lemma used in {topic}.", "Transform the active line into the lemma conclusion and fill the lemma tile.", "finish the lemma", ["equation ladder", "lemma conclusion", "filled tile"], ["transform active line", "highlight conclusion", "fill lemma tile"]),
        ("Bridge Back", "Section 3 - Proof Machinery", "bridge", f"Connect the lemma back to the main claim about {topic}.", "Move the filled lemma tile into the main proof map.", "connect lemma to theorem", ["filled lemma", "main proof map", "bridge arrow"], ["move lemma", "draw bridge", "activate main claim"]),
        ("Main Proof Step 1", "Section 4 - Main Proof", "proof", f"Start the main proof of {topic}.", "Show the first implication step with assumptions dimmed as background context.", "begin the proof", ["proof line", "assumption context", "justification note"], ["activate assumption", "derive line", "add justification"]),
        ("Main Proof Step 2", "Section 4 - Main Proof", "proof", f"Advance the proof of {topic} using the lemma.", "Insert the lemma result into the active derivation line.", "use the lemma correctly", ["lemma tile", "active derivation", "substitution arrow"], ["bring lemma tile", "substitute result", "update derivation"]),
        ("Main Proof Step 3", "Section 4 - Main Proof", "proof", f"Resolve the central equality or implication in {topic}.", "Transform the equation ladder until the target expression is visible.", "resolve the core step", ["equation ladder", "target expression", "focus plate"], ["transform ladder", "highlight target", "dim old lines"]),
        ("Proof Closure", "Section 4 - Main Proof", "proof", f"Close the proof of {topic}.", "Check off each assumption used and draw a box around the final result.", "understand proof closure", ["assumption checklist", "final result", "proof box"], ["check assumptions", "box result", "connect to statement"]),
        ("Worked Example Setup", "Section 5 - Worked Example", "example", f"Prepare a concrete worked example for {topic}.", "Instantiate the symbols from the theorem with concrete values or objects.", "set up an example", ["example objects", "symbol substitution", "value table"], ["instantiate symbols", "fill table", "connect to theorem"]),
        ("Worked Example Run", "Section 5 - Worked Example", "example", f"Run the worked example for {topic}.", "Step through the same proof logic with concrete values.", "execute the example", ["example ledger", "active calculation", "theorem reference"], ["step calculation", "compare to theorem", "update result"]),
        ("Example Interpretation", "Section 5 - Worked Example", "interpretation", f"Interpret the worked example for {topic}.", "Translate the final calculation back into the original visual or problem setting.", "interpret the result", ["final value", "original diagram", "interpretation arrow"], ["move result", "attach to diagram", "state meaning visually"]),
        ("Common False Proof", "Section 6 - Pitfalls", "pitfall", f"Show a tempting false proof of {topic}.", "Run the invalid proof quickly and mark the exact illegal step.", "detect false proofs", ["false proof ladder", "illegal step marker", "warning tag"], ["run false proof", "mark illegal step", "cross out line"]),
        ("Repair The False Step", "Section 6 - Pitfalls", "repair", f"Repair the false proof step in {topic}.", "Replace the illegal step with the valid lemma or missing assumption.", "repair the argument", ["repair patch", "valid lemma", "corrected line"], ["replace illegal step", "insert lemma", "reconnect proof"]),
        ("Boundary Case", "Section 6 - Pitfalls", "edge case", f"Check a boundary case for {topic}.", "Push the assumptions to their boundary and show whether the conclusion survives.", "handle boundaries", ["boundary slider", "assumption meter", "conclusion status"], ["move boundary", "test conclusion", "mark status"]),
        ("Generalization", "Section 7 - Extensions", "generalization", f"Show what changes if {topic} is generalized.", "Compare the original statement with a generalized version using aligned clauses.", "see possible extensions", ["original statement", "generalized statement", "clause alignment"], ["align clauses", "highlight changed assumptions", "mark preserved conclusion"]),
        ("Application Map", "Section 7 - Extensions", "application", f"Map {topic} to one application.", "Connect the theorem result to a concrete application diagram without changing the proof.", "transfer the theorem", ["application diagram", "theorem tile", "transfer arrow"], ["place theorem tile", "draw transfer", "activate application"]),
        ("Lecture Recap", "Section 8 - Recap", "recap", f"Recap the proof architecture for {topic}.", "Return to the proof map and light up each completed section.", "remember the architecture", ["proof map", "completed sections", "recap rail"], ["reveal completed map", "pulse sections", "connect sequence"]),
        ("Final Board", "Section 8 - Recap", "takeaway", f"Leave the final academic takeaway for {topic}.", "Show the statement, proof idea, and example meaning as three compact linked cards.", "retain the theorem and method", ["statement card", "proof idea card", "example card"], ["arrange three cards", "link cards", "hold final board"]),
    ]

    blueprint = []
    for idx, (
        title,
        section,
        role,
        description,
        visual,
        objective,
        objects,
        motions,
    ) in enumerate(specs):
        blueprint.append(
            {
                "id": f"lecture_content_{idx}",
                "title": title,
                "lecture_section": section,
                "scene_role": role,
                "description": description,
                "narration": description,
                "visual_description": visual,
                "learning_objective": objective,
                "objects": objects,
                "required_motions": motions,
                "estimated_duration": content_duration,
                "type": "content",
                "lecture_directives": common_directives,
                "forbidden_visuals": [
                    "viral hook",
                    "comment CTA",
                    "text-only title card",
                    "full paragraph proof wall",
                    "uncleared derivation clutter",
                ],
            }
        )
    return blueprint


def _question_segment(topic: str, after_idx: int, question_idx: int, pause_seconds: int) -> dict:
    prompts = [
        f"Which assumption in the current proof of {topic} is doing the most work?",
        f"What line would fail if one assumption behind {topic} were removed?",
        "Can you predict the next derivation step before it appears?",
        f"Where does the lemma enter the proof of {topic}?",
        "Which step in the worked example mirrors the formal proof?",
        "What boundary case would you test before trusting this result?",
    ]
    prompt = prompts[(question_idx - 1) % len(prompts)]
    return {
        "id": f"lecture_checkpoint_{question_idx}",
        "title": f"Lecture Pause {question_idx}",
        "lecture_section": "Thinking Pause",
        "scene_role": "question",
        "description": f"Lecture pause. {prompt} Take a moment to think about it.",
        "narration": f"{prompt} Take a moment to think about it.",
        "visual_description": "Show one academic prompt over a faint proof map and a subtle timer pulse.",
        "learning_objective": "self-check the proof logic",
        "objects": ["question prompt", "faint proof map", "timer pulse"],
        "required_motions": ["fade prior proof map", "pulse timer", "hold question"],
        "estimated_duration": pause_seconds,
        "duration": pause_seconds,
        "type": "question",
        "checkpoint_id": f"lecture_checkpoint_{question_idx}",
        "after_content_index": after_idx,
        "lecture_directives": [
            "Show exactly one academic question.",
            "Keep the prior proof map faint; do not reveal the answer.",
            "Use a subtle timer or progress pulse, not social-media CTA language.",
        ],
        "forbidden_visuals": ["multiple-choice quiz wall", "comment CTA", "answer reveal"],
    }


def build_lecture_segments(
    prompt: str,
    topic: str | None = None,
    duration: int = 900,
    pause_seconds: int = 10,
) -> list[dict]:
    topic = _clean_text(topic) or _topic_from(prompt, {})
    question_total = LECTURE_TARGET_QUESTIONS
    content_duration = max(
        28,
        min(45, (int(duration or 900) - question_total * pause_seconds) // LECTURE_TARGET_CONTENT_SCENES),
    )
    content = _content_blueprint(topic, content_duration)
    question_after = [3, 7, 11, 15, 19, 23]
    questions = {
        after_idx: _question_segment(topic, after_idx, i + 1, pause_seconds)
        for i, after_idx in enumerate(question_after)
    }

    segments: list[dict] = []
    for idx, seg in enumerate(content):
        item = copy.deepcopy(seg)
        item["id"] = f"scene_{len(segments)}"
        segments.append(item)
        if idx in questions:
            q = copy.deepcopy(questions[idx])
            q["id"] = f"scene_{len(segments)}"
            segments.append(q)
    return segments


def _attach_lecture_contract(segment: dict, blueprint: dict, idx: int) -> dict:
    seg = copy.deepcopy(segment)
    bp = blueprint[min(idx, len(blueprint) - 1)]
    seg.setdefault("title", bp.get("title"))
    seg.setdefault("description", seg.get("narration") or bp.get("description"))
    seg.setdefault("narration", seg.get("description") or bp.get("narration"))
    seg.setdefault("visual_description", bp.get("visual_description"))
    raw_duration = _positive_int(
        seg.get("duration") or seg.get("estimated_duration"),
        _positive_int(bp.get("estimated_duration"), 35),
    )
    blueprint_duration = _positive_int(bp.get("estimated_duration"), 35)
    seg["estimated_duration"] = max(
        LECTURE_MIN_SCENE_SECONDS,
        min(max(raw_duration, blueprint_duration), LECTURE_MAX_SCENE_SECONDS),
    )
    seg.setdefault("type", "content")
    seg.setdefault("lecture_section", bp.get("lecture_section"))
    seg.setdefault("scene_role", bp.get("scene_role"))
    seg.setdefault("learning_objective", bp.get("learning_objective"))
    seg.setdefault("objects", bp.get("objects", []))
    seg.setdefault("required_motions", bp.get("required_motions", []))
    seg["lecture_directives"] = list(
        dict.fromkeys([*(seg.get("lecture_directives") or []), *bp.get("lecture_directives", [])])
    )
    forbidden = [*(seg.get("forbidden_visuals") or []), *(bp.get("forbidden_visuals") or [])]
    seg["forbidden_visuals"] = list(dict.fromkeys(forbidden))
    return seg


def _select_lecture_content(raw_segments: list[dict], blueprint: list[dict]) -> list[dict]:
    content = [seg for seg in raw_segments if seg.get("type") != "question"]
    selected = content[:LECTURE_TARGET_CONTENT_SCENES]
    if len(selected) < LECTURE_TARGET_CONTENT_SCENES:
        for bp in blueprint:
            if len(selected) >= LECTURE_TARGET_CONTENT_SCENES:
                break
            selected.append(copy.deepcopy(bp))
    return selected[:LECTURE_TARGET_CONTENT_SCENES]


def upgrade_lecture_plan_data(
    plan_data: dict,
    prompt: str,
    analysis: dict | None,
    profile: Any,
) -> dict:
    """Make lecture mode academic, scenelet-based, and proof-oriented."""
    requested_mode = str(getattr(profile, "mode", "") or "").strip().lower()
    plan_mode = str(plan_data.get("video_mode") or "").strip().lower()
    if requested_mode != "lecture" and plan_mode != "lecture":
        return plan_data

    upgraded = copy.deepcopy(plan_data)
    upgraded["video_mode"] = "lecture"
    upgraded["target_duration"] = int(
        upgraded.get("target_duration") or getattr(profile, "target_duration", 900) or 900
    )
    upgraded["duration_range"] = list(
        upgraded.get("duration_range") or getattr(profile, "duration_range", (900, 900))
    )
    upgraded["min_scenes"] = min(int(getattr(profile, "min_scenes", 15) or 15), 30)
    upgraded["max_scenes"] = min(int(getattr(profile, "max_scenes", 40) or 40), 30)
    upgraded["aspect"] = "16:9"

    topic = _topic_from(prompt, analysis)
    pause_seconds = int((getattr(profile, "questions", {}) or {}).get("pause_seconds", 10))
    blueprint = build_lecture_segments(prompt, topic, upgraded["target_duration"], pause_seconds)
    blueprint_content = [seg for seg in blueprint if seg.get("type") != "question"]

    raw_segments = _raw_plan_segments(upgraded)
    if lecture_plan_is_thin({"segments": raw_segments}):
        segments = blueprint
        strategy = "replaced_thin_plan_with_academic_lecture"
    else:
        selected = _select_lecture_content(raw_segments, blueprint_content)
        content = [
            _attach_lecture_contract(seg, blueprint_content[min(idx, len(blueprint_content) - 1)], idx)
            for idx, seg in enumerate(selected)
        ]
        question_after = [3, 7, 11, 15, 19, 23]
        segments = []
        for idx, seg in enumerate(content):
            item = copy.deepcopy(seg)
            item["id"] = f"scene_{len(segments)}"
            segments.append(item)
            if idx in question_after:
                q = _question_segment(topic, idx, len([s for s in segments if s.get("type") == "question"]) + 1, pause_seconds)
                q["id"] = f"scene_{len(segments)}"
                segments.append(q)
        strategy = "enriched_existing_plan_with_academic_lecture_contract"

    for stale_key in ("scenes", "beats"):
        upgraded.pop(stale_key, None)
    upgraded["segments"] = segments[:30]
    upgraded["lecture_strategy"] = strategy
    upgraded["lecture_contract"] = {
        "format": "academic_lecture",
        "scenelet_duration": "28-45s content, 10s thinking pauses",
        "target_content_scenes": LECTURE_TARGET_CONTENT_SCENES,
        "target_questions": LECTURE_TARGET_QUESTIONS,
        "requires_focus_layering": True,
        "requires_safe_inner_frame": True,
    }
    return upgraded
