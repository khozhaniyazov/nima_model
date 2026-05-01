from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from algorithms.webhook_service import render_event_payload


@dataclass
class JobSubmissionDeps:
    set_status: Callable[[str, dict], None]
    finish_status: Callable[..., dict]
    set_request: Callable[[str, dict], None]
    generate_and_validate_code: Callable[..., tuple]
    stream_generate_and_render: Callable[..., tuple]
    render_async: Callable[..., Any]
    dispatch_background: Callable[..., Any]
    max_generation_attempts: int
    trigger_webhooks: Callable[[str, str, dict], Any] | None = None


def _new_job_id() -> str:
    return str(uuid.uuid4())[:8]


def _safe_prompt(prompt: str, *, limit: int | None = None) -> str:
    text = prompt.encode("ascii", "ignore").decode()
    return text[:limit] if limit else text


def _finish_failed_job(
    deps: JobSubmissionDeps,
    job_id: str,
    exc: Exception,
    *,
    video_mode: str,
) -> None:
    snapshot = deps.finish_status(
        job_id,
        status="error",
        message=str(exc),
        video_file="",
        video_mode=video_mode,
    )
    if deps.trigger_webhooks:
        deps.trigger_webhooks(
            job_id,
            "render.error",
            render_event_payload(
                job_id,
                (snapshot or {}).get("batch_id"),
                "error",
                error=str(exc),
            ),
        )


def submit_form_job(
    prompt: str,
    *,
    deps: JobSubmissionDeps,
    voiceover: bool,
    video_mode: str,
) -> str:
    job_id = _new_job_id()
    filename = f"video_{job_id}"

    print(f"\n{'#' * 60}")
    print(f"[{job_id}] NEW REQUEST: {_safe_prompt(prompt)}")
    print(f"{'#' * 60}\n")

    deps.set_status(
        job_id,
        {
            "status": "generating",
            "message": "Analyzing and planning...",
            "video_file": "",
            "video_mode": video_mode,
        },
    )

    (
        code,
        attempts_log,
        request_id,
        attempt_id,
        a_segs,
        a_order,
        is_fast,
        analysis,
    ) = deps.generate_and_validate_code(
        prompt,
        job_id,
        max_attempts=deps.max_generation_attempts,
        voiceover=voiceover,
        video_mode=video_mode,
    )

    deps.set_request(job_id, {"request_id": request_id, "prompt": prompt})
    deps.render_async(
        code,
        filename,
        job_id,
        request_id,
        prompt,
        attempt_id,
        a_segs,
        a_order,
        is_fast,
        analysis,
    )
    return job_id


def submit_api_job(
    prompt: str,
    *,
    deps: JobSubmissionDeps,
    streaming: bool,
    voiceover: bool,
    voice: str,
    visual_template: str | None,
    intro_outro: dict,
    watermark: dict,
    video_mode: str,
) -> str:
    job_id = _new_job_id()
    filename = f"video_{job_id}"

    print(f"\n{'#' * 60}")
    print(f"[{job_id}] NEW REQUEST (API) Voiceover={voiceover}: {_safe_prompt(prompt)}")
    print(f"[{job_id}] PIPELINE: {'STREAMING' if streaming else 'BULK'}")
    print(f"[{job_id}] MODE: {video_mode}")
    print(f"{'#' * 60}\n")

    deps.set_status(
        job_id,
        {
            "status": "queued",
            "message": "Queued for processing...",
            "video_file": "",
            "video_mode": video_mode,
        },
    )

    def background_generate() -> None:
        try:
            deps.set_status(
                job_id,
                {
                    "status": "generating",
                    "message": "Analyzing and planning...",
                    "video_file": "",
                    "video_mode": video_mode,
                },
            )
            if streaming:
                deps.stream_generate_and_render(
                    prompt,
                    job_id,
                    analysis=None,
                    voiceover=voiceover,
                    voice=voice,
                    visual_template=visual_template,
                    intro_outro=intro_outro,
                    watermark=watermark,
                    video_mode=video_mode,
                )
                deps.set_request(job_id, {"request_id": None, "prompt": prompt})
            else:
                (
                    code,
                    attempts_log,
                    req_id,
                    att_id,
                    a_segs,
                    a_order,
                    is_fast,
                    analysis,
                ) = deps.generate_and_validate_code(
                    prompt,
                    job_id,
                    max_attempts=deps.max_generation_attempts,
                    voiceover=voiceover,
                    voice=voice,
                    video_mode=video_mode,
                )
                deps.set_request(job_id, {"request_id": req_id, "prompt": prompt})
                deps.render_async(
                    code,
                    filename,
                    job_id,
                    req_id,
                    prompt,
                    att_id,
                    a_segs,
                    a_order,
                    is_fast,
                    analysis,
                    watermark,
                )
        except Exception as exc:
            print(f"[{job_id}] [ERR] ERROR in background generation: {exc}")
            _finish_failed_job(deps, job_id, exc, video_mode=video_mode)

    deps.dispatch_background(background_generate, name=f"generate-{job_id}")
    return job_id


def submit_batch_jobs(
    prompts_data: list,
    *,
    deps: JobSubmissionDeps,
    voiceover: bool,
    voice: str,
    video_mode: str,
) -> tuple[str, list[dict]]:
    from algorithms.request_analysis import expand_short_prompt

    batch_id = _new_job_id()
    jobs: list[dict] = []

    for i, item in enumerate(prompts_data):
        if isinstance(item, dict):
            prompt = (item.get("prompt") or "").strip()
        else:
            prompt = str(item).strip()

        if not prompt:
            continue

        job_id = _new_job_id()
        filename = f"video_{job_id}"

        print(
            f"\n[{job_id}] BATCH [{batch_id}] ITEM {i + 1}: "
            f"{_safe_prompt(prompt, limit=50)}..."
        )

        deps.set_status(
            job_id,
            {
                "status": "queued",
                "message": "Queued for processing...",
                "video_file": "",
                "batch_id": batch_id,
                "video_mode": video_mode,
            },
        )

        def background_generate(
            prompt_text: str = prompt,
            item_job_id: str = job_id,
            item_filename: str = filename,
        ) -> None:
            try:
                deps.set_status(
                    item_job_id,
                    {
                        "status": "generating",
                        "message": "Analyzing and planning...",
                        "video_file": "",
                        "batch_id": batch_id,
                        "video_mode": video_mode,
                    },
                )
                expanded_prompt = expand_short_prompt(prompt_text)
                (
                    code,
                    attempts_log,
                    req_id,
                    att_id,
                    a_segs,
                    a_order,
                    is_fast,
                    analysis,
                ) = deps.generate_and_validate_code(
                    expanded_prompt,
                    item_job_id,
                    max_attempts=deps.max_generation_attempts,
                    voiceover=voiceover,
                    voice=voice,
                    video_mode=video_mode,
                )
                deps.set_request(
                    item_job_id,
                    {"request_id": req_id, "prompt": expanded_prompt},
                )
                deps.render_async(
                    code,
                    item_filename,
                    item_job_id,
                    req_id,
                    expanded_prompt,
                    att_id,
                    a_segs,
                    a_order,
                    is_fast,
                    analysis,
                )
            except Exception as exc:
                print(f"[{item_job_id}] [ERR] Batch item error: {exc}")
                _finish_failed_job(deps, item_job_id, exc, video_mode=video_mode)

        deps.dispatch_background(background_generate, name=f"batch-{job_id}")
        jobs.append({"prompt": prompt, "job_id": job_id})

    return batch_id, jobs
