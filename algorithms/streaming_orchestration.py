"""Scene orchestration for ``algorithms.streaming`` (#59).

Top-level scene lifecycle:

- ``generate_scene``                 — stream-generate one scene
- ``retry_scene``                    — retry with error feedback
- ``_recover_render_failure``        — surgical retry after render fail
- ``_accept_or_recover_scene_render``— validate render + recover
- ``stream_render_scenes``           — parallel render-while-generate
- ``stitch_scenes``                  — ffmpeg concat
- ``estimate_scene_cost``            — token budget helper
- ``select_provider_for_budget``     — provider picker by budget

Extracted from ``algorithms/streaming.py`` in the third PR for
issue #59 to keep streaming.py within the <1,500-LoC budget.

Leaf-module contract:

- Does NOT import ``algorithms.streaming`` at module-load time.
- Every name the tests monkey-patch via ``streaming.<name>`` setattr is
  resolved through a lazy helper ``_s()`` inside the call site so the
  monkey-patches still fire.  This is the same pattern PRs #57/#58/#60/#61
  used for ``detect_static_layout_risks`` / ``STREAM_PROVIDER`` / RAG
  retrievers / ``validate_video_file`` / ``subprocess.run``.

Back-compat: all eight public/private names are re-exported from
``algorithms.streaming``.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from config import (
    MAX_RENDER_RETRIES,
    RENDER_TIMEOUT_SECONDS,
    STREAM_PARALLEL_RENDERS,
)
from algorithms.media_tools import ffmpeg_command as _ffmpeg_command
from algorithms.streaming_fallbacks import (
    _make_course_fallback_scene_code,
    _make_lecture_fallback_scene_code,
    _make_short_fallback_scene_code,
    _make_standard_fallback_scene_code,
)
from algorithms.streaming_prompts import (
    _build_retry_addendum,
    _build_scene_prompt,
    _classify_retry_error,
    _mark_scene_generation,
    _surgical_repair_tips,
    _update_context_from_scene,
)
from algorithms.streaming_providers import stream_generate
from algorithms.streaming_render import (
    _pad_scene_to_min_duration,
    _render_mode_fallback_scene,
    _render_short_fallback_scene,
    _render_single_scene,
    _should_pad_scene_duration,
    _validate_scene_video,
)
from algorithms.streaming_validation import (
    _enforce_minimum_font_size,
    _extract_manim_code,
    _reject_course_instructional_code,
    _reject_known_bad_patterns,
    _reject_layout_hygiene_code,
    _reject_lecture_academic_code,
    _reject_short_duration_code,
    _reject_standard_engagement_code,
    _reject_static_short_code,
    _reject_unbounded_long_text_code,
    _sanitize_generated_code,
    classify_render_error,
)
from algorithms.video_quality import (
    analyze_video_frames,
    short_video_quality_requires_fallback,
    video_quality_requires_hard_failure,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from algorithms.streaming import NarrativeContext


def _s():
    """Return ``algorithms.streaming`` lazily so test monkey-patches on
    that module are honoured by the extracted code paths. See module
    docstring for the rationale.
    """
    from algorithms import streaming as _streaming  # lazy to avoid load cycle
    return _streaming



# ─── Scene orchestration ─────────────────────────────────────────────────
def generate_scene(
    scene_plan: dict,
    narrative_context: NarrativeContext,
    scene_num: int,
    max_retries: int = 2,
) -> Tuple[str, NarrativeContext]:
    """
    Generate single scene code with full narrative context.

    Args:
        scene_plan: Scene data from split_plan_into_scenes
        narrative_context: Current narrative state
        scene_num: Scene number for naming
        max_retries: Max generation retries

    Returns:
        Tuple of (generated_code, updated_context)
    """
    context = narrative_context
    context.scene_index = scene_num
    _s()._mark_scene_generation(scene_plan, "pending")

    scene_desc = scene_plan.get("description", "")
    duration_hint = scene_plan.get("duration_hint", 10)

    # Build generation prompt
    prompt = _s()._build_scene_prompt(scene_plan, context, duration_hint)

    # Anti-repeat guard: don't let scene regenerate near-identical recent content
    recent_ctx = "\n".join(context.scene_history[-3:])
    if recent_ctx:
        prompt += (
            "\n\nANTI-REPEAT CHECK:\n"
            "- Your scene must add NEW conceptual progress compared to recent scenes.\n"
            "- Do not restate the same explanation in different words.\n"
            "- If similar to prior content, skip recap and move to the next logical step.\n"
            f"Recent scene summaries:\n{recent_ctx}\n"
        )

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            # Stream the generation with timeout
            code_chunks = []
            start_time = time.time()

            attempt_prompt = prompt
            if last_error is not None:
                attempt_prompt += _build_retry_addendum(
                    last_error, attempt=attempt, scene_plan=scene_plan
                )

            for token in _s().stream_generate(attempt_prompt, context):
                code_chunks.append(token)

            full_code = "".join(code_chunks)
            elapsed = time.time() - start_time

            if not full_code or len(full_code) < 50:
                raise ValueError(
                    f"Empty or very short response ({len(full_code)} chars)"
                )

            # Extract code from markdown if present
            code = _extract_manim_code(full_code)
            code = _sanitize_generated_code(code)
            if context.domain_state.get("video_mode") == "lecture":
                code = _enforce_minimum_font_size(
                    code,
                    int(context.domain_state.get("minimum_label_font_size") or 24),
                )

            # Validate syntax and known bad patterns early to force retry before render
            from algorithms.code_digest import (
                validate_python_syntax,
                validate_manim_code,
                validate_names_and_imports,
                check_code_quality,
            )

            syntax_ok, syntax_err = validate_python_syntax(code)
            if not syntax_ok:
                raise ValueError(f"Syntax error: {syntax_err}")

            structure_ok, structure_err = validate_manim_code(code)
            if not structure_ok:
                raise ValueError(structure_err)

            imports_ok, import_issues = validate_names_and_imports(code)
            if not imports_ok:
                raise ValueError("; ".join(import_issues[:3]))

            quality_ok, quality_messages = check_code_quality(code)
            blocking_quality = [
                msg for msg in quality_messages if msg.startswith("[ERR]")
            ]
            if blocking_quality:
                raise ValueError("; ".join(blocking_quality[:3]))

            pattern_err = _s()._reject_known_bad_patterns(code)
            if pattern_err:
                raise ValueError(pattern_err)
            layout_hygiene_err = _s()._reject_layout_hygiene_code(
                code, context, scene_plan
            )
            if layout_hygiene_err:
                raise ValueError(layout_hygiene_err)
            long_text_err = _s()._reject_unbounded_long_text_code(
                code, context, scene_plan
            )
            if long_text_err:
                raise ValueError(long_text_err)
            short_static_err = _s()._reject_static_short_code(code, context)
            if short_static_err:
                raise ValueError(short_static_err)
            short_duration_err = _s()._reject_short_duration_code(
                code, context, scene_plan
            )
            if short_duration_err:
                raise ValueError(short_duration_err)
            standard_engagement_err = _s()._reject_standard_engagement_code(
                code, context, scene_plan
            )
            if standard_engagement_err:
                raise ValueError(standard_engagement_err)
            course_instruction_err = _s()._reject_course_instructional_code(
                code, context, scene_plan
            )
            if course_instruction_err:
                raise ValueError(course_instruction_err)
            lecture_academic_err = _s()._reject_lecture_academic_code(
                code, context, scene_plan
            )
            if lecture_academic_err:
                raise ValueError(lecture_academic_err)

            if "self.camera.frame" in code or ".camera.frame" in code:
                raise ValueError(
                    "Invalid camera.frame usage in Scene; regenerate without MovingCameraScene APIs"
                )

            # Validate basic structure
            if "class GeneratedScene" not in code and "class Scene" not in code:
                raise ValueError("No Scene class found in generated code")

            # Reject obvious recap/repeat patterns in non-first scenes
            if scene_num > 0:
                lowered = code.lower()
                repeat_markers = [
                    "let's start",
                    "in this video",
                    "we begin",
                    "introduction",
                    "recap",
                    "summary of what we saw",
                ]
                if any(m in lowered for m in repeat_markers):
                    raise ValueError(
                        "Detected recap/intro pattern in mid-scene; forcing regenerate"
                    )

            print(
                f"[STREAM] Scene {scene_num} generated in {elapsed:.1f}s ({len(code)} chars)"
            )
            _s()._mark_scene_generation(scene_plan, "llm")

            # Update narrative context with this scene's objects
            context = _s()._update_context_from_scene(context, code, scene_desc)

            return code, context

        except Exception as e:
            last_error = e
            print(f"[STREAM] Scene {scene_num} attempt {attempt} failed: {e}")
            error_text = str(e).lower()
            mode = context.domain_state.get("video_mode")
            provider_failure = (
                "generation exceeded" in error_text
                or "empty or very short response" in error_text
            )
            if mode == "standard" and provider_failure:
                code = _make_standard_fallback_scene_code(scene_plan, context)
                _s()._mark_scene_generation(scene_plan, "deterministic_standard_fallback", e)
                context = _s()._update_context_from_scene(context, code, scene_desc)
                print(
                    f"[STREAM] Scene {scene_num} using deterministic standard fallback "
                    f"after provider failure: {e}"
                )
                return code, context
            if mode == "lecture" and provider_failure:
                code = _make_lecture_fallback_scene_code(scene_plan, context)
                _s()._mark_scene_generation(scene_plan, "deterministic_lecture_fallback", e)
                context = _s()._update_context_from_scene(context, code, scene_desc)
                print(
                    f"[STREAM] Scene {scene_num} using deterministic lecture fallback "
                    f"after provider failure: {e}"
                )
                return code, context
            if mode == "course" and provider_failure:
                code = _make_course_fallback_scene_code(scene_plan, context)
                _s()._mark_scene_generation(scene_plan, "deterministic_course_fallback", e)
                context = _s()._update_context_from_scene(context, code, scene_desc)
                print(
                    f"[STREAM] Scene {scene_num} using deterministic course fallback "
                    f"after provider failure: {e}"
                )
                return code, context
            if mode == "short" and provider_failure:
                code = _make_short_fallback_scene_code(scene_plan, context)
                _s()._mark_scene_generation(scene_plan, "deterministic_short_fallback", e)
                context = _s()._update_context_from_scene(context, code, scene_desc)
                print(
                    f"[STREAM] Scene {scene_num} using deterministic short fallback "
                    f"after provider failure: {e}"
                )
                return code, context

            # Add error feedback to context for retry
            if attempt < max_retries:
                context.scene_history.append(f"[RETRY] {scene_desc}: {str(e)[:100]}")

    # Issue #20: in speed_mode (DRAFT/FAST), `max_retries == 1`, so the loop
    # above fires exactly once — the gate-aware surgical retry that PR #7
    # added is therefore *never* given a chance and the deterministic
    # fallback overrides the scene on every classifiable layout error.
    # Guarantee one surgical retry whenever the failure is classifiable
    # (overlap / accumulation / leftover / edge_crowding / text_overlap),
    # regardless of the speed-mode budget. The cost is one extra LLM call
    # per affected scene — tiny compared to permanently discarding the
    # LLM render and shipping a deterministic template.
    if (
        last_error is not None
        and max_retries < 2
        and _classify_retry_error(str(last_error)) != "generic"
    ):
        try:
            print(
                f"[STREAM] Scene {scene_num} attempting surgical retry before "
                f"deterministic fallback (gate={_classify_retry_error(str(last_error))})"
            )
            surgical_prompt = prompt + _build_retry_addendum(
                last_error, attempt=2, scene_plan=scene_plan
            )
            code_chunks = []
            for token in _s().stream_generate(surgical_prompt, context):
                code_chunks.append(token)
            full_code = "".join(code_chunks)
            if not full_code or len(full_code) < 50:
                raise ValueError(
                    f"Empty surgical response ({len(full_code)} chars)"
                )
            code = _extract_manim_code(full_code)
            code = _sanitize_generated_code(code)
            if context.domain_state.get("video_mode") == "lecture":
                code = _enforce_minimum_font_size(
                    code,
                    int(context.domain_state.get("minimum_label_font_size") or 24),
                )

            from algorithms.code_digest import (
                validate_python_syntax,
                validate_manim_code,
                validate_names_and_imports,
                check_code_quality,
            )

            ok, err = validate_python_syntax(code)
            if not ok:
                raise ValueError(f"Syntax error: {err}")
            ok, err = validate_manim_code(code)
            if not ok:
                raise ValueError(err)
            ok, issues = validate_names_and_imports(code)
            if not ok:
                raise ValueError("; ".join(issues[:3]))
            quality_ok, quality_messages = check_code_quality(code)
            blocking = [m for m in quality_messages if m.startswith("[ERR]")]
            if blocking:
                raise ValueError("; ".join(blocking[:3]))
            pattern_err = _s()._reject_known_bad_patterns(code)
            if pattern_err:
                raise ValueError(pattern_err)
            layout_err = _s()._reject_layout_hygiene_code(code, context, scene_plan)
            if layout_err:
                raise ValueError(layout_err)

            print(
                f"[STREAM] Scene {scene_num} surgical retry succeeded "
                f"({len(code)} chars); using LLM render instead of deterministic fallback"
            )
            _s()._mark_scene_generation(scene_plan, "llm_surgical_retry")
            context = _s()._update_context_from_scene(context, code, scene_desc)
            return code, context
        except Exception as surgical_error:
            print(
                f"[STREAM] Scene {scene_num} surgical retry also failed: "
                f"{surgical_error}"
            )
            last_error = surgical_error

    # All retries (including the surgical retry above when it ran) failed —
    # fall back to a deterministic scene where one is available for this
    # mode. Short mode previously had no per-scene fallback, which meant a
    # single failing scene aborted the whole short video; the job-level
    # short-fallback retry that re-renders every scene is far more expensive
    # than just dropping a deterministic last-resort scene here.
    mode = context.domain_state.get("video_mode")
    if mode == "standard":
        code = _make_standard_fallback_scene_code(scene_plan, context)
        _s()._mark_scene_generation(scene_plan, "deterministic_standard_fallback", last_error)
        context = _s()._update_context_from_scene(context, code, scene_desc)
        print(
            f"[STREAM] Scene {scene_num} using deterministic standard fallback "
            f"after generation failure: {last_error}"
        )
        return code, context

    if mode == "lecture":
        code = _make_lecture_fallback_scene_code(scene_plan, context)
        _s()._mark_scene_generation(scene_plan, "deterministic_lecture_fallback", last_error)
        context = _s()._update_context_from_scene(context, code, scene_desc)
        print(
            f"[STREAM] Scene {scene_num} using deterministic lecture fallback "
            f"after generation failure: {last_error}"
        )
        return code, context

    if mode == "course":
        code = _make_course_fallback_scene_code(scene_plan, context)
        _s()._mark_scene_generation(scene_plan, "deterministic_course_fallback", last_error)
        context = _s()._update_context_from_scene(context, code, scene_desc)
        print(
            f"[STREAM] Scene {scene_num} using deterministic course fallback "
            f"after generation failure: {last_error}"
        )
        return code, context

    if mode == "short":
        code = _make_short_fallback_scene_code(scene_plan, context)
        _s()._mark_scene_generation(scene_plan, "deterministic_short_fallback", last_error)
        context = _s()._update_context_from_scene(context, code, scene_desc)
        print(
            f"[STREAM] Scene {scene_num} using deterministic short fallback "
            f"after generation failure: {last_error}"
        )
        return code, context

    raise RuntimeError(
        f"Scene generation failed after {max_retries} attempts: {last_error}"
    )


def retry_scene(
    scene_plan: dict,
    context: NarrativeContext,
    scene_num: int,
    error: str,
) -> Tuple[str, NarrativeContext]:
    """
    Retry single scene generation with error feedback.

    Unlike full pipeline restart, this only retries the failed scene,
    preserving all previously generated and rendered scenes.

    Args:
        scene_plan: Original scene plan
        context: Current narrative context
        scene_num: Scene index
        error: Error message from failed render

    Returns:
        Tuple of (fixed_code, updated_context)
    """
    print(f"[STREAM] Retrying scene {scene_num} after error: {error[:200]}")

    # Add error context for targeted fix
    context.scene_history.append(
        f"[ERROR] {scene_plan.get('description', '')}: {error[:150]}"
    )

    # Build retry prompt with error context
    scene_desc = scene_plan.get("description", "")
    duration_hint = scene_plan.get("duration_hint", 10)

    mode_contract_prompt = _s()._build_scene_prompt(scene_plan, context, duration_hint)
    mode = str(context.domain_state.get("video_mode") or "").lower()
    # Render-failure retries reuse the same surgical-addendum dispatcher used
    # by generate_scene's in-loop retry; if no specific gate matches we keep
    # the old layout-recovery requirements as the generic fallback so
    # render-time failures (manim runtime errors etc.) still get layout
    # advice when the error mentions overlap/edges.
    layout_recovery = ""
    if _classify_retry_error(error) == "generic" and any(
        marker in error.lower()
        for marker in ("overlap", "crowd frame edges", "ocr", "layout")
    ):
        layout_recovery = """
LAYOUT RECOVERY REQUIREMENTS:
- Rebuild the layout from scratch; do not patch the previous object positions.
- Keep one main anchor VGroup at ORIGIN and scale it to max width 10.4 and max height 5.0.
- Only the main title may sit near the top edge; all other labels must be next_to visible objects with buff >= 0.25.
- Use separate vertical lanes for arrows, captions, and counters so text never lands over cells, lines, or markers.
- Prefer fewer, larger labels over many small labels; no paragraph blocks.
"""
        if mode == "standard":
            layout_recovery += (
                "- For standard mode, keep the YouTube pacing but use a clean "
                "three-lane composition: title lane, animation lane, payoff lane.\n"
            )

    surgical = _surgical_repair_tips(error)

    retry_prompt = f"""{mode_contract_prompt}

The previous generated code failed validation or rendering. Regenerate the full scene under the same storyboard and mode contract.

SCENE: {scene_desc}
DURATION HINT: ~{duration_hint} seconds

RENDER ERROR:
{error}
{layout_recovery}{surgical}
Return ONLY the corrected Python code.
"""

    code_chunks = []
    for token in _s().stream_generate(retry_prompt, context):
        code_chunks.append(token)

    full_code = "".join(code_chunks)
    code = _extract_manim_code(full_code)
    code = _sanitize_generated_code(code)
    if context.domain_state.get("video_mode") == "lecture":
        code = _enforce_minimum_font_size(
            code,
            int(context.domain_state.get("minimum_label_font_size") or 24),
        )

    if "self.camera.frame" in code or ".camera.frame" in code:
        raise ValueError("Retry still used invalid camera.frame API")

    from algorithms.code_digest import (
        check_code_quality,
        validate_manim_code,
        validate_names_and_imports,
        validate_python_syntax,
    )

    syntax_ok, syntax_err = validate_python_syntax(code)
    if not syntax_ok:
        raise ValueError(f"Retry produced syntax error: {syntax_err}")
    structure_ok, structure_err = validate_manim_code(code)
    if not structure_ok:
        raise ValueError(f"Retry produced invalid Manim code: {structure_err}")
    imports_ok, import_issues = validate_names_and_imports(code)
    if not imports_ok:
        raise ValueError(
            "Retry produced invalid imports/names: " + "; ".join(import_issues[:3])
        )
    quality_ok, quality_messages = check_code_quality(code)
    blocking_quality = [msg for msg in quality_messages if msg.startswith("[ERR]")]
    if blocking_quality:
        raise ValueError(
            "Retry produced blocked quality issue: " + "; ".join(blocking_quality[:3])
        )
    pattern_err = _s()._reject_known_bad_patterns(code)
    if pattern_err:
        raise ValueError(f"Retry produced known bad pattern: {pattern_err}")
    layout_hygiene_err = _s()._reject_layout_hygiene_code(code, context, scene_plan)
    if layout_hygiene_err:
        raise ValueError(f"Retry produced layout hygiene issue: {layout_hygiene_err}")
    long_text_err = _s()._reject_unbounded_long_text_code(code, context, scene_plan)
    if long_text_err:
        raise ValueError(f"Retry produced unbounded long text: {long_text_err}")
    short_static_err = _s()._reject_static_short_code(code, context)
    if short_static_err:
        raise ValueError(f"Retry produced static short issue: {short_static_err}")
    short_duration_err = _s()._reject_short_duration_code(code, context, scene_plan)
    if short_duration_err:
        raise ValueError(f"Retry produced short duration issue: {short_duration_err}")
    standard_engagement_err = _s()._reject_standard_engagement_code(
        code, context, scene_plan
    )
    if standard_engagement_err:
        raise ValueError(
            f"Retry produced standard engagement issue: {standard_engagement_err}"
        )
    course_instruction_err = _s()._reject_course_instructional_code(
        code, context, scene_plan
    )
    if course_instruction_err:
        raise ValueError(
            f"Retry produced course instructional issue: {course_instruction_err}"
        )
    lecture_academic_err = _s()._reject_lecture_academic_code(code, context, scene_plan)
    if lecture_academic_err:
        raise ValueError(
            f"Retry produced lecture academic issue: {lecture_academic_err}"
        )

    # Update context
    context = _s()._update_context_from_scene(context, code, f"[RETRY] {scene_desc}")

    return code, context


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE PREAMBLE GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════


def _recover_render_failure(
    scene_plan: dict,
    context: NarrativeContext,
    scene_num: int,
    error_msg: str,
    filename: str,
    job_id: str,
    render_resolution: Optional[Tuple[int, int]] = None,
    quality_flag: str = "-ql",
    fps: int = 30,
    timeout_seconds: Optional[int] = None,
) -> Tuple[Optional[str], bool, str, NarrativeContext]:
    """Retry a failed render once using the targeted scene retry path."""
    try:
        fixed_code, new_context = retry_scene(scene_plan, context, scene_num, error_msg)
        video_path, success, retry_error = _s()._render_single_scene(
            fixed_code,
            filename,
            job_id,
            scene_num,
            render_resolution,
            quality_flag,
            fps,
            timeout_seconds,
        )
        return video_path if success else None, success, retry_error, new_context
    except Exception as e:
        return None, False, str(e), context


def _accept_or_recover_scene_render(
    *,
    scene_num: int,
    scene_plan: dict,
    context: NarrativeContext,
    video_path: str,
    success: bool,
    error_msg: str,
    filename: str,
    job_id: str,
    render_resolution: Optional[Tuple[int, int]],
    quality_flag: str,
    fps: int,
    scene_timeout_seconds: Optional[int],
) -> Tuple[Optional[str], bool, str, NarrativeContext]:
    """Validate a scene render and recover once on render or quality failure."""
    mode = str(context.domain_state.get("video_mode") or "").lower()
    recoverable_original_path = ""
    recoverable_original_reason = ""
    if success and video_path:
        valid, validation_error = _s()._validate_scene_video(
            scene_num,
            video_path,
            mode=mode,
            allow_quality_recovery=mode in {"standard", "course", "lecture"},
        )
        if valid:
            if context.domain_state.get("video_mode") == "short":
                quality = _s().analyze_video_frames(video_path, max_frames=4)
                if short_video_quality_requires_fallback(quality):
                    error_msg = (
                        "short scene failed strict phone-quality gate: "
                        + "; ".join(quality.get("warnings") or ["low short score"])
                    )
                    print(f"[STREAM] Scene {scene_num} strict short gate: {error_msg}")
                else:
                    video_path = _s()._pad_scene_to_min_duration(
                        video_path,
                        float(scene_plan.get("duration_hint") or 0),
                        fps=fps,
                        scene_num=scene_num,
                    )
                    return video_path, True, "", context
            else:
                if _s()._should_pad_scene_duration(context):
                    video_path = _s()._pad_scene_to_min_duration(
                        video_path,
                        float(scene_plan.get("duration_hint") or 0),
                        fps=fps,
                        scene_num=scene_num,
                    )
                return video_path, True, "", context
        else:
            if mode in {"standard", "course", "lecture"}:
                # Look up validate_video_file lazily so tests that
                # monkey-patch ``streaming.validate_video_file`` still stub the
                # call here.
                _streaming = _s()
                original_validation = _streaming.validate_video_file(video_path)
                if original_validation.ok:
                    original_quality = _s().analyze_video_frames(video_path, max_frames=4)
                    if not video_quality_requires_hard_failure(original_quality):
                        recoverable_original_path = video_path
                        recoverable_original_reason = validation_error
            error_msg = validation_error
        success = False

    recovered_path, recovered_ok, recovered_err, context = _s()._recover_render_failure(
        scene_plan,
        context,
        scene_num,
        error_msg,
        filename,
        job_id,
        render_resolution,
        quality_flag,
        fps,
        scene_timeout_seconds,
    )
    if recovered_ok and recovered_path:
        valid, validation_error = _s()._validate_scene_video(
            scene_num,
            recovered_path,
            mode=mode,
            allow_quality_recovery=False,
        )
        if valid:
            if context.domain_state.get("video_mode") == "short":
                quality = _s().analyze_video_frames(recovered_path, max_frames=4)
                if not short_video_quality_requires_fallback(quality):
                    recovered_path = _s()._pad_scene_to_min_duration(
                        recovered_path,
                        float(scene_plan.get("duration_hint") or 0),
                        fps=fps,
                        scene_num=scene_num,
                    )
                    return recovered_path, True, "", context
                error_msg = (
                    "recovered short scene failed strict phone-quality gate: "
                    + "; ".join(quality.get("warnings") or ["low short score"])
                )
                print(f"[STREAM] Scene {scene_num} strict short gate: {error_msg}")
            else:
                if _s()._should_pad_scene_duration(context):
                    recovered_path = _s()._pad_scene_to_min_duration(
                        recovered_path,
                        float(scene_plan.get("duration_hint") or 0),
                        fps=fps,
                        scene_num=scene_num,
                    )
                return recovered_path, True, "", context
        else:
            error_msg = validation_error
    else:
        error_msg = recovered_err or error_msg

    if recoverable_original_path and mode in {"standard", "course", "lecture"}:
        accepted_path = recoverable_original_path
        if _s()._should_pad_scene_duration(context):
            accepted_path = _s()._pad_scene_to_min_duration(
                accepted_path,
                float(scene_plan.get("duration_hint") or 0),
                fps=fps,
                scene_num=scene_num,
            )
        detail = (
            "accepted original render after failed mode-aware recovery: "
            + (error_msg or recoverable_original_reason)
        )
        scene_plan["_render_recovery_note"] = re.sub(r"\s+", " ", detail).strip()[:260]
        print(f"[STREAM] Scene {scene_num} {scene_plan['_render_recovery_note']}")
        return accepted_path, True, "", context

    current_mode = str(context.domain_state.get("video_mode") or "").lower()
    if current_mode == "short":
        fallback_path, fallback_ok, fallback_err, context = _s()._render_short_fallback_scene(
            scene_plan,
            context,
            scene_num,
            filename,
            job_id,
            render_resolution,
            quality_flag,
            fps,
            scene_timeout_seconds,
        )
        if fallback_ok:
            fallback_path = _s()._pad_scene_to_min_duration(
                fallback_path,
                float(scene_plan.get("duration_hint") or 0),
                fps=fps,
                scene_num=scene_num,
            )
            return fallback_path, True, "", context
        return fallback_path, False, fallback_err or error_msg, context
    if current_mode in {"standard", "course", "lecture"}:
        fallback_path, fallback_ok, fallback_err, context = _s()._render_mode_fallback_scene(
            scene_plan,
            context,
            scene_num,
            filename,
            job_id,
            render_resolution,
            quality_flag,
            fps,
            scene_timeout_seconds,
        )
        if fallback_ok and fallback_path:
            if _s()._should_pad_scene_duration(context):
                fallback_path = _s()._pad_scene_to_min_duration(
                    fallback_path,
                    float(scene_plan.get("duration_hint") or 0),
                    fps=fps,
                    scene_num=scene_num,
                )
            detail = (
                f"accepted deterministic {current_mode} fallback after failed "
                f"mode-aware recovery: " + (error_msg or "unknown")
            )
            scene_plan["_render_recovery_note"] = re.sub(r"\s+", " ", detail).strip()[:260]
            print(f"[STREAM] Scene {scene_num} {scene_plan['_render_recovery_note']}")
            return fallback_path, True, "", context
        return None, False, fallback_err or error_msg, context
    return None, False, error_msg, context


# ═══════════════════════════════════════════════════════════════════════════════
# PARALLEL RENDER-WHILE-GENERATE
# ═══════════════════════════════════════════════════════════════════════════════


def stream_render_scenes(
    scenes: List[dict],
    job_id: str,
    narrative_context: NarrativeContext,
    filename: str,
    max_scene_retries: int = 2,
    render_resolution: Optional[Tuple[int, int]] = None,
    quality_flag: str = "-ql",
    fps: int = 30,
    scene_timeout_seconds: Optional[int] = None,
) -> Tuple[List[str], NarrativeContext, List[dict], Dict[int, Tuple[str, bool, str]]]:
    """
    Render scenes in parallel while generating the next scene.

    Algorithm:
    1. Generate scene 0
    2. Start rendering scene 0 in background thread
    3. While scene 0 renders, generate scene 1
    4. When scene 0 render completes, start scene 1 render
    5. Continue until all scenes are generated and rendered

    This achieves overlap: scene N is rendering while scene N+1 is being generated.

    Args:
        scenes: List of scene plans from split_plan_into_scenes
        job_id: Job identifier for tracking
        narrative_context: Initial narrative context
        filename: Base filename for output
        max_scene_retries: Max retries per scene

    Returns:
        Tuple of (video_paths, final_context, errors, completed_renders)
    """
    video_paths = []
    errors = []
    context = narrative_context
    # Thread pool for parallel rendering
    render_executor = ThreadPoolExecutor(max_workers=max(1, STREAM_PARALLEL_RENDERS))

    # Track pending renders
    pending_renders = {}  # scene_num -> future
    completed_renders = {}  # scene_num -> (video_path, success, error)

    context.domain_state["total_scenes"] = len(scenes)
    print(f"[STREAM] Starting streaming pipeline for {len(scenes)} scenes")

    for scene_num, scene_plan in enumerate(scenes):
        print(f"[STREAM] === Scene {scene_num + 1}/{len(scenes)} ===")

        # ── Generate this scene ───────────────────────────────────────
        try:
            code, context = generate_scene(
                scene_plan, context, scene_num, max_scene_retries
            )
        except Exception as e:
            print(f"[STREAM] Scene {scene_num} generation failed: {e}")
            # Try retry with error feedback
            if max_scene_retries > 0:
                try:
                    code, context = retry_scene(scene_plan, context, scene_num, str(e))
                    _s()._mark_scene_generation(scene_plan, "llm_retry", e)
                except Exception as retry_err:
                    _s()._mark_scene_generation(scene_plan, "generation_failed", retry_err)
                    errors.append(
                        {
                            "scene": scene_num,
                            "error": str(retry_err),
                            "type": "generation_retry",
                            "initial_error": str(e),
                        }
                    )
                continue
            else:
                _s()._mark_scene_generation(scene_plan, "generation_failed", e)
                errors.append(
                    {"scene": scene_num, "error": str(e), "type": "generation"}
                )
                continue

        # ── Check if previous scene render is done, then start new render ──
        if scene_num > 0 and (scene_num - 1) in pending_renders:
            # Wait for previous scene's render to complete
            prev_future = pending_renders.pop(scene_num - 1)
            try:
                video_path, success, error_msg = prev_future.result(
                    timeout=RENDER_TIMEOUT_SECONDS
                )
                accepted_path, accepted_ok, accepted_err, context = (
                    _accept_or_recover_scene_render(
                        scene_num=scene_num - 1,
                        scene_plan=scenes[scene_num - 1],
                        context=context,
                        video_path=video_path,
                        success=success,
                        error_msg=error_msg,
                        filename=filename,
                        job_id=job_id,
                        render_resolution=render_resolution,
                        quality_flag=quality_flag,
                        fps=fps,
                        scene_timeout_seconds=scene_timeout_seconds,
                    )
                )
                completed_renders[scene_num - 1] = (
                    accepted_path or "",
                    accepted_ok,
                    accepted_err,
                )
                if not accepted_ok:
                    errors.append(
                        {
                            "scene": scene_num - 1,
                            "error": accepted_err,
                            "type": classify_render_error(accepted_err),
                        }
                    )
            except Exception as e:
                errors.append(
                    {"scene": scene_num - 1, "error": str(e), "type": "render_timeout"}
                )

        # ── Start rendering this scene in background ───────────────────
        print(f"[STREAM] Starting render for scene {scene_num} in background")
        future = render_executor.submit(
            _render_single_scene,
            code,
            filename,
            job_id,
            scene_num,
            render_resolution,
            quality_flag,
            fps,
            scene_timeout_seconds,
        )
        pending_renders[scene_num] = future

    # ── Wait for final scene render ─────────────────────────────────────
    for scene_num in list(pending_renders.keys()):
        if scene_num in pending_renders:
            future = pending_renders.pop(scene_num)
            try:
                video_path, success, error_msg = future.result(
                    timeout=RENDER_TIMEOUT_SECONDS
                )
                accepted_path, accepted_ok, accepted_err, context = (
                    _accept_or_recover_scene_render(
                        scene_num=scene_num,
                        scene_plan=scenes[scene_num],
                        context=context,
                        video_path=video_path,
                        success=success,
                        error_msg=error_msg,
                        filename=filename,
                        job_id=job_id,
                        render_resolution=render_resolution,
                        quality_flag=quality_flag,
                        fps=fps,
                        scene_timeout_seconds=scene_timeout_seconds,
                    )
                )
                completed_renders[scene_num] = (
                    accepted_path or "",
                    accepted_ok,
                    accepted_err,
                )
                if not accepted_ok:
                    errors.append(
                        {
                            "scene": scene_num,
                            "error": accepted_err,
                            "type": classify_render_error(accepted_err),
                        }
                    )
            except Exception as e:
                errors.append(
                    {
                        "scene": scene_num,
                        "error": str(e),
                        "type": classify_render_error(str(e)),
                    }
                )

    render_executor.shutdown(wait=True)

    # Build ordered, de-duplicated list of successful scene videos.
    video_paths = []
    for scene_num in sorted(completed_renders.keys()):
        video_path, success, _ = completed_renders[scene_num]
        if success and video_path:
            video_paths.append(video_path)

    print(
        f"[STREAM] Pipeline complete: {len(video_paths)} scenes rendered, {len(errors)} errors"
    )

    return video_paths, context, errors, completed_renders


# ═══════════════════════════════════════════════════════════════════════════════
# SCENE STITCHING
# ═══════════════════════════════════════════════════════════════════════════════


def stitch_scenes(scene_videos: List[str], output: str, fps: int = 30) -> str:
    """
    Concatenate scene videos using ffmpeg.

    Args:
        scene_videos: List of video file paths in order
        output: Output file path

    Returns:
        Path to stitched video
    """
    if not scene_videos:
        raise ValueError("No scene videos to stitch")

    fps = max(1, int(fps or 30))

    if len(scene_videos) == 1:
        # Single scene — just copy
        import shutil

        shutil.copy2(scene_videos[0], output)
        return output

    normalized_dir = Path(
        tempfile.mkdtemp(prefix="nima-stitch-", dir=str(Path(output).parent))
    )
    concat_file = str(normalized_dir / "concat.txt")
    normalized_paths = []

    try:
        for idx, video_path in enumerate(scene_videos):
            source = Path(video_path)
            if not source.exists():
                continue

            normalized_path = normalized_dir / f"clip_{idx:03d}.mp4"
            result = subprocess.run(
                [
                    *_ffmpeg_command(),
                    "-y",
                    "-i",
                    str(source),
                    "-vf",
                    f"scale=trunc(iw/2)*2:trunc(ih/2)*2,fps={fps},format=yuv420p",
                    "-r",
                    str(fps),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-af",
                    "aresample=44100",
                    str(normalized_path),
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0 or not normalized_path.exists():
                raise RuntimeError(
                    f"ffmpeg normalize failed for {source.name}: {result.stderr[-300:]}"
                )
            normalized_paths.append(str(normalized_path))

        if not normalized_paths:
            raise RuntimeError("No normalized scene videos available for stitching")

        with open(concat_file, "w", encoding="utf-8") as f:
            for video_path in normalized_paths:
                safe_path = video_path.replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        result = subprocess.run(
            [
                *_ffmpeg_command(),
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_file,
                "-fflags",
                "+genpts",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-r",
                str(fps),
                output,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-300:]}")

        print(f"[STITCH] Created {output} from {len(scene_videos)} scenes")

    except FileNotFoundError as err:
        raise RuntimeError("ffmpeg not found — install ffmpeg to use scene stitching") from err
    finally:
        for normalized_path in normalized_paths:
            path = Path(normalized_path)
            if path.exists():
                path.unlink()
        if Path(concat_file).exists():
            Path(concat_file).unlink()
        if normalized_dir.exists():
            normalized_dir.rmdir()

    return output


# ═══════════════════════════════════════════════════════════════════════════════
# TOKEN BUDGET ESTIMATION
# ═══════════════════════════════════════════════════════════════════════════════


def estimate_scene_cost(scene_plan: dict) -> int:
    """
    Estimate tokens needed for a scene.

    Used for token budget tracking and provider selection.
    Returns estimated token count.
    """
    desc = scene_plan.get("description", "")
    animation_steps = scene_plan.get("animation_steps", [])
    objects = scene_plan.get("objects", [])

    # Rough estimation: ~4 chars per token average
    base_tokens = len(desc) // 4
    step_tokens = sum(len(str(s)) // 4 for s in animation_steps)
    object_tokens = sum(len(o) // 4 for o in objects)

    # Add overhead for context and system prompt (~500 tokens)
    overhead = 500

    return base_tokens + step_tokens + object_tokens + overhead


def select_provider_for_budget(token_estimate: int) -> str:
    """
    Select appropriate provider based on token budget.

    Higher token estimates need more reliable/slower providers.
    """
    if token_estimate < 500:
        return "zjuapi"  # Fast, good for simple scenes
    elif token_estimate < 1500:
        return "wenwen"  # Balanced
    else:
        return "openai"  # Most reliable for complex scenes
