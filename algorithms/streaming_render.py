"""Per-scene render helpers for ``algorithms.streaming`` (#59).

Extracted from ``algorithms/streaming.py`` in the second PR of three for
issue #59. Owns the side of scene generation that drives ``manim -ql``
via subprocess, collects the rendered MP4, validates it for integrity
and frame quality, pads short scenes to a minimum duration, and emits
deterministic-fallback scenes when LLM output is missing.

Module-load contract:

- Leaf module. MUST NOT import ``algorithms.streaming`` at module load
  time. Call sites that need to observe test-level monkeypatches on
  ``streaming.validate_video_file`` / ``streaming.analyze_video_frames``
  / ``streaming._update_context_from_scene`` resolve those names via
  ``from algorithms import streaming as _streaming`` inside the
  function body (same pattern PRs #57 / #58 / #60 used).

Back-compat: ``algorithms.streaming`` re-exports every function defined
here, so ``streaming.<name>`` attribute access continues to reach the
moved objects — including tests that set
``streaming._render_short_fallback_scene = ...``.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional, Tuple, TYPE_CHECKING

from config import (
    MANIM_SCRIPTS,
    OUTPUTS,
    RENDER_TIMEOUT_SECONDS,
)
from algorithms.media_tools import (
    ffmpeg_command as _ffmpeg_command,
    manim_command as _manim_command,
    probe_media_duration_seconds,
    validate_video_file,
)
from algorithms.rendering import cleanup_manim_partials, inject_manim_frame_config
from algorithms.streaming_fallbacks import (
    _make_course_fallback_scene_code,
    _make_lecture_fallback_scene_code,
    _make_short_fallback_scene_code,
    _make_standard_fallback_scene_code,
)
from algorithms.streaming_prompts import (
    _mark_scene_generation,
    _update_context_from_scene,
)
from algorithms.streaming_validation import (
    _reject_known_bad_patterns,
    _sanitize_generated_code,
)
from algorithms.video_quality import (
    analyze_video_frames,
    video_quality_requires_hard_failure,
    video_quality_requires_mode_recovery,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from algorithms.streaming import NarrativeContext


def _streaming_module():
    """Return the algorithms.streaming module lazily.

    Tests monkeypatch attributes on ``algorithms.streaming`` (e.g.
    ``streaming.validate_video_file = fake_validate``,
    ``streaming.subprocess.run = fake_run``). We honour those monkeypatches
    by resolving the name via the streaming module at call time instead of
    binding it at import time. Same pattern PRs #57/#58/#60 used.
    """
    from algorithms import streaming as _streaming
    return _streaming


# ─── Scene render helpers ─────────────────────────────────────────────────
def _render_single_scene(
    code: str,
    filename: str,
    job_id: str,
    scene_num: int,
    render_resolution: Optional[Tuple[int, int]] = None,
    quality_flag: str = "-ql",
    fps: int = 30,
    timeout_seconds: Optional[int] = None,
) -> Tuple[str, bool, str]:
    """
    Render a single scene's Manim code.

    Returns:
        Tuple of (video_path_or_error, success, error_message)
    """
    from algorithms.code_digest import (
        downgrade_tex_to_text_if_needed,
        validate_python_syntax,
        validate_manim_code,
        validate_names_and_imports,
        check_code_quality,
    )

    script_path = MANIM_SCRIPTS / f"{filename}_scene{scene_num}.py"
    code = _sanitize_generated_code(downgrade_tex_to_text_if_needed(code))
    code = inject_manim_frame_config(code, render_resolution)

    # Validate before writing
    syntax_ok, syntax_err = validate_python_syntax(code)
    if not syntax_ok:
        return "", False, f"Syntax error: {syntax_err}"

    structure_ok, structure_err = validate_manim_code(code)
    if not structure_ok:
        return "", False, structure_err

    imports_ok, import_issues = validate_names_and_imports(code)
    if not imports_ok:
        return "", False, "; ".join(import_issues[:3])

    quality_ok, quality_messages = check_code_quality(code)
    blocking_quality = [msg for msg in quality_messages if msg.startswith("[ERR]")]
    if blocking_quality:
        return "", False, "; ".join(blocking_quality[:3])

    pattern_err = _reject_known_bad_patterns(code)
    if pattern_err:
        return "", False, pattern_err

    # Write script
    with open(script_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(code)

    # Clean old files for THIS exact scene only.
    # IMPORTANT: avoid prefix collisions like scene1 matching scene10/scene11.
    scene_prefix = f"{filename}_scene{scene_num}"
    for old_file in OUTPUTS.rglob(f"{scene_prefix}*.mp4"):
        name = old_file.name
        if not name.startswith(scene_prefix):
            continue
        suffix = name[len(scene_prefix) :]
        # Allow only exact scene or scene-specific suffixes that begin with non-digit
        # (e.g. _tts.mp4). Reject names where next char is a digit (scene10 collision).
        if suffix and suffix[0].isdigit():
            continue
        try:
            old_file.unlink()
        except OSError:
            pass

    # Build render command
    cmd = [
        *_manim_command(),
        str(script_path),
        "GeneratedScene",
        quality_flag,
        "--format=mp4",
        "--media_dir",
        str(OUTPUTS),
        "--output_file",
        f"{filename}_scene{scene_num}.mp4",
        "--disable_caching",
        "--fps",
        str(fps),
    ]

    if render_resolution and len(render_resolution) == 2:
        w, h = render_resolution
        cmd.extend(["--resolution", f"{w},{h}"])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds or (RENDER_TIMEOUT_SECONDS // 3),
        )

        if result.returncode == 0:
            # Find video file
            video_path = _find_scene_video(filename, scene_num)
            if video_path and video_path.exists():
                cleanup_manim_partials(video_path)
                return str(video_path), True, ""
            return "", False, "Render succeeded but video file not found"

        return "", False, result.stderr[-500:]

    except subprocess.TimeoutExpired:
        return "", False, "Render timeout"
    except Exception as e:
        return "", False, str(e)


def _find_scene_video(filename: str, scene_num: int) -> Optional[Path]:
    """Find the rendered video file for a scene."""
    scene_prefix = f"{filename}_scene{scene_num}"
    patterns = [OUTPUTS / f"{scene_prefix}.mp4"]

    for p in patterns:
        if p.exists():
            return p

    # Glob fallback with exact scene prefix guard
    candidates = []
    for mp4 in OUTPUTS.rglob(f"{scene_prefix}*.mp4"):
        name = mp4.name
        if not name.startswith(scene_prefix):
            continue
        suffix = name[len(scene_prefix) :]
        # Reject scene3 -> scene30/scene31 collisions
        if suffix and suffix[0].isdigit():
            continue
        candidates.append(mp4)

    if candidates:
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        # Prefer TTS merged outputs when available
        for c in candidates:
            if c.name.endswith("_tts.mp4"):
                return c
        return candidates[0]

    return None


# Deterministic fallback scene generators were extracted to
# algorithms.streaming_fallbacks in the PR for #11. Re-exported here for
# back-compat: tests and internal callers access them via streaming.<name>.


def _render_mode_fallback_scene(
    scene_plan: dict,
    context: NarrativeContext,
    scene_num: int,
    filename: str,
    job_id: str,
    render_resolution: Optional[Tuple[int, int]],
    quality_flag: str,
    fps: int,
    timeout_seconds: Optional[int],
) -> Tuple[Optional[str], bool, str, NarrativeContext]:
    """Last-resort deterministic render for a non-short mode.

    Invoked when the LLM retry itself also fails (hygiene reject, syntax error,
    or render error on the retried code). The deterministic helpers already
    honour ``NIMA_LANGUAGE_LOCK`` via ``localize_scene_code``, so a recovered
    scene still matches the target language.
    """
    mode = str(context.domain_state.get("video_mode") or "").lower()
    if mode == "standard":
        code = _make_standard_fallback_scene_code(scene_plan, context)
    elif mode == "course":
        code = _make_course_fallback_scene_code(scene_plan, context)
    elif mode == "lecture":
        code = _make_lecture_fallback_scene_code(scene_plan, context)
    else:
        return None, False, f"no deterministic fallback for mode {mode!r}", context

    video_path, success, error = _render_single_scene(
        code,
        filename,
        job_id,
        scene_num,
        render_resolution,
        quality_flag,
        fps,
        timeout_seconds,
    )
    if not success or not video_path:
        return None, False, error, context
    valid, validation_error = _validate_scene_video(scene_num, video_path, mode=mode)
    if not valid:
        return video_path, False, validation_error, context
    _streaming = _streaming_module()
    _update = getattr(_streaming, "_update_context_from_scene", _update_context_from_scene)
    new_context = _update(
        context, code, f"[FALLBACK] {scene_plan.get('description', '')}"
    )
    _mark_scene_generation(
        scene_plan,
        f"deterministic_{mode}_fallback_render_recovery",
        None,
    )
    return video_path, True, "", new_context


def _render_short_fallback_scene(
    scene_plan: dict,
    context: NarrativeContext,
    scene_num: int,
    filename: str,
    job_id: str,
    render_resolution: Optional[Tuple[int, int]],
    quality_flag: str,
    fps: int,
    timeout_seconds: Optional[int],
) -> Tuple[Optional[str], bool, str, NarrativeContext]:
    code = _make_short_fallback_scene_code(scene_plan, context)
    video_path, success, error = _render_single_scene(
        code,
        filename,
        job_id,
        scene_num,
        render_resolution,
        quality_flag,
        fps,
        timeout_seconds,
    )
    if not success or not video_path:
        return None, False, error, context
    valid, validation_error = _validate_scene_video(scene_num, video_path)
    if not valid:
        return video_path, False, validation_error, context
    if context.domain_state.get("video_mode") == "short":
        video_path = _pad_scene_to_min_duration(
            video_path,
            float(scene_plan.get("duration_hint") or 0),
            fps=fps,
            scene_num=scene_num,
        )
    _streaming = _streaming_module()
    _update = getattr(_streaming, "_update_context_from_scene", _update_context_from_scene)
    new_context = _update(
        context, code, f"[FALLBACK] {scene_plan.get('description', '')}"
    )
    return video_path, True, "", new_context


def _validate_scene_video(
    scene_num: int,
    video_path: str,
    *,
    mode: str | None = None,
    allow_quality_recovery: bool = False,
) -> Tuple[bool, str]:
    """Run local integrity and severe frame-quality checks for one scene."""
    _streaming = _streaming_module()
    _validate = getattr(_streaming, "validate_video_file", validate_video_file)
    _analyze = getattr(_streaming, "analyze_video_frames", analyze_video_frames)
    validation = _validate(video_path)
    if not validation.ok:
        return (
            False,
            f"scene {scene_num} video failed integrity check: {validation.error}",
        )

    quality = _analyze(video_path, max_frames=4)
    warnings = quality.get("warnings") or []
    if warnings:
        print(f"[STREAM] Scene {scene_num} frame-quality warnings: {warnings}")
    if not quality.get("ok", False) and video_quality_requires_hard_failure(quality):
        return (
            False,
            f"scene {scene_num} failed frame-quality check: {'; '.join(warnings)}",
        )
    if allow_quality_recovery and video_quality_requires_mode_recovery(quality, mode):
        return (
            False,
            f"scene {scene_num} needs mode-aware layout recovery: "
            + "; ".join(warnings or [f"quality score {quality.get('score')}"]),
        )
    return True, ""


def _pad_scene_to_min_duration(
    video_path: str,
    min_duration_seconds: float,
    *,
    fps: int,
    scene_num: int,
) -> str:
    """Clone the final frame when a short beat renders under its planned length."""
    try:
        target = float(min_duration_seconds)
    except (TypeError, ValueError):
        return video_path
    if target <= 0:
        return video_path

    _streaming = _streaming_module()
    _probe = getattr(
        _streaming, "probe_media_duration_seconds", probe_media_duration_seconds
    )
    current = _probe(video_path)
    if current is None or current + 0.2 >= target:
        return video_path

    pad_by = max(0.0, target - current)
    source = Path(video_path)
    padded = source.with_name(f"{source.stem}_padded.mp4")
    cmd = [
        *_ffmpeg_command(),
        "-y",
        "-i",
        str(source),
        "-vf",
        f"tpad=stop_mode=clone:stop_duration={pad_by:.3f},fps={int(fps or 10)}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(padded),
    ]
    try:
        # Resolve subprocess via the streaming module so tests that swap
        # ``streaming.subprocess.run`` keep intercepting the pad command.
        _subprocess = getattr(_streaming, "subprocess", subprocess)
        result = _subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(60, int(pad_by * 8) + 30),
        )
    except Exception as exc:
        print(f"[STREAM] Scene {scene_num} duration pad skipped: {exc}")
        return video_path

    if result.returncode != 0:
        print(
            f"[STREAM] Scene {scene_num} duration pad failed: "
            f"{(result.stderr or result.stdout)[-300:]}"
        )
        return video_path

    _validate = getattr(_streaming, "validate_video_file", validate_video_file)
    validation = _validate(str(padded), min_duration_seconds=target - 0.2)
    if not validation.ok:
        print(
            f"[STREAM] Scene {scene_num} padded output failed validation: "
            f"{validation.error}"
        )
        return video_path

    print(
        f"[STREAM] Scene {scene_num} padded from {current:.2f}s "
        f"to {validation.duration_seconds or target:.2f}s"
    )
    return str(padded)


def _should_pad_scene_duration(context: NarrativeContext) -> bool:
    return bool(
        context.domain_state.get("video_mode") == "short"
        or context.domain_state.get("duration_padding_enabled")
    )
