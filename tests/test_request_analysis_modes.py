"""Video-mode post-processing checks for narrated plans."""

import json
import os

os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["USE_DATABASE"] = "false"

import algorithms.request_analysis as request_analysis
from algorithms.request_analysis import (
    _apply_narrative_qa,
    _enforce_question_rules,
    create_animation_plan,
    create_narrated_plan,
    heuristic_request_analysis,
)


def test_short_mode_moves_existing_question_to_the_end():
    plan = {
        "segments": [
            {"id": "scene_1", "narration": "Introduce the idea.", "type": "content"},
            {
                "id": "scene_2",
                "narration": "What changes if the input doubles?",
                "type": "question",
            },
            {"id": "scene_3", "narration": "Close with the takeaway.", "type": "content"},
        ]
    }

    result = _enforce_question_rules(
        plan,
        "short",
        {"enabled": True, "cta_text": "Type your answer in the comments!"},
        {},
    )

    segments = result["segments"]
    assert [segment["type"] for segment in segments] == [
        "content",
        "content",
        "question",
    ]
    assert segments[-1]["id"] == "scene_2"
    assert "Type your answer in the comments!" in segments[-1]["narration"]
    print("[OK] request analysis - short mode preserves explicit final question")


def test_standard_mode_strips_question_segments():
    plan = {
        "segments": [
            {"id": "scene_1", "narration": "Explain directly.", "type": "content"},
            {"id": "scene_2", "narration": "What do you think?", "type": "question"},
        ]
    }

    result = _enforce_question_rules(plan, "standard", {"enabled": False}, {})

    assert all(segment["type"] == "content" for segment in result["segments"])
    print("[OK] request analysis - standard mode strips question segment types")


def test_short_narration_tightening_keeps_sentence_boundaries():
    plan = {
        "target_duration": 58,
        "segments": [
            {
                "id": "scene_1",
                "type": "content",
                "narration": (
                    "Let's begin with a simple picture of derivative of x squared. "
                    "Think of one concrete situation so the main idea feels natural before any formal details."
                ),
            },
            {
                "id": "scene_2",
                "type": "content",
                "narration": (
                    "Now test derivative with a quick what-if scenario. "
                    "Notice what changes and what stays invariant in derivative of x squared."
                ),
            },
        ],
    }

    result = _apply_narrative_qa(plan, "short")
    narrations = [segment["narration"] for segment in result["segments"]]

    assert "Think of one concrete." not in narrations[0]
    assert "Notice what." not in narrations[1]
    assert all(narration.endswith(".") for narration in narrations)
    print("[OK] request analysis - short narration is not cut mid-sentence")


def test_planning_helpers_accept_sparse_analysis_payloads():
    original_llm = request_analysis._llm_text
    try:
        request_analysis._llm_text = lambda *args, **kwargs: json.dumps(
            {
                "segments": [
                    {
                        "id": "scene_1",
                        "narration": "Show the tangent slope cleanly.",
                        "visual_description": "Draw a graph and tangent line.",
                        "estimated_duration": 8,
                        "type": "content",
                    }
                ]
            }
        )
        sparse = {"domain": "math", "duration": 58, "video_mode": "short"}

        narrated = json.loads(create_narrated_plan("Explain slopes", sparse))

        assert narrated["segments"]

        request_analysis._llm_text = lambda *args, **kwargs: "Storyboard text"
        assert create_animation_plan("Explain slopes", sparse) == "Storyboard text"
    finally:
        request_analysis._llm_text = original_llm
    print("[OK] request analysis - planning helpers accept sparse analysis")


def test_heuristic_analysis_routes_algorithm_prompts_to_cs():
    analysis = heuristic_request_analysis(
        "Explain Dijkstra shortest path as a 60 second vertical short"
    )

    assert analysis["domain"] == "computer_science", analysis
    assert "dijkstra" in analysis["topic"], analysis
    print("[OK] request analysis - heuristic routes algorithm prompts to CS")


def test_short_fallback_plan_uses_social_visual_beats():
    original_llm = request_analysis._llm_text
    try:
        request_analysis._llm_text = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("planner unavailable")
        )
        plan = json.loads(
            create_narrated_plan(
                "Make a viral vertical short explaining Dijkstra's algorithm with moving nodes.",
                {
                    "domain": "computer_science",
                    "duration": 58,
                    "video_mode": "short",
                    "topic": "dijkstra algorithm",
                    "subtopics": ["weighted graph", "distance labels"],
                },
            )
        )
    finally:
        request_analysis._llm_text = original_llm

    text = json.dumps(plan).lower()
    assert len(plan["segments"]) == 5, plan
    assert "relax" in text, text
    assert "weighted graph" in text, text
    assert "viral explaining" not in text, text
    assert plan["segments"][-1]["type"] == "question", plan
    print("[OK] request analysis - short fallback uses social visual beats")


def test_course_fallback_plan_uses_modular_long_form_segments():
    original_llm = request_analysis._llm_text
    try:
        request_analysis._llm_text = lambda *args, **kwargs: (_ for _ in ()).throw(
            TimeoutError("planner exceeded timeout")
        )
        plan = json.loads(
            create_narrated_plan(
                "Create a course lesson about binary search for beginners.",
                {
                    "domain": "computer_science",
                    "duration": 900,
                    "video_mode": "course",
                    "topic": "binary search",
                    "subtopics": ["sorted arrays", "midpoint", "halving"],
                },
            )
        )
    finally:
        request_analysis._llm_text = original_llm

    segments = plan["segments"]
    questions = [segment for segment in segments if segment.get("type") == "question"]

    assert plan["video_mode"] == "course", plan
    assert len(segments) >= 25, plan
    assert len(questions) >= 8, plan
    assert plan["duration_range"][0] == 600, plan
    assert all(segment.get("estimated_duration") for segment in segments), plan
    print("[OK] request analysis - course fallback uses modular long-form plan")


def test_coerce_completion_text_handles_proxy_shapes():
    """Live planner failure mode (issue #21): proxies sometimes pre-unwrap
    ``chat.completions.create`` and return a raw ``str`` or an OpenAI-shape
    ``dict`` instead of a typed ``ChatCompletion``. Without this shim, the
    planner silently dropped the response to ``""`` and surfaced as
    ``Empty narrated plan response``.
    """
    coerce = request_analysis._coerce_completion_text

    # Raw string: write through verbatim.
    assert coerce("plan text") == "plan text"

    # OpenAI-shape dict: extract choices[0].message.content.
    assert (
        coerce({"choices": [{"message": {"content": "from dict"}}]}) == "from dict"
    )

    # Bare {"content": "..."} fallback some proxies use.
    assert coerce({"content": "bare"}) == "bare"

    # Choice with .text instead of .message (legacy completion shape).
    assert coerce({"choices": [{"text": "legacy"}]}) == "legacy"

    # None / unknown shapes degrade to "" (planner then raises a clearer
    # "Empty narrated plan response" up the stack rather than crashing).
    assert coerce(None) == ""
    assert coerce({"unrecognised": "shape"}) == ""

    # Typed ChatCompletion-shaped object still works.
    from types import SimpleNamespace

    typed = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="typed"))]
    )
    assert coerce(typed) == "typed"


if __name__ == "__main__":
    test_short_mode_moves_existing_question_to_the_end()
    test_standard_mode_strips_question_segments()
    test_short_narration_tightening_keeps_sentence_boundaries()
    test_planning_helpers_accept_sparse_analysis_payloads()
    test_heuristic_analysis_routes_algorithm_prompts_to_cs()
    test_short_fallback_plan_uses_social_visual_beats()
    test_course_fallback_plan_uses_modular_long_form_segments()
    test_coerce_completion_text_handles_proxy_shapes()
    print("\nALL REQUEST ANALYSIS MODE CHECKS PASSED")
