"""Bulk render retry service for generated Manim code."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from config import DEFAULT_VIDEO_MODE, DRAFT_PIPELINE, MANIM_SCRIPTS, OUTPUTS
from algorithms.ai_functions import evaluate_with_gpt4, fix_render_error, polish_manim_code
from algorithms.code_digest import (
    ensure_scene_class,
    latex_toolchain_available,
    validate_latex_strings,
    validate_manim_code,
    validate_names_and_imports,
    validate_python_syntax,
)
from algorithms.media_tools import (
    apply_watermark_to_video,
    media_has_audio_stream,
    validate_video_file,
)
from algorithms.rendering import (
    cleanup_manim_partials,
    find_video_file,
    render_manim_code,
)
from algorithms.video_quality import analyze_video_frames
from algorithms.tts import merge_audio_video
from algorithms.video_modes import build_video_mode_profile
from algorithms.webhook_service import render_event_payload


@dataclass
class RenderServiceDeps:
    db: Any = None
    update_status: Callable[..., dict] | None = None
    finish_status: Callable[..., dict] | None = None
    get_job_field: Callable[[str, str, Any], Any] | None = None
    trigger_webhooks: Callable[[str, str, dict], None] | None = None


def _db_available(db: Any) -> bool:
    return bool(db and getattr(db, "available", False))


def _noop_status(job_id: str, **updates: Any) -> dict:
    return dict(updates)


def _noop_get_job_field(job_id: str, key: str, default: Any = None) -> Any:
    return default


def _noop_trigger_webhooks(job_id: str, event: str, payload: dict) -> None:
    return None


def _render_cache_variant(profile) -> dict:
    return {
        "mode": profile.mode,
        "quality_flag": profile.quality_flag,
        "fps": profile.fps,
        "render_resolution": list(profile.render_resolution)
        if profile.render_resolution
        else None,
        "latex_available": latex_toolchain_available(),
    }


def _available_audio_segment_count(
    audio_segments: dict | None, segment_order: list | None
) -> int:
    if not audio_segments:
        return 0
    keys = segment_order or list(audio_segments.keys())
    count = 0
    for key in keys:
        payload = audio_segments.get(key, {})
        path = payload.get("path") if isinstance(payload, dict) else None
        if path and Path(path).exists():
            count += 1
    return count


def _voiceover_audio_report(
    audio_segments: dict | None,
    segment_order: list | None,
    final_video_path: str,
) -> dict:
    available_segments = _available_audio_segment_count(audio_segments, segment_order)
    has_audio = media_has_audio_stream(final_video_path) if available_segments else False
    return {
        "requested": bool(audio_segments),
        "available_segments": available_segments,
        "has_audio_stream": has_audio,
    }


def save_and_render_job(
    code: str,
    filename: str,
    job_id: str,
    *,
    deps: RenderServiceDeps,
    request_id: str | None = None,
    prompt: str = "",
    attempt_id: str | None = None,
    audio_segments: dict | None = None,
    segment_order: list | None = None,
    is_fast: bool = False,
    analysis: dict | None = None,
    watermark: dict | None = None,
) -> None:
    """
    Render pipeline with self-healing retry loop.

    On failure, Manim stderr is fed back into a fixer and the render is retried
    according to the active video-mode profile.
    """
    update_status = deps.update_status or _noop_status
    finish_status = deps.finish_status or update_status
    get_job_field = deps.get_job_field or _noop_get_job_field
    trigger_webhooks = deps.trigger_webhooks or _noop_trigger_webhooks
    db = deps.db

    print(f"\n[{job_id}] === RENDER STARTED ===")
    update_status(job_id, status="rendering", message="Rendering video...")

    current_code = code
    render_job_id = None
    render_video_mode = (analysis or {}).get("video_mode", DEFAULT_VIDEO_MODE)
    profile = build_video_mode_profile(
        render_video_mode, is_fast=is_fast, draft=DRAFT_PIPELINE, streaming=False
    )
    cache_variant = _render_cache_variant(profile)

    try:
        from cache import render_cache

        cached_video = render_cache.check(code, variant=cache_variant)
        if cached_video and cached_video.exists():
            print("[CACHE] Render cache HIT — skipping manim")
            video_path = cached_video
            final_video_path = str(video_path)
            if audio_segments and segment_order:
                update_status(job_id, message="Merging audio and video...")
                narrated_output = str(OUTPUTS / f"{filename}_narrated.mp4")
                final_video_path = merge_audio_video(
                    str(video_path), audio_segments, segment_order, narrated_output
                )
            final_video_path = apply_watermark_to_video(final_video_path, watermark)
            cached_validation = validate_video_file(final_video_path)
            if not cached_validation.ok:
                print(
                    f"[{job_id}] [CACHE] [WARN] cached video failed integrity check: "
                    f"{cached_validation.error}"
                )
                raise ValueError(cached_validation.error)
            cached_audio = _voiceover_audio_report(
                audio_segments, segment_order, final_video_path
            )
            if (
                cached_audio["available_segments"]
                and not cached_audio["has_audio_stream"]
            ):
                raise ValueError(
                    "voiceover audio was generated but cached final video has no audio stream"
                )
            cached_quality = analyze_video_frames(final_video_path)
            if cached_quality.get("warnings"):
                print(f"[{job_id}] [VIDEO_QUALITY] {cached_quality['warnings']}")
            if not cached_quality.get("ok", False):
                print(
                    f"[{job_id}] [CACHE] [WARN] cached video failed frame-quality "
                    f"check: {cached_quality.get('warnings')}"
                )
                raise ValueError(
                    "; ".join(cached_quality.get("warnings") or ["frame-quality failed"])
                )
            final_video_file = Path(final_video_path).name
            finish_status(
                job_id,
                status="done",
                video_file=final_video_file,
                video_mode=profile.mode,
                mode_label=profile.label,
                aspect=profile.aspect,
                message="Video ready (cached)!",
                video_integrity=cached_validation.as_dict(),
                video_quality=cached_quality,
                voiceover_audio=cached_audio,
            )
            print(f"[{job_id}] [CACHE] [OK] SUCCESS — {final_video_path}")

            batch_id = get_job_field(job_id, "batch_id", None)
            trigger_webhooks(
                job_id,
                "render.complete",
                render_event_payload(
                    job_id, batch_id, "done", video_file=final_video_file
                ),
            )
            return
    except Exception as e:
        print(f"[CACHE] Render cache check failed: {e}")

    render_retries = profile.render_retries

    for render_attempt in range(1, render_retries + 1):
        print(f"[{job_id}] Render attempt {render_attempt}/{render_retries}")
        started_at = datetime.now()

        t_render = time.time()
        try:
            result = render_manim_code(
                current_code,
                filename,
                is_fast=is_fast,
                video_mode=profile.mode,
            )
            render_duration = int((datetime.now() - started_at).total_seconds())
            print(f"[TIMING] Manim render: {time.time() - t_render:.2f}s")

            render_data = {
                "code": current_code,
                "script_path": str(MANIM_SCRIPTS / f"{filename}.py"),
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration": render_duration,
                "started_at": started_at,
                "completed_at": datetime.now(),
            }

            video_path = find_video_file(filename)
            if not video_path and result.returncode == 0:
                for _ in range(3):
                    time.sleep(1)
                    video_path = find_video_file(filename)
                    if video_path:
                        break

            if video_path:
                if result.returncode != 0:
                    print(
                        f"[{job_id}] [WARN] Manim exited with code {result.returncode} but video was produced — treating as success"
                    )

                cleanup_manim_partials(video_path)
                final_video_path = str(video_path)
                if audio_segments and segment_order:
                    update_status(job_id, message="Merging audio and video...")
                    print(f"[{job_id}] Merging audio + video...")
                    narrated_output = str(OUTPUTS / f"{filename}_narrated.mp4")
                    final_video_path = merge_audio_video(
                        str(video_path), audio_segments, segment_order, narrated_output
                    )
                final_video_path = apply_watermark_to_video(final_video_path, watermark)
                final_validation = validate_video_file(final_video_path)
                if not final_validation.ok:
                    integrity_error = (
                        f"Video integrity check failed: {final_validation.error}"
                    )
                    print(f"[{job_id}] [ERR] {integrity_error}")
                    render_data["status"] = "error"
                    render_data["error_type"] = "video_integrity"
                    render_data["error_message"] = integrity_error
                    if render_attempt < render_retries:
                        update_status(
                            job_id,
                            message=(
                                "Rendered file failed integrity check; retrying render..."
                            ),
                        )
                        continue

                    finish_status(
                        job_id,
                        status="error",
                        message="Rendered video failed integrity check",
                        video_mode=profile.mode,
                    )
                    if _db_available(db) and request_id:
                        db.save_render_job(request_id, None, render_data)

                    batch_id = get_job_field(job_id, "batch_id", None)
                    trigger_webhooks(
                        job_id,
                        "render.error",
                        render_event_payload(
                            job_id,
                            batch_id,
                            "error",
                            error=integrity_error,
                        ),
                    )
                    return
                voiceover_audio = _voiceover_audio_report(
                    audio_segments, segment_order, final_video_path
                )
                if (
                    voiceover_audio["available_segments"]
                    and not voiceover_audio["has_audio_stream"]
                ):
                    audio_error = (
                        "Voiceover was generated but the final video has no audio stream"
                    )
                    print(f"[{job_id}] [ERR] {audio_error}")
                    render_data["status"] = "error"
                    render_data["error_type"] = "voiceover_audio"
                    render_data["error_message"] = audio_error
                    if render_attempt < render_retries:
                        update_status(
                            job_id,
                            message=(
                                "Rendered file lost voiceover audio; retrying render..."
                            ),
                        )
                        continue

                    finish_status(
                        job_id,
                        status="error",
                        message="Rendered video lost voiceover audio",
                        video_mode=profile.mode,
                    )
                    if _db_available(db) and request_id:
                        db.save_render_job(request_id, None, render_data)

                    batch_id = get_job_field(job_id, "batch_id", None)
                    trigger_webhooks(
                        job_id,
                        "render.error",
                        render_event_payload(
                            job_id,
                            batch_id,
                            "error",
                            error=audio_error,
                        ),
                    )
                    return
                video_quality_report = analyze_video_frames(final_video_path)
                if video_quality_report.get("warnings"):
                    print(
                        f"[{job_id}] [VIDEO_QUALITY] "
                        f"{video_quality_report['warnings']}"
                    )
                if not video_quality_report.get("ok", False):
                    quality_error = (
                        "Video frame-quality check failed: "
                        + "; ".join(
                            video_quality_report.get("warnings")
                            or ["unknown frame-quality issue"]
                        )
                    )
                    print(f"[{job_id}] [ERR] {quality_error}")
                    render_data["status"] = "error"
                    render_data["error_type"] = "video_quality"
                    render_data["error_message"] = quality_error
                    if render_attempt < render_retries:
                        update_status(
                            job_id,
                            message=(
                                "Rendered file failed frame-quality check; retrying render..."
                            ),
                        )
                        continue

                    finish_status(
                        job_id,
                        status="error",
                        message="Rendered video failed frame-quality check",
                        video_mode=profile.mode,
                    )
                    if _db_available(db) and request_id:
                        db.save_render_job(request_id, None, render_data)

                    batch_id = get_job_field(job_id, "batch_id", None)
                    trigger_webhooks(
                        job_id,
                        "render.error",
                        render_event_payload(
                            job_id,
                            batch_id,
                            "error",
                            error=quality_error,
                        ),
                    )
                    return
                final_video_file = Path(final_video_path).name

                render_data["status"] = "done"
                render_data["video_path"] = final_video_path
                render_data["video_integrity"] = final_validation.as_dict()
                render_data["video_quality"] = video_quality_report
                render_data["voiceover_audio"] = voiceover_audio
                finish_status(
                    job_id,
                    status="done",
                    video_file=final_video_file,
                    video_mode=profile.mode,
                    mode_label=profile.label,
                    aspect=profile.aspect,
                    message="Video ready!",
                    video_integrity=final_validation.as_dict(),
                    video_quality=video_quality_report,
                    voiceover_audio=voiceover_audio,
                )
                print(f"[{job_id}] [OK] SUCCESS — {final_video_path}")

                if _db_available(db) and request_id:
                    render_job_id = db.save_render_job(
                        request_id, attempt_id, render_data
                    )
                    print(f"[DB] [OK] Saved render job: {render_job_id}")

                try:
                    from cache import render_cache

                    render_cache.store(
                        current_code, Path(video_path), variant=cache_variant
                    )
                    print("[CACHE] Stored render in cache")
                except Exception as e:
                    print(f"[CACHE] Store failed: {e}")

                update_status(job_id, message="Evaluating quality...")
                try:
                    evaluation = evaluate_with_gpt4(
                        current_code,
                        str(video_path),
                        prompt,
                        {
                            "status": "done",
                            "duration": render_duration,
                            "error": None,
                        },
                    )
                    if _db_available(db) and request_id and render_job_id:
                        db.save_ai_evaluation(request_id, render_job_id, evaluation)
                        score = evaluation.get("overall", 0)
                        print(f"[DB] [OK] Saved evaluation (score: {score}/100)")
                        if score >= 80:
                            print("[TRAINING] High-quality example candidate!")
                except Exception as e:
                    print(f"[{job_id}] [WARN] Quality evaluation failed: {e}")
                finally:
                    update_status(job_id, message="Video ready!")

                batch_id = get_job_field(job_id, "batch_id", None)
                trigger_webhooks(
                    job_id,
                    "render.complete",
                    render_event_payload(
                        job_id, batch_id, "done", video_file=final_video_file
                    ),
                )
                return

            if result.returncode == 0 and not video_path:
                render_data["status"] = "error"
                render_data["error_type"] = "file_not_found_after_retry"
                render_data["error_message"] = (
                    "Video file not found after render and poll retry"
                )
                finish_status(
                    job_id,
                    status="error",
                    message="Video file not found",
                    video_mode=profile.mode,
                )
                if _db_available(db) and request_id:
                    db.save_render_job(request_id, None, render_data)

                batch_id = get_job_field(job_id, "batch_id", None)
                trigger_webhooks(
                    job_id,
                    "render.error",
                    render_event_payload(
                        job_id,
                        batch_id,
                        "error",
                        error="Video file not found after render",
                    ),
                )
                return

            stderr = result.stderr
            print(f"[{job_id}] [ERR] Render failed (attempt {render_attempt})")
            print(f"[{job_id}] stderr (last 800 chars): {stderr[-800:]}")

            if _db_available(db):
                try:
                    db.record_error_pattern(
                        {
                            "category": "runtime",
                            "signature": str(hash(stderr[-500:])),
                            "message": stderr[-500:],
                            "code_snippet": current_code[:200],
                            "root_cause": "Manim runtime error",
                            "fix": "Feed error back to LLM for targeted fix",
                        }
                    )
                except Exception as e:
                    print(
                        f"[{job_id}] [DB] [ERR] Failed to record error pattern: {e}",
                        flush=True,
                    )
            else:
                print(
                    f"[{job_id}] [DB] [WARN] Database unavailable — error pattern not recorded",
                    flush=True,
                )

            if render_attempt < render_retries:
                update_status(
                    job_id,
                    message=f"Fixing render error (attempt {render_attempt})...",
                )
                print(f"[{job_id}] → Feeding error to LLM for fix...")
                current_code = fix_render_error(current_code, stderr, prompt)

                is_safe, safety_issues = validate_names_and_imports(current_code)
                if not is_safe:
                    print(
                        f"[{job_id}] [WARN] Post-fix safety check failed: {safety_issues}"
                    )
                    current_code = polish_manim_code(current_code)
                    is_safe, safety_issues = validate_names_and_imports(current_code)
                    if not is_safe:
                        print(
                            f"[{job_id}] [ERR] Safety issues persist after polish: {safety_issues}"
                        )

                structure_valid, structure_error = validate_manim_code(current_code)
                if not structure_valid:
                    print(
                        f"[{job_id}] [WARN] Post-fix structure check failed: {structure_error}"
                    )
                    current_code = ensure_scene_class(current_code)

                if analysis and analysis.get("domain") == "math" and not is_fast:
                    latex_valid, latex_issues = validate_latex_strings(current_code)
                    if not latex_valid:
                        print(
                            f"[{job_id}] [WARN] Post-fix LaTeX check failed: {latex_issues}"
                        )

                syn_ok, _ = validate_python_syntax(current_code)
                if not syn_ok:
                    current_code = polish_manim_code(current_code)
                current_code = ensure_scene_class(current_code)
                continue

            render_data["status"] = "error"
            render_data["error_type"] = "runtime"
            render_data["error_message"] = stderr[-2000:]
            finish_status(
                job_id,
                status="error",
                message="Render failed after all retries",
                video_mode=profile.mode,
            )
            if _db_available(db) and request_id:
                db.save_render_job(request_id, None, render_data)

            batch_id = get_job_field(job_id, "batch_id", None)
            trigger_webhooks(
                job_id,
                "render.error",
                render_event_payload(
                    job_id,
                    batch_id,
                    "error",
                    error="Render failed after all retries",
                ),
            )

        except subprocess.TimeoutExpired:
            finish_status(
                job_id,
                status="error",
                message="Rendering timed out",
                video_mode=profile.mode,
            )
            print(f"[{job_id}] [ERR] TIMEOUT")

            batch_id = get_job_field(job_id, "batch_id", None)
            trigger_webhooks(
                job_id,
                "render.error",
                render_event_payload(
                    job_id, batch_id, "error", error="Rendering timed out"
                ),
            )
            return

        except Exception as e:
            finish_status(
                job_id,
                status="error",
                message=f"Error: {str(e)}",
                video_mode=profile.mode,
            )
            print(f"[{job_id}] [ERR] Exception: {e}")

            batch_id = get_job_field(job_id, "batch_id", None)
            trigger_webhooks(
                job_id,
                "render.error",
                render_event_payload(job_id, batch_id, "error", error=str(e)),
            )
            return
