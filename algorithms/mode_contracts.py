"""Mode-specific planning and runtime contracts for streaming renders."""

from __future__ import annotations

from typing import Any

from algorithms.course import upgrade_course_plan_data
from algorithms.lecture import upgrade_lecture_plan_data
from algorithms.shorts import upgrade_short_plan_data
from algorithms.standard import upgrade_standard_plan_data


def upgrade_plan_for_mode(
    plan_data: dict,
    prompt: str,
    analysis: dict | None,
    profile: Any,
    *,
    short_draft_fast_path: bool = False,
) -> tuple[dict, str | None, Any]:
    """Apply the active mode's plan upgrade and return its strategy key/value."""
    mode = str(getattr(profile, "mode", "") or "").lower()
    if mode == "short" and not short_draft_fast_path:
        upgraded = upgrade_short_plan_data(plan_data, prompt, analysis, profile)
        return upgraded, "Short", upgraded.get("short_strategy")
    if mode == "standard":
        upgraded = upgrade_standard_plan_data(plan_data, prompt, analysis, profile)
        return upgraded, "Standard", upgraded.get("standard_strategy")
    if mode == "course":
        upgraded = upgrade_course_plan_data(plan_data, prompt, analysis, profile)
        return upgraded, "Course", upgraded.get("course_strategy")
    if mode == "lecture":
        upgraded = upgrade_lecture_plan_data(plan_data, prompt, analysis, profile)
        return upgraded, "Lecture", upgraded.get("lecture_strategy")
    return plan_data, None, None


def context_state_for_mode(profile: Any) -> dict[str, Any]:
    """Return NarrativeContext domain_state additions for the active mode."""
    mode = str(getattr(profile, "mode", "") or "").lower()
    questions = getattr(profile, "questions", {}) or {}
    if mode == "short":
        return {
            "safe_x_range": "-3.2 to 3.2",
            "safe_y_range": "-6.5 to 6.5",
            "minimum_label_font_size": 34,
        }
    if mode == "standard":
        return {
            "format_contract": "youtube_explainer",
            "duration_padding_enabled": True,
            "minimum_label_font_size": 28,
        }
    if mode == "course":
        return {
            "format_contract": "course_lesson",
            "duration_padding_enabled": True,
            "minimum_label_font_size": 24,
            "course_checkpoint_enabled": True,
            "course_question_pause_seconds": int(questions.get("pause_seconds", 10)),
        }
    if mode == "lecture":
        return {
            "format_contract": "academic_lecture",
            "duration_padding_enabled": True,
            "minimum_label_font_size": 24,
            "lecture_checkpoint_enabled": True,
            "lecture_question_pause_seconds": int(questions.get("pause_seconds", 10)),
        }
    return {}


def final_duration_contract_min(profile: Any) -> tuple[float | None, str]:
    """Return the minimum acceptable final duration and user-facing mode label."""
    mode = str(getattr(profile, "mode", "") or "").lower()
    duration_range = getattr(profile, "duration_range", (0, 0)) or (0, 0)
    lower = int(duration_range[0])
    if mode == "short":
        return max(1, lower - 1), "short"
    if mode == "standard":
        return max(1, lower - 5), "standard"
    if mode == "course":
        return max(1, lower - 30), "course"
    if mode == "lecture":
        return max(1, lower - 30), "lecture"
    return None, mode


def mode_allows_final_duration_padding(profile: Any) -> bool:
    """Return true when a stitched near-miss should be padded instead of failed."""
    return str(getattr(profile, "mode", "") or "").lower() in {
        "standard",
        "course",
        "lecture",
    }
