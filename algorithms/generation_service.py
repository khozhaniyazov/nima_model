"""Bulk Manim code generation and validation service."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from config import (
    DEFAULT_VIDEO_MODE,
    DRAFT_PIPELINE,
    FAST_PIPELINE,
    MAX_GENERATION_ATTEMPTS,
    OUTPUTS,
)
from algorithms.ai_functions import generate_manim_code, polish_manim_code, review_and_fix
from algorithms.code_digest import (
    check_code_quality,
    ensure_scene_class,
    validate_latex_strings,
    validate_manim_code,
    validate_names_and_imports,
    validate_python_syntax,
)
from algorithms.overlap_detector import run_all_checks as detect_overlaps
from algorithms.plan.compiler import compile_plan
from algorithms.plan.schema import validate_plan_dict
from algorithms.request_analysis import (
    analyze_request_type,
    create_animation_plan,
    create_narrated_plan,
    create_plan_json,
    expand_short_prompt,
)
from algorithms.template_registry import choose_template
from algorithms.tts import generate_voiceover
from algorithms.video_modes import apply_video_mode_to_analysis


@dataclass
class GenerationServiceDeps:
    db: Any = None
    update_status: Callable[..., dict] | None = None


def _available_audio_segment_count(audio_segments: dict) -> int:
    return sum(
        1
        for payload in (audio_segments or {}).values()
        if isinstance(payload, dict)
        and payload.get("path")
        and Path(payload["path"]).exists()
    )


def _noop_status(job_id: str, **updates: Any) -> dict:
    return dict(updates)


def generate_and_validate_code_job(
    prompt: str,
    job_id: str,
    max_attempts: int = MAX_GENERATION_ATTEMPTS,
    voiceover: bool = False,
    voice: str = None,
    video_mode: str = DEFAULT_VIDEO_MODE,
    *,
    deps: GenerationServiceDeps,
) -> tuple[str, list, str | None, str | None, dict, list, bool, dict]:
    """
    Full AI pipeline:
      analyze → plan → [voiceover] → generate → combined review → validate → polish
    Returns (code, attempts_log, request_id, attempt_id, audio_segments, segment_order, is_fast, analysis).
    """
    update_status = deps.update_status or _noop_status
    db = deps.db
    attempts_log = []
    request_id = None
    is_fast = FAST_PIPELINE or DRAFT_PIPELINE
    if is_fast:
        max_attempts = 1
    audio_segments = {}
    segment_order = []

    prompt = expand_short_prompt(prompt)

    # TIMING: Analysis
    t0 = time.time()
    update_status(job_id, message="Analyzing request...")
    analysis = apply_video_mode_to_analysis(analyze_request_type(prompt), video_mode)
    video_mode = analysis["video_mode"]
    print(f"[TIMING] Analysis: {time.time() - t0:.2f}s")
    attempts_log.append({"stage": "analysis", "data": analysis})

    if db and db.available:
        request_id = db.save_request(prompt, analysis)
        print(f"[DB] [OK] Saved request: {request_id}")

    # TIMING: Planning
    t1 = time.time()
    if voiceover:
        update_status(job_id, message="Creating narrated timeline...")
        plan = create_narrated_plan(prompt, analysis)
        try:
            parsed = json.loads(plan)
            segments = parsed.get("segments", [])
            segment_order = [s["id"] for s in segments]

            update_status(job_id, message="Generating narration audio...")
            audio_out_dir = OUTPUTS / "audio" / job_id
            audio_segments = generate_voiceover(
                segments, str(audio_out_dir), voice=voice
            )
            if _available_audio_segment_count(audio_segments) == 0:
                segment_errors = [
                    str(payload.get("error"))
                    for payload in audio_segments.values()
                    if isinstance(payload, dict) and payload.get("error")
                ]
                detail = f": {'; '.join(segment_errors[:3])}" if segment_errors else ""
                raise RuntimeError(
                    "Voiceover was requested but no narration audio was generated"
                    + detail
                )
        except Exception as e:
            print(f"[{job_id}] [ERR] Narration failed: {e}")
            raise RuntimeError(f"Narration failed: {e}") from e
    else:
        update_status(job_id, message="Creating animation storyboard...")
        plan = create_animation_plan(prompt, analysis)

    print(f"[TIMING] Planning: {time.time() - t1:.2f}s")

    if is_fast and (analysis.get("domain") == "math") and (not voiceover):
        try:
            update_status(job_id, message="Creating plan JSON (deterministic)...")
            template_name = choose_template(prompt, analysis.get("domain"))
            if template_name:
                print(f"[{job_id}] [PLAN] Using template: {template_name}")
            plan_json = create_plan_json(prompt, analysis, template_name=template_name)
            if not plan_json.strip():
                raise ValueError("Empty plan JSON")
            plan_data = json.loads(plan_json)
            issues = validate_plan_dict(plan_data)
            if issues:
                raise ValueError("; ".join(issues))
            plan_compiled_code = compile_plan(plan_data)
            attempts_log.append(
                {
                    "stage": "plan_json",
                    "success": True,
                    "template": template_name,
                    "fast": True,
                }
            )
        except Exception as e:
            print(f"[{job_id}] [PLAN] [ERR] Fast plan compiler fallback: {e}")
            plan_compiled_code = None

    else:
        # ── Plan-first deterministic compilation (hybrid mode) ───────────────────
        plan_compiled_code = None
        use_plan_compiler = (analysis.get("domain") == "math") and (not voiceover)
        if use_plan_compiler:
            try:
                update_status(
                    job_id, message="Creating plan JSON (deterministic)..."
                )
                template_name = choose_template(prompt, analysis.get("domain"))
                if template_name:
                    print(f"[{job_id}] [PLAN] Using template: {template_name}")
                plan_json = create_plan_json(
                    prompt, analysis, template_name=template_name
                )
                plan_data = json.loads(plan_json)
                issues = validate_plan_dict(plan_data)
                if issues:
                    raise ValueError("; ".join(issues))
                plan_compiled_code = compile_plan(plan_data)
                attempts_log.append(
                    {"stage": "plan_json", "success": True, "template": template_name}
                )
            except Exception as e:
                print(f"[{job_id}] [PLAN] [ERR] Plan compiler fallback: {e}")
                plan_compiled_code = None

    if plan_compiled_code:
        code = ensure_scene_class(plan_compiled_code)

        # Safety validation
        update_status(job_id, message="Validating code safety...")
        is_safe, safety_issues = validate_names_and_imports(code)
        if not is_safe:
            print(f"[{job_id}] [SECURITY] Plan code unsafe: {safety_issues}")
            # Fallback to LLM path
        else:
            # Syntax validation
            update_status(job_id, message="Validating syntax...")
            syntax_valid, syntax_error = validate_python_syntax(code)
            if not syntax_valid:
                print(f"[{job_id}] [ERR] Plan syntax error: {syntax_error}")
            else:
                # Structure validation
                structure_valid, structure_error = validate_manim_code(code)
                if not structure_valid:
                    print(f"[{job_id}] [ERR] Plan structure error: {structure_error}")
                else:
                    # Quality warnings (non-blocking)
                    quality_passes, quality_feedback = check_code_quality(code)
                    attempts_log.append(
                        {
                            "stage": "quality",
                            "success": quality_passes,
                            "feedback": quality_feedback,
                        }
                    )

                    # Block on critical errors (MathTex indexing, forbidden imports, etc.)
                    critical_errors = [
                        w for w in quality_feedback if w.startswith("[ERR]")
                    ]
                    if critical_errors:
                        print(
                            f"[{job_id}] [QUALITY] Critical errors detected, falling back to LLM path:"
                        )
                        for err in critical_errors:
                            print(f"  {err}")
                        # Fall through to LLM generation path which can fix these
                    else:
                        # Overlap / scene-hygiene detection (non-blocking here)
                        update_status(
                            job_id, message="Checking for layout overlaps..."
                        )
                        overlap_warnings = detect_overlaps(code)
                        if overlap_warnings:
                            print(
                                f"[{job_id}] [OVERLAP] {len(overlap_warnings)} issues detected in plan code"
                            )
                            for w in overlap_warnings:
                                print(f"  {w}")
                            attempts_log.append(
                                {"stage": "overlap_check", "warnings": overlap_warnings}
                            )

                        return (
                            code,
                            attempts_log,
                            request_id,
                            None,
                            audio_segments,
                            segment_order,
                            is_fast,
                            analysis,
                        )

    for attempt in range(1, max_attempts + 1):
        print(f"\n[{job_id}] {'=' * 50}")
        print(f"[{job_id}] GENERATION ATTEMPT {attempt}/{max_attempts}")
        print(f"[{job_id}] {'=' * 50}\n")
        attempt_start = time.time()

        # TIMING: Code generation
        t_gen = time.time()
        # 1. Generate
        update_status(job_id, message=f"Generating code (attempt {attempt})...")

        # ── Check prompt cache ──────────────────────────────────────────
        try:
            from cache import prompt_cache

            cache_extra = {
                "plan": str(plan)[:500] if plan else "",
                "video_mode": analysis.get("video_mode", video_mode),
                "target_duration": analysis.get("target_duration"),
                "aspect": analysis.get("aspect"),
            }
            cached_result = prompt_cache.check(
                prompt,
                domain=analysis.get("domain", ""),
                voiceover=bool(voiceover),
                extra=cache_extra,
            )
            if cached_result:
                print(f"[CACHE] Prompt cache HIT — skipping AI generation")
                code = cached_result.get("code", "")
                attempts_log.extend(cached_result.get("attempts_log", []))
                print(f"[TIMING] LLM generation: 0.00s (cache hit)")
            else:
                code = generate_manim_code(
                    prompt,
                    analysis,
                    plan,
                    attempt,
                    db=db,
                    segment_durations=audio_segments if voiceover else None,
                )
                # Store in cache
                prompt_cache.store(
                    prompt,
                    {"code": code, "attempts_log": attempts_log.copy()},
                    domain=analysis.get("domain", ""),
                    voiceover=bool(voiceover),
                    extra=cache_extra,
                )
        except Exception as e:
            print(f"[CACHE] Prompt cache error: {e}")
            code = generate_manim_code(
                prompt,
                analysis,
                plan,
                attempt,
                db=db,
                segment_durations=audio_segments if voiceover else None,
            )
        print(f"[TIMING] LLM generation: {time.time() - t_gen:.2f}s")
        attempts_log.append(
            {"attempt": attempt, "stage": "generation", "success": True}
        )

        # 2. Combined review - check for critical errors
        # Skip expensive quality checks in FAST/DRAFT_PIPELINE
        is_fast = FAST_PIPELINE or DRAFT_PIPELINE
        if is_fast:
            quality_passes, quality_feedback = True, []
            has_critical_errors = False
        else:
            quality_passes, quality_feedback = check_code_quality(code)
            has_critical_errors = any(w.startswith("[ERR]") for w in quality_feedback)

        # 2b. LaTeX validation for math domain - skip in FAST/DRAFT_PIPELINE
        latex_valid, latex_issues = True, []
        if not is_fast and analysis.get("domain") == "math":
            latex_valid, latex_issues = validate_latex_strings(code)
            if not latex_valid:
                print(f"[{job_id}] [LATEX] LaTeX issues detected: {latex_issues}")
                latex_note = "\n".join(latex_issues)
                code = review_and_fix(
                    code, f"{prompt}\n\n[LATEX ERRORS TO FIX]:\n{latex_note}", analysis
                )
                latex_valid, latex_issues = validate_latex_strings(code)
                if not latex_valid:
                    has_critical_errors = True

        force_review = has_critical_errors

        # In FAST/DRAFT_PIPELINE, skip review entirely unless there are critical errors
        if is_fast:
            if has_critical_errors:
                update_status(job_id, message="Fixing critical errors...")
                error_note = "\n".join(
                    [w for w in quality_feedback if w.startswith("[ERR]")]
                )
                code = review_and_fix(
                    code,
                    f"{prompt}\n\n[CRITICAL ERRORS TO FIX]:\n{error_note}",
                    analysis,
                )
            else:
                attempts_log.append(
                    {
                        "attempt": attempt,
                        "stage": "review",
                        "skipped": True,
                        "reason": "fast_pipeline",
                    }
                )

        # 3. Security / safety validation - skip in FAST/DRAFT_PIPELINE
        if not is_fast:
            update_status(job_id, message="Validating code safety...")
            is_safe, safety_issues = validate_names_and_imports(code)
            if not is_safe:
                print(
                    f"[{job_id}] [SECURITY] Unsafe patterns detected: {safety_issues}"
                )
                # Feed safety violations into the review pass to auto-fix them
                safety_note = "\n".join(safety_issues)
                code = review_and_fix(
                    code,
                    f"{prompt}\n\n[SECURITY VIOLATIONS TO FIX]:\n{safety_note}",
                    analysis,
                )
                is_safe, safety_issues = validate_names_and_imports(code)
                if not is_safe and attempt < max_attempts:
                    continue
        else:
            is_safe, safety_issues = True, []

        # 4. Syntax validation
        update_status(job_id, message="Validating syntax...")
        syntax_valid, syntax_error = validate_python_syntax(code)
        if not syntax_valid:
            print(f"[{job_id}] [ERR] Syntax error: {syntax_error}")
            attempts_log.append(
                {
                    "attempt": attempt,
                    "stage": "syntax",
                    "success": False,
                    "error": syntax_error,
                }
            )
            if db and db.available:
                db.record_error_pattern(
                    {
                        "category": "syntax",
                        "signature": str(hash(syntax_error)),
                        "message": syntax_error,
                        "code_snippet": code[:200],
                    }
                )
            if not is_fast:
                code = polish_manim_code(code)
                syntax_valid, syntax_error = validate_python_syntax(code)
                if not syntax_valid:
                    if attempt < max_attempts:
                        continue
                    raise Exception(f"Syntax error could not be fixed: {syntax_error}")
            else:
                if attempt < max_attempts:
                    continue
                raise Exception(f"Syntax error: {syntax_error}")

        attempts_log.append({"attempt": attempt, "stage": "syntax", "success": True})

        # 4. Scene class / structure
        code = ensure_scene_class(code)
        structure_valid, structure_error = validate_manim_code(code)
        if not structure_valid:
            if attempt < max_attempts:
                if not is_fast:
                    code = polish_manim_code(code)
                continue
            raise Exception(f"Structure error: {structure_error}")

        attempts_log.append({"attempt": attempt, "stage": "structure", "success": True})

        # 5. Quality warnings (non-blocking) - skip in FAST/DRAFT_PIPELINE
        if not is_fast:
            quality_passes, quality_feedback = check_code_quality(code)
            attempts_log.append(
                {
                    "attempt": attempt,
                    "stage": "quality",
                    "success": quality_passes,
                    "feedback": quality_feedback,
                }
            )
        else:
            quality_passes, quality_feedback = True, []

        # 6. Overlap detection - skip in FAST/DRAFT_PIPELINE
        if not is_fast:
            update_status(job_id, message="Checking for layout overlaps...")
            overlap_warnings = detect_overlaps(code)
            if overlap_warnings:
                print(f"[{job_id}] [OVERLAP] {len(overlap_warnings)} issues detected")
                for w in overlap_warnings:
                    print(f"  {w}")
                # Feed overlap warnings back to review for a targeted fix
                overlap_note = "\n".join(overlap_warnings)
                code = review_and_fix(
                    code,
                    f"{prompt}\n\n[LAYOUT OVERLAP ISSUES TO FIX]:\n{overlap_note}",
                    analysis,
                )
                code = ensure_scene_class(code)
                # Re-check (don't loop — one repair pass is enough)
                remaining = detect_overlaps(code)
                if remaining:
                    print(
                        f"[{job_id}] [OVERLAP] {len(remaining)} issues remain after fix attempt"
                    )
                    quality_feedback.extend(remaining)
                else:
                    print(f"[{job_id}] [OVERLAP] All issues resolved")

            attempts_log.append(
                {
                    "attempt": attempt,
                    "stage": "overlap_fix",
                    "warnings": overlap_warnings,
                    "remaining": len(overlap_warnings) if overlap_warnings else 0,
                }
            )
        else:
            # FAST/DRAFT_PIPELINE: skip overlap detection
            overlap_warnings = []
            attempts_log.append(
                {"attempt": attempt, "stage": "overlap_fix", "skipped": True}
            )

        attempt_time = int((time.time() - attempt_start) * 1000)
        attempt_id = None
        if db and db.available and request_id:
            attempt_id = db.save_generation_attempt(
                request_id,
                {
                    "attempt_number": attempt,
                    "plan": plan,
                    "code": code,
                    "critique": "",
                    "improved_code": code,
                    "syntax_valid": syntax_valid,
                    "syntax_error": None,
                    "structure_valid": structure_valid,
                    "warnings": quality_feedback,
                    "generation_time_ms": attempt_time,
                },
            )
            print(f"[DB] [OK] Saved attempt: {attempt_id}")

        print(f"[TIMING] Total code generation: {time.time() - t0:.2f}s")
        return (
            code,
            attempts_log,
            request_id,
            attempt_id,
            audio_segments,
            segment_order,
            is_fast,
            analysis,
        )

    raise Exception("All generation attempts failed.")


