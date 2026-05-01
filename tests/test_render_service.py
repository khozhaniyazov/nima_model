"""Render service checks for post-render integrity gates."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import algorithms.render_service as render_service
from algorithms.media_tools import VideoValidationResult
from algorithms.render_service import RenderServiceDeps, save_and_render_job


def test_bulk_render_rejects_generated_voiceover_without_audio_stream() -> None:
    status = {}
    webhooks = []

    def update_status(_job_id: str, **updates):
        status.update(updates)
        return dict(status)

    def finish_status(_job_id: str, **updates):
        status.update(updates)
        return dict(status)

    def trigger_webhooks(_job_id: str, event: str, payload: dict):
        webhooks.append((event, payload))

    deps = RenderServiceDeps(
        update_status=update_status,
        finish_status=finish_status,
        trigger_webhooks=trigger_webhooks,
    )

    original_render = render_service.render_manim_code
    original_find_video = render_service.find_video_file
    original_validate = render_service.validate_video_file
    original_analyze = render_service.analyze_video_frames
    original_merge = render_service.merge_audio_video
    original_audio_probe = render_service.media_has_audio_stream
    original_cache_variant = render_service._render_cache_variant
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "bulk_voiceover_lost_audio.mp4"
            audio = root / "scene_0.mp3"
            video.write_bytes(b"fake-video")
            audio.write_bytes(b"fake-audio")

            render_service.render_manim_code = lambda *args, **kwargs: SimpleNamespace(
                returncode=0,
                stdout="",
                stderr="",
            )
            render_service.find_video_file = lambda filename: video
            render_service.validate_video_file = lambda path: VideoValidationResult(
                ok=True,
                size_bytes=2048,
                duration_seconds=1.0,
            )
            render_service.analyze_video_frames = lambda path: {
                "ok": True,
                "score": 100,
                "warnings": [],
                "sampled_frames": 1,
                "frames": [],
            }
            render_service.merge_audio_video = (
                lambda video_path, audio_segments, segment_order, output_path: video_path
            )
            render_service.media_has_audio_stream = lambda path: False
            render_service._render_cache_variant = lambda profile: {
                "mode": profile.mode,
                "test": "audio-gate",
            }

            save_and_render_job(
                "from manim import *\nclass GeneratedScene(Scene):\n    pass\n",
                "bulk_voiceover_lost_audio",
                "rendervoice001",
                deps=deps,
                audio_segments={
                    "scene_0": {
                        "path": str(audio),
                        "duration": 1.0,
                        "error": None,
                    }
                },
                segment_order=["scene_0"],
            )
    finally:
        render_service.render_manim_code = original_render
        render_service.find_video_file = original_find_video
        render_service.validate_video_file = original_validate
        render_service.analyze_video_frames = original_analyze
        render_service.merge_audio_video = original_merge
        render_service.media_has_audio_stream = original_audio_probe
        render_service._render_cache_variant = original_cache_variant

    assert status.get("status") == "error", status
    assert status.get("message") == "Rendered video lost voiceover audio", status
    assert webhooks and webhooks[-1][0] == "render.error", webhooks
    assert "no audio stream" in webhooks[-1][1]["error"], webhooks
    print("[OK] render service - generated voiceover requires final audio stream")


if __name__ == "__main__":
    test_bulk_render_rejects_generated_voiceover_without_audio_stream()
    print("\nALL RENDER SERVICE CHECKS PASSED")
