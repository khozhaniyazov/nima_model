"""
Request analysis — classifies a user prompt and creates an animation storyboard.
"""

from openai import OpenAI
import os
import re
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_TIMEOUT,
    GENERATION_MODEL,
    FAST_MODEL,
)
from algorithms.template_registry import TEMPLATES

REQUEST_ANALYSIS_TIMEOUT_SECONDS = max(
    10,
    int(os.getenv("REQUEST_ANALYSIS_TIMEOUT", str(min(int(OPENAI_TIMEOUT or 60), 60)))),
)

client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    timeout=REQUEST_ANALYSIS_TIMEOUT_SECONDS,
)


def _heuristic_analysis_defaults(prompt: str) -> dict:
    text = (prompt or "").lower()
    domain = "math"

    math_markers = [
        "function",
        "functions",
        "domain",
        "range",
        "linear",
        "quadratic",
        "polynomial",
        "algebra",
        "equation",
        "inequality",
        "derivative",
        "integral",
        "slope",
        "y-intercept",
        "trigonometry",
        "geometry",
        "graph interpretation",
    ]
    has_strong_math_signal = any(k in text for k in math_markers)
    if (not has_strong_math_signal) and any(
        k in text
        for k in [
            "algorithm",
            "dijkstra",
            "shortest path",
            "pathfinding",
            "breadth first",
            "depth first",
            "bfs",
            "dfs",
            "graph",
            "tree",
            "queue",
            "stack",
            "dynamic programming",
            "binary",
            "recursion",
            "complexity",
            "sorting",
            "sort",
            "linked list",
            "hash",
            "search",
        ]
    ):
        domain = "computer_science"
    elif any(
        k in text
        for k in [
            "orbital",
            "molecule",
            "atom",
            "chemical",
            "reaction",
            "equilibrium",
            "ph ",
        ]
    ):
        domain = "chemistry"
    elif any(
        k in text
        for k in [
            "wavefunction",
            "entropy",
            "thermodynamics",
            "energy",
            "momentum",
            "electric",
            "field",
            "quantum",
            "velocity",
            "acceleration",
            "force",
            "motion",
            "mechanics",
        ]
    ):
        domain = "physics"
    elif any(
        k in text
        for k in [
            "economics",
            "supply",
            "demand",
            "game theory",
            "prisoner",
            "nash",
            "payoff",
        ]
    ):
        domain = "general"

    tokens = [w.strip(".,()[]{}") for w in text.split() if len(w.strip(".,()[]{}")) > 3]
    # Strip common prompt verbs from topic — these are instructions, not subject matter
    topic_stop_verbs = {
        "explain",
        "teach",
        "show",
        "create",
        "make",
        "generate",
        "build",
        "demonstrate",
        "illustrate",
        "visualize",
        "visualise",
        "describe",
        "animate",
        "present",
        "cover",
        "discuss",
        "introduce",
        "what",
        "how",
        "does",
        "work",
        "works",
        "with",
        "from",
        "into",
        "using",
        "without",
        "worked",
        "example",
        "examples",
        "audience",
        "questions",
        "seconds",
        "second",
        "minute",
        "minutes",
        "vertical",
        "short",
        "viral",
        "social",
        "media",
        "network",
        "tiktok",
        "reel",
        "reels",
        "fast",
        "hook",
        "pacing",
        "sorted",
        "boxes",
        "box",
        "target",
        "number",
        "lesson",
        "full",
        "scratch",
    }
    topic_tokens = [t for t in tokens if t not in topic_stop_verbs]
    topic = " ".join(topic_tokens[:6]) if topic_tokens else (prompt or "concept")[:60]
    subtopics = topic_tokens[:8] if topic_tokens else tokens[:8]

    # ── Estimate duration from prompt breadth ──────────────────────────
    # Count distinct topic-like segments separated by commas / "and"
    # e.g. "motion, velocity, acceleration, forces, momentum, and energy"
    import re as _re

    # Split on commas and " and " to count listed topics
    listed_items = _re.split(r",\s*|\band\b", text)
    listed_items = [s.strip() for s in listed_items if len(s.strip()) > 2]
    topic_count = max(len(listed_items), len(subtopics))

    # Detect breadth signals — words that imply a broad lesson
    breadth_signals = [
        "lesson",
        "course",
        "overview",
        "introduction",
        "introductory",
        "crash course",
        "survey",
        "comprehensive",
        "complete",
        "full",
    ]
    is_broad = any(signal in text for signal in breadth_signals)

    # Scale duration: ~90s per distinct topic, with breadth bonus
    if topic_count >= 6 or is_broad:
        base_duration = min(1200, max(600, topic_count * 90))
        complexity = "ADVANCED" if topic_count >= 8 else "INTERMEDIATE"
        depth = "DEEP" if topic_count >= 8 else "MODERATE"
    elif topic_count >= 4:
        base_duration = min(720, max(420, topic_count * 90))
        complexity = "INTERMEDIATE"
        depth = "MODERATE"
    elif topic_count >= 2:
        base_duration = min(420, max(240, topic_count * 100))
        complexity = "INTERMEDIATE"
        depth = "MODERATE"
    else:
        base_duration = 300
        complexity = "INTERMEDIATE"
        depth = "MODERATE"

    # Bump if breadth signal present but duration is still modest
    if is_broad and base_duration < 480:
        base_duration = 480

    print(
        f"[ANALYZE] Heuristic: topic_count={topic_count}, broad={is_broad}, duration={base_duration}s"
    )

    return {
        "type": "EDUCATIONAL_CONCEPT",
        "complexity": complexity,
        "topic": topic,
        "subtopics": subtopics,
        "duration": base_duration,
        "depth": depth,
        "domain": domain,
        "approach": "visual explanation with concrete examples",
    }


def heuristic_request_analysis(prompt: str) -> dict:
    """Return local request metadata without making any model calls."""
    return _heuristic_analysis_defaults(prompt)


def _fallback_subtopics(prompt: str, domain: str, topic: str) -> list[str]:
    text = (prompt or "").lower()

    phrase_map = [
        ("rock-paper-scissors", "rock-paper-scissors"),
        ("payoff matrix", "payoff matrix"),
        ("nash equilibrium", "nash equilibrium"),
        ("wavefunction", "wavefunction"),
        ("probability amplitudes", "probability amplitudes"),
        ("energy levels", "energy levels"),
        ("transition matrix", "transition matrix"),
        ("central limit theorem", "central limit theorem"),
        ("dynamic programming", "dynamic programming"),
        ("coin change", "coin change"),
        ("open sets", "open sets"),
        ("closed sets", "closed sets"),
        ("metric space", "metric space"),
        ("electron orbitals", "electron orbitals"),
    ]
    found = []
    for needle, label in phrase_map:
        if needle in text and label not in found:
            found.append(label)

    stop = {
        "explain",
        "teach",
        "show",
        "using",
        "with",
        "from",
        "through",
        "what",
        "how",
        "and",
        "the",
        "this",
        "that",
        "into",
        "their",
        "they",
        "them",
        "one",
        "gentle",
        "introduction",
        "visualize",
        "visualise",
        "viral",
        "social",
        "media",
        "network",
        "tiktok",
        "reel",
        "reels",
        "fast",
        "hook",
        "pacing",
        "vertical",
        "short",
    }
    words = [w.strip(".,()[]{}") for w in text.split()]
    words = [w for w in words if len(w) > 3 and w not in stop]
    for w in words:
        if w not in found:
            found.append(w)
        if len(found) >= 6:
            break

    if domain == "general" and "game" in text and "equilibrium" not in found:
        found.append("strategic equilibrium")
    if domain == "physics" and "wavefunction" in text and "orbitals" not in found:
        found.append("orbitals")

    return found[:6] or [topic]


def _build_fallback_segment_narration(
    topic: str,
    subtopic: str,
    index: int,
    total: int,
    video_mode: str = "standard",
) -> str:
    long_form = video_mode in ("course", "lecture")

    if index == 0:
        if long_form:
            return (
                f"Let’s start with an intuitive picture of {topic}. "
                "Imagine a simple real-world situation and focus on the one quantity that changes first. "
                "That quantity will anchor everything we build in the next sections."
            )
        return (
            f"Let’s begin with a simple picture of {topic}. "
            "Think of one concrete situation so the main idea feels natural before any formal details."
        )
    if index == total - 1:
        if long_form:
            return (
                f"Now connect {subtopic} back to the full story of {topic}. "
                "Here is the key principle in plain language, and here is one practical way to apply it in a new problem."
            )
        return (
            f"Now connect {subtopic} back to the main idea of {topic}. "
            "Keep this final relationship in mind, because it is the one you will reuse most often."
        )
    short_templates = [
        (
            f"Let’s zoom in on {subtopic}. "
            f"In one concrete case, compare it with the previous idea so the role of {topic} becomes clearer."
        ),
        (
            f"Now test {subtopic} with a quick what-if scenario. "
            f"Notice what changes and what stays invariant in {topic}."
        ),
        (
            f"Build intuition for {subtopic} by connecting symbols to geometry. "
            f"Then keep one practical rule you can reuse for {topic}."
        ),
    ]

    if not long_form:
        return short_templates[index % len(short_templates)]

    long_templates = [
        (
            f"For {subtopic}, start with a concrete setup and identify the one quantity that drives the behavior. "
            f"As that quantity changes, notice how the outcome shifts, and link that pattern back to {topic}. "
            "A common misconception appears here, so let’s point it out and correct it clearly."
        ),
        (
            f"Think of {subtopic} as a prediction question. "
            "First, make a quick expectation. Then test it with a small numerical check. "
            f"This helps separate what is always true from what only seems true in special cases of {topic}."
        ),
        (
            f"Now view {subtopic} geometrically so the structure is visible before any formula memorization. "
            f"Then translate that picture back into symbols and keep one reusable rule for {topic}."
        ),
        (
            f"Compare two versions of {subtopic}: one correct setup and one subtly incorrect setup. "
            "Watch where the reasoning diverges, then fix it step by step so the difference becomes intuitive."
        ),
        (
            f"Use a real-world analogy for {subtopic}, then map each piece of that analogy to the formal model. "
            f"Some parts transfer perfectly and some do not, and that distinction keeps your intuition for {topic} accurate."
        ),
        (
            f"Let’s do a short worked example for {subtopic}, keeping units and signs explicit. "
            "At each step, focus on why the operation is valid, not only what to compute next."
        ),
        (
            f"Ask yourself a quick diagnostic for {subtopic}: which quantity is fixed, which quantity is changing, and which relationship links them? "
            f"Once that is clear, the logic of {topic} becomes far easier to trust."
        ),
        (
            f"Take {subtopic} and test the limiting case where one input is very small or very large. "
            "That stress test reveals whether your intuition is robust or only working in a narrow range."
        ),
        (
            f"Translate {subtopic} into a graph-first story: describe what bends, shifts, or stays fixed. "
            f"Then map that visual story back to the algebraic statement used in {topic}."
        ),
        (
            f"Use two checkpoints for {subtopic}: a conceptual check in words and a numerical check with simple values. "
            "If both agree, your setup is probably correct; if not, identify where the assumption drifted."
        ),
        (
            f"Connect {subtopic} to an earlier concept and state the bridge explicitly. "
            "This bridge is what prevents fragmented understanding and helps ideas transfer to new problems."
        ),
        (
            f"For {subtopic}, compare the symbolic method and the visual method side by side. "
            "Use whichever is clearer first, then verify with the other so your conclusion is not fragile."
        ),
    ]
    return long_templates[index % len(long_templates)]


_GENERIC_NARRATION_PHRASES = {
    "as you can see": "State the visual takeaway directly instead of narrating the obvious.",
    "let's take a look": "Use a precise transition instead of a generic host phrase.",
    "now let's": "Use a stronger transition with a concrete teaching purpose.",
    "basically": "Replace with the exact claim.",
    "kind of": "Avoid hedging; say what is actually true.",
    "sort of": "Avoid hedging; say what is actually true.",
    "in this video": "Stay inside the lesson flow instead of referring to the medium.",
    "we can see": "Prefer a direct observation or conclusion.",
}


def _clean_narration_text(text: str) -> str:
    """Lightweight cleanup to keep narration direct and less GPT-generic."""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.replace("Let’s", "Let's")
    cleaned = re.sub(r"\bNow let's\b", "Now", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\bLet's take a look at\b", "Consider", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\bAs you can see,?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bWe can see that\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bBasically,?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    return cleaned.strip()


def _truncate_to_sentence_limit(
    text: str, max_words: int, *, minimum_words: int = 8
) -> str:
    words = (text or "").split()
    if len(words) <= max_words:
        return text.strip()

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    kept = []
    kept_words = 0
    for sentence in sentences:
        sentence_words = sentence.split()
        if kept and kept_words + len(sentence_words) > max_words:
            break
        if not kept and len(sentence_words) > max_words:
            break
        kept.append(sentence)
        kept_words += len(sentence_words)

    if kept and kept_words >= minimum_words:
        return " ".join(kept).strip()

    keep = max(minimum_words, max_words)
    return " ".join(words[:keep]).rstrip(",;:") + "."


def _tighten_short_narration(text: str, preserve_cta: bool = False) -> str:
    """Trim short-form narration so voiceover mode stays closer to target duration."""
    cleaned = _clean_narration_text(text)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]
    if len(sentences) > (4 if preserve_cta else 3):
        sentences = sentences[:3]
    tightened = " ".join(sentences)

    filler_patterns = [
        r"\bjust\b",
        r"\breally\b",
        r"\bvery\b",
        r"\bquite\b",
        r"\bactually\b",
        r"\bsimply\b",
    ]
    for pattern in filler_patterns:
        tightened = re.sub(pattern, "", tightened, flags=re.IGNORECASE)
    tightened = re.sub(r"\s+", " ", tightened).strip()

    max_words = 52 if preserve_cta else 40
    return _truncate_to_sentence_limit(tightened, max_words, minimum_words=10)


def _narration_issues(text: str) -> list[str]:
    """Return concise issues for narration that sounds generic, weak, or non-teaching."""
    lowered = (text or "").lower()
    issues = []
    for phrase, note in _GENERIC_NARRATION_PHRASES.items():
        if phrase in lowered:
            issues.append(note)

    if lowered.count("?") > 1:
        issues.append(
            "Use at most one question per segment unless it is explicitly a question scene."
        )

    sentences = [s.strip() for s in re.split(r"[.!?]", text or "") if s.strip()]
    if any(len(sentence.split()) > 28 for sentence in sentences):
        issues.append("Break long sentences into shorter spoken lines.")

    if len(re.findall(r"\b(this|that|it)\b", lowered)) >= 6:
        issues.append("Too many vague pronouns; name the concept directly more often.")

    if len((text or "").split()) < 6:
        issues.append("Narration is too thin to sound authoritative.")

    return issues


def _apply_narrative_qa(plan_data: dict, video_mode: str) -> dict:
    """Lightweight narration QA without bloating prompts or adding another model pass."""
    segments = plan_data.get("segments", []) or []
    repeated_openers = {}
    qa_summary = []

    for idx, seg in enumerate(segments):
        narration = _clean_narration_text(seg.get("narration", ""))
        if video_mode == "short":
            narration = _tighten_short_narration(
                narration,
                preserve_cta=(
                    seg.get("type") == "question" and "comments" in narration.lower()
                ),
            )
        seg["narration"] = narration

        issues = _narration_issues(narration)
        opener = " ".join(narration.lower().split()[:3])
        if opener:
            repeated_openers[opener] = repeated_openers.get(opener, 0) + 1

        if (
            seg.get("type") != "question"
            and narration.count("?") > 0
            and video_mode == "standard"
        ):
            issues.append(
                "Standard mode narration should explain directly instead of asking questions."
            )

        qa_summary.append(
            {
                "id": seg.get("id", f"scene_{idx + 1}"),
                "issues": issues,
            }
        )

    if video_mode == "short":
        total_words = sum(len((seg.get("narration") or "").split()) for seg in segments)
        try:
            target_duration = int(plan_data.get("target_duration") or 60)
        except (TypeError, ValueError):
            target_duration = 60
        max_total_words = max(70, min(130, int(target_duration * 2.0)))
        if total_words > max_total_words:
            overflow = total_words - max_total_words
            protected_ids = {
                seg.get("id")
                for seg in segments
                if seg.get("type") == "question"
                and "comments" in (seg.get("narration") or "").lower()
            }
            for seg in reversed(segments):
                if seg.get("id") in protected_ids:
                    continue
                narration_words = (seg.get("narration") or "").split()
                if not narration_words:
                    continue
                keep = max(10, len(narration_words) - overflow)
                original_count = len(narration_words)
                seg["narration"] = _truncate_to_sentence_limit(
                    seg.get("narration") or "", keep, minimum_words=10
                )
                overflow -= max(0, original_count - len(seg["narration"].split()))
                if overflow <= 0:
                    break

            if overflow > 0:
                for seg in reversed(segments):
                    narration_words = (seg.get("narration") or "").split()
                    if not narration_words:
                        continue
                    minimum = 8 if seg.get("id") in protected_ids else 10
                    if len(narration_words) <= minimum:
                        continue
                    keep = max(minimum, len(narration_words) - overflow)
                    original_count = len(narration_words)
                    seg["narration"] = _truncate_to_sentence_limit(
                        seg.get("narration") or "", keep, minimum_words=minimum
                    )
                    overflow -= max(0, original_count - len(seg["narration"].split()))
                    if overflow <= 0:
                        break

            for seg in segments:
                seg["estimated_duration"] = min(
                    12, max(5, len((seg.get("narration") or "").split()) // 2)
                )

    repeated_issue_openers = {k for k, v in repeated_openers.items() if v >= 3 and k}
    if repeated_issue_openers:
        for item in qa_summary:
            seg = next((s for s in segments if s.get("id") == item["id"]), None)
            narration = (seg or {}).get("narration", "").lower()
            opener = " ".join(narration.split()[:3])
            if opener in repeated_issue_openers:
                item["issues"].append(
                    "Repeated segment opener weakens brand voice; vary the transition."
                )

    plan_data["narrative_qa"] = {
        "mode": video_mode,
        "segments_with_issues": sum(1 for item in qa_summary if item["issues"]),
        "segment_notes": qa_summary,
    }
    return plan_data


def _expand_topics_for_count(
    topics: list[str], target_count: int, topic: str
) -> list[str]:
    """Expand/shape topic list to a target count by cycling focused variants."""
    base = [t.strip() for t in topics if (t or "").strip()]
    if not base:
        base = [topic]

    if len(base) >= target_count:
        return base[:target_count]

    variants = []
    suffixes = [
        "intuition",
        "worked example",
        "edge case",
        "common mistake",
        "formal statement",
        "visual interpretation",
        "quick check",
        "real-world analogy",
    ]

    seen = {x.lower() for x in base}
    i = 0
    while len(base) + len(variants) < target_count:
        src = base[i % len(base)]
        suffix = suffixes[(i // len(base)) % len(suffixes)]
        cycle = i // (len(base) * len(suffixes))
        candidate = f"{src} - {suffix}"
        if cycle:
            candidate = f"{candidate} {cycle + 1}"
        key = candidate.lower()
        if key not in seen:
            variants.append(candidate)
            seen.add(key)
        i += 1

    return (base + variants)[:target_count]


def _build_fallback_visual_description(
    topic: str, subtopic: str, index: int, total: int
) -> str:
    if index == 0:
        return f"Open with a title for {topic}, then show a simple visual setup that introduces the core objects and labels."
    if index == total - 1:
        return f"Summarize {topic} by reusing the main visual elements and highlighting the final connection around {subtopic}."
    variants = [
        f"Use a focused center-stage visual for {subtopic}, animate one transformation, and keep one anchor object from the previous scene for continuity.",
        f"Present a side-by-side comparison for {subtopic}, then animate arrows/labels that highlight what changes and what stays constant.",
        f"Show a stepwise construction for {subtopic} with one key object revealed per beat, then briefly recap using a compact diagram.",
    ]
    return variants[index % len(variants)]


def _short_social_fallback_segments(prompt: str, topic: str, duration: int) -> list[dict]:
    """Build concrete short-form beats when LLM planning is unavailable."""
    text = (prompt or "").lower()
    per_seg = max(9, min(13, duration // 5))

    if "dijkstra" in text or "shortest path" in text or "weighted graph" in text:
        beats = [
            (
                "Hook: the obvious path lies",
                "Two routes look close. Dijkstra wins by refusing to guess.",
                "Open on a vertical weighted graph. Pulse two competing routes, then snap attention to start node A.",
                "content",
            ),
            (
                "Distances go live",
                "Start at A. Zero is locked. Every neighbor gets a temporary price tag.",
                "Animate node A glowing, then draw distance badges d(A)=0, d(B)=2, d(C)=5 as edges light up.",
                "content",
            ),
            (
                "Relax the graph",
                "Pick the smallest unlocked number. Relax its edges. If a cheaper route appears, overwrite the label.",
                "Move a bright dot along A to B to C. Transform an old distance label into a smaller one.",
                "content",
            ),
            (
                "Path reveal",
                "When a node is locked, its number is final. The shortest path appears one highlighted edge at a time.",
                "Freeze the distance table, thicken the winning path, and fade losing edges into the background.",
                "content",
            ),
            (
                "Your turn",
                "Your turn: if one edge gets cheaper, which node changes first? Type your answer in the comments!",
                "Keep the graph on screen, drop one edge weight, and pulse the next node candidates as a viewer challenge.",
                "question",
            ),
        ]
    elif "binary search" in text:
        beats = [
            (
                "Hook: delete half",
                "Binary search feels like cheating: every guess deletes half the world.",
                "Show eight sorted boxes. Smash-cut a search window around all boxes and flash the target.",
                "content",
            ),
            (
                "Middle first",
                "Never start at the edge. Jump to the middle and ask one brutal question.",
                "Drop a pointer onto the middle box, show target comparison, and animate a yes/no split.",
                "content",
            ),
            (
                "Half disappears",
                "If the middle is too small, the entire left side is dead. Not maybe. Dead.",
                "Fade the rejected half to gray, shrink the active window, and keep the target badge alive.",
                "content",
            ),
            (
                "Repeat fast",
                "Do it again. Eight boxes become four, then two, then one.",
                "Animate three rapid window transforms with a counter: 8 to 4 to 2 to 1.",
                "content",
            ),
            (
                "Your turn",
                "Your turn: target is eleven. Which half survives the first guess? Type your answer in the comments!",
                "Freeze the first midpoint and pulse the two possible halves as the challenge.",
                "question",
            ),
        ]
    elif any(k in text for k in ["bond", "molecule", "atom", "chemical", "chemistry", "hybrid"]):
        beats = [
            (
                "Hook: atoms snap together",
                "A chemical bond is not a stick. It is shared attraction locking atoms into shape.",
                "Throw atoms into frame, then pull them into a molecule with glowing bond lines.",
                "content",
            ),
            (
                "Electrons choose the shape",
                "Electron clouds repel. That invisible push decides the angle you actually see.",
                "Animate small electron dots orbiting, then push bond arms into a clear geometry.",
                "content",
            ),
            (
                "Bond forms",
                "When sharing wins, the bond brightens. When repulsion wins, the atoms spread out.",
                "Create a bond line between atoms, then transform it thicker as the distance stabilizes.",
                "content",
            ),
            (
                "Geometry reveal",
                "The molecule is the final receipt: bond count, angle, and lone pairs all show up in one shape.",
                "Rotate the finished molecule, label bond angle, and highlight lone-pair pressure.",
                "content",
            ),
            (
                "Your turn",
                "Your turn: add one lone pair. Does the bond angle open or squeeze? Type your answer in the comments!",
                "Keep the molecule visible and pulse two possible angle outcomes.",
                "question",
            ),
        ]
    elif any(k in text for k in ["car", "cart", "collision", "momentum", "velocity", "acceleration"]):
        beats = [
            (
                "Hook: crash math",
                "A collision looks chaotic, but momentum keeps the receipt.",
                "Send a car across a track toward a block, with a bright velocity arrow attached.",
                "content",
            ),
            (
                "Before impact",
                "Mass times velocity is the number to watch before anything hits.",
                "Scale a momentum arrow as speed increases and show m times v as a compact badge.",
                "content",
            ),
            (
                "Impact",
                "At contact, force spikes. Momentum transfers through the collision.",
                "Animate the car hitting the block, compress a spring shape, then flash the contact point.",
                "content",
            ),
            (
                "After impact",
                "The motion changes bodies, but the total momentum has to balance.",
                "Move both objects after collision with shorter arrows and a total-momentum meter.",
                "content",
            ),
            (
                "Your turn",
                "Your turn: double the mass, same speed. What happens after impact? Type your answer in the comments!",
                "Freeze two mass options and pulse the expected outcome as a challenge.",
                "question",
            ),
        ]
    else:
        beats = [
            (
                "Hook",
                f"Here is the part of {topic} that people usually miss.",
                "Open with one surprising visual contrast, then zoom into the changing object.",
                "content",
            ),
            (
                "Moving pieces",
                "Track the object that changes. Ignore everything else for three seconds.",
                "Animate the main object moving along a curve while secondary labels fade behind it.",
                "content",
            ),
            (
                "Rule",
                "The rule is simple: one input changes, one output reacts, and the pattern repeats.",
                "Transform input/output badges while a bright path traces the relationship.",
                "content",
            ),
            (
                "Payoff",
                "Once you see the pattern, the formula stops being decoration.",
                "Snap the visual pattern into a compact rule card without clearing the scene.",
                "content",
            ),
            (
                "Your turn",
                "Your turn: change the input. What moves first? Type your answer in the comments!",
                "Keep the final visual alive and pulse two possible next moves.",
                "question",
            ),
        ]

    return [
        {
            "id": f"scene_{idx + 1}",
            "title": title,
            "narration": narration,
            "visual_description": visual,
            "estimated_duration": per_seg,
            "type": seg_type,
        }
        for idx, (title, narration, visual, seg_type) in enumerate(beats)
    ]


def _is_codex_model(model: str) -> bool:
    return "codex" in (model or "").lower()


def _llm_text(prompt_messages, model: str) -> str:
    use_subprocess = os.getenv("REQUEST_ANALYSIS_USE_SUBPROCESS", "true").lower()
    if use_subprocess not in {"0", "false", "no", "off"}:
        return _llm_text_subprocess(prompt_messages, model)
    return _llm_text_in_process(prompt_messages, model)


def _llm_text_in_process(prompt_messages, model: str) -> str:
    if _is_codex_model(model):
        parts = []
        for m in prompt_messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            parts.append(f"[{role.upper()}]\n{content}")
        input_text = "\n\n".join(parts)
        resp = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": input_text}],
                }
            ],
            timeout=REQUEST_ANALYSIS_TIMEOUT_SECONDS,
        )
        return resp.output_text or ""

    response = client.chat.completions.create(
        model=model,
        messages=prompt_messages,
        timeout=REQUEST_ANALYSIS_TIMEOUT_SECONDS,
    )
    if not response or not getattr(response, "choices", None):
        return ""
    message = response.choices[0].message
    if not message:
        return ""
    return message.content or ""


def _llm_text_subprocess(prompt_messages, model: str) -> str:
    """Run planning LLM calls in a child process so timeout kills are real."""
    payload = {
        "api_key": OPENAI_API_KEY or "",
        "base_url": OPENAI_BASE_URL,
        "model": model,
        "messages": prompt_messages,
        "timeout": REQUEST_ANALYSIS_TIMEOUT_SECONDS,
        "codex": _is_codex_model(model),
    }
    child_code = r"""
import json
import sys
from openai import OpenAI

payload_path = sys.argv[1]
output_path = sys.argv[2]
with open(payload_path, "r", encoding="utf-8") as f:
    payload = json.load(f)

client = OpenAI(
    api_key=payload["api_key"],
    base_url=payload.get("base_url"),
    timeout=payload.get("timeout") or 60,
)

if payload.get("codex"):
    parts = []
    for m in payload["messages"]:
        role = m.get("role", "user")
        content = m.get("content", "")
        parts.append(f"[{role.upper()}]\n{content}")
    input_text = "\n\n".join(parts)
    response = client.responses.create(
        model=payload["model"],
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": input_text}],
            }
        ],
        timeout=payload.get("timeout") or 60,
    )
    text = response.output_text or ""
else:
    response = client.chat.completions.create(
        model=payload["model"],
        messages=payload["messages"],
        timeout=payload.get("timeout") or 60,
    )
    text = ""
    if response and getattr(response, "choices", None):
        message = response.choices[0].message
        text = (message.content if message else "") or ""

with open(output_path, "w", encoding="utf-8", errors="replace") as out:
    out.write(text)
    out.flush()
"""
    tmp_dir = Path(tempfile.mkdtemp(prefix="nima-plan-"))
    payload_path = tmp_dir / "payload.json"
    output_path = tmp_dir / "output.txt"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    output_path.write_text("", encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", child_code, str(payload_path), str(output_path)],
            capture_output=True,
            text=True,
            timeout=REQUEST_ANALYSIS_TIMEOUT_SECONDS + 5,
        )
        text = output_path.read_text(encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "planner subprocess failed")[-1200:])
        return text
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"planner generation exceeded {REQUEST_ANALYSIS_TIMEOUT_SECONDS}s"
        ) from exc
    finally:
        try:
            payload_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass


def _extract_first_json_object(text: str) -> str:
    """Extract first balanced JSON object from model output."""
    raw = (text or "").strip()
    if not raw:
        return raw

    start = raw.find("{")
    if start == -1:
        return raw

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]

    return raw[start:]


def _llm_routing_json(prompt: str) -> dict:
    """Small structured routing call to avoid brittle keyword guessing."""
    system_msg = """You classify educational animation requests. Return ONLY valid JSON.

Schema:
{
  "type": "EDUCATIONAL_CONCEPT|DETAILED_ANIMATION|SIMPLE_ANIMATION",
  "complexity": "BASIC|INTERMEDIATE|ADVANCED",
  "topic": "2-6 words",
  "subtopics": ["3-8 short strings"],
  "duration": 120-1200,
  "depth": "SURFACE|MODERATE|DEEP",
  "domain": "math|physics|computer_science|chemistry|general",
  "approach": "1 sentence"
}

Prefer broad course-style durations when the prompt asks to teach multiple connected ideas.
Return only JSON, no markdown fences."""

    text = _llm_text(
        [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        model=FAST_MODEL,
    )
    if not text:
        raise ValueError("Empty routing response")
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Routing response is not a JSON object")
    return data


def analyze_request_type(prompt: str) -> dict:
    """Classify the prompt and extract metadata needed to drive generation."""
    print("[ANALYZE] Analyzing request type...")

    system_msg = """\
You are a classifier for an educational animation generator (Manim CE).

Determine the following about the user's request:
1. TYPE: EDUCATIONAL_CONCEPT | DETAILED_ANIMATION | SIMPLE_ANIMATION
2. COMPLEXITY: BASIC | INTERMEDIATE | ADVANCED
3. TOPIC: The main subject in 2–6 words
4. SUBTOPICS: 3–8 comma-separated subtopics to cover
5. DURATION: Target video length in seconds
   - BASIC educational: 120–240s
   - INTERMEDIATE educational: 240–480s
   - ADVANCED educational: 480–720s
   - Simple animations: 30–90s
6. DEPTH: SURFACE | MODERATE | DEEP
7. DOMAIN: math | physics | computer_science | chemistry | general

Respond in this EXACT format (one key per line):
TYPE: [type]
COMPLEXITY: [level]
TOPIC: [topic]
SUBTOPICS: [subtopic1, subtopic2, ...]
DURATION: [integer seconds]
DEPTH: [depth]
DOMAIN: [domain]
APPROACH: [1 sentence: main teaching approach]
"""

    defaults = _heuristic_analysis_defaults(prompt)

    try:
        analysis = dict(defaults)
        try:
            routed = _llm_routing_json(prompt)
            analysis.update(
                {
                    "type": routed.get("type") or analysis["type"],
                    "complexity": routed.get("complexity") or analysis["complexity"],
                    "topic": routed.get("topic") or analysis["topic"],
                    "subtopics": routed.get("subtopics") or analysis["subtopics"],
                    "duration": int(routed.get("duration") or analysis["duration"]),
                    "depth": routed.get("depth") or analysis["depth"],
                    "domain": routed.get("domain") or analysis["domain"],
                    "approach": routed.get("approach") or analysis["approach"],
                }
            )
        except Exception:
            result = _llm_text(
                [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": f"Classify this request: {prompt}"},
                ],
                model=FAST_MODEL,
            )

            if not result:
                raise ValueError("Empty analysis response")

            for line in result.split("\n"):
                line = line.strip()
                if line.startswith("TYPE:"):
                    analysis["type"] = line[5:].strip()
                elif line.startswith("COMPLEXITY:"):
                    analysis["complexity"] = line[11:].strip()
                elif line.startswith("TOPIC:"):
                    analysis["topic"] = line[6:].strip()
                elif line.startswith("SUBTOPICS:"):
                    raw = line[10:].strip()
                    analysis["subtopics"] = [
                        s.strip() for s in raw.split(",") if s.strip()
                    ]
                elif line.startswith("DURATION:"):
                    m = re.search(r"\d+", line)
                    if m:
                        analysis["duration"] = int(m.group())
                elif line.startswith("DEPTH:"):
                    analysis["depth"] = line[6:].strip()
                elif line.startswith("DOMAIN:"):
                    analysis["domain"] = line[7:].strip()
                elif line.startswith("APPROACH:"):
                    analysis["approach"] = line[9:].strip()

        print(
            f"[ANALYZE] [OK] type={analysis['type']} domain={analysis['domain']} duration={analysis['duration']}s"
        )
        return analysis

    except Exception as e:
        print(f"[ANALYZE] [ERR] {e} — using defaults")
        return defaults


def create_animation_plan(prompt: str, analysis: dict) -> str:
    """Generate a detailed scene-by-scene storyboard for the animator."""
    print("[PLAN] Creating animation storyboard...")

    system_msg = """\
You are a Manim animation director. Create a precise, scene-by-scene plan.

For each scene use this format:

### SCENE N (start–end seconds): [Short scene title]
- Visual Objects: [List every Manim object needed]
- Animation Sequence: [What happens, in order, with timing]
- On-Screen Text: [Short text/formulas to display]
- ValueTracker/Dynamic: [Any live-updating elements?]
- Cleanup: [Which objects to FadeOut before the next scene]
- Transition: [How we move to the next scene — prefer Transform over FadeOut+FadeIn]

PEDAGOGICAL REQUIREMENTS (CRITICAL):
- Every concept MUST follow a "conceptual ladder":
    prerequisite → simple case → build up → full concept → takeaway
- NEVER plan a scene that is just "show formula then show result"
- ALWAYS include intermediate visual steps between introduction and conclusion
- For any transformation topic: show basis/starting state FIRST, then transform
- For any formula topic: show the geometric/visual meaning, not just the symbols

TRANSITION REQUIREMENTS:
- Plan transitions that maintain visual context
- Use Transform to morph related objects instead of removing and recreating
- NEVER plan a step that says "clear the screen" or "remove everything"
- Prefer ReplacementTransform for evolving objects (e.g., equation step-by-step)

VISUAL QUALITY:
- Grids/planes should be subtle background elements, not the main focus
- Keep the viewer's attention on the concept, not on decorations
- Every scene should have a clear focal point

REQUIREMENTS:
- Cover every subtopic in the provided list
- Each scene should be 20–60 seconds
- Include a hook (Scene 1) and a summary (last scene)
- Prefer dynamic visuals (ValueTracker, TracedPath) over static text dumps
- Every scene MUST end with explicit cleanup instructions
- Suggest which PROVEN PATTERNS are appropriate for each scene

Return ONLY the storyboard text.
"""

    try:
        plan = _llm_text(
            [
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": (
                        f"Create a storyboard for: {prompt}\n"
                        f"Duration: {analysis.get('duration', 300)}s\n"
                        f"Complexity: {analysis.get('complexity', 'INTERMEDIATE')}\n"
                        f"Subtopics: {', '.join(analysis.get('subtopics', []))}\n"
                        f"Teaching approach: {analysis.get('approach', '')}"
                    ),
                },
            ],
            model=GENERATION_MODEL,
        )
        print("[PLAN] [OK] Storyboard created")
        return plan
    except Exception as e:
        print(f"[PLAN] [ERR] {e}")
        return "No detailed plan — create a clear educational animation covering the topic step by step."


def create_plan_json(prompt: str, analysis: dict, template_name: str = None) -> str:
    """Generate a plan-first JSON (v1) for deterministic compilation.

    If template_name is provided, the model must follow that template's slots.
    Returns a JSON string compatible with algorithms/plan/schema.py.
    """
    print("[PLAN] Creating plan JSON (v1)...")

    template_block = ""
    if template_name and template_name in TEMPLATES:
        t = TEMPLATES[template_name]
        template_block = (
            f"\nTEMPLATE SELECTED: {template_name}\n"
            f"Slots: {', '.join(t['slots'])}\n"
            f"Beats: {t['beats']}\n"
            f"Notes: {t['notes']}\n"
        )

    system_msg = f"""\
You generate plan-first JSON for Manim (schema v1). Output ONLY JSON.

Schema keys:
- version: "v1"
- meta: {{"name": string, "template"?: string}}
- objects: list of object specs
- beats: list of beat actions

Object spec:
  {{"id": str, "kind": one of [Text, MathTex, VGroup, NumberPlane, Axes, Dot, Line, Arrow, Rectangle, Circle, Square, Polygon],
   "zone": one of [top, center, bottom, full],
   "style": {{"color"?: "BLUE"|"YELLOW"|..., "font_size"?: int, "stroke_width"?: float, "stroke_opacity"?: float, "fill_opacity"?: float}},
   "params": {{"text"?: str, "tex"?: str}}}}

Beat action:
  {{"op": "create"|"write"|"fade_in"|"fade_out"|"transform"|"move_to"|"arrange"|"set_color"|"wait",
   "target"?: object id, "source"?: object id, "run_time"?: float, "wait"?: float}}

Rules:
- Always include a top title object and a bottom caption object.
- Use zones for placement (top/center/bottom) and keep visuals in center.
- Keep it deterministic; do not include arbitrary code.
- Keep the plan concise (6–10 objects, 4–6 beats).
{template_block}
"""

    try:
        plan_json = _llm_text(
            [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Create a plan JSON for: {prompt}"},
            ],
            model=GENERATION_MODEL,
        )
        print("[PLAN] [OK] Plan JSON created")
        return plan_json
    except Exception as e:
        print(f"[PLAN] [ERR] {e}")
        return ""


def _enforce_question_rules(
    plan_data: dict, video_mode: str, q_cfg: dict, mode_cfg: dict
) -> dict:
    """Post-process a narrated plan to enforce question rules for the video mode.

    - short: exactly 1 question at end with CTA
    - standard: strip all questions
    - course/lecture: ensure min/max question count, spaced throughout
    """
    segments = plan_data.get("segments", [])
    if not segments:
        return plan_data

    questions_enabled = q_cfg.get("enabled", False)

    if not questions_enabled:
        # Strip any question segments the LLM may have added
        for seg in segments:
            seg["type"] = "content"
        plan_data["segments"] = segments
        return plan_data

    # ── SHORT mode: exactly 1 question at end ──────────────────────────
    if video_mode == "short":
        existing_questions = [
            i for i, s in enumerate(segments) if s.get("type") == "question"
        ]
        if existing_questions:
            question_idx = existing_questions[-1]
            question_segment = segments[question_idx]
            segments = [
                seg for idx, seg in enumerate(segments) if idx != question_idx
            ] + [question_segment]

        # Remove any question segments except the final one.
        for seg in segments[:-1]:
            seg["type"] = "content"

        last = segments[-1]
        last["type"] = "question"
        cta = q_cfg.get("cta_text", "Type your answer in the comments!")
        if cta and cta not in (last.get("narration") or ""):
            # Append CTA if not already present
            narration = (last.get("narration") or "").rstrip(". ")
            last["narration"] = f"{narration}. {cta}" if narration else cta

        plan_data["segments"] = segments
        return plan_data

    # ── COURSE / LECTURE mode: enforce min/max question count ───────────
    min_q = q_cfg.get("min_questions", 3)
    max_q = q_cfg.get("max_questions", 6)
    pause_s = q_cfg.get("pause_seconds", 10)

    # Count existing question segments
    existing_questions = [
        i for i, s in enumerate(segments) if s.get("type") == "question"
    ]

    # If too many, convert excess back to content (keep evenly spaced ones)
    if len(existing_questions) > max_q:
        keep = set()
        step = max(1, len(existing_questions) // max_q)
        for j in range(0, len(existing_questions), step):
            keep.add(existing_questions[j])
            if len(keep) >= max_q:
                break
        for i in existing_questions:
            if i not in keep:
                segments[i]["type"] = "content"
        existing_questions = [i for i in existing_questions if i in keep]

    # If too few, inject question segments at even intervals
    if len(existing_questions) < min_q:
        content_indices = [
            i
            for i, s in enumerate(segments)
            if s.get("type") == "content" and i > 0 and i < len(segments) - 1
        ]
        needed = min_q - len(existing_questions)
        if content_indices and needed > 0:
            step = max(1, len(content_indices) // (needed + 1))
            inject_after = []
            for j in range(step, len(content_indices), step):
                inject_after.append(content_indices[j])
                if len(inject_after) >= needed:
                    break

            # Insert question segments (iterate in reverse to keep indices stable)
            for insert_idx in reversed(inject_after):
                prev_topic = segments[insert_idx].get("title", "this concept")
                question_stems = [
                    f"How does {prev_topic} connect to what we covered earlier?",
                    f"What would change if one key assumption in {prev_topic} were different?",
                    f"Why does {prev_topic} matter for solving a real problem, not just a textbook example?",
                    f"What is the most common mistake in {prev_topic}, and how would you avoid it?",
                ]
                stem = question_stems[insert_idx % len(question_stems)]
                q_seg = {
                    "id": f"question_after_{insert_idx}",
                    "title": f"Check Your Understanding",
                    "narration": (
                        f"Pause and think about this question: {stem} "
                        "Take a moment to think about it."
                    ),
                    "visual_description": (
                        f"Display a question card for {prev_topic} with the prompt text. "
                        f"Hold for {pause_s} seconds with a subtle thinking animation."
                    ),
                    "estimated_duration": pause_s,
                    "type": "question",
                }
                segments.insert(insert_idx + 1, q_seg)

    # Ensure all question segments have correct duration
    for seg in segments:
        if seg.get("type") == "question":
            seg["estimated_duration"] = pause_s

    # Re-number IDs
    for i, seg in enumerate(segments):
        seg["id"] = f"scene_{i + 1}"

    plan_data["segments"] = segments
    return plan_data


def create_narrated_plan(prompt: str, analysis: dict) -> str:
    """Generate a structured JSON timeline with narration text per segment.

    Used when voiceover is enabled.  Each segment contains narration text
    that will be sent to TTS, and the measured audio duration will drive
    the Manim animation timing.

    The plan is shaped by analysis['video_mode'] when present:
      - short:    55-60s, 1 question at end with CTA
      - standard: 2-5 min, no questions
      - course:   ~15 min, open questions spaced throughout with 10s pauses
      - lecture:   30+ min (stubbed to 15 min), lecture-style questions

    Returns a JSON string with:
    {
      "segments": [
        {
          "id": "scene_1",
          "title": "...",
          "narration": "spoken text for this segment",
          "visual_description": "what Manim should show",
          "estimated_duration": 8,
          "type": "content" | "question"
        },
        ...
      ]
    }
    """
    from algorithms.video_modes import build_video_mode_profile

    profile = build_video_mode_profile(analysis.get("video_mode"))
    video_mode = profile.mode
    mode_cfg = dict(profile.raw or {})
    q_cfg = dict(profile.questions)
    questions_enabled = q_cfg.get("enabled", False)
    narration_style = profile.narration_style
    duration_target = profile.target_duration

    print(
        f"[PLAN] Creating narrated animation timeline (mode={video_mode}, duration={duration_target}s)..."
    )

    # ── Build mode-specific instructions for the LLM ───────────────────
    question_instructions = ""
    if questions_enabled:
        if video_mode == "short":
            question_instructions = """
QUESTION RULES (SHORT MODE):
- Add EXACTLY 1 open-ended question as the LAST segment.
- The question segment must have "type": "question".
- The narration for the question MUST end with: "Type your answer in the comments!"
- The question should be thought-provoking and directly related to the content.
- Keep the question simple — the audience is casual social media viewers.
"""
        elif video_mode in ("course", "lecture"):
            min_q = q_cfg.get("min_questions", 3)
            max_q = q_cfg.get("max_questions", 6)
            pause_s = q_cfg.get("pause_seconds", 10)
            question_instructions = f"""
QUESTION RULES ({video_mode.upper()} MODE):
- Include {min_q}–{max_q} open-ended question segments distributed throughout.
- Place question segments AFTER the content they test, not before.
- Each question segment must have "type": "question" and "estimated_duration": {pause_s}.
- The narration should pose the question, then say: "Take a moment to think about it."
- Questions should test understanding, not recall. Ask "why" or "what would happen if" questions.
- Space questions roughly evenly across the timeline.
"""
    else:
        question_instructions = """
QUESTION RULES:
- Do NOT include any questions. This is a pure information delivery format.
- Every segment must have "type": "content".
"""

    # ── Build duration / segment count guidance ─────────────────────────
    if video_mode == "short":
        segment_guidance = f"""
SEGMENT COUNT AND TIMING:
- Total video duration: EXACTLY {duration_target} seconds.
- Use 2–4 content segments plus the final question segment.
- Each content segment: 10–20 seconds of narration.
- Keep it tight — every sentence must earn its place.
"""
    elif video_mode == "course":
        segment_guidance = f"""
SEGMENT COUNT AND TIMING:
- Total video duration: approximately {duration_target} seconds (~{duration_target // 60} minutes).
- Use 10–18 content segments plus question segments.
- Each content segment: 30–90 seconds of narration.
- Build concepts gradually with recap transitions between major sections.
"""
    elif video_mode == "lecture":
        segment_guidance = f"""
SEGMENT COUNT AND TIMING:
- Total video duration: approximately {duration_target} seconds (~{duration_target // 60} minutes).
- Use 15–30 content segments plus question segments.
- Each content segment: 30–120 seconds of narration.
- Pace like a real lecture — allow thorough derivations and examples.
"""
    else:  # standard
        segment_guidance = f"""
SEGMENT COUNT AND TIMING:
- Total video duration: approximately {duration_target} seconds (~{duration_target // 60} minutes).
- BASIC topics: 4–8 segments
- INTERMEDIATE: 6–12 segments
- ADVANCED: 10–15 segments
- Each segment: 15–40 seconds of narration.
"""

    system_msg = f"""\
You are a Manim animation director AND narrator. Create a scene timeline with
narration text that will be spoken aloud over each scene.

Return ONLY valid JSON with this structure:
{{
  "segments": [
    {{
      "id": "scene_1",
      "title": "Hook / Opening",
      "narration": "The spoken narration for this segment.",
      "visual_description": "What the Manim animation should show.",
      "estimated_duration": 8,
      "type": "content"
    }}
  ]
}}

NARRATION STYLE: {narration_style}

NARRATION RULES:
- Write for speech: short sentences, no jargon, no LaTeX notation in narration
- For math, spell it out: "two x squared" not "2x^2"
- Start with a hook, end with a takeaway
- Narration should DESCRIBE what the viewer sees, not repeat on-screen text
- Use pauses implied by sentence breaks for visual breathing room

VISUAL DESCRIPTION RULES:
- Reference specific Manim objects: NumberPlane, MathTex, Arrow, Dot, ValueTracker
- Describe animations: FadeIn, Transform, Create, Write
- NOTE which objects persist vs which fade out
- Each scene should have a clear focal point

{segment_guidance}
{question_instructions}

Return ONLY the JSON. No markdown fences, no explanation."""

    try:
        plan_text = _llm_text(
            [
                {"role": "system", "content": system_msg},
                {
                    "role": "user",
                    "content": (
                        f"Create a narrated animation timeline for: {prompt}\n"
                        f"Video mode: {video_mode} ({profile.label})\n"
                        f"Target duration: {duration_target}s\n"
                        f"Complexity: {analysis.get('complexity', 'intermediate')}\n"
                        f"Subtopics: {', '.join(analysis.get('subtopics', []))}\n"
                        f"Teaching approach: {analysis.get('approach', '')}"
                    ),
                },
            ],
            model=GENERATION_MODEL,
        )

        if not plan_text:
            raise ValueError("Empty narrated plan response")

        plan_text = plan_text.strip()

        # Strip markdown fences if present
        if plan_text.startswith("```"):
            lines = plan_text.split("\n")
            plan_text = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            )

        # Validate JSON
        import json

        try:
            data = json.loads(plan_text)
        except Exception:
            plan_text = _extract_first_json_object(plan_text)
            data = json.loads(plan_text)
        assert "segments" in data, "Missing 'segments' key"
        assert len(data["segments"]) > 0, "No segments"
        for seg in data["segments"]:
            assert "id" in seg, "Segment missing 'id'"
            assert "narration" in seg, "Segment missing 'narration'"
            # Default type to "content" if not set
            if "type" not in seg:
                seg["type"] = "content"

        # ── Post-process: enforce question rules per mode ──────────────
        data["video_mode"] = profile.mode
        data["target_duration"] = profile.target_duration
        data["duration_range"] = list(profile.duration_range)
        data["min_scenes"] = profile.min_scenes
        data["max_scenes"] = profile.max_scenes
        data["aspect"] = profile.aspect
        data = _enforce_question_rules(data, video_mode, q_cfg, mode_cfg)
        data = _apply_narrative_qa(data, video_mode)

        print(
            f"[PLAN] [OK] Narrated timeline: {len(data['segments'])} segments "
            f"({sum(1 for s in data['segments'] if s.get('type') == 'question')} questions)"
        )
        return json.dumps(data)

    except Exception as e:
        print(f"[PLAN] [ERR] Narrated plan failed: {e}")
        import json

        topic = analysis.get("topic", "this concept")
        subtopics = analysis.get("subtopics") or _fallback_subtopics(
            prompt, analysis.get("domain", "general"), topic
        )
        duration = int(profile.target_duration or 60)
        unique_subtopics = []
        seen = set()
        for sub in [topic, *subtopics]:
            clean = (sub or "").strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            unique_subtopics.append(clean)

        if video_mode == "short":
            fallback = {
                "segments": _short_social_fallback_segments(prompt, topic, duration),
                "video_mode": profile.mode,
                "target_duration": profile.target_duration,
                "duration_range": list(profile.duration_range),
                "min_scenes": profile.min_scenes,
                "max_scenes": profile.max_scenes,
                "aspect": profile.aspect,
            }
            fallback = _enforce_question_rules(fallback, video_mode, q_cfg, mode_cfg)
            fallback = _apply_narrative_qa(fallback, video_mode)
            return json.dumps(fallback)
        elif video_mode == "standard":
            content_target = max(5, min(10, len(unique_subtopics) + 2))
            per_seg = max(20, duration // max(1, content_target))
        elif video_mode == "course":
            # Aggressive long-form fallback for course mode.
            # Intentionally target many scenes (experimental) to reduce giant tail padding.
            content_target = max(25, min(34, len(unique_subtopics) + 18))
            per_seg = max(20, min(45, duration // max(1, content_target)))
        else:  # lecture
            content_target = max(16, min(26, len(unique_subtopics) + 8))
            per_seg = max(40, min(110, duration // max(1, content_target)))

        ordered_topics = _expand_topics_for_count(
            unique_subtopics, content_target, topic
        )
        if len(ordered_topics) < 4:
            defaults = [
                f"intuition behind {topic}",
                f"worked example for {topic}",
                f"common mistake in {topic}",
                f"core takeaway of {topic}",
            ]
            for item in defaults:
                if item.lower() not in seen:
                    ordered_topics.append(item)
                    seen.add(item.lower())
                if len(ordered_topics) >= 4:
                    break

        segments = []
        for idx, subtopic in enumerate(ordered_topics):
            is_first = idx == 0
            is_last = idx == len(ordered_topics) - 1
            if is_first:
                title = "Hook / Opening"
            elif is_last:
                title = "Takeaway"
            else:
                title = subtopic[:40]

            segments.append(
                {
                    "id": f"scene_{idx + 1}",
                    "title": title,
                    "narration": _build_fallback_segment_narration(
                        topic,
                        subtopic,
                        idx,
                        len(ordered_topics),
                        video_mode,
                    ),
                    "visual_description": _build_fallback_visual_description(
                        topic, subtopic, idx, len(ordered_topics)
                    ),
                    "estimated_duration": per_seg,
                    "type": "content",
                }
            )

        fallback = {
            "segments": segments,
            "video_mode": profile.mode,
            "target_duration": profile.target_duration,
            "duration_range": list(profile.duration_range),
            "min_scenes": profile.min_scenes,
            "max_scenes": profile.max_scenes,
            "aspect": profile.aspect,
        }
        # Enforce question rules on fallback too
        fallback = _enforce_question_rules(fallback, video_mode, q_cfg, mode_cfg)
        fallback = _apply_narrative_qa(fallback, video_mode)
        return json.dumps(fallback)


def expand_short_prompt(prompt: str) -> str:
    """Expand truncated or short problem-solving prompts for better generation.

    Detects prompts like:
    - "Solve log_3(x) = 2…"
    - "Compute lim(x→0) sin(x)/x…"
    - "Find the derivative of..."

    And expands them with what the animation should show.
    """
    original = prompt
    prompt = prompt.strip()

    is_truncated = prompt.endswith("…") or prompt.endswith("...")
    starts_with_verb = re.match(
        r"^(solve|compute|find|calculate|evaluate|determine|prove|show|derive)",
        prompt.lower(),
    )

    if is_truncated or starts_with_verb:
        extension = ""

        if "log" in prompt.lower():
            extension = " Show the step-by-step solution with clear visual explanation of logarithms."
        elif "lim" in prompt.lower() or "limit" in prompt.lower():
            extension = " Show the graphical interpretation and step-by-step evaluation of the limit."
        elif "derivative" in prompt.lower() or "differentiate" in prompt.lower():
            extension = " Show the step-by-step differentiation with visual interpretation of the rate of change."
        elif "integral" in prompt.lower():
            extension = " Show the step-by-step integration with area under curve visualization."
        elif "solve" in prompt.lower() and any(
            x in prompt.lower() for x in ["equation", "="]
        ):
            extension = (
                " Show each step of solving the equation with visual transformation."
            )
        elif "compute" in prompt.lower() or "calculate" in prompt.lower():
            extension = (
                " Show the computation step-by-step with clear visual explanation."
            )

        if extension:
            prompt = prompt.rstrip("…").rstrip("...") + extension

    if prompt != original:
        print(f"[EXPAND] Expanded prompt: '{original}' -> '{prompt}'")

    return prompt
