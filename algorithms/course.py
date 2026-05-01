"""Course-mode planning helpers.

Course videos are the long-form lesson lane: modular, checkpointed, and built
around durable understanding rather than retention shocks. They need enough
structure to avoid generic filler while still leaving room for worked examples,
practice pauses, and recap transitions.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any


COURSE_TARGET_CONTENT_SCENES = 32
COURSE_TARGET_QUESTIONS = 8
COURSE_MIN_SCENE_SECONDS = 24
COURSE_MAX_SCENE_SECONDS = 35

GENERIC_COURSE_PHRASES = {
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
    "take a moment to think about it",
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
    "step",
    "walk through",
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
        r"\b(?:for|about|on|explaining|explain|teaching|teach|lesson\s+about)\s+(.+?)"
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
            r"\b(course|lesson|video|minute|minutes|teach|teaching|explainer|"
            r"tutorial|curriculum|lecture)\b",
            topic,
            re.I,
        )
    )
    if prompt_topic and (contaminated or len(topic.split()) > 8):
        topic = prompt_topic
    topic = re.sub(
        r"\b(make|create|explain|explaining|teach|teaching|course|lesson|video|"
        r"tutorial|minutes?|animation)\b",
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
            segment.get("required_motions"),
        ]
    )
    return sum(1 for word in VISUAL_MOTION_WORDS if word in blob) >= 2


def _looks_generic(segment: dict) -> bool:
    blob = _text_blob(segment)
    return any(phrase in blob for phrase in GENERIC_COURSE_PHRASES)


def _raw_plan_segments(plan_data: dict) -> list[dict]:
    for key in ("segments", "scenes", "beats"):
        items = [item for item in plan_data.get(key, []) if isinstance(item, dict)]
        if items:
            return items
    return []


def _module_count(segments: list[dict]) -> int:
    modules = {
        _clean_text(seg.get("module")).lower()
        for seg in segments
        if _clean_text(seg.get("module"))
    }
    if modules:
        return len(modules)

    titles = " ".join(_clean_text(seg.get("title")) for seg in segments).lower()
    return sum(
        1
        for marker in ("foundation", "mechanism", "practice", "transfer", "capstone")
        if marker in titles
    )


def course_plan_is_thin(plan_data: dict) -> bool:
    segments = _raw_plan_segments(plan_data)
    if len(segments) < 18:
        return True

    content = [seg for seg in segments if seg.get("type") != "question"]
    questions = [seg for seg in segments if seg.get("type") == "question"]
    if len(content) < 14:
        return True
    if not (6 <= len(questions) <= 14):
        return True

    motionful = sum(1 for seg in content if _has_visual_motion(seg))
    generic = sum(1 for seg in content if _looks_generic(seg))
    modules = _module_count(segments)
    return (
        motionful < max(8, len(content) // 2)
        or generic >= 5
        or modules < 4
    )


def _content_blueprint(topic: str, content_duration: int) -> list[dict]:
    common_directives = [
        "Keep a small progress rail or module label visible so the lesson feels structured.",
        "Use the same anchor visual when possible, extending it instead of restarting from blank slides.",
        "Use definitions, examples, and checks as separate visual layers; avoid paragraph-heavy boards.",
        "When a new idea appears, attach it to a concrete object, state marker, graph, array, or diagram.",
    ]

    specs = [
        (
            "Orientation Map",
            "Module 1 - Orientation",
            "map",
            f"Show what the learner will be able to do with {topic} by the end.",
            "Build a course map with three milestones and a blank final challenge slot.",
            "predict the lesson path",
            ["course map", "milestones", "anchor visual"],
            ["build module map", "highlight final challenge", "connect milestones"],
        ),
        (
            "Prerequisite Check",
            "Module 1 - Orientation",
            "prerequisite",
            f"Surface the tiny prerequisites needed for {topic}, without detouring.",
            "Place prerequisite tiles beside the anchor visual and mark which ones will be used.",
            "know the prerequisites",
            ["prerequisite tiles", "anchor visual", "status marks"],
            ["reveal prerequisite tiles", "mark used ideas", "connect to anchor"],
        ),
        (
            "Concrete Analogy",
            "Module 1 - Orientation",
            "analogy",
            f"Ground {topic} in one concrete situation before formal language appears.",
            "Animate a simple real-world or data-structure analogy that maps to the anchor visual.",
            "connect intuition to the formal object",
            ["concrete object", "mapping arrows", "anchor visual"],
            ["animate analogy", "draw mapping arrows", "merge with anchor"],
        ),
        (
            "Core Vocabulary",
            "Module 2 - Foundations",
            "definition",
            f"Introduce the vocabulary for {topic} as labels attached to moving parts.",
            "Attach short labels to the anchor visual; each label appears only when its object is used.",
            "name the moving parts",
            ["anchor visual", "vocabulary labels", "focus ring"],
            ["attach labels", "pulse focused object", "fade unused labels"],
        ),
        (
            "Vocabulary To Picture",
            "Module 2 - Foundations",
            "symbol-to-picture",
            f"Connect each key word in {topic} to one visible part of the diagram.",
            "Animate terms moving from a compact legend onto the exact objects they name.",
            "translate words into objects",
            ["term legend", "object labels", "anchor visual"],
            ["move terms to objects", "highlight matches", "hide unused terms"],
        ),
        (
            "Definition In Action",
            "Module 2 - Foundations",
            "definition-example",
            f"Turn the definition of {topic} into a small animated action.",
            "Show the definition being tested on one toy example with pass/fail markers.",
            "apply the definition once",
            ["toy example", "test markers", "definition badge"],
            ["run toy example", "mark pass fail", "update badge"],
        ),
        (
            "Non Example",
            "Module 2 - Foundations",
            "non-example",
            f"Show one case that looks like {topic} but violates the definition.",
            "Place a valid case and a near-miss case side by side, then mark the exact failing condition.",
            "separate examples from non-examples",
            ["valid case", "near miss", "failure marker"],
            ["compare cases", "mark failing condition", "fade false match"],
        ),
        (
            "First Micro Example",
            "Module 2 - Foundations",
            "micro-example",
            f"Work through the smallest useful example of {topic}.",
            "Use a compact example with numbered steps and visible state changes.",
            "complete the first example",
            ["small example", "step counter", "state labels"],
            ["step through example", "update state labels", "lock result"],
        ),
        (
            "Mechanism Overview",
            "Module 3 - Mechanism",
            "mechanism-map",
            f"Reveal the mechanism that makes {topic} work.",
            "Transform the foundation visual into a mechanism diagram with inputs, rule, and output.",
            "see the mechanism as a system",
            ["input", "rule box", "output", "anchor visual"],
            ["transform to mechanism", "move input through rule", "reveal output"],
        ),
        (
            "Pointer Update Rule",
            "Module 3 - Mechanism",
            "state-update-rule",
            f"Isolate the update rule that drives {topic}.",
            "Show the current state, decision rule, and next state as three connected panels.",
            "perform one state update",
            ["current state", "decision rule", "next state"],
            ["move current to rule", "choose branch", "reveal next state"],
        ),
        (
            "Invariant",
            "Module 3 - Mechanism",
            "invariant",
            f"Identify what must stay true while {topic} is running.",
            "Use a highlighted invariant strip that stays on screen while the other objects change.",
            "track the invariant",
            ["invariant strip", "changing objects", "check marks"],
            ["pin invariant", "change objects", "verify invariant"],
        ),
        (
            "Invariant Stress Test",
            "Module 3 - Mechanism",
            "invariant-test",
            f"Stress-test the invariant behind {topic} with a deliberately tricky state.",
            "Try to break the invariant, then animate why the allowed update keeps it true.",
            "test the invariant under pressure",
            ["tricky state", "invariant strip", "allowed update"],
            ["try to break invariant", "reject bad update", "apply allowed update"],
        ),
        (
            "Worked Example One",
            "Module 3 - Mechanism",
            "worked-example",
            f"Run {topic} through a medium example with live states.",
            "Advance through the example one state at a time; every state update changes the anchor visual.",
            "execute the mechanism",
            ["worked example", "state table", "moving marker"],
            ["advance states", "update table", "move marker"],
        ),
        (
            "Worked Example Replay",
            "Module 3 - Mechanism",
            "worked-example-replay",
            f"Replay the same {topic} example faster so the pattern becomes visible.",
            "Compress the example into a fast pass with each repeated decision color-coded.",
            "see the repeated pattern",
            ["example replay", "decision colors", "state trail"],
            ["replay decisions", "color repeated steps", "draw state trail"],
        ),
        (
            "Why The Step Works",
            "Module 3 - Mechanism",
            "justification",
            f"Explain why the main step in {topic} is valid.",
            "Split the screen into before/rule/after, then animate the rule preserving the invariant.",
            "justify the main step",
            ["before state", "rule bridge", "after state"],
            ["compare before after", "animate rule bridge", "confirm invariant"],
        ),
        (
            "Edge Case",
            "Module 4 - Mistakes",
            "edge-case",
            f"Show the edge case that usually breaks weak understanding of {topic}.",
            "Perturb the example, show the wrong prediction, then correct it with the invariant.",
            "handle an edge case",
            ["edge case", "wrong prediction", "correction marker"],
            ["perturb example", "show wrong prediction", "repair with invariant"],
        ),
        (
            "Boundary Condition",
            "Module 4 - Mistakes",
            "boundary-condition",
            f"Identify the smallest boundary condition that changes how {topic} behaves.",
            "Shrink the example to its smallest non-trivial case and show the boundary decision.",
            "handle the smallest case",
            ["small case", "boundary marker", "decision badge"],
            ["shrink example", "mark boundary", "choose action"],
        ),
        (
            "Mistake Clinic",
            "Module 4 - Mistakes",
            "mistake",
            f"Name the most common mistake people make with {topic}.",
            "Animate a wrong path in red and a correct path in accent color, then collapse the wrong path.",
            "recognize the common mistake",
            ["wrong path", "correct path", "mistake label"],
            ["compare paths", "shake wrong path", "collapse wrong path"],
        ),
        (
            "Mistake Replay",
            "Module 4 - Mistakes",
            "mistake-replay",
            f"Replay the mistake in {topic} and freeze the exact moment it goes wrong.",
            "Run the wrong path quickly, freeze the bad decision, then overlay the repair cue.",
            "spot the failure moment",
            ["wrong replay", "freeze marker", "repair cue"],
            ["replay wrong path", "freeze bad decision", "overlay repair cue"],
        ),
        (
            "Repair Strategy",
            "Module 4 - Mistakes",
            "repair",
            f"Give a repair strategy for debugging {topic}.",
            "Turn the mistake into a checklist that points back to the invariant and worked example.",
            "debug using a checklist",
            ["debug checklist", "invariant strip", "example marker"],
            ["build checklist", "link to invariant", "test checklist"],
        ),
        (
            "Practice Setup",
            "Module 5 - Practice",
            "practice-setup",
            f"Set up a new practice problem for {topic}.",
            "Create a fresh problem state while keeping the same visual vocabulary and progress rail.",
            "set up independent practice",
            ["practice problem", "state markers", "progress rail"],
            ["create practice state", "copy visual vocabulary", "mark unknown"],
        ),
        (
            "Prediction Beat",
            "Module 5 - Practice",
            "prediction",
            f"Pause the practice setup at the decision point for {topic}.",
            "Freeze the current state, pulse the possible next moves, and prepare the reveal.",
            "predict the next move",
            ["frozen state", "possible moves", "reveal slot"],
            ["freeze state", "pulse possible moves", "prepare reveal slot"],
        ),
        (
            "Practice Walkthrough",
            "Module 5 - Practice",
            "practice-walkthrough",
            f"Walk through the practice problem for {topic}.",
            "Let the learner see each decision, then reveal the answer only after the visual evidence appears.",
            "solve the practice problem",
            ["decision path", "evidence markers", "answer badge"],
            ["walk through decisions", "reveal evidence", "show answer"],
        ),
        (
            "Practice Replay",
            "Module 5 - Practice",
            "practice-replay",
            f"Replay the practice solution for {topic} as a compact decision trace.",
            "Turn the solved problem into a trace line that records each decision in order.",
            "remember the solved path",
            ["decision trace", "solved problem", "order labels"],
            ["draw trace line", "stamp order labels", "hold solved path"],
        ),
        (
            "Pattern Generalization",
            "Module 5 - Practice",
            "generalization",
            f"Generalize the pattern behind {topic}.",
            "Morph the practice solution into a reusable template with empty slots.",
            "transfer the pattern",
            ["template", "empty slots", "pattern arrows"],
            ["morph solution", "highlight reusable slots", "connect arrows"],
        ),
        (
            "Template Fill",
            "Module 5 - Practice",
            "template-fill",
            f"Fill the reusable {topic} template with a new tiny input.",
            "Drop new values into the template slots and animate the same route working again.",
            "reuse the template",
            ["template slots", "new values", "route arrows"],
            ["drop values into slots", "run route", "confirm reuse"],
        ),
        (
            "Cost And Tradeoff",
            "Module 6 - Transfer",
            "tradeoff",
            f"Explain the cost, tradeoff, or performance story behind {topic}.",
            "Use a side-by-side comparison of naive versus structured approach with changing counters.",
            "evaluate tradeoffs",
            ["naive counter", "structured counter", "comparison axis"],
            ["animate counters", "compare approaches", "highlight tradeoff"],
        ),
        (
            "Complexity Curve",
            "Module 6 - Transfer",
            "complexity-curve",
            f"Show how the cost of {topic} changes as the input grows.",
            "Animate two small curves or counters diverging as the input size increases.",
            "read the growth pattern",
            ["growth counters", "input slider", "comparison curve"],
            ["increase input", "update counters", "highlight divergence"],
        ),
        (
            "When It Breaks",
            "Module 6 - Transfer",
            "boundary",
            f"Show where {topic} stops being the right tool.",
            "Move the anchor visual outside its assumptions and mark the boundary where the method breaks.",
            "know the boundaries",
            ["assumption boundary", "broken case", "warning marker"],
            ["move outside assumptions", "mark boundary", "show alternative hint"],
        ),
        (
            "Assumption Repair",
            "Module 6 - Transfer",
            "assumption-repair",
            f"Show how to repair the setup before using {topic}.",
            "Move the broken input back inside the assumptions or switch to the right fallback route.",
            "repair prerequisites before applying the method",
            ["broken input", "assumption checklist", "fallback route"],
            ["mark broken input", "repair checklist", "choose fallback route"],
        ),
        (
            "Transfer Example",
            "Module 6 - Transfer",
            "transfer-example",
            f"Apply {topic} to a second context so it does not feel memorized.",
            "Reuse the same template on a new-looking problem and animate the matching pieces.",
            "recognize the idea in a new context",
            ["second context", "template overlay", "matching pieces"],
            ["overlay template", "match pieces", "run transfer"],
        ),
        (
            "Context Swap",
            "Module 6 - Transfer",
            "context-swap",
            f"Swap the surface story while keeping the {topic} structure unchanged.",
            "Replace the original objects with new objects while the template overlay stays fixed.",
            "see through surface changes",
            ["old context", "new context", "fixed template"],
            ["swap objects", "keep template fixed", "match structure"],
        ),
        (
            "Recap Map",
            "Module 7 - Synthesis",
            "recap-map",
            f"Recap {topic} as a map of connected ideas, not a list.",
            "Return to the course map and fill each milestone with the visual built during the lesson.",
            "organize the whole lesson",
            ["course map", "filled milestones", "connection arrows"],
            ["return to map", "fill milestones", "draw connections"],
        ),
        (
            "One Screen Summary",
            "Module 7 - Synthesis",
            "one-screen-summary",
            f"Compress {topic} into a one-screen visual summary.",
            "Arrange the map, invariant, example trace, and checklist as four linked mini-panels.",
            "summarize without losing structure",
            ["map panel", "invariant panel", "trace panel", "checklist panel"],
            ["arrange mini panels", "draw links", "highlight flow"],
        ),
        (
            "Decision Checklist",
            "Module 7 - Synthesis",
            "checklist",
            f"Build a decision checklist for using {topic}.",
            "Animate a compact checklist that routes from problem features to the right action.",
            "choose the right next step",
            ["decision checklist", "routing arrows", "action badges"],
            ["build checklist", "route examples", "highlight action"],
        ),
        (
            "Checklist Test",
            "Module 7 - Synthesis",
            "checklist-test",
            f"Test the {topic} checklist on one last small input.",
            "Route a fresh input through the checklist and mark each decision as it passes.",
            "trust the checklist",
            ["fresh input", "checklist route", "pass marks"],
            ["route fresh input", "mark passed checks", "show action"],
        ),
        (
            "Capstone Example",
            "Module 7 - Synthesis",
            "capstone",
            f"Run one final integrated example for {topic}.",
            "Compress the full lesson into a fast capstone pass with labels appearing only when needed.",
            "integrate the full method",
            ["capstone problem", "full method", "final state"],
            ["run capstone", "flash key labels", "lock final state"],
        ),
        (
            "Final Takeaway",
            "Module 7 - Synthesis",
            "takeaway",
            f"Leave the learner with the mental model for {topic}.",
            "Hold the finished map, replay the core transformation, and show one reusable sentence.",
            "remember the mental model",
            ["finished map", "core transformation", "takeaway sentence"],
            ["replay transformation", "hold finished map", "reveal takeaway"],
        ),
    ]

    return [
        {
            "id": f"content_{idx}",
            "title": title,
            "module": module,
            "narration": narration,
            "visual_description": visual,
            "estimated_duration": content_duration,
            "type": "content",
            "scene_role": role,
            "learning_objective": objective,
            "objects": objects,
            "required_motions": motions,
            "course_directives": common_directives,
            "forbidden_visuals": [
                "static title slide",
                "paragraph wall of text",
                "unrelated decorative scene",
                "quiz before teaching the tested idea",
            ],
        }
        for idx, (
            title,
            module,
            role,
            narration,
            visual,
            objective,
            objects,
            motions,
        ) in enumerate(specs)
    ]


def _question_after(
    content: dict,
    topic: str,
    idx: int,
    pause_seconds: int,
) -> dict:
    focus = content.get("learning_objective") or content.get("title") or topic
    module = content.get("module") or "Checkpoint"
    stems = [
        f"What would fail first if the invariant behind {topic} stopped holding?",
        f"Which part of the current example proves that {topic} is not just memorized?",
        f"If one assumption changed, which step in {topic} would you inspect first?",
        "Can you predict the next state before the method reveals it?",
        "What mistake would produce the wrong answer here, and how would you catch it?",
        "Which visual cue tells you the method is still on track?",
        "How would you explain this checkpoint to someone using one concrete object?",
        "Where would this pattern transfer outside the current example?",
    ]
    stem = stems[idx % len(stems)]
    return {
        "id": f"question_{idx}",
        "title": f"Checkpoint {idx + 1}",
        "module": module,
        "narration": (
            f"Checkpoint. {stem} Take a moment to think about it."
        ),
        "visual_description": (
            f"Display one checkpoint prompt for {focus}. Keep the prior anchor "
            f"visual faintly visible, add two small answer paths, and hold for "
            f"{pause_seconds} seconds with a subtle timer pulse."
        ),
        "estimated_duration": pause_seconds,
        "type": "question",
        "scene_role": "checkpoint",
        "learning_objective": str(focus),
        "checkpoint_id": f"checkpoint_{idx + 1}",
        "objects": ["checkpoint prompt", "two answer paths", "timer pulse"],
        "required_motions": ["pulse timer", "highlight answer paths", "hold thinking pause"],
        "course_directives": [
            "Use exactly one question prompt; do not add a dense paragraph.",
            "Keep the previous anchor visual faintly present for context.",
            "Hold long enough for the planned thinking pause.",
        ],
        "forbidden_visuals": ["multi-question quiz slide", "comment CTA", "answer reveal before pause"],
    }


def build_course_lesson_segments(
    prompt: str,
    topic: str | None = None,
    duration: int = 900,
    *,
    min_questions: int = 8,
    max_questions: int = 14,
    pause_seconds: int = 10,
) -> list[dict]:
    """Build a modular long-form lesson with spaced checkpoints."""
    topic = _clean_text(topic) or _topic_from(prompt, {})
    question_count = max(1, min(COURSE_TARGET_QUESTIONS, max_questions))
    question_count = max(min_questions, question_count)
    question_count = min(question_count, max_questions)
    content_count = COURSE_TARGET_CONTENT_SCENES
    content_seconds = max(24, int(duration or 900) - question_count * pause_seconds)
    per_content = max(24, min(44, content_seconds // content_count))

    contents = _content_blueprint(topic, per_content)[:content_count]
    # Spread questions after taught material, never before the first content scene.
    question_after_indices = [3, 7, 11, 15, 19, 23, 27, 31][:question_count]

    segments: list[dict] = []
    q_idx = 0
    for idx, content in enumerate(contents):
        segments.append(copy.deepcopy(content))
        if idx in question_after_indices:
            segments.append(_question_after(content, topic, q_idx, pause_seconds))
            q_idx += 1

    for idx, seg in enumerate(segments):
        seg["id"] = f"scene_{idx}"
    return segments


def _attach_course_contract(segment: dict, blueprint: dict, idx: int) -> dict:
    seg = copy.deepcopy(segment)
    bp = copy.deepcopy(blueprint)

    seg.setdefault("id", f"scene_{idx}")
    seg.setdefault("title", bp.get("title", f"Lesson Part {idx + 1}"))
    seg["type"] = "content"
    raw_duration = _positive_int(
        seg.get("duration") or seg.get("estimated_duration"),
        _positive_int(bp.get("estimated_duration"), 32),
    )
    blueprint_duration = _positive_int(bp.get("estimated_duration"), 32)
    seg["estimated_duration"] = max(
        COURSE_MIN_SCENE_SECONDS,
        min(max(raw_duration, blueprint_duration), COURSE_MAX_SCENE_SECONDS),
    )

    if not _has_visual_motion(seg) or _looks_generic(seg):
        seg["visual_description"] = bp["visual_description"]
        if not seg.get("narration"):
            seg["narration"] = bp["narration"]

    for key in ("module", "scene_role", "learning_objective"):
        seg[key] = seg.get(key) or bp.get(key)
    seg["objects"] = list(dict.fromkeys([*(seg.get("objects") or []), *bp.get("objects", [])]))
    seg["required_motions"] = list(
        dict.fromkeys([*(seg.get("required_motions") or []), *bp.get("required_motions", [])])
    )[:6]
    seg["course_directives"] = list(
        dict.fromkeys([*(seg.get("course_directives") or []), *bp.get("course_directives", [])])
    )
    seg["forbidden_visuals"] = list(
        dict.fromkeys([*(seg.get("forbidden_visuals") or []), *bp.get("forbidden_visuals", [])])
    )
    return seg


def _select_course_content(raw_segments: list[dict], blueprint: list[dict]) -> list[dict]:
    content = [seg for seg in raw_segments if seg.get("type") != "question"]
    selected = content[:COURSE_TARGET_CONTENT_SCENES]
    if len(selected) < COURSE_TARGET_CONTENT_SCENES:
        for filler in copy.deepcopy(blueprint):
            if len(selected) >= COURSE_TARGET_CONTENT_SCENES:
                break
            selected.append(filler)
    return selected[:COURSE_TARGET_CONTENT_SCENES]


def _with_spaced_questions(
    content_segments: list[dict],
    topic: str,
    pause_seconds: int,
    question_count: int,
) -> list[dict]:
    question_after_indices = [3, 7, 11, 15, 19, 23, 27, 31][:question_count]
    segments: list[dict] = []
    q_idx = 0
    for idx, content in enumerate(content_segments):
        segments.append(content)
        if idx in question_after_indices:
            segments.append(_question_after(content, topic, q_idx, pause_seconds))
            q_idx += 1
    for idx, seg in enumerate(segments):
        seg["id"] = f"scene_{idx}"
    return segments


def upgrade_course_plan_data(
    plan_data: dict,
    prompt: str,
    analysis: dict | None,
    profile: Any,
) -> dict:
    """Make course mode modular, checkpointed, and visually teachable."""
    requested_mode = str(getattr(profile, "mode", "") or "").strip().lower()
    plan_mode = str(plan_data.get("video_mode") or "").strip().lower()
    if requested_mode != "course" and plan_mode != "course":
        return plan_data

    upgraded = copy.deepcopy(plan_data)
    upgraded["video_mode"] = "course"
    topic = _topic_from(prompt, analysis)
    duration = int(
        upgraded.get("target_duration")
        or getattr(profile, "target_duration", 900)
        or 900
    )
    questions = dict(getattr(profile, "questions", {}) or {})
    pause_seconds = _positive_int(questions.get("pause_seconds"), 10)
    min_q = _positive_int(questions.get("min_questions"), 8)
    max_q = _positive_int(questions.get("max_questions"), 14)
    target_q = max(min_q, min(COURSE_TARGET_QUESTIONS, max_q))
    blueprint = build_course_lesson_segments(
        prompt,
        topic,
        duration,
        min_questions=min_q,
        max_questions=max_q,
        pause_seconds=pause_seconds,
    )
    blueprint_content = [seg for seg in blueprint if seg.get("type") != "question"]
    raw_segments = _raw_plan_segments(upgraded)

    if course_plan_is_thin({"segments": raw_segments}):
        segments = copy.deepcopy(blueprint)
        strategy = "replaced_thin_plan_with_course_lesson"
    else:
        selected = _select_course_content(raw_segments, blueprint_content)
        content_segments = [
            _attach_course_contract(
                seg,
                blueprint_content[min(idx, len(blueprint_content) - 1)],
                idx,
            )
            for idx, seg in enumerate(selected)
        ]
        segments = _with_spaced_questions(content_segments, topic, pause_seconds, target_q)
        strategy = "enriched_existing_plan_with_course_contract"

    upgraded["segments"] = segments
    upgraded.pop("scenes", None)
    upgraded.pop("beats", None)
    upgraded["min_scenes"] = max(len(segments), int(getattr(profile, "min_scenes", 25)))
    upgraded["max_scenes"] = max(len(segments), int(getattr(profile, "max_scenes", 40)))
    upgraded["course_strategy"] = strategy
    upgraded["course_contract"] = {
        "format": "modular_course_lesson",
        "target_content_scenes": COURSE_TARGET_CONTENT_SCENES,
        "target_questions": target_q,
        "pause_seconds": pause_seconds,
        "modules_required": True,
        "spaced_checkpoints": True,
        "text_walls_allowed": False,
    }
    return upgraded
