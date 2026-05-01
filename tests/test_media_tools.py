"""Media helper regression checks."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import algorithms.media_tools as media_tools


def test_media_has_audio_stream_detects_audio_track() -> None:
    original_run = media_tools.subprocess.run
    try:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "with_audio.mp4"
            video.write_bytes(b"fake-video")

            media_tools.subprocess.run = lambda *args, **kwargs: SimpleNamespace(
                returncode=0,
                stdout="0\n",
                stderr="",
            )

            assert media_tools.media_has_audio_stream(video) is True
    finally:
        media_tools.subprocess.run = original_run
    print("[OK] media tools - audio stream detected from ffprobe output")


def test_media_has_audio_stream_returns_false_without_audio_track() -> None:
    original_run = media_tools.subprocess.run
    try:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "silent.mp4"
            video.write_bytes(b"fake-video")

            media_tools.subprocess.run = lambda *args, **kwargs: SimpleNamespace(
                returncode=0,
                stdout="",
                stderr="",
            )

            assert media_tools.media_has_audio_stream(video) is False
    finally:
        media_tools.subprocess.run = original_run
    print("[OK] media tools - silent video reports no audio stream")


def test_media_has_audio_stream_falls_back_to_ffmpeg_probe() -> None:
    original_run = media_tools.subprocess.run
    calls = {"count": 0}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "with_audio_ffmpeg_only.mp4"
            video.write_bytes(b"fake-video")

            def fake_run(*args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise FileNotFoundError("ffprobe missing")
                return SimpleNamespace(
                    returncode=0,
                    stdout="",
                    stderr=(
                        "Input #0, mov, from 'x':\n"
                        "  Stream #0:0: Video: h264\n"
                        "  Stream #0:1: Audio: aac (LC), 44100 Hz, stereo\n"
                    ),
                )

            media_tools.subprocess.run = fake_run

            assert media_tools.media_has_audio_stream(video) is True
    finally:
        media_tools.subprocess.run = original_run
    print("[OK] media tools - ffmpeg fallback detects audio stream")


if __name__ == "__main__":
    test_media_has_audio_stream_detects_audio_track()
    test_media_has_audio_stream_returns_false_without_audio_track()
    test_media_has_audio_stream_falls_back_to_ffmpeg_probe()
    print("\nALL MEDIA TOOL CHECKS PASSED")
