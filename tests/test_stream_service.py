"""Deterministic streaming service smoke without LLM or Manim."""

import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["USE_DATABASE"] = "false"

import algorithms.stream_service as stream_service
from algorithms.media_tools import VideoValidationResult
from algorithms.stream_service import StreamServiceDeps, stream_generate_and_render_job


_ORIGINAL_OUTPUTS = stream_service.OUTPUTS
_ORIGINAL_VALIDATE_VIDEO_FILE = stream_service.validate_video_file
_ORIGINAL_ANALYZE_VIDEO_FRAMES = stream_service.analyze_video_frames
TEST_OUTPUTS = Path(tempfile.mkdtemp(prefix="nima-stream-service-test-"))
stream_service.OUTPUTS = TEST_OUTPUTS
stream_service.validate_video_file = lambda path: VideoValidationResult(
    ok=True, size_bytes=2048
)
stream_service.analyze_video_frames = lambda path: {
    "ok": True,
    "score": 100,
    "warnings": [],
    "sampled_frames": 1,
    "frames": [],
}


def _cleanup_test_outputs() -> None:
    stream_service.OUTPUTS = _ORIGINAL_OUTPUTS
    stream_service.validate_video_file = _ORIGINAL_VALIDATE_VIDEO_FILE
    stream_service.analyze_video_frames = _ORIGINAL_ANALYZE_VIDEO_FRAMES
    shutil.rmtree(TEST_OUTPUTS, ignore_errors=True)


atexit.register(_cleanup_test_outputs)


def _dummy_video(name: str) -> Path:
    dummy_video = TEST_OUTPUTS / name
    dummy_video.parent.mkdir(parents=True, exist_ok=True)
    dummy_video.write_bytes(b"not-a-real-mp4-but-enough-for-copy")
    return dummy_video


def _install_stubs(status: dict, webhooks: list, stream_result):
    def update_status(_job_id: str, **updates):
        status.update(updates)
        return dict(status)

    def finish_status(_job_id: str, **updates):
        status.update(updates)
        return dict(status)

    def trigger_webhooks(_job_id: str, event: str, payload: dict):
        webhooks.append((event, payload))

    stream_service.analyze_request_type = lambda prompt: {
        "domain": "general",
        "duration": 120,
        "topic": "stub",
    }
    stream_service.create_narrated_plan = lambda prompt, analysis: json.dumps(
        {
            "segments": [
                {
                    "id": "scene_0",
                    "narration": "A short deterministic scene.",
                    "estimated_duration": 1,
                }
            ]
        }
    )
    stream_service.split_plan_into_scenes = lambda plan_data, max_scenes: [
        {"scene_id": "scene_0", "description": "deterministic scene"}
    ]
    stream_service.choose_visual_template = (
        lambda prompt, analysis, visual_template=None: "default"
    )
    stream_service.apply_visual_template = lambda context, template_id: context
    stream_service.stream_render_scenes = stream_result

    return StreamServiceDeps(
        update_status=update_status,
        finish_status=finish_status,
        trigger_webhooks=trigger_webhooks,
    )


def test_stream_service_smoke() -> None:
    job_id = "streamsvc001"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub.mp4")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video)],
            kwargs["narrative_context"],
            [],
            {0: (str(dummy_video), True, "")},
        ),
    )

    output, scene_results, _ = stream_generate_and_render_job(
        "Explain a stub scene",
        job_id,
        voiceover=False,
        video_mode="standard",
        deps=deps,
    )

    assert status.get("status") == "done", status
    assert status.get("partial") is False, status
    assert status.get("video_integrity", {}).get("ok") is True, status
    assert status.get("video_quality", {}).get("ok") is True, status
    assert Path(output).exists(), output
    assert scene_results and scene_results[0].get("status") == "done", scene_results
    assert webhooks and webhooks[0][0] == "render.complete", webhooks
    print(f"[OK] stream service smoke output={output}")


def test_successful_completed_render_overrides_stale_error() -> None:
    job_id = "streamsvc002"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub_recovered.mp4")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video)],
            kwargs["narrative_context"],
            [{"scene": 0, "error": "initial generation failed", "type": "generation"}],
            {0: (str(dummy_video), True, "")},
        ),
    )

    _, scene_results, _ = stream_generate_and_render_job(
        "Explain a recovered stub scene",
        job_id,
        voiceover=False,
        video_mode="standard",
        deps=deps,
    )

    assert status.get("status") == "done", status
    assert status.get("partial") is False, status
    assert scene_results[0]["status"] == "done", scene_results
    assert scene_results[0]["error"] is None, scene_results
    assert scene_results[0]["video_path"] == str(dummy_video), scene_results
    print("[OK] stream service - successful render wins over stale retry error")


def test_voiceover_uses_final_scene_list_after_splitting() -> None:
    job_id = "streamsvc003"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub_voiceover.mp4")
    captured_tts_segments = []

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video), str(dummy_video)],
            kwargs["narrative_context"],
            [],
            {
                0: (str(dummy_video), True, ""),
                1: (str(dummy_video), True, ""),
            },
        ),
    )
    from algorithms.streaming import split_plan_into_scenes as real_split_plan_into_scenes

    original_split = stream_service.split_plan_into_scenes
    original_generate_voiceover = stream_service.generate_voiceover
    original_merge_audio_video = stream_service.merge_audio_video
    original_audio_probe = stream_service.media_has_audio_stream
    original_stitch_scenes = stream_service.stitch_scenes
    try:
        stream_service.create_narrated_plan = lambda prompt, analysis: json.dumps(
            {
                "segments": [
                    {"id": "scene_0", "narration": "Original content zero"},
                    {"id": "scene_1", "narration": "Original dropped content"},
                    {"id": "final_question", "narration": "Original final question"},
                ]
            }
        )
        stream_service.split_plan_into_scenes = lambda plan_data, max_scenes: [
            {
                "scene_id": "scene_0",
                "description": "Selected content",
                "narration": "Selected content narration",
                "duration_hint": 8,
            },
            {
                "scene_id": "final_question",
                "description": "Selected final question",
                "narration": "Selected final question narration",
                "duration_hint": 5,
                "type": "question",
            },
        ]

        def fake_generate_voiceover(segments, output_dir, voice=None):
            captured_tts_segments.extend(segments)
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            for segment in segments:
                Path(output_dir, f"{segment['id']}.mp3").write_bytes(b"fake-audio")
            return {
                segment["id"]: {
                    "path": f"{output_dir}/{segment['id']}.mp3",
                    "duration": segment["estimated_duration"],
                    "error": None,
                }
                for segment in segments
            }

        stream_service.generate_voiceover = fake_generate_voiceover
        stream_service.merge_audio_video = (
            lambda video_path, audio_segments, segment_order, output_path: video_path
        )
        stream_service.media_has_audio_stream = lambda path: True
        stream_service.stitch_scenes = (
            lambda video_paths, output, fps=30: video_paths[0]
        )

        stream_generate_and_render_job(
            "Explain a short scene with a final question",
            job_id,
            voiceover=True,
            video_mode="short",
            deps=deps,
        )
    finally:
        stream_service.split_plan_into_scenes = real_split_plan_into_scenes
        stream_service.generate_voiceover = original_generate_voiceover
        stream_service.merge_audio_video = original_merge_audio_video
        stream_service.media_has_audio_stream = original_audio_probe
        stream_service.stitch_scenes = original_stitch_scenes

    assert [segment["narration"] for segment in captured_tts_segments] == [
        "Selected content narration",
        "Selected final question narration",
    ]
    assert captured_tts_segments[-1]["id"] == "scene_1"
    print("[OK] stream service - voiceover follows final split scene list")


def test_intro_outro_do_not_inflate_partial_scene_counts() -> None:
    job_id = "streamsvc004"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub_partial.mp4")
    intro_video = _dummy_video("stream_service_stub_intro.mp4")
    outro_video = _dummy_video("stream_service_stub_outro.mp4")
    final_video = _dummy_video("stream_service_stub_partial_final.mp4")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video)] * 7,
            kwargs["narrative_context"],
            [{"scene": 7, "error": "render failed", "type": "render"}],
            {idx: (str(dummy_video), True, "") for idx in range(7)},
        ),
    )
    original_split = stream_service.split_plan_into_scenes
    original_render_single_scene = stream_service._render_single_scene
    original_subprocess_run = stream_service.subprocess.run
    original_stitch_scenes = stream_service.stitch_scenes
    try:
        stream_service.split_plan_into_scenes = lambda plan_data, max_scenes: [
            {"scene_id": f"scene_{i}", "description": f"scene {i}"}
            for i in range(8)
        ]

        def fake_render_single_scene(*args, **kwargs):
            suffix = args[3]
            return (
                str(intro_video if suffix == "intro" else outro_video),
                True,
                "",
            )

        class FakeCompletedProcess:
            returncode = 1
            stderr = ""

        stream_service._render_single_scene = fake_render_single_scene
        stream_service.subprocess.run = lambda *args, **kwargs: FakeCompletedProcess()
        stream_service.stitch_scenes = (
            lambda video_paths, output, fps=30: str(final_video)
        )

        _, scene_results, _ = stream_generate_and_render_job(
            "Explain a partial render with intro and outro",
            job_id,
            voiceover=False,
            video_mode="standard",
            intro_outro={
                "enabled": True,
                "introText": "Intro",
                "outroText": "Outro",
            },
            deps=deps,
        )
    finally:
        stream_service.split_plan_into_scenes = original_split
        stream_service._render_single_scene = original_render_single_scene
        stream_service.subprocess.run = original_subprocess_run
        stream_service.stitch_scenes = original_stitch_scenes

    assert status.get("partial") is True, status
    assert status.get("message") == "Done (7/8 scenes)", status
    assert len(scene_results) == 8, scene_results
    assert sum(1 for result in scene_results if result["status"] == "done") == 7
    print("[OK] stream service - intro/outro clips do not inflate scene counts")


def test_final_video_integrity_failure_aborts_success_status() -> None:
    job_id = "streamsvc005"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub_invalid.mp4")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video)],
            kwargs["narrative_context"],
            [],
            {0: (str(dummy_video), True, "")},
        ),
    )
    original_validate = stream_service.validate_video_file
    try:
        stream_service.validate_video_file = lambda path: VideoValidationResult(
            ok=False,
            error="file too small to be a valid render: 34 bytes",
            size_bytes=34,
        )
        try:
            stream_generate_and_render_job(
                "Explain an invalid final render",
                job_id,
                voiceover=False,
                video_mode="standard",
                deps=deps,
            )
            raise AssertionError("Expected final integrity validation failure")
        except RuntimeError as exc:
            assert "Final video failed integrity check" in str(exc)
    finally:
        stream_service.validate_video_file = original_validate

    assert status.get("status") != "done", status
    assert not webhooks, webhooks
    print("[OK] stream service - invalid final video cannot be marked done")


def test_final_video_quality_failure_aborts_success_status() -> None:
    job_id = "streamsvc006"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub_quality_fail.mp4")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video)],
            kwargs["narrative_context"],
            [],
            {0: (str(dummy_video), True, "")},
        ),
    )
    original_analyze = stream_service.analyze_video_frames
    try:
        stream_service.analyze_video_frames = lambda path: {
            "ok": False,
            "score": 20,
            "warnings": ["4/4 sampled frames look blank"],
            "sampled_frames": 4,
            "frames": [],
        }
        try:
            stream_generate_and_render_job(
                "Explain a visually blank final render",
                job_id,
                voiceover=False,
                video_mode="standard",
                deps=deps,
            )
            raise AssertionError("Expected final frame-quality validation failure")
        except RuntimeError as exc:
            assert "Final video failed frame-quality check" in str(exc)
    finally:
        stream_service.analyze_video_frames = original_analyze

    assert status.get("status") != "done", status
    assert not webhooks, webhooks
    print("[OK] stream service - severe final frame quality cannot be marked done")


def test_long_form_final_mode_quality_failure_aborts_success_status() -> None:
    job_id = "streamsvc006q"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub_mode_quality_fail.mp4")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video)],
            kwargs["narrative_context"],
            [],
            {0: (str(dummy_video), True, "")},
        ),
    )
    original_analyze = stream_service.analyze_video_frames
    try:
        stream_service.analyze_video_frames = lambda path: {
            "ok": False,
            "score": 49,
            "warnings": ["8/12 sampled frames crowd frame edges"],
            "sampled_frames": 12,
            "frames": [
                {"blank": False, "tiny_content": False, "cluttered": False, "edge_crowded": True}
                for _ in range(8)
            ]
            + [
                {"blank": False, "tiny_content": False, "cluttered": False, "edge_crowded": False}
                for _ in range(4)
            ],
            "ocr": {"summary": {"max_overlap_ratio": 0.0, "max_edge_clip_ratio": 0.0}},
        }
        try:
            stream_generate_and_render_job(
                "Explain a low quality long-form final render",
                job_id,
                voiceover=False,
                video_mode="lecture",
                deps=deps,
            )
            raise AssertionError("Expected long-form mode frame-quality failure")
        except RuntimeError as exc:
            assert "Final video failed frame-quality check" in str(exc)
    finally:
        stream_service.analyze_video_frames = original_analyze

    assert status.get("status") != "done", status
    assert not webhooks, webhooks
    print("[OK] stream service - low-score long-form final quality cannot be marked done")


def test_long_form_final_duration_near_miss_is_padded() -> None:
    job_id = "streamsvc006b"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub_short_long_form.mp4")
    padded_video = _dummy_video("stream_service_stub_padded_long_form.mp4")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video)],
            kwargs["narrative_context"],
            [],
            {0: (str(dummy_video), True, "")},
        ),
    )
    original_validate = stream_service.validate_video_file
    original_pad = stream_service.pad_video_to_min_duration
    calls = {"pad": []}
    try:
        def fake_validate(path):
            if Path(path) == padded_video:
                return VideoValidationResult(
                    ok=True, size_bytes=2048, duration_seconds=999.0
                )
            return VideoValidationResult(
                ok=True, size_bytes=2048, duration_seconds=1.0
            )

        def fake_pad(path, min_duration_seconds, **kwargs):
            calls["pad"].append(
                {
                    "path": path,
                    "min_duration_seconds": min_duration_seconds,
                    "fps": kwargs.get("fps"),
                }
            )
            return str(padded_video)

        stream_service.validate_video_file = fake_validate
        stream_service.pad_video_to_min_duration = fake_pad

        output, _, _ = stream_generate_and_render_job(
            "Explain a standard render that lands slightly short",
            job_id,
            voiceover=False,
            video_mode="standard",
            deps=deps,
        )
    finally:
        stream_service.validate_video_file = original_validate
        stream_service.pad_video_to_min_duration = original_pad

    assert output == str(padded_video), output
    assert status.get("status") == "done", status
    assert status.get("video_file") == padded_video.name, status
    assert calls["pad"], calls
    assert calls["pad"][0]["min_duration_seconds"] > 1.0
    print("[OK] stream service - long-form near-miss finals are padded")


def test_short_final_quality_failure_uses_fallback_render() -> None:
    job_id = "streamsvc007"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub_short_bad.mp4")
    fallback_scene = _dummy_video("stream_service_stub_short_fallback_scene.mp4")
    fallback_final = _dummy_video("stream_service_stub_short_fallback_final.mp4")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video)],
            kwargs["narrative_context"],
            [],
            {0: (str(dummy_video), True, "")},
        ),
    )
    original_analyze = stream_service.analyze_video_frames
    original_fallback = stream_service._render_short_fallback_scene
    original_stitch = stream_service.stitch_scenes
    calls = {"analyze": 0, "fallback": 0}
    try:
        stream_service.analyze_video_frames = lambda path: (
            calls.__setitem__("analyze", calls["analyze"] + 1)
            or {
                "ok": calls["analyze"] > 1,
                "score": 100 if calls["analyze"] > 1 else 30,
                "warnings": [] if calls["analyze"] > 1 else ["crowded"],
                "sampled_frames": 4,
                "frames": [],
            }
        )

        def fake_fallback(*args, **kwargs):
            calls["fallback"] += 1
            return str(fallback_scene), True, "", args[1]

        stream_service._render_short_fallback_scene = fake_fallback
        stream_service.stitch_scenes = (
            lambda video_paths, output, fps=30: str(fallback_final)
        )

        output, scene_results, _ = stream_generate_and_render_job(
            "Explain a visually crowded short",
            job_id,
            voiceover=False,
            video_mode="short",
            deps=deps,
        )
    finally:
        stream_service.analyze_video_frames = original_analyze
        stream_service._render_short_fallback_scene = original_fallback
        stream_service.stitch_scenes = original_stitch

    assert status.get("status") == "done", status
    assert calls["fallback"] == 1
    assert Path(output).exists(), output
    assert scene_results[0]["video_path"] == str(fallback_scene)
    print("[OK] stream service - short final quality failure uses fallback render")


def test_short_final_fallback_reuses_already_deterministic_scene() -> None:
    """Closes #10: the job-level short fallback should reuse scenes that are
    already marked `_generation_source == "deterministic_short_fallback"` and
    have a valid prior render on disk, instead of re-rendering them."""
    job_id = "streamsvc007b"
    status = {}
    webhooks = []
    # The per-scene fallback already produced this MP4.
    prior_scene_video = _dummy_video("stream_service_already_det_scene.mp4")
    # If the bug recurs and we re-render, this would be the new path.
    rerender_scene = _dummy_video("stream_service_already_det_rerender.mp4")
    fallback_final = _dummy_video("stream_service_already_det_final.mp4")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(prior_scene_video)],
            kwargs["narrative_context"],
            [],
            {0: (str(prior_scene_video), True, "")},
        ),
    )
    original_analyze = stream_service.analyze_video_frames
    original_fallback = stream_service._render_short_fallback_scene
    original_stitch = stream_service.stitch_scenes
    original_split = stream_service.split_plan_into_scenes
    calls = {"analyze": 0, "fallback": 0}
    try:
        # Override the splitter to mark the scene as already deterministic —
        # this simulates the per-scene fallback path having already done its
        # work in `algorithms.streaming.generate_scene` (PR #6).
        stream_service.split_plan_into_scenes = lambda plan_data, max_scenes: [
            {
                "scene_id": "scene_0",
                "description": "deterministic scene",
                "_generation_source": "deterministic_short_fallback",
            }
        ]
        # Force the job-level fallback path: first analyze fails, second passes.
        stream_service.analyze_video_frames = lambda path: (
            calls.__setitem__("analyze", calls["analyze"] + 1)
            or {
                "ok": calls["analyze"] > 1,
                "score": 100 if calls["analyze"] > 1 else 30,
                "warnings": [] if calls["analyze"] > 1 else ["crowded"],
                "sampled_frames": 4,
                "frames": [],
            }
        )

        def fake_fallback(*args, **kwargs):  # pragma: no cover - must not run
            calls["fallback"] += 1
            return str(rerender_scene), True, "", args[1]

        stream_service._render_short_fallback_scene = fake_fallback
        stream_service.stitch_scenes = (
            lambda video_paths, output, fps=30: str(fallback_final)
        )

        output, scene_results, _ = stream_generate_and_render_job(
            "Explain a visually crowded short with already-deterministic scene",
            job_id,
            voiceover=False,
            video_mode="short",
            deps=deps,
        )
    finally:
        stream_service.analyze_video_frames = original_analyze
        stream_service._render_short_fallback_scene = original_fallback
        stream_service.stitch_scenes = original_stitch
        stream_service.split_plan_into_scenes = original_split

    assert status.get("status") == "done", status
    # Key assertion: the job-level retry must have skipped re-rendering.
    assert calls["fallback"] == 0, (
        "expected job-level final fallback to reuse already-deterministic "
        f"scene, but _render_short_fallback_scene was called {calls['fallback']} time(s)"
    )
    assert Path(output).exists(), output
    # The reused video path should be the prior per-scene fallback, not the rerender.
    assert scene_results[0]["video_path"] == str(prior_scene_video), scene_results
    print("[OK] stream service - already-deterministic short scene is reused, not re-rendered")


def test_short_final_fallback_preserves_scene_voiceover() -> None:
    job_id = "streamsvc008"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub_short_bad_voice.mp4")
    fallback_scene = _dummy_video("stream_service_stub_short_voice_fallback_scene.mp4")
    fallback_final = _dummy_video("stream_service_stub_short_voice_fallback_final.mp4")
    fallback_audio = TEST_OUTPUTS / "scene_0.mp3"
    fallback_audio.write_bytes(b"fake-audio")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video)],
            kwargs["narrative_context"],
            [],
            {0: (str(dummy_video), True, "")},
        ),
    )
    original_analyze = stream_service.analyze_video_frames
    original_fallback = stream_service._render_short_fallback_scene
    original_generate_voiceover = stream_service.generate_voiceover
    original_merge_audio_video = stream_service.merge_audio_video
    original_audio_probe = stream_service.media_has_audio_stream
    original_stitch = stream_service.stitch_scenes
    calls = {"analyze": 0, "merge": []}
    try:
        stream_service.analyze_video_frames = lambda path: (
            calls.__setitem__("analyze", calls["analyze"] + 1)
            or {
                "ok": calls["analyze"] > 1,
                "score": 100 if calls["analyze"] > 1 else 30,
                "warnings": [] if calls["analyze"] > 1 else ["crowded"],
                "sampled_frames": 4,
                "frames": [],
            }
        )
        stream_service.generate_voiceover = lambda segments, output_dir, voice=None: {
            "scene_0": {
                "path": str(fallback_audio),
                "duration": 1.0,
                "error": None,
            }
        }

        def fake_fallback(*args, **kwargs):
            return str(fallback_scene), True, "", args[1]

        def fake_merge(video_path, audio_segments, segment_order, output_path):
            Path(output_path).write_bytes(b"fake-merged-video")
            calls["merge"].append(
                {
                    "video_path": video_path,
                    "audio_segments": audio_segments,
                    "segment_order": segment_order,
                    "output_path": output_path,
                }
            )
            return output_path

        stream_service._render_short_fallback_scene = fake_fallback
        stream_service.merge_audio_video = fake_merge
        stream_service.media_has_audio_stream = lambda path: True
        stream_service.stitch_scenes = (
            lambda video_paths, output, fps=30: str(fallback_final)
        )

        stream_generate_and_render_job(
            "Explain a short with fallback voiceover",
            job_id,
            voiceover=True,
            video_mode="short",
            deps=deps,
        )
    finally:
        stream_service.analyze_video_frames = original_analyze
        stream_service._render_short_fallback_scene = original_fallback
        stream_service.generate_voiceover = original_generate_voiceover
        stream_service.merge_audio_video = original_merge_audio_video
        stream_service.media_has_audio_stream = original_audio_probe
        stream_service.stitch_scenes = original_stitch

    assert status.get("status") == "done", status
    assert status.get("video_quality", {}).get("fallback_used") is True, status
    assert status.get("video_quality", {}).get("fallback_audio_scene_count") == 1, status
    assert len(calls["merge"]) == 2, calls
    assert calls["merge"][-1]["video_path"] == str(fallback_scene), calls
    assert calls["merge"][-1]["segment_order"] == ["scene_0"], calls
    print("[OK] stream service - short fallback preserves scene voiceover")


def test_generated_voiceover_requires_final_audio_stream() -> None:
    job_id = "streamsvc009"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub_voiceover_no_audio.mp4")
    audio_path = TEST_OUTPUTS / "voiceover_no_audio_scene_0.mp3"
    audio_path.write_bytes(b"fake-audio")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video)],
            kwargs["narrative_context"],
            [],
            {0: (str(dummy_video), True, "")},
        ),
    )
    original_generate_voiceover = stream_service.generate_voiceover
    original_merge_audio_video = stream_service.merge_audio_video
    original_audio_probe = stream_service.media_has_audio_stream
    try:
        stream_service.generate_voiceover = lambda segments, output_dir, voice=None: {
            "scene_0": {
                "path": str(audio_path),
                "duration": 1.0,
                "error": None,
            }
        }
        stream_service.merge_audio_video = (
            lambda video_path, audio_segments, segment_order, output_path: video_path
        )
        stream_service.media_has_audio_stream = lambda path: False

        try:
            stream_generate_and_render_job(
                "Explain a voiceover that fails to mux",
                job_id,
                voiceover=True,
                video_mode="standard",
                deps=deps,
            )
            raise AssertionError("Expected missing final audio stream failure")
        except RuntimeError as exc:
            assert "final video has no audio stream" in str(exc)
    finally:
        stream_service.generate_voiceover = original_generate_voiceover
        stream_service.merge_audio_video = original_merge_audio_video
        stream_service.media_has_audio_stream = original_audio_probe

    assert status.get("status") != "done", status
    assert not webhooks, webhooks
    print("[OK] stream service - generated voiceover requires final audio stream")


def test_requested_voiceover_requires_generated_audio_segments() -> None:
    job_id = "streamsvc010"
    status = {}
    webhooks = []
    dummy_video = _dummy_video("stream_service_stub_voiceover_no_segments.mp4")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (
            [str(dummy_video)],
            kwargs["narrative_context"],
            [],
            {0: (str(dummy_video), True, "")},
        ),
    )
    original_generate_voiceover = stream_service.generate_voiceover
    try:
        stream_service.generate_voiceover = lambda segments, output_dir, voice=None: {
            "scene_0": {
                "path": None,
                "duration": 5.0,
                "error": "TTS provider unavailable",
            }
        }

        try:
            stream_generate_and_render_job(
                "Explain a voiceover that never generates",
                job_id,
                voiceover=True,
                video_mode="standard",
                deps=deps,
            )
            raise AssertionError("Expected missing generated voiceover failure")
        except RuntimeError as exc:
            assert "no scene audio was generated" in str(exc)
            assert "TTS provider unavailable" in str(exc)
    finally:
        stream_service.generate_voiceover = original_generate_voiceover

    assert status.get("status") != "done", status
    assert not webhooks, webhooks
    print("[OK] stream service - requested voiceover requires generated segments")


def test_short_draft_fast_path_skips_llm_scene_generation() -> None:
    job_id = "streamsvc011"
    status = {}
    webhooks = []
    final_video = _dummy_video("stream_service_short_draft_final.mp4")

    deps = _install_stubs(
        status,
        webhooks,
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("stream_render_scenes should not run")
        ),
    )
    original_draft = stream_service.DRAFT_PIPELINE
    original_fast_path = stream_service.SHORT_DRAFT_FAST_PATH
    original_analyze = stream_service.analyze_request_type
    original_create_plan = stream_service.create_narrated_plan
    from algorithms.streaming import split_plan_into_scenes as real_split_plan_into_scenes

    original_split = stream_service.split_plan_into_scenes
    original_fallback = stream_service._render_short_fallback_scene
    original_stitch = stream_service.stitch_scenes
    try:
        stream_service.DRAFT_PIPELINE = True
        stream_service.SHORT_DRAFT_FAST_PATH = True
        stream_service.analyze_request_type = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("analyze_request_type should not run")
        )
        stream_service.create_narrated_plan = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("create_narrated_plan should not run")
        )
        stream_service.split_plan_into_scenes = real_split_plan_into_scenes

        def fake_fallback(scene, context, scene_num, *args, **kwargs):
            return (
                str(_dummy_video(f"stream_service_short_draft_scene_{scene_num}.mp4")),
                True,
                "",
                context,
            )

        stream_service._render_short_fallback_scene = fake_fallback
        stream_service.stitch_scenes = (
            lambda video_paths, output, fps=30: str(final_video)
        )

        stream_generate_and_render_job(
            "Explain Dijkstra as a short draft",
            job_id,
            voiceover=False,
            video_mode="short",
            deps=deps,
        )
    finally:
        stream_service.DRAFT_PIPELINE = original_draft
        stream_service.SHORT_DRAFT_FAST_PATH = original_fast_path
        stream_service.analyze_request_type = original_analyze
        stream_service.create_narrated_plan = original_create_plan
        stream_service.split_plan_into_scenes = original_split
        stream_service._render_short_fallback_scene = original_fallback
        stream_service.stitch_scenes = original_stitch

    assert status.get("status") == "done", status
    assert status.get("video_quality", {}).get("deterministic_short_draft") is True
    assert len(status.get("scene_results", [])) == 5
    assert webhooks and webhooks[0][0] == "render.complete", webhooks
    print("[OK] stream service - draft short fast path skips LLM analysis and scene generation")


def test_course_mode_uses_course_plan_upgrade_before_rendering() -> None:
    job_id = "streamsvc012"
    status = {}
    webhooks = []
    final_video = _dummy_video("stream_service_course_final.mp4")
    captured = {}

    def update_status(_job_id: str, **updates):
        status.update(updates)
        return dict(status)

    def finish_status(_job_id: str, **updates):
        status.update(updates)
        return dict(status)

    def trigger_webhooks(_job_id: str, event: str, payload: dict):
        webhooks.append((event, payload))

    deps = StreamServiceDeps(
        update_status=update_status,
        finish_status=finish_status,
        trigger_webhooks=trigger_webhooks,
    )

    original_analyze = stream_service.analyze_request_type
    original_create_plan = stream_service.create_narrated_plan
    original_split = stream_service.split_plan_into_scenes
    original_render = stream_service.stream_render_scenes
    original_stitch = stream_service.stitch_scenes
    from algorithms.streaming import split_plan_into_scenes as real_split_plan_into_scenes

    try:
        stream_service.analyze_request_type = lambda prompt: {
            "domain": "computer_science",
            "duration": 900,
            "topic": "binary search",
        }
        stream_service.create_narrated_plan = lambda prompt, analysis: json.dumps(
            {
                "segments": [
                    {
                        "id": "scene_0",
                        "type": "content",
                        "narration": "Explain binary search.",
                        "visual_description": "Show a title.",
                        "estimated_duration": 20,
                    }
                ]
            }
        )
        stream_service.split_plan_into_scenes = real_split_plan_into_scenes

        def fake_render(**kwargs):
            scenes = kwargs["scenes"]
            captured["scenes"] = scenes
            captured["context"] = kwargs["narrative_context"]
            paths = []
            completed = {}
            for idx, _scene in enumerate(scenes):
                path = _dummy_video(f"stream_service_course_scene_{idx}.mp4")
                paths.append(str(path))
                completed[idx] = (str(path), True, "")
            return paths, kwargs["narrative_context"], [], completed

        stream_service.stream_render_scenes = fake_render
        stream_service.stitch_scenes = (
            lambda video_paths, output, fps=30: str(final_video)
        )

        stream_generate_and_render_job(
            "Make a course lesson about binary search using sorted boxes.",
            job_id,
            voiceover=False,
            video_mode="course",
            deps=deps,
        )
    finally:
        stream_service.analyze_request_type = original_analyze
        stream_service.create_narrated_plan = original_create_plan
        stream_service.split_plan_into_scenes = original_split
        stream_service.stream_render_scenes = original_render
        stream_service.stitch_scenes = original_stitch

    scenes = captured["scenes"]
    assert status.get("status") == "done", status
    assert status.get("video_mode") == "course", status
    assert len(scenes) == 40
    assert sum(1 for scene in scenes if scene.get("type") == "question") == 8
    assert all(scene.get("course_directives") for scene in scenes)
    assert captured["context"].domain_state["format_contract"] == "course_lesson"
    assert captured["context"].domain_state["duration_padding_enabled"] is True
    assert webhooks and webhooks[0][0] == "render.complete", webhooks
    print("[OK] stream service - course mode upgrades plan before rendering")


def test_lecture_mode_uses_lecture_plan_upgrade_before_rendering() -> None:
    job_id = "streamsvc013"
    status = {}
    webhooks = []
    final_video = _dummy_video("stream_service_lecture_final.mp4")
    captured = {}

    def update_status(_job_id: str, **updates):
        status.update(updates)
        return dict(status)

    def finish_status(_job_id: str, **updates):
        status.update(updates)
        return dict(status)

    def trigger_webhooks(_job_id: str, event: str, payload: dict):
        webhooks.append((event, payload))

    deps = StreamServiceDeps(
        update_status=update_status,
        finish_status=finish_status,
        trigger_webhooks=trigger_webhooks,
    )

    original_analyze = stream_service.analyze_request_type
    original_create_plan = stream_service.create_narrated_plan
    original_split = stream_service.split_plan_into_scenes
    original_render = stream_service.stream_render_scenes
    original_stitch = stream_service.stitch_scenes
    from algorithms.streaming import split_plan_into_scenes as real_split_plan_into_scenes

    try:
        stream_service.analyze_request_type = lambda prompt: {
            "domain": "math",
            "duration": 900,
            "topic": "eigenvalues",
        }
        stream_service.create_narrated_plan = lambda prompt, analysis: json.dumps(
            {
                "segments": [
                    {
                        "id": "scene_0",
                        "type": "content",
                        "narration": "Explain eigenvalues.",
                        "visual_description": "Show a title.",
                        "estimated_duration": 60,
                    }
                ]
            }
        )
        stream_service.split_plan_into_scenes = real_split_plan_into_scenes

        def fake_render(**kwargs):
            scenes = kwargs["scenes"]
            captured["scenes"] = scenes
            captured["context"] = kwargs["narrative_context"]
            paths = []
            completed = {}
            for idx, _scene in enumerate(scenes):
                path = _dummy_video(f"stream_service_lecture_scene_{idx}.mp4")
                paths.append(str(path))
                completed[idx] = (str(path), True, "")
            return paths, kwargs["narrative_context"], [], completed

        stream_service.stream_render_scenes = fake_render
        stream_service.stitch_scenes = (
            lambda video_paths, output, fps=30: str(final_video)
        )

        stream_generate_and_render_job(
            "Make an academic lecture about eigenvalues using matrices and proof steps.",
            job_id,
            voiceover=False,
            video_mode="lecture",
            deps=deps,
        )
    finally:
        stream_service.analyze_request_type = original_analyze
        stream_service.create_narrated_plan = original_create_plan
        stream_service.split_plan_into_scenes = original_split
        stream_service.stream_render_scenes = original_render
        stream_service.stitch_scenes = original_stitch

    scenes = captured["scenes"]
    assert status.get("status") == "done", status
    assert status.get("video_mode") == "lecture", status
    assert len(scenes) == 30
    assert sum(1 for scene in scenes if scene.get("type") == "question") == 6
    assert all(
        scene.get("lecture_directives")
        for scene in scenes
        if scene.get("type") != "question"
    )
    assert captured["context"].domain_state["format_contract"] == "academic_lecture"
    assert captured["context"].domain_state["duration_padding_enabled"] is True
    assert webhooks and webhooks[0][0] == "render.complete", webhooks
    print("[OK] stream service - lecture mode upgrades plan before rendering")


def main() -> int:
    test_stream_service_smoke()
    test_successful_completed_render_overrides_stale_error()
    test_voiceover_uses_final_scene_list_after_splitting()
    test_intro_outro_do_not_inflate_partial_scene_counts()
    test_final_video_integrity_failure_aborts_success_status()
    test_final_video_quality_failure_aborts_success_status()
    test_long_form_final_mode_quality_failure_aborts_success_status()
    test_long_form_final_duration_near_miss_is_padded()
    test_short_final_quality_failure_uses_fallback_render()
    test_short_final_fallback_preserves_scene_voiceover()
    test_generated_voiceover_requires_final_audio_stream()
    test_requested_voiceover_requires_generated_audio_segments()
    test_short_draft_fast_path_skips_llm_scene_generation()
    test_course_mode_uses_course_plan_upgrade_before_rendering()
    test_lecture_mode_uses_lecture_plan_upgrade_before_rendering()
    print("\nALL STREAM SERVICE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
