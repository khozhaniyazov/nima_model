"""
NIMA — Flask server.
Orchestrates the full pipeline:
  analyze → plan → generate → review → [render → (error→fix→render)×3]

Key improvements vs. original:
  - Single source of truth: all config from config.py
  - Render-error self-healing: up to MAX_RENDER_RETRIES attempts,
    feeding Manim stderr back to fix_render_error() between each attempt
  - ManimDatabase lives in a database adapter and is injected into services
  - Clean separation: code generation is synchronous before the async render
"""

from functools import partial
from datetime import datetime

from flask import Flask
from flask_cors import CORS
from typing import Optional, Any

from dotenv import load_dotenv

load_dotenv(override=False)

# ── Config ────────────────────────────────────────────────────────────────────
from config import (
    DB_CONNECTION_STRING,
    USE_DATABASE,
    MANIM_SCRIPTS,
    OUTPUTS,
    MAX_RENDER_RETRIES,
    MAX_GENERATION_ATTEMPTS,
    ENABLE_VOICEOVER,
    FAST_PIPELINE,
    DRAFT_PIPELINE,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW,
    CDN_BASE_URL,
    CDN_ENABLED,
    TTS_VOICE,
    WARMUP_PLANES,
    VIDEO_MODES,
    DEFAULT_VIDEO_MODE,
    JOB_STATE_PERSISTENCE,
    JOB_STATE_PATH,
    BACKGROUND_MAX_WORKERS,
    WEBHOOK_MAX_WORKERS,
)

# ── Algorithm imports ──────────────────────────────────────────────────────────
from algorithms.database import ManimDatabase
from algorithms.batch_completion import BatchCompletionDeps
from algorithms.batch_completion import check_batch_completion as check_batch_completion_job
from algorithms.generation_service import (
    GenerationServiceDeps,
    generate_and_validate_code_job,
)
from algorithms.video_modes import normalize_video_mode
from algorithms.media_tools import (
    manim_command as _manim_command,
)
from algorithms.job_dispatcher import BackgroundDispatcher
from algorithms.job_state import JobStateStore, PersistentJobStateStore
from algorithms.manim_warmup import start_manim_warmup_background
from algorithms.rate_limiter import SlidingWindowRateLimiter
from algorithms.rendering import find_video_file
from algorithms.render_service import RenderServiceDeps, save_and_render_job
from algorithms.stream_service import StreamServiceDeps, stream_generate_and_render_job
from algorithms.webhook_service import (
    deliver_webhook_background as deliver_webhook_service,
    trigger_webhooks as trigger_webhook_service,
)
from api_routes.api_keys import create_api_keys_blueprint
from api_routes.batches import create_batches_blueprint
from api_routes.core import create_core_blueprint
from api_routes.lti import create_lti_blueprint
from api_routes.media import create_media_blueprint
from api_routes.payload import (
    bool_payload,
    dict_payload,
    parse_video_mode_payload,
    request_json_object,
)
from api_routes.templates import create_templates_blueprint
from api_routes.webhooks import create_webhooks_blueprint

_job_state = (
    PersistentJobStateStore(JOB_STATE_PATH) if JOB_STATE_PERSISTENCE else JobStateStore()
)
_dispatcher = BackgroundDispatcher(max_concurrent=BACKGROUND_MAX_WORKERS)
_webhook_dispatcher = BackgroundDispatcher(max_concurrent=WEBHOOK_MAX_WORKERS)
_rate_limiter = SlidingWindowRateLimiter(
    enabled=RATE_LIMIT_ENABLED,
    max_requests=RATE_LIMIT_REQUESTS,
    window_seconds=RATE_LIMIT_WINDOW,
)


def check_rate_limit(client_id: str) -> tuple:
    """Check if client exceeds rate limit. Returns (allowed, retry_after)."""
    return _rate_limiter.check(client_id)


def get_job_status(job_id: str) -> Optional[dict]:
    return _job_state.get_status(job_id)


def set_job_status(job_id: str, status: dict) -> None:
    _job_state.set_status(job_id, status)


def update_job_status(job_id: str, **updates: Any) -> dict:
    """Merge fields into a job status safely and return a snapshot."""
    return _job_state.update_status(job_id, **updates)


def finish_job_status(job_id: str, **updates: Any) -> dict:
    """Mark a job terminal and run terminal-status side effects."""
    snapshot = update_job_status(job_id, **updates)
    if snapshot.get("status") in ("done", "error"):
        batch_id = snapshot.get("batch_id")
        if batch_id:
            check_batch_completion(batch_id)
    return snapshot


def get_job_field(job_id: str, key: str, default: Any = None) -> Any:
    return _job_state.get_field(job_id, key, default)


def list_job_statuses() -> list[tuple[str, dict]]:
    return _job_state.list_statuses()


def set_job_request(job_id: str, request: dict) -> None:
    _job_state.set_request(job_id, request)


parse_current_video_mode_payload = partial(
    parse_video_mode_payload,
    default_video_mode=DEFAULT_VIDEO_MODE,
    video_modes=VIDEO_MODES,
    normalize_video_mode=normalize_video_mode,
)


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════════════════════


db = ManimDatabase(DB_CONNECTION_STRING) if USE_DATABASE else None


# ═══════════════════════════════════════════════════════════════════════════════
# CODE GENERATION PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════


def _generation_service_deps() -> GenerationServiceDeps:
    return GenerationServiceDeps(db=db, update_status=update_job_status)


def generate_and_validate_code(
    prompt: str,
    job_id: str,
    max_attempts: int = MAX_GENERATION_ATTEMPTS,
    voiceover: bool = False,
    voice: str = None,
    video_mode: str = DEFAULT_VIDEO_MODE,
) -> tuple[str, list, str | None, str | None, dict, list, bool, dict]:
    """Compatibility wrapper around the bulk generation service."""
    return generate_and_validate_code_job(
        prompt,
        job_id,
        max_attempts=max_attempts,
        voiceover=voiceover,
        voice=voice,
        video_mode=video_mode,
        deps=_generation_service_deps(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# STREAMING GENERATION PIPELINE (Phase 13)
# ═══════════════════════════════════════════════════════════════════════════════


def _stream_service_deps() -> StreamServiceDeps:
    return StreamServiceDeps(
        update_status=update_job_status,
        finish_status=finish_job_status,
        get_job_field=get_job_field,
        trigger_webhooks=trigger_webhooks,
    )


def stream_generate_and_render(
    prompt: str,
    job_id: str,
    analysis: dict = None,
    voiceover: bool = False,
    voice: str = None,
    visual_template: str = None,
    intro_outro: dict = None,
    watermark: dict = None,
    video_mode: str = DEFAULT_VIDEO_MODE,
) -> tuple[str, list[dict], Any]:
    """Compatibility wrapper around the streaming render service."""
    return stream_generate_and_render_job(
        prompt,
        job_id,
        analysis=analysis,
        voiceover=voiceover,
        voice=voice,
        visual_template=visual_template,
        intro_outro=intro_outro,
        watermark=watermark,
        video_mode=video_mode,
        deps=_stream_service_deps(),
    )


def stream_render_async(
    prompt: str,
    job_id: str,
    analysis: dict = None,
    voiceover: bool = False,
    voice: str = None,
    visual_template: str = None,
    intro_outro: dict = None,
    watermark: dict = None,
    video_mode: str = DEFAULT_VIDEO_MODE,
):
    """Non-blocking wrapper for stream_generate_and_render."""

    def _run_streaming_job():
        try:
            stream_generate_and_render(
                prompt,
                job_id,
                analysis,
                voiceover,
                voice,
                visual_template,
                intro_outro,
                watermark,
                video_mode,
            )
        except Exception as exc:
            print(f"[{job_id}] [ERR] Streaming background job failed: {exc}")
            finish_job_status(
                job_id,
                status="error",
                message=str(exc),
                video_file="",
                video_mode=video_mode,
            )
            batch_id = get_job_field(job_id, "batch_id")
            trigger_webhooks(
                job_id,
                "render.error",
                {
                    "event": "render.error",
                    "job_id": job_id,
                    "batch_id": batch_id,
                    "status": "error",
                    "error": str(exc),
                    "timestamp": datetime.now().isoformat(),
                },
            )

    _dispatcher.submit(_run_streaming_job, name=f"stream-{job_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOK DELIVERY
# ═══════════════════════════════════════════════════════════════════════════════


def deliver_webhook_background(
    webhook_id: str,
    url: str,
    secret: str,
    job_id: str,
    payload: dict,
    max_retries: int = 3,
):
    """Non-blocking webhook delivery with exponential backoff retry."""
    deliver_webhook_service(
        db, webhook_id, url, secret, job_id, payload, max_retries=max_retries
    )


def trigger_webhooks(job_id: str, event: str, payload: dict):
    """Trigger all webhooks subscribed to event for job."""
    trigger_webhook_service(
        db,
        job_id,
        event,
        payload,
        dispatch_background=_webhook_dispatcher.submit,
    )


def check_batch_completion(batch_id: str):
    """Check if all jobs in a batch are done/failed and trigger batch webhook."""
    return check_batch_completion_job(
        batch_id,
        deps=BatchCompletionDeps(
            job_state=_job_state,
            db=db,
            deliver_webhook=deliver_webhook_background,
        ),
    )


def save_and_render(
    code: str,
    filename: str,
    job_id: str,
    request_id: str = None,
    prompt: str = "",
    attempt_id: str = None,
    audio_segments: dict = None,
    segment_order: list = None,
    is_fast: bool = False,
    analysis: dict = None,
    watermark: dict = None,
):
    """Compatibility wrapper around the render service."""
    deps = RenderServiceDeps(
        db=db,
        update_status=update_job_status,
        finish_status=finish_job_status,
        get_job_field=get_job_field,
        trigger_webhooks=trigger_webhooks,
    )
    return save_and_render_job(
        code,
        filename,
        job_id,
        deps=deps,
        request_id=request_id,
        prompt=prompt,
        attempt_id=attempt_id,
        audio_segments=audio_segments,
        segment_order=segment_order,
        is_fast=is_fast,
        analysis=analysis,
        watermark=watermark,
    )


def render_async(
    code: str,
    filename: str,
    job_id: str,
    request_id: str = None,
    prompt: str = "",
    attempt_id: str = None,
    audio_segments: dict = None,
    segment_order: list = None,
    is_fast: bool = False,
    analysis: dict = None,
    watermark: dict = None,
):
    _dispatcher.submit(
        save_and_render,
        name=f"render-{job_id}",
        args=(
            code,
            filename,
            job_id,
            request_id,
            prompt,
            attempt_id,
            audio_segments,
            segment_order,
            is_fast,
            analysis,
            watermark,
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FLASK APP FACTORY
# ═══════════════════════════════════════════════════════════════════════════════


def create_app() -> Flask:
    flask_app = Flask(__name__)
    CORS(
        flask_app,
        origins=["http://localhost:3000"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )
    flask_app.register_blueprint(create_templates_blueprint(db, request_json_object))
    flask_app.register_blueprint(
        create_media_blueprint(
            db=db,
            request_json_object=request_json_object,
            find_video_file=find_video_file,
            outputs=OUTPUTS,
            cdn_enabled=CDN_ENABLED,
            cdn_base_url=CDN_BASE_URL,
        )
    )
    flask_app.register_blueprint(
        create_api_keys_blueprint(
            db=db,
            check_rate_limit=check_rate_limit,
            request_json_object=request_json_object,
        )
    )
    flask_app.register_blueprint(
        create_webhooks_blueprint(db=db, request_json_object=request_json_object)
    )
    flask_app.register_blueprint(
        create_batches_blueprint(job_state=_job_state, list_statuses=list_job_statuses)
    )
    flask_app.register_blueprint(
        create_lti_blueprint(
            db=db,
            request_json_object=request_json_object,
            get_job_status=get_job_status,
        )
    )
    flask_app.register_blueprint(
        create_core_blueprint(
            request_json_object=request_json_object,
            dict_payload=dict_payload,
            bool_payload=bool_payload,
            parse_video_mode_payload=parse_current_video_mode_payload,
            check_rate_limit=check_rate_limit,
            get_job_status=get_job_status,
            set_job_status=set_job_status,
            finish_job_status=finish_job_status,
            list_job_statuses=list_job_statuses,
            set_job_request=set_job_request,
            generate_and_validate_code=generate_and_validate_code,
            stream_generate_and_render=stream_generate_and_render,
            render_async=render_async,
            trigger_webhooks=trigger_webhooks,
            dispatch_background=_dispatcher.submit,
            database_available=lambda: db.available if db else False,
            background_active_count=_dispatcher.active_count,
            background_running_count=_dispatcher.running_count,
            background_queued_count=_dispatcher.queued_count,
            webhook_active_count=_webhook_dispatcher.active_count,
            max_generation_attempts=MAX_GENERATION_ATTEMPTS,
            enable_voiceover=ENABLE_VOICEOVER,
            tts_voice=TTS_VOICE,
            default_video_mode=DEFAULT_VIDEO_MODE,
        )
    )
    return flask_app


app = create_app()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("NIMA — Manim AI Generator")
    print("=" * 60)
    print(f"[STARTUP] Manim scripts: {MANIM_SCRIPTS.absolute()}")
    print(f"[STARTUP] Outputs:       {OUTPUTS.absolute()}")
    print(f"[OK] Model: {__import__('config').GENERATION_MODEL}")
    print(f"[OK] Fast model: {__import__('config').FAST_MODEL}")
    print(f"[OK] Database: {'ENABLED' if USE_DATABASE else 'DISABLED'}")
    print(f"[OK] Background workers: {BACKGROUND_MAX_WORKERS}")
    print(f"[OK] Webhook workers: {WEBHOOK_MAX_WORKERS}")
    print(
        f"[OK] Render retries: {MAX_RENDER_RETRIES} (with LLM error-fix between each)"
    )
    print(
        f"[OK] Pipeline: {'DRAFT' if DRAFT_PIPELINE else ('FAST' if FAST_PIPELINE else 'FULL')}"
    )
    print("[OK] RAG corpus: 25+ curated patterns")
    print("[OK] Review pass: consolidated (layout + API + pacing)")

    start_manim_warmup_background(
        draft_pipeline=DRAFT_PIPELINE,
        warmup_planes=WARMUP_PLANES,
        manim_command=_manim_command,
    )

    print("=" * 60)
    print("http://localhost:5000")
    print("Stats: http://localhost:5000/stats")
    print("=" * 60 + "\n")

    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True, use_reloader=False)
