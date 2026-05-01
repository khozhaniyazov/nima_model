"""Optional local OCR adapter checks."""

import os
import stat
import tempfile
from pathlib import Path

import algorithms.vision_adapters as vision_adapters


def _write_stub_command(path: Path, text: str) -> None:
    if os.name == "nt":
        path.write_text(f"@echo off\necho {text}\n", encoding="utf-8")
    else:
        path.write_text(f"#!/bin/sh\necho {text}\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_ocr_report_disabled_without_backend():
    original_backends = vision_adapters.available_ocr_backends
    try:
        vision_adapters.available_ocr_backends = lambda: []

        report = vision_adapters.analyze_frame_ocr_paths([Path("missing.png")])

        assert report["enabled"] is False
        assert report["backend"] is None
        assert report["sampled_frames"] == 0
        assert "no local OCR backend" in report["error"]
    finally:
        vision_adapters.available_ocr_backends = original_backends
    print("[OK] vision adapters - OCR disabled report is explicit")


def test_command_ocr_backend_extracts_text():
    original_command = os.environ.get("NIMA_OCR_COMMAND")
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
        try:
            temp_dir = Path(tmp)
            command_path = temp_dir / ("ocr_stub.cmd" if os.name == "nt" else "ocr_stub.sh")
            image_path = temp_dir / "frame.png"
            image_path.write_bytes(b"placeholder")
            _write_stub_command(command_path, "Clean title block")
            os.environ["NIMA_OCR_COMMAND"] = str(command_path)

            result = vision_adapters.extract_text_from_image(image_path, timeout=5)

            assert result["enabled"] is True
            assert result["backend"] == "command"
            assert result["text"] == "Clean title block"
            assert result["error"] == ""
        finally:
            if original_command is None:
                os.environ.pop("NIMA_OCR_COMMAND", None)
            else:
                os.environ["NIMA_OCR_COMMAND"] = original_command
    print("[OK] vision adapters - command OCR backend extracts text")


def test_frame_ocr_summary_counts_text_frames():
    original_command = os.environ.get("NIMA_OCR_COMMAND")
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
        try:
            temp_dir = Path(tmp)
            command_path = temp_dir / ("ocr_stub.cmd" if os.name == "nt" else "ocr_stub.sh")
            frames = [temp_dir / "frame_001.png", temp_dir / "frame_002.png"]
            for frame in frames:
                frame.write_bytes(b"placeholder")
            _write_stub_command(command_path, "Readable equation")
            os.environ["NIMA_OCR_COMMAND"] = str(command_path)

            report = vision_adapters.analyze_frame_ocr_paths(frames, timeout=5)

            assert report["enabled"] is True
            assert report["backend"] == "command"
            assert report["sampled_frames"] == 2
            assert report["text_frames"] == 2
            assert report["warnings"] == []
        finally:
            if original_command is None:
                os.environ.pop("NIMA_OCR_COMMAND", None)
            else:
                os.environ["NIMA_OCR_COMMAND"] = original_command
    print("[OK] vision adapters - OCR summary counts text-bearing frames")


def test_frame_ocr_summary_flags_overlapping_text_boxes():
    original_backends = vision_adapters.available_ocr_backends
    original_extract = vision_adapters.extract_text_from_image
    try:
        vision_adapters.available_ocr_backends = lambda: ["pytesseract"]

        def fake_extract(_path, timeout=20):
            return {
                "enabled": True,
                "backend": "pytesseract",
                "text": "alpha beta",
                "boxes": [
                    {
                        "x1": 10,
                        "y1": 10,
                        "x2": 90,
                        "y2": 40,
                        "text": "alpha",
                        "confidence": 0.9,
                    },
                    {
                        "x1": 40,
                        "y1": 12,
                        "x2": 120,
                        "y2": 42,
                        "text": "beta",
                        "confidence": 0.8,
                    },
                ],
                "text_boxes": 2,
                "overlap_ratio": 0.31,
                "edge_clip_ratio": 0.0,
                "mean_confidence": 0.85,
                "error": "",
            }

        vision_adapters.extract_text_from_image = fake_extract

        report = vision_adapters.analyze_frame_ocr_paths([Path("frame.png")])

        assert report["enabled"] is True
        assert report["summary"]["max_overlap_ratio"] == 0.31
        assert report["layout_warnings"] == ["OCR text overlap peak 0.31"]
    finally:
        vision_adapters.available_ocr_backends = original_backends
        vision_adapters.extract_text_from_image = original_extract
    print("[OK] vision adapters - OCR summary flags overlapping text boxes")


if __name__ == "__main__":
    test_ocr_report_disabled_without_backend()
    test_command_ocr_backend_extracts_text()
    test_frame_ocr_summary_counts_text_frames()
    test_frame_ocr_summary_flags_overlapping_text_boxes()
    print("\nALL VISION ADAPTER CHECKS PASSED")
