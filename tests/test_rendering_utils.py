"""Rendering helper safety checks."""

import os
import tempfile
import time
from pathlib import Path

import algorithms.media_tools as media_tools
import algorithms.rendering as rendering
from algorithms.media_tools import validate_video_file
from algorithms.rendering import (
    build_manim_render_command,
    cleanup_manim_partials,
    find_video_file,
    inject_manim_frame_config,
    render_manim_code,
)


def test_find_video_file_rejects_path_segments():
    assert find_video_file("../secret.mp4") is None
    assert find_video_file("..\\secret.mp4") is None
    assert find_video_file("C:secret.mp4") is None
    assert find_video_file("video.txt") is None
    print("[OK] rendering utils - file lookup rejects unsafe names")


def test_find_video_file_avoids_prefix_collisions():
    original_outputs = rendering.OUTPUTS
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rendering.OUTPUTS = Path(tmp)
            wanted = (
                rendering.OUTPUTS
                / "videos"
                / "video_1"
                / "720p30"
                / "video_1_retry.mp4"
            )
            collision = (
                rendering.OUTPUTS
                / "videos"
                / "video_10"
                / "720p30"
                / "video_10.mp4"
            )
            wanted.parent.mkdir(parents=True)
            collision.parent.mkdir(parents=True)
            wanted.write_bytes(b"wanted")
            collision.write_bytes(b"collision")

            assert find_video_file("video_1") == wanted
            assert collision not in rendering._matching_render_files("video_1")
    finally:
        rendering.OUTPUTS = original_outputs
    print("[OK] rendering utils - file lookup avoids prefix collisions")


def test_find_video_file_can_serve_old_outputs_when_age_disabled():
    original_outputs = rendering.OUTPUTS
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rendering.OUTPUTS = Path(tmp)
            old_video = (
                rendering.OUTPUTS
                / "videos"
                / "video_old"
                / "720p30"
                / "video_old.mp4"
            )
            old_video.parent.mkdir(parents=True)
            old_video.write_bytes(b"old")
            old_time = time.time() - 3600
            os.utime(old_video, (old_time, old_time))

            assert find_video_file("video_old") is None
            assert find_video_file("video_old", max_age_seconds=None) == old_video
    finally:
        rendering.OUTPUTS = original_outputs
    print("[OK] rendering utils - old outputs can be served without age cutoff")


def test_render_helpers_reject_unsafe_filenames_before_writing():
    try:
        build_manim_render_command(Path("scene.py"), "../escape.mp4")
        raise AssertionError("Expected unsafe output filename rejection")
    except ValueError:
        pass

    try:
        render_manim_code("from manim import *", "../escape")
        raise AssertionError("Expected unsafe render filename rejection")
    except ValueError:
        pass

    print("[OK] rendering utils - render helpers reject unsafe filenames")


def test_vertical_render_injects_phone_coordinate_frame():
    code = "from manim import *\n\nclass GeneratedScene(Scene):\n    pass\n"

    configured = inject_manim_frame_config(code, (720, 1280))

    assert "config.frame_width = 8" in configured
    assert "config.frame_height = 14.2222" in configured
    assert "_NIMA_ORIGINAL_TEXT = Text" in configured
    assert configured.index("config.frame_width") > configured.index("from manim import *")
    compile(configured, "<configured>", "exec")
    print("[OK] rendering utils - vertical renders get phone coordinate frame")


def test_horizontal_render_keeps_default_coordinate_frame():
    code = "from manim import *\n\nclass GeneratedScene(Scene):\n    pass\n"

    configured = inject_manim_frame_config(code, None)

    assert configured == code
    print("[OK] rendering utils - horizontal renders keep default frame")


def test_cleanup_manim_partials_removes_only_adjacent_cache():
    with tempfile.TemporaryDirectory() as tmp:
        render_dir = Path(tmp) / "videos" / "video_demo" / "720p30"
        render_dir.mkdir(parents=True)
        video = render_dir / "video_demo.mp4"
        video.write_bytes(b"mp4")
        partial = render_dir / "partial_movie_files" / "GeneratedScene"
        partial.mkdir(parents=True)
        (partial / "chunk.mp4").write_bytes(b"chunk")
        sibling = render_dir.parent / "partial_movie_files"
        sibling.mkdir()

        cleanup_manim_partials(video)

        assert video.exists()
        assert not (render_dir / "partial_movie_files").exists()
        assert sibling.exists()

    print("[OK] rendering utils - Manim partial cache cleaned after final render")


def test_video_validation_rejects_missing_and_tiny_files():
    with tempfile.TemporaryDirectory() as tmp:
        missing = validate_video_file(Path(tmp) / "missing.mp4")
        assert not missing.ok
        assert "missing file" in missing.error

        tiny_path = Path(tmp) / "tiny.mp4"
        tiny_path.write_bytes(b"x")
        tiny = validate_video_file(tiny_path)
        assert not tiny.ok
        assert "too small" in tiny.error
        assert tiny.size_bytes == 1

        large_path = Path(tmp) / "large.mp4"
        large_path.write_bytes(b"x" * 2048)
        large_no_decode = validate_video_file(large_path, decode=False)
        assert large_no_decode.ok
        assert large_no_decode.size_bytes == 2048

    print("[OK] rendering utils - video integrity rejects missing and tiny outputs")


def test_video_validation_rejects_too_short_duration():
    original_probe = media_tools.probe_media_duration_seconds
    try:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "decode-skipped.mp4"
            video.write_bytes(b"x" * 4096)
            media_tools.probe_media_duration_seconds = lambda path: 0.1

            result = validate_video_file(video, decode=False)

            assert not result.ok
            assert "duration too short" in result.error
            assert result.duration_seconds == 0.1
    finally:
        media_tools.probe_media_duration_seconds = original_probe

    print("[OK] rendering utils - video integrity rejects near-zero duration")


if __name__ == "__main__":
    test_find_video_file_rejects_path_segments()
    test_find_video_file_avoids_prefix_collisions()
    test_find_video_file_can_serve_old_outputs_when_age_disabled()
    test_render_helpers_reject_unsafe_filenames_before_writing()
    test_vertical_render_injects_phone_coordinate_frame()
    test_horizontal_render_keeps_default_coordinate_frame()
    test_cleanup_manim_partials_removes_only_adjacent_cache()
    test_video_validation_rejects_missing_and_tiny_files()
    test_video_validation_rejects_too_short_duration()
    print("\nALL RENDERING UTIL CHECKS PASSED")
