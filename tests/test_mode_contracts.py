"""Mode contract registry checks."""

from algorithms.mode_contracts import (
    context_state_for_mode,
    final_duration_contract_min,
    mode_allows_final_duration_padding,
    upgrade_plan_for_mode,
)


class Profile:
    def __init__(self, mode: str):
        self.mode = mode
        self.target_duration = 900 if mode in {"course", "lecture"} else 240
        self.duration_range = (900, 900) if mode in {"course", "lecture"} else (180, 300)
        self.min_scenes = 15
        self.max_scenes = 40
        self.aspect = "16:9"
        self.questions = {"pause_seconds": 10}


def test_mode_contract_registry_sets_runtime_context():
    assert context_state_for_mode(Profile("standard"))["format_contract"] == "youtube_explainer"
    assert context_state_for_mode(Profile("course"))["course_checkpoint_enabled"] is True
    lecture_state = context_state_for_mode(Profile("lecture"))
    assert lecture_state["format_contract"] == "academic_lecture"
    assert lecture_state["minimum_label_font_size"] == 24
    assert context_state_for_mode(Profile("short"))["safe_y_range"] == "-6.5 to 6.5"
    print("[OK] mode contracts - runtime context is centralized")


def test_mode_contract_registry_applies_plan_upgrades():
    plan = {
        "video_mode": "lecture",
        "segments": [
            {
                "id": "scene_0",
                "type": "content",
                "narration": "Explain eigenvalues.",
                "visual_description": "Show a title.",
                "estimated_duration": 60,
            }
        ],
    }

    upgraded, label, strategy = upgrade_plan_for_mode(
        plan,
        "Make an academic lecture about eigenvalues.",
        {"topic": "eigenvalues", "domain": "math"},
        Profile("lecture"),
    )

    assert label == "Lecture"
    assert strategy == "replaced_thin_plan_with_academic_lecture"
    assert upgraded["lecture_contract"]["format"] == "academic_lecture"
    assert len(upgraded["segments"]) == 30
    print("[OK] mode contracts - plan upgrades route through registry")


def test_long_form_plan_upgrades_cap_oversized_scenelets():
    raw_segments = [
        {
            "id": f"scene_{idx}",
            "type": "content",
            "narration": f"Detailed content {idx}",
            "visual_description": "Animate, transform, trace, compare the idea.",
            "estimated_duration": 90,
            "animation_steps": ["animate the setup", "transform the relation"],
        }
        for idx in range(30)
    ]

    upgraded, _, _ = upgrade_plan_for_mode(
        {"video_mode": "course", "segments": raw_segments},
        "Make a course about matrices.",
        {"topic": "matrices", "domain": "math"},
        Profile("course"),
    )

    content_durations = [
        segment["estimated_duration"]
        for segment in upgraded["segments"]
        if segment.get("type") == "content"
    ]
    assert content_durations
    assert max(content_durations) <= 35
    print("[OK] mode contracts - oversized scenelets are capped during upgrade")


def test_mode_contract_registry_defines_final_duration_policy():
    assert final_duration_contract_min(Profile("standard")) == (175, "standard")
    assert final_duration_contract_min(Profile("lecture")) == (870, "lecture")
    assert mode_allows_final_duration_padding(Profile("short")) is False
    assert mode_allows_final_duration_padding(Profile("lecture")) is True
    print("[OK] mode contracts - final duration policy is centralized")


if __name__ == "__main__":
    test_mode_contract_registry_sets_runtime_context()
    test_mode_contract_registry_applies_plan_upgrades()
    test_long_form_plan_upgrades_cap_oversized_scenelets()
    test_mode_contract_registry_defines_final_duration_policy()
    print("\nALL MODE CONTRACT CHECKS PASSED")
