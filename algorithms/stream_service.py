"""Streaming scene-by-scene render service."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from config import DEFAULT_VIDEO_MODE, DRAFT_PIPELINE, OUTPUTS, SHORT_DRAFT_FAST_PATH
from algorithms.media_tools import (
    apply_watermark_to_video,
    ffmpeg_command as _ffmpeg_command,
    media_has_audio_stream,
    pad_video_to_min_duration,
    validate_video_file,
)
from algorithms.request_analysis import (
    analyze_request_type,
    create_narrated_plan,
    heuristic_request_analysis,
)
from algorithms.streaming import (
    NarrativeContext,
    apply_visual_template,
    choose_visual_template,
    _render_short_fallback_scene,
    _render_single_scene,
    split_plan_into_scenes,
    stream_render_scenes,
    stitch_scenes,
)
from algorithms.mode_contracts import (
    context_state_for_mode,
    final_duration_contract_min,
    mode_allows_final_duration_padding,
    upgrade_plan_for_mode,
)
from algorithms.tts import generate_voiceover, merge_audio_video
from algorithms.video_quality import (
    analyze_video_frames,
    short_video_quality_requires_fallback,
    video_quality_requires_hard_failure,
    video_quality_requires_mode_recovery,
)
from algorithms.video_modes import apply_video_mode_to_analysis, build_video_mode_profile
from algorithms.webhook_service import render_event_payload


@dataclass
class StreamServiceDeps:
    update_status: Callable[..., dict] | None = None
    finish_status: Callable[..., dict] | None = None
    get_job_field: Callable[[str, str, Any], Any] | None = None
    trigger_webhooks: Callable[[str, str, dict], None] | None = None


def _noop_status(job_id: str, **updates: Any) -> dict:
    return dict(updates)


def _noop_get_job_field(job_id: str, key: str, default: Any = None) -> Any:
    return default


def _noop_trigger_webhooks(job_id: str, event: str, payload: dict) -> None:
    return None


def _preview_text(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    preview = text[:limit].rstrip()
    if " " in preview:
        preview = preview.rsplit(" ", 1)[0].rstrip(",;:")
    return f"{preview}..."


def _available_tts_segment_count(scene_tts: dict[int, dict] | None) -> int:
    """Count generated scene audio files that are available for muxing."""
    if not scene_tts:
        return 0
    count = 0
    for payload in scene_tts.values():
        path = payload.get("path") if isinstance(payload, dict) else None
        if path and Path(path).exists():
            count += 1
    return count


def _final_duration_contract_min(profile) -> tuple[float | None, str]:
    """Return the minimum acceptable final duration for a mode."""
    return final_duration_contract_min(profile)


def _enforce_final_duration_contract(
    final_output: str,
    profile,
    final_validation,
) -> tuple[str, Any]:
    """Pad long-form near-misses, then enforce the final duration contract."""
    min_duration, label = _final_duration_contract_min(profile)
    if min_duration is None or final_validation.duration_seconds is None:
        return final_output, final_validation

    if (
        final_validation.duration_seconds < min_duration
        and mode_allows_final_duration_padding(profile)
    ):
        padded_output = pad_video_to_min_duration(
            final_output,
            min_duration,
            fps=profile.fps,
        )
        if padded_output != final_output:
            final_output = padded_output
            final_validation = validate_video_file(final_output)

    if (
        final_validation.duration_seconds is not None
        and final_validation.duration_seconds < min_duration
    ):
        raise RuntimeError(
            f"Final {label} video missed duration contract: "
            f"{final_validation.duration_seconds:.1f}s < {min_duration}s"
        )
    return final_output, final_validation


def _make_short_draft_plan(prompt: str, analysis: dict, profile) -> dict:
    """Build a deterministic short plan for fast draft previews."""
    topic = (
        analysis.get("topic")
        or analysis.get("concept")
        or prompt
        or "the key idea"
    )
    topic = re.sub(r"\s+", " ", str(topic)).strip()
    if len(topic) > 72:
        topic = topic[:72].rsplit(" ", 1)[0].strip()

    return {
        "description": f"Fast deterministic short draft for {topic}",
        "video_mode": profile.mode,
        "target_duration": profile.target_duration,
        "duration_range": list(profile.duration_range),
        "min_scenes": 5,
        "max_scenes": 5,
        "aspect": profile.aspect,
        "segments": [
            {
                "id": "scene_0",
                "type": "hook",
                "description": f"Open with a fast visual hook for {topic}.",
                "narration": f"Here is the fastest way to see {topic}.",
                "estimated_duration": 10,
            },
            {
                "id": "scene_1",
                "type": "setup",
                "description": f"Set up the moving objects for {topic}.",
                "narration": f"First, lock onto the moving pieces for {topic}.",
                "estimated_duration": 10,
            },
            {
                "id": "scene_2",
                "type": "step",
                "description": f"Show the first useful update for {topic}.",
                "narration": "Now watch the first useful update.",
                "estimated_duration": 10,
            },
            {
                "id": "scene_3",
                "type": "result",
                "description": f"Reveal the result or reusable rule for {topic}.",
                "narration": "The reusable rule is the part that matters.",
                "estimated_duration": 10,
            },
            {
                "id": "scene_4",
                "type": "question",
                "description": "End with a quick viewer check.",
                "narration": "Your turn: predict the next step before moving on.",
                "estimated_duration": 10,
            },
        ],
    }


def _render_short_final_fallback(
    *,
    scenes: list[dict],
    narrative_context: NarrativeContext,
    filename: str,
    job_id: str,
    profile,
    final_output: str,
    watermark: dict | None,
    scene_tts: dict[int, dict] | None = None,
    existing_completed_renders: dict[int, tuple[str, bool, str]] | None = None,
) -> tuple[str, dict, dict[int, tuple[str, bool, str]]]:
    """Render deterministic short fallback scenes and stitch them as a final retry.

    When `existing_completed_renders` is supplied, scenes whose plan already
    carries `_generation_source == "deterministic_short_fallback"` (set by
    PR #6's per-scene fallback path in `algorithms.streaming.generate_scene`)
    AND whose prior MP4 is on disk and passes `validate_video_file` are
    reused verbatim instead of being re-rendered. This avoids re-running the
    deterministic short renderer over inputs that produce identical output.
    Closes #10.
    """
    fallback_paths: list[str] = []
    fallback_completed: dict[int, tuple[str, bool, str]] = {}
    fallback_context = narrative_context
    fallback_filename = f"{filename}_fallback"
    audio_scene_count = 0

    for scene_num, scene in enumerate(scenes):
        fallback_context.scene_index = scene_num

        prior = (existing_completed_renders or {}).get(scene_num)
        prior_path = prior[0] if prior else ""
        prior_ok = bool(prior and prior[1])
        if (
            prior_ok
            and prior_path
            and scene.get("_generation_source") == "deterministic_short_fallback"
            and Path(prior_path).exists()
            and validate_video_file(prior_path).ok
        ):
            print(
                f"[{job_id}] [STREAM] reusing deterministic short fallback "
                f"for scene {scene_num}"
            )
            path, ok, err = prior_path, True, ""
            fallback_completed[scene_num] = (path, ok, err)
            fallback_paths.append(path)
            continue

        path, ok, err, fallback_context = _render_short_fallback_scene(
            scene,
            fallback_context,
            scene_num,
            fallback_filename,
            job_id,
            profile.render_resolution,
            profile.quality_flag,
            profile.fps,
            profile.scene_timeout_seconds,
        )
        fallback_completed[scene_num] = (path or "", ok, err)
        if not (ok and path):
            raise RuntimeError(f"fallback scene {scene_num} failed: {err}")

        tts_payload = (scene_tts or {}).get(scene_num)
        if tts_payload and tts_payload.get("path"):
            narrated_scene = str(
                Path(path).with_name(f"{Path(path).stem}_tts.mp4")
            )
            merged = merge_audio_video(
                path,
                {f"scene_{scene_num}": tts_payload},
                [f"scene_{scene_num}"],
                narrated_scene,
            )
            if merged and Path(merged).exists():
                merged_validation = validate_video_file(merged)
                if merged_validation.ok:
                    path = merged
                    audio_scene_count += 1
                else:
                    print(
                        f"[{job_id}] [WARN] fallback scene {scene_num} audio merge "
                        f"failed validation: {merged_validation.error}"
                    )

        fallback_completed[scene_num] = (path or "", True, "")
        fallback_paths.append(path)

    fallback_output = str(Path(final_output).with_name(f"{Path(final_output).stem}_fallback.mp4"))
    if len(fallback_paths) == 1:
        shutil.copy2(fallback_paths[0], fallback_output)
    else:
        fallback_output = stitch_scenes(fallback_paths, fallback_output, fps=profile.fps)
    fallback_output = apply_watermark_to_video(fallback_output, watermark)

    fallback_validation = validate_video_file(fallback_output)
    if not fallback_validation.ok:
        raise RuntimeError(
            f"fallback final video failed integrity check: {fallback_validation.error}"
        )
    fallback_quality = analyze_video_frames(fallback_output)
    if not fallback_quality.get("ok", False):
        raise RuntimeError(
            "fallback final video failed frame-quality check: "
            + "; ".join(fallback_quality.get("warnings") or ["unknown issue"])
        )
    shutil.copy2(fallback_output, final_output)
    fallback_quality["fallback_used"] = True
    fallback_quality["fallback_audio_scene_count"] = audio_scene_count
    return final_output, fallback_quality, fallback_completed


def stream_generate_and_render_job(
    prompt: str,
    job_id: str,
    analysis: dict = None,
    voiceover: bool = False,
    voice: str = None,
    visual_template: str = None,
    intro_outro: dict = None,
    watermark: dict = None,
    video_mode: str = DEFAULT_VIDEO_MODE,
    *,
    deps: StreamServiceDeps,
) -> tuple[str, list[dict], Any]:
    """
    Streaming scene-by-scene generation with parallel render-while-generate.

    This replaces bulk generation (which times out on 10K+ chars) with:
      1. Split plan into individual scenes
      2. Generate scene N with narrative context
      3. Render scene N while generating scene N+1 (parallel)
      4. Scene-level retry on failure (not full pipeline restart)
      5. Stitch rendered scenes into final video

    Args:
        prompt: User's animation request
        job_id: Job identifier
        analysis: Optional pre-computed analysis dict
        voiceover: Whether to include voiceover
        voice: TTS voice preset

    Returns:
        Tuple of (final_video_path, scene_results, final_context)
        scene_results: List of {scene_num, status, video_path, error}
        final_context: NarrativeContext after all scenes
    """
    update_status = deps.update_status or _noop_status
    finish_status = deps.finish_status or update_status
    get_job_field = deps.get_job_field or _noop_get_job_field
    trigger_webhooks = deps.trigger_webhooks or _noop_trigger_webhooks
    print(f"\n[{job_id}] === STREAMING PIPELINE STARTED ===")
    profile = build_video_mode_profile(video_mode, streaming=True)
    requested_short_draft_fast_path = (
        profile.mode == "short" and DRAFT_PIPELINE and SHORT_DRAFT_FAST_PATH
    )

    # ── Step 1: Analyze request (if not provided) ────────────────────────
    if analysis is None:
        if requested_short_draft_fast_path:
            update_status(job_id, message="Analyzing request locally...")
            analysis = heuristic_request_analysis(prompt)
            print(
                "[STREAM] Short draft fast path: using local request analysis "
                f"(domain={analysis.get('domain')}, topic={analysis.get('topic')})"
            )
        else:
            update_status(job_id, message="Analyzing request (streaming)...")
            analysis = analyze_request_type(prompt)
            print(
                f"[STREAM] Domain: {analysis.get('domain')}, Duration: {analysis.get('duration')}s"
            )
    analysis = apply_video_mode_to_analysis(analysis, profile.mode)
    profile = build_video_mode_profile(analysis["video_mode"], streaming=True)
    video_mode = profile.mode
    short_draft_fast_path = (
        profile.mode == "short" and DRAFT_PIPELINE and SHORT_DRAFT_FAST_PATH
    )

    # ── Step 2: Create animation plan ─────────────────────────────────
    update_status(job_id, message="Creating animation plan...")

    if short_draft_fast_path:
        plan_data = _make_short_draft_plan(prompt, analysis, profile)
        plan = json.dumps(plan_data)
        print("[STREAM] Short draft fast path: using deterministic plan")
    else:
        plan = create_narrated_plan(prompt, analysis)
        print(f"[STREAM] Plan created ({len(plan)} chars)")

    # ── Step 3: Parse plan into scenes ─────────────────────────────────
    update_status(job_id, message="Splitting into scenes...")
    if not short_draft_fast_path:
        try:
            plan_data = json.loads(plan)
        except (json.JSONDecodeError, TypeError):
            # Fallback: treat as single scene
            plan_data = {
                "description": plan,
                "scenes": [{"id": "scene_0", "description": plan}],
            }
    plan_data["video_mode"] = profile.mode
    plan_data.setdefault("target_duration", profile.target_duration)
    plan_data.setdefault("duration_range", list(profile.duration_range))
    plan_data.setdefault("min_scenes", profile.min_scenes)
    plan_data.setdefault("max_scenes", profile.max_scenes)
    plan_data.setdefault("aspect", profile.aspect)
    plan_data, strategy_label, strategy = upgrade_plan_for_mode(
        plan_data,
        prompt,
        analysis,
        profile,
        short_draft_fast_path=short_draft_fast_path,
    )
    if strategy_label:
        print(f"[STREAM] {strategy_label} plan strategy: {strategy}")

    scenes = split_plan_into_scenes(plan_data, max_scenes=profile.max_scenes)
    print(
        f"[STREAM] Split into {len(scenes)} scenes "
        f"(mode={profile.mode}, aspect={profile.aspect}, fps={profile.fps})"
    )

    if not scenes:
        raise ValueError("Could not split plan into scenes — empty scene list")

    # ── Step 4: Initialize narrative context ───────────────────────────
    narrative_context = NarrativeContext.from_analysis(prompt, analysis)
    narrative_context.domain_state["video_mode"] = profile.mode
    narrative_context.domain_state["aspect"] = profile.aspect
    narrative_context.domain_state.update(context_state_for_mode(profile))
    visual_template = choose_visual_template(prompt, analysis, visual_template)
    narrative_context = apply_visual_template(narrative_context, visual_template)
    print(f"[STREAM] Visual template: {visual_template}")
    print(
        f"[STREAM] NarrativeContext initialized for {narrative_context.domain} domain"
    )

    # ── Step 5: Generate and render scenes in streaming pipeline ───────
    update_status(job_id, message=f"Generating {len(scenes)} scenes...")
    filename = f"video_{job_id}"

    if short_draft_fast_path:
        update_status(job_id, message="Rendering deterministic short draft...")
        narrative_context.domain_state["total_scenes"] = len(scenes)
        video_paths = []
        errors = []
        completed_renders = {}
        final_context = narrative_context
        for scene_num, scene in enumerate(scenes):
            final_context.scene_index = scene_num
            path, ok, err, final_context = _render_short_fallback_scene(
                scene,
                final_context,
                scene_num,
                filename,
                job_id,
                profile.render_resolution,
                profile.quality_flag,
                profile.fps,
                profile.scene_timeout_seconds,
            )
            completed_renders[scene_num] = (path or "", ok, err)
            if ok and path:
                video_paths.append(path)
            else:
                errors.append(
                    {
                        "scene": scene_num,
                        "error": err or "short draft fallback failed",
                        "type": "short_draft_fallback",
                    }
                )
    else:
        video_paths, final_context, errors, completed_renders = stream_render_scenes(
            scenes=scenes,
            job_id=job_id,
            narrative_context=narrative_context,
            filename=filename,
            max_scene_retries=profile.scene_retries,
            render_resolution=profile.render_resolution,
            quality_flag=profile.quality_flag,
            fps=profile.fps,
            scene_timeout_seconds=profile.scene_timeout_seconds,
        )

    errors = [
        err
        for err in errors
        if not (
            err.get("scene") in completed_renders
            and completed_renders[err.get("scene")][1]
        )
    ]

    print(
        f"[STREAM] Render results: {len(video_paths)} successful, {len(errors)} failed"
    )

    success_ratio = len(video_paths) / max(1, len(scenes))
    min_success_ratio = profile.min_success_ratio
    if success_ratio < min_success_ratio:
        raise RuntimeError(
            f"Streaming job aborted: only {len(video_paths)}/{len(scenes)} scenes rendered "
            f"({success_ratio:.0%} < required {min_success_ratio:.0%}). Errors: {errors[:5]}"
        )

    # ── Optional: Scene-level TTS generation and mux ───────────────────
    scene_tts = {}  # scene_num -> {path, duration, error}
    print(f"[STREAM] Voiceover={voiceover}")
    if voiceover:
        update_status(job_id, message="Generating scene voiceovers...")
        tts_segments = []
        for i, scene in enumerate(scenes):
            tts_segments.append(
                {
                    "id": f"scene_{i}",
                    "narration": (
                        scene.get("narration")
                        or scene.get("description")
                        or scene.get("title")
                        or ""
                    ).strip(),
                    "estimated_duration": scene.get("duration_hint", 8),
                }
            )
        tts_dir = str(OUTPUTS / f"tts_{job_id}")
        tts_failure_detail = ""
        try:
            tts_results = generate_voiceover(tts_segments, tts_dir, voice=voice)
            scene_tts = {
                int(k.split("_")[-1]): v for k, v in tts_results.items() if "_" in k
            }
        except Exception as e:
            print(f"[STREAM] [WARN] Scene TTS generation failed: {e}")
            tts_failure_detail = str(e)
            scene_tts = {}

        if _available_tts_segment_count(scene_tts) == 0:
            segment_errors = [
                str(payload.get("error"))
                for payload in scene_tts.values()
                if isinstance(payload, dict) and payload.get("error")
            ]
            if segment_errors:
                tts_failure_detail = "; ".join(segment_errors[:3])
            suffix = f": {tts_failure_detail}" if tts_failure_detail else ""
            raise RuntimeError(
                "Voiceover was requested but no scene audio was generated" + suffix
            )

        # Mux per-scene audio where available
        for scene_num, payload in list(completed_renders.items()):
            video_path, success, err = payload
            if not success or not video_path:
                continue
            tts_payload = scene_tts.get(scene_num)
            if not tts_payload or not tts_payload.get("path"):
                continue
            narrated_scene = str(
                Path(video_path).with_name(f"{Path(video_path).stem}_tts.mp4")
            )
            merged = merge_audio_video(
                video_path,
                {f"scene_{scene_num}": tts_payload},
                [f"scene_{scene_num}"],
                narrated_scene,
            )
            if merged and Path(merged).exists():
                completed_renders[scene_num] = (merged, True, "")

        # Rebuild ordered video_paths from completed_renders after mux
        video_paths = []
        for scene_num in sorted(completed_renders.keys()):
            vp, success, _ = completed_renders[scene_num]
            if success and vp:
                video_paths.append(vp)

    rendered_scene_count = sum(
        1
        for scene_num in range(len(scenes))
        if (completed_renders.get(scene_num) and completed_renders[scene_num][1])
    )

    # ── Optional: Intro/outro scenes ───────────────────────────────────
    intro_outro = intro_outro or {}
    if intro_outro.get("enabled"):
        bg = narrative_context.domain_state.get("background_color", "#0F1117")
        fg = narrative_context.domain_state.get("foreground_color", "#F5F7FA")

        def _render_text_card(card_text: str, suffix: str) -> str | None:
            if not card_text:
                return None
            safe = card_text.replace('"', '\\"')
            code = f'''from manim import *
class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = "{bg}"
        title = Text("{safe}", font_size=48, color="{fg}")
        subtitle = Text("NIMA", font_size=22, color="{fg}").next_to(title, DOWN, buff=0.4)
        self.play(FadeIn(title, shift=UP*0.3), FadeIn(subtitle, shift=DOWN*0.3), run_time=1.2)
        self.wait(2.2)
        self.play(FadeOut(title), FadeOut(subtitle), run_time=0.8)
'''
            path, ok, _ = _render_single_scene(
                code,
                filename,
                job_id,
                suffix,
                profile.render_resolution,
                profile.quality_flag,
                profile.fps,
                profile.scene_timeout_seconds,
            )
            if not (ok and path):
                return None

            # Add silent audio so stitched output keeps a consistent audio stream.
            silent_path = str(Path(path).with_name(f"{Path(path).stem}_silent.mp4"))
            result = subprocess.run(
                [
                    *_ffmpeg_command(),
                    "-y",
                    "-i",
                    path,
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-shortest",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    silent_path,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0 and Path(silent_path).exists():
                return silent_path
            return path

        intro_path = _render_text_card(
            (intro_outro.get("introText") or "").strip(), "intro"
        )
        outro_path = _render_text_card(
            (intro_outro.get("outroText") or "").strip(), "outro"
        )
        if intro_path:
            video_paths = [intro_path] + video_paths
        if outro_path:
            video_paths = video_paths + [outro_path]

    # ── Step 6: Stitch scenes into final video ─────────────────────────
    if len(video_paths) == 0:
        raise RuntimeError(f"All scenes failed to render: {errors}")

    update_status(job_id, message="Stitching scenes...")
    final_output = str(OUTPUTS / f"{filename}_stream.mp4")

    if len(video_paths) == 1:
        # Single scene — use directly
        shutil.copy2(video_paths[0], final_output)
        print(f"[STREAM] Single scene output: {final_output}")
    else:
        # Multiple scenes — stitch with ffmpeg
        try:
            final_output = stitch_scenes(video_paths, final_output, fps=profile.fps)
            print(f"[STREAM] Stitched output: {final_output}")
        except RuntimeError as e:
            print(f"[STREAM] Stitch failed: {e} — using first scene")
            final_output = video_paths[0]

    final_output = apply_watermark_to_video(final_output, watermark)
    final_validation = validate_video_file(final_output)
    if not final_validation.ok:
        raise RuntimeError(
            f"Final video failed integrity check: {final_validation.error}"
        )
    final_output, final_validation = _enforce_final_duration_contract(
        final_output, profile, final_validation
    )
    video_quality_report = analyze_video_frames(final_output)
    if video_quality_report.get("warnings"):
        print(f"[{job_id}] [VIDEO_QUALITY] {video_quality_report['warnings']}")
    if short_draft_fast_path:
        video_quality_report["deterministic_short_draft"] = True
    if profile.mode == "short" and not short_draft_fast_path:
        if short_video_quality_requires_fallback(video_quality_report):
            print(
                f"[{job_id}] [VIDEO_QUALITY] final short failed; "
                "rendering deterministic fallback"
            )
            final_output, video_quality_report, completed_renders = (
                _render_short_final_fallback(
                    scenes=scenes,
                    narrative_context=narrative_context,
                    filename=filename,
                    job_id=job_id,
                    profile=profile,
                    final_output=final_output,
                    watermark=watermark,
                    scene_tts=scene_tts,
                    existing_completed_renders=completed_renders,
                )
            )
            final_validation = validate_video_file(final_output)
            if not final_validation.ok:
                raise RuntimeError(
                    f"Fallback final video failed integrity check: {final_validation.error}"
                )
    elif not video_quality_report.get("ok", False) and (
        video_quality_requires_hard_failure(video_quality_report)
        or video_quality_requires_mode_recovery(
            video_quality_report, profile.mode, final=True
        )
    ):
        raise RuntimeError(
            "Final video failed frame-quality check: "
            + "; ".join(video_quality_report.get("warnings") or ["unknown issue"])
        )

    expected_audio_segments = _available_tts_segment_count(scene_tts)
    voiceover_audio_report = {
        "requested": bool(voiceover),
        "available_segments": expected_audio_segments,
        "has_audio_stream": False,
    }
    if expected_audio_segments:
        has_audio = media_has_audio_stream(final_output)
        voiceover_audio_report["has_audio_stream"] = has_audio
        if not has_audio:
            raise RuntimeError(
                "Voiceover was generated but the final video has no audio stream"
            )

    # ── Step 7: Build scene results summary + repetition analysis ──────
    repetition_pairs = []
    if scenes:
        texts = [
            scene.get("narration") or scene.get("description") or ""
            for scene in scenes
        ]

        def _tok(t):
            stop = {
                "the",
                "a",
                "an",
                "and",
                "or",
                "to",
                "of",
                "in",
                "on",
                "for",
                "with",
                "this",
                "that",
                "is",
                "are",
            }
            ws = re.findall(r"[a-zA-Z0-9]+", (t or "").lower())
            return {w for w in ws if w not in stop and len(w) > 2}

        def _jac(a, b):
            if not a or not b:
                return 0.0
            return len(a & b) / max(1, len(a | b))

        toks = [_tok(t) for t in texts]
        for i in range(len(toks)):
            for j in range(i + 1, len(toks)):
                score = _jac(toks[i], toks[j])
                if score >= 0.75:
                    repetition_pairs.append(
                        {"scene_i": i, "scene_j": j, "score": round(score, 3)}
                    )

    errors_by_scene = {}
    for err in errors:
        scene_idx = err.get("scene")
        if scene_idx is None:
            continue
        errors_by_scene.setdefault(scene_idx, []).append(
            err.get("error") or err.get("type") or "Unknown error"
        )

    scene_results = []
    for i, scene in enumerate(scenes):
        completed = completed_renders.get(i)
        video_path = completed[0] if completed and completed[1] else None
        status = "done" if video_path else "failed"
        error_info = None if status == "done" else " | ".join(
            errors_by_scene.get(i, ["Scene did not produce a successful render"])
        )

        scene_results.append(
            {
                "scene_num": i,
                "scene_id": scene.get("scene_id", f"scene_{i}"),
                "description": _preview_text(scene.get("description", "")),
                "status": status,
                "video_path": video_path,
                "error": error_info,
                "generation_source": scene.get("_generation_source", "unknown"),
                "generation_error": scene.get("_generation_error"),
                "render_recovery_note": scene.get("_render_recovery_note"),
            }
        )

    # ── Step 8: Update job status ──────────────────────────────────────
    failed_count = sum(1 for r in scene_results if r["status"] == "failed")
    if failed_count > 0:
        terminal_status = {
            "status": "done",  # Pipeline completed, but some scenes failed
            "message": f"Done ({rendered_scene_count}/{len(scenes)} scenes)",
            "partial": True,
        }
    else:
        terminal_status = {
            "status": "done",
            "message": "Video ready!",
            "partial": False,
        }

    finish_status(
        job_id,
        **terminal_status,
        video_file=Path(final_output).name,
        video_mode=profile.mode,
        mode_label=profile.label,
        aspect=profile.aspect,
        scene_results=scene_results,
        repetition_pairs=repetition_pairs,
        video_integrity=final_validation.as_dict(),
        video_quality=video_quality_report,
        voiceover_audio=voiceover_audio_report,
    )
    final_video_file = Path(final_output).name
    batch_id = get_job_field(job_id, "batch_id", None)
    trigger_webhooks(
        job_id,
        "render.complete",
        render_event_payload(job_id, batch_id, "done", video_file=final_video_file),
    )

    # Persist per-job scene stats for later analysis
    try:
        reports_dir = OUTPUTS / "stream_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / f"{job_id}.json"
        report = {
            "job_id": job_id,
            "prompt": prompt,
            "domain": analysis.get("domain"),
            "video_mode": analysis.get("video_mode", video_mode),
            "duration_target": analysis.get("duration"),
            "voiceover": voiceover,
            "visual_template": visual_template,
            "planned_scenes": len(scenes),
            "rendered_scenes": rendered_scene_count,
            "failed_scenes": failed_count,
            "errors": errors,
            "scene_results": scene_results,
            "repetition_pairs": repetition_pairs,
            "video_integrity": final_validation.as_dict(),
            "video_quality": video_quality_report,
            "voiceover_audio": voiceover_audio_report,
            "video_file": str(final_output),
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        update_status(job_id, report_file=str(report_path))
    except Exception as e:
        print(f"[{job_id}] [WARN] Could not persist stream report: {e}")

    print(f"[{job_id}] === STREAMING PIPELINE COMPLETE ===")
    print(f"[{job_id}] Output: {final_output}")
    print(f"[{job_id}] Scenes: {len(scene_results)}, Failed: {failed_count}")
    if repetition_pairs:
        print(
            f"[{job_id}] [REPEAT] potential repeated narration pairs: {repetition_pairs}"
        )

    return final_output, scene_results, final_context


