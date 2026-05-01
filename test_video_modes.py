"""Regression checks for centralized video-mode profiles."""

from algorithms.video_modes import (
    VERTICAL_SHORT_RESOLUTION,
    apply_video_mode_to_analysis,
    build_video_mode_profile,
    normalize_video_mode,
)


def test_short_profile_drives_vertical_strict_rendering():
    profile = build_video_mode_profile("short", is_fast=False, draft=False)

    assert profile.mode == "short"
    assert profile.aspect == "9:16"
    assert profile.render_resolution == VERTICAL_SHORT_RESOLUTION
    assert profile.min_success_ratio == 1.0
    assert profile.duration_range == (55, 60)
    print("[OK] video modes - short profile is vertical and strict")


def test_lecture_profile_is_capped_until_long_form_renderer_is_ready():
    profile = build_video_mode_profile("lecture", is_fast=False, draft=False)

    assert profile.mode == "lecture"
    assert profile.capped is True
    assert profile.target_duration == 900
    assert profile.duration_range == (900, 900)
    assert profile.max_scenes == 30
    assert profile.scene_timeout_seconds >= 300
    assert profile.scene_timeout_seconds < 420
    print("[OK] video modes - lecture profile is intentionally capped")


def test_course_profile_uses_scenelet_timeout():
    profile = build_video_mode_profile("course", is_fast=False, draft=False)

    assert profile.mode == "course"
    assert profile.max_scenes == 40
    assert profile.min_success_ratio == 0.90
    assert profile.scene_timeout_seconds >= 240
    assert profile.scene_timeout_seconds < 420
    print("[OK] video modes - course profile uses shorter scenelet timeout")


def test_standard_profile_requires_near_complete_render():
    profile = build_video_mode_profile("standard", is_fast=False, draft=False)

    assert profile.min_success_ratio == 0.875
    print("[OK] video modes - standard profile rejects weak partial renders")


def test_mode_application_overrides_stale_analysis_fields():
    analysis = {
        "video_mode": "standard",
        "target_duration": 999,
        "aspect": "16:9",
    }

    merged = apply_video_mode_to_analysis(analysis, "short")

    assert merged["video_mode"] == "short"
    assert merged["target_duration"] == 58
    assert merged["aspect"] == "9:16"
    assert merged["render_resolution"] == VERTICAL_SHORT_RESOLUTION
    assert normalize_video_mode("unknown") == "standard"
    print("[OK] video modes - mode application replaces stale analysis")


def test_draft_profile_uses_preview_quality():
    profile = build_video_mode_profile("standard", is_fast=False, draft=True)

    assert profile.quality_flag == "-ql"
    assert profile.fps == 10
    assert profile.render_retries == 1
    print("[OK] video modes - draft profile uses preview render settings")


def test_full_profile_uses_production_quality():
    profile = build_video_mode_profile("standard", is_fast=False, draft=False)

    assert profile.quality_flag == "-qm"
    assert profile.fps == 30
    print("[OK] video modes - full profile uses production render settings")


if __name__ == "__main__":
    test_short_profile_drives_vertical_strict_rendering()
    test_lecture_profile_is_capped_until_long_form_renderer_is_ready()
    test_course_profile_uses_scenelet_timeout()
    test_standard_profile_requires_near_complete_render()
    test_mode_application_overrides_stale_analysis_fields()
    test_draft_profile_uses_preview_quality()
    test_full_profile_uses_production_quality()
    print("\nALL VIDEO MODE CHECKS PASSED")
