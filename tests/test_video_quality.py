"""Local frame quality heuristic checks."""

import tempfile
from pathlib import Path
from types import SimpleNamespace

import algorithms.video_quality as video_quality
from algorithms.video_quality import (
    analyze_frame_pixels,
    short_video_quality_requires_fallback,
    video_quality_requires_hard_failure,
    video_quality_requires_mode_recovery,
)


def _frame(width, height, fill=(0, 0, 0)):
    return [fill for _ in range(width * height)]


def test_blank_frame_detected():
    metrics = analyze_frame_pixels(80, 45, _frame(80, 45, (10, 10, 10)))

    assert metrics["blank"] is True
    assert metrics["foreground_ratio"] == 0
    print("[OK] video quality - blank frame detected")


def test_center_visual_not_marked_edge_crowded():
    width, height = 80, 45
    pixels = _frame(width, height, (0, 0, 0))
    for y in range(16, 29):
        for x in range(28, 52):
            pixels[y * width + x] = (240, 240, 240)

    metrics = analyze_frame_pixels(width, height, pixels)

    assert metrics["blank"] is False
    assert metrics["tiny_content"] is False
    assert metrics["cluttered"] is False
    assert metrics["edge_crowded"] is False
    print("[OK] video quality - centered visual passes local heuristics")


def test_tiny_center_visual_detected():
    width, height = 80, 45
    pixels = _frame(width, height, (0, 0, 0))
    for y in range(21, 24):
        for x in range(38, 42):
            pixels[y * width + x] = (240, 240, 240)

    metrics = analyze_frame_pixels(width, height, pixels)

    assert metrics["blank"] is False
    assert metrics["tiny_content"] is True
    print("[OK] video quality - tiny centered content detected")


def test_edge_crowding_detected():
    width, height = 80, 45
    pixels = _frame(width, height, (0, 0, 0))
    for y in range(height):
        for x in range(width):
            if x < 8 or x >= width - 8 or y < 6 or y >= height - 6:
                pixels[y * width + x] = (255, 255, 255)

    metrics = analyze_frame_pixels(width, height, pixels)

    assert metrics["edge_crowded"] is True
    print("[OK] video quality - edge crowding detected")


def test_single_top_title_is_not_edge_crowding():
    width, height = 80, 45
    pixels = _frame(width, height, (0, 0, 0))
    for y in range(1, 6):
        for x in range(18, 62):
            pixels[y * width + x] = (240, 240, 240)

    metrics = analyze_frame_pixels(width, height, pixels)

    assert metrics["touched_edges"] == 1
    assert metrics["edge_crowded"] is False
    print("[OK] video quality - top title alone is not edge crowding")


def test_clutter_detected():
    width, height = 80, 45
    pixels = _frame(width, height, (0, 0, 0))
    for y in range(height):
        for x in range(width):
            if y < 22 or (22 <= y < 26 and x % 2 == 0):
                pixels[y * width + x] = (230, 230, 230)

    metrics = analyze_frame_pixels(width, height, pixels)

    assert metrics["cluttered"] is True
    print("[OK] video quality - cluttered frame detected")


def test_video_frame_report_includes_optional_ocr_section():
    original_run = video_quality.subprocess.run
    original_read_png_rgb = video_quality._read_png_rgb
    original_ocr = video_quality.analyze_frame_ocr_paths
    with tempfile.TemporaryDirectory() as tmp:
        try:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"fake video")

            def fake_run(args, **_kwargs):
                Path(args[-1].replace("%03d", "001")).write_bytes(b"fake png")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            def fake_read_png_rgb(_path):
                pixels = _frame(80, 45, (0, 0, 0))
                for y in range(16, 29):
                    for x in range(28, 52):
                        pixels[y * 80 + x] = (240, 240, 240)
                return 80, 45, pixels

            expected_ocr = {
                "enabled": True,
                "backend": "command",
                "sampled_frames": 1,
                "text_frames": 1,
                "warnings": [],
                "error": "",
            }
            video_quality.subprocess.run = fake_run
            video_quality._read_png_rgb = fake_read_png_rgb
            video_quality.analyze_frame_ocr_paths = lambda paths, timeout=8: expected_ocr

            report = video_quality.analyze_video_frames(video, max_frames=1)

            assert report["ok"] is True
            assert report["ocr"] == expected_ocr
        finally:
            video_quality.subprocess.run = original_run
            video_quality._read_png_rgb = original_read_png_rgb
            video_quality.analyze_frame_ocr_paths = original_ocr
    print("[OK] video quality - frame report includes optional OCR section")


def test_video_frame_sampling_spreads_across_long_duration():
    original_run = video_quality.subprocess.run
    original_read_png_rgb = video_quality._read_png_rgb
    original_ocr = video_quality.analyze_frame_ocr_paths
    original_probe = video_quality.probe_media_duration_seconds
    commands = []
    with tempfile.TemporaryDirectory() as tmp:
        try:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"fake video")

            def fake_run(args, **_kwargs):
                commands.append(args)
                pattern = args[-1]
                for i in range(1, 5):
                    Path(pattern.replace("%03d", f"{i:03d}")).write_bytes(b"fake png")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            def fake_read_png_rgb(_path):
                pixels = _frame(80, 45, (0, 0, 0))
                for y in range(16, 29):
                    for x in range(28, 52):
                        pixels[y * 80 + x] = (240, 240, 240)
                return 80, 45, pixels

            video_quality.subprocess.run = fake_run
            video_quality._read_png_rgb = fake_read_png_rgb
            video_quality.analyze_frame_ocr_paths = lambda paths, timeout=8: {
                "enabled": False,
                "backend": None,
                "sampled_frames": 0,
                "text_frames": 0,
                "warnings": [],
                "layout_warnings": [],
                "summary": {},
                "error": "not run",
            }
            video_quality.probe_media_duration_seconds = lambda _path: 40.0

            report = video_quality.analyze_video_frames(video, max_frames=4)

            assert report["sampled_frames"] == 4
            assert any("fps=0.100000" in " ".join(cmd) for cmd in commands)
        finally:
            video_quality.subprocess.run = original_run
            video_quality._read_png_rgb = original_read_png_rgb
            video_quality.analyze_frame_ocr_paths = original_ocr
            video_quality.probe_media_duration_seconds = original_probe
    print("[OK] video quality - frame sampling spans long renders")


def test_video_frame_report_penalizes_ocr_overlap():
    original_run = video_quality.subprocess.run
    original_read_png_rgb = video_quality._read_png_rgb
    original_ocr = video_quality.analyze_frame_ocr_paths
    with tempfile.TemporaryDirectory() as tmp:
        try:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"fake video")

            def fake_run(args, **_kwargs):
                Path(args[-1].replace("%03d", "001")).write_bytes(b"fake png")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            pixels = _frame(80, 45, (0, 0, 0))
            for y in range(16, 29):
                for x in range(28, 52):
                    pixels[y * 80 + x] = (240, 240, 240)

            video_quality.subprocess.run = fake_run
            video_quality._read_png_rgb = lambda _path: (80, 45, pixels)
            video_quality.analyze_frame_ocr_paths = lambda paths, timeout=8: {
                "enabled": True,
                "backend": "pytesseract",
                "sampled_frames": 1,
                "text_frames": 1,
                "warnings": [],
                "layout_warnings": ["OCR text overlap peak 0.35"],
                "summary": {
                    "mean_text_boxes": 2,
                    "mean_overlap_ratio": 0.35,
                    "max_overlap_ratio": 0.35,
                    "max_edge_clip_ratio": 0.0,
                    "mean_confidence": 0.9,
                },
                "error": "",
            }

            report = video_quality.analyze_video_frames(video, max_frames=1)

            assert report["ok"] is False
            assert "OCR: OCR text overlap peak 0.35" in report["warnings"]
            assert report["score"] < 100
        finally:
            video_quality.subprocess.run = original_run
            video_quality._read_png_rgb = original_read_png_rgb
            video_quality.analyze_frame_ocr_paths = original_ocr
    print("[OK] video quality - OCR overlap lowers score and can fail quality")


def test_video_frame_report_fails_sustained_tiny_content():
    original_run = video_quality.subprocess.run
    original_read_png_rgb = video_quality._read_png_rgb
    original_ocr = video_quality.analyze_frame_ocr_paths
    with tempfile.TemporaryDirectory() as tmp:
        try:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"fake video")

            def fake_run(args, **_kwargs):
                pattern = args[-1]
                for i in range(1, 5):
                    Path(pattern.replace("%03d", f"{i:03d}")).write_bytes(b"fake png")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            def fake_read_png_rgb(_path):
                pixels = _frame(80, 45, (0, 0, 0))
                for y in range(21, 24):
                    for x in range(38, 42):
                        pixels[y * 80 + x] = (240, 240, 240)
                return 80, 45, pixels

            video_quality.subprocess.run = fake_run
            video_quality._read_png_rgb = fake_read_png_rgb
            video_quality.analyze_frame_ocr_paths = lambda paths, timeout=8: {
                "enabled": False,
                "backend": None,
                "sampled_frames": 0,
                "text_frames": 0,
                "warnings": [],
                "layout_warnings": [],
                "summary": {},
                "error": "not run",
            }

            report = video_quality.analyze_video_frames(video, max_frames=4)

            assert report["ok"] is False
            assert "sampled frames have tiny content" in " ".join(report["warnings"])
        finally:
            video_quality.subprocess.run = original_run
            video_quality._read_png_rgb = original_read_png_rgb
            video_quality.analyze_frame_ocr_paths = original_ocr
    print("[OK] video quality - sustained tiny content fails quality")


def test_short_video_quality_gate_keeps_creative_non_severe_scenes():
    report = {
        "ok": True,
        "score": 80,
        "warnings": [],
        "frames": [],
        "ocr": {"text_frames": 0, "summary": {}},
    }

    assert short_video_quality_requires_fallback(report) is False

    severe_report = dict(report)
    severe_report["score"] = 65
    assert short_video_quality_requires_fallback(severe_report) is True
    print("[OK] video quality - short gate allows creative non-severe scenes")


def test_hard_quality_gate_separates_warnings_from_integrity_failures():
    warning_report = {
        "ok": False,
        "score": 64,
        "sampled_frames": 4,
        "warnings": [
            "1/4 sampled frames have tiny content",
            "2/4 sampled frames crowd frame edges",
        ],
        "frames": [
            {"blank": False, "tiny_content": True, "cluttered": False},
            {"blank": False, "tiny_content": False, "cluttered": False},
            {"blank": False, "tiny_content": False, "cluttered": False},
            {"blank": False, "tiny_content": False, "cluttered": False},
        ],
        "ocr": {"summary": {"max_overlap_ratio": 0.31, "max_edge_clip_ratio": 0.0}},
    }
    blank_report = {
        "ok": False,
        "score": 20,
        "sampled_frames": 4,
        "warnings": ["3/4 sampled frames look blank"],
        "frames": [
            {"blank": True, "tiny_content": False, "cluttered": False},
            {"blank": True, "tiny_content": False, "cluttered": False},
            {"blank": True, "tiny_content": False, "cluttered": False},
            {"blank": False, "tiny_content": False, "cluttered": False},
        ],
        "ocr": {"summary": {}},
    }

    assert video_quality_requires_hard_failure(warning_report) is False
    assert video_quality_requires_hard_failure(blank_report) is True
    print("[OK] video quality - hard gate preserves warnings without hiding blanks")


def test_mode_recovery_gate_retries_bad_long_form_layouts_once():
    warning_report = {
        "ok": True,
        "score": 76,
        "sampled_frames": 4,
        "warnings": ["3/4 sampled frames crowd frame edges"],
        "frames": [
            {"blank": False, "tiny_content": False, "cluttered": False, "edge_crowded": True},
            {"blank": False, "tiny_content": False, "cluttered": False, "edge_crowded": True},
            {"blank": False, "tiny_content": False, "cluttered": False, "edge_crowded": True},
            {"blank": False, "tiny_content": False, "cluttered": False, "edge_crowded": False},
        ],
        "ocr": {"summary": {"max_overlap_ratio": 0.0, "max_edge_clip_ratio": 0.0}},
    }
    clean_report = {
        "ok": True,
        "score": 84,
        "sampled_frames": 4,
        "warnings": [],
        "frames": [
            {"blank": False, "tiny_content": False, "cluttered": False, "edge_crowded": False}
            for _ in range(4)
        ],
        "ocr": {"summary": {"max_overlap_ratio": 0.0, "max_edge_clip_ratio": 0.0}},
    }

    assert video_quality_requires_mode_recovery(warning_report, "lecture") is True
    assert video_quality_requires_mode_recovery(warning_report, "short") is False
    assert video_quality_requires_mode_recovery(clean_report, "course") is False
    print("[OK] video quality - long-form mode gate retries bad layouts once")


def test_mode_recovery_gate_retries_standard_ocr_overlap():
    report = {
        "ok": True,
        "score": 78,
        "sampled_frames": 8,
        "warnings": ["OCR: OCR text overlap peak 0.21"],
        "frames": [
            {"blank": False, "tiny_content": False, "cluttered": False, "edge_crowded": False}
            for _ in range(8)
        ],
        "ocr": {"summary": {"max_overlap_ratio": 0.21, "max_edge_clip_ratio": 0.0}},
    }

    assert video_quality_requires_mode_recovery(report, "standard") is True
    print("[OK] video quality - standard mode retries OCR-overlapped layouts")


def test_final_standard_gate_allows_mild_transient_warnings():
    report = {
        "ok": False,
        "score": 63,
        "sampled_frames": 16,
        "warnings": [
            "1/16 sampled frames look blank",
            "OCR: OCR text overlap peak 0.15",
        ],
        "frames": [
            {"blank": False, "tiny_content": False, "cluttered": False, "edge_crowded": False}
            for _ in range(15)
        ]
        + [{"blank": True, "tiny_content": True, "cluttered": False, "edge_crowded": False}],
        "ocr": {"summary": {"max_overlap_ratio": 0.1518, "max_edge_clip_ratio": 0.25}},
    }

    assert video_quality_requires_mode_recovery(report, "standard") is True
    assert video_quality_requires_mode_recovery(report, "standard", final=True) is False
    print("[OK] video quality - final standard gate allows mild transient warnings")


if __name__ == "__main__":
    test_blank_frame_detected()
    test_center_visual_not_marked_edge_crowded()
    test_tiny_center_visual_detected()
    test_edge_crowding_detected()
    test_clutter_detected()
    test_video_frame_report_includes_optional_ocr_section()
    test_video_frame_report_penalizes_ocr_overlap()
    test_video_frame_report_fails_sustained_tiny_content()
    test_short_video_quality_gate_keeps_creative_non_severe_scenes()
    test_hard_quality_gate_separates_warnings_from_integrity_failures()
    test_mode_recovery_gate_retries_bad_long_form_layouts_once()
    print("\nALL VIDEO QUALITY CHECKS PASSED")
