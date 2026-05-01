import random
import time

from flask import Blueprint, jsonify, render_template, request

from algorithms.job_submission import (
    JobSubmissionDeps,
    submit_api_job,
    submit_batch_jobs,
    submit_form_job,
)


def create_core_blueprint(
    *,
    request_json_object,
    dict_payload,
    bool_payload,
    parse_video_mode_payload,
    check_rate_limit,
    get_job_status,
    set_job_status,
    finish_job_status,
    list_job_statuses,
    set_job_request,
    generate_and_validate_code,
    stream_generate_and_render,
    render_async,
    dispatch_background,
    database_available,
    background_active_count,
    max_generation_attempts: int,
    enable_voiceover: bool,
    tts_voice: str,
    default_video_mode: str,
    background_running_count=None,
    background_queued_count=None,
    webhook_active_count=None,
    trigger_webhooks=None,
):
    bp = Blueprint("core_api", __name__)
    submission_deps = JobSubmissionDeps(
        set_status=set_job_status,
        finish_status=finish_job_status,
        set_request=set_job_request,
        generate_and_validate_code=generate_and_validate_code,
        stream_generate_and_render=stream_generate_and_render,
        render_async=render_async,
        dispatch_background=dispatch_background,
        max_generation_attempts=max_generation_attempts,
        trigger_webhooks=trigger_webhooks,
    )

    @bp.route("/", methods=["GET", "POST"])
    def index():
        job_id = None
        error = None

        if request.method == "POST":
            prompt = request.form.get("prompt", "").strip()
            if not prompt:
                error = "Please enter a prompt."
                return render_template("index.html", error=error)

            try:
                job_id = submit_form_job(
                    prompt,
                    deps=submission_deps,
                    voiceover=enable_voiceover,
                    video_mode=default_video_mode,
                )
            except Exception as e:
                error = f"Error: {str(e)}"
                print(f"[{job_id}] [ERR] ERROR: {error}")
                if job_id:
                    finish_job_status(
                        job_id, status="error", message=error, video_file=""
                    )
                time.sleep(2)

        return render_template("index.html", job_id=job_id, error=error)

    @bp.route("/status/<job_id>")
    def check_status(job_id):
        status = get_job_status(job_id) or {
            "status": "unknown",
            "message": "Job not found",
        }
        return jsonify(status)

    @bp.route("/api/generate", methods=["POST"])
    def api_generate():
        """JSON API for the Next.js frontend."""
        data = request_json_object(force=True)
        prompt = (data.get("prompt") or "").strip()
        use_voiceover = bool_payload(data.get("voiceover"), enable_voiceover)
        use_voice = data.get("voice", tts_voice)
        render_template_id = data.get("render_template")
        watermark_settings = dict_payload(data.get("watermark", {}))
        intro_outro_settings = dict_payload(data.get("intro_outro", {}))
        try:
            video_mode = parse_video_mode_payload(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        client_id = request.remote_addr or "unknown"
        allowed, retry_after = check_rate_limit(client_id)
        if not allowed:
            return jsonify(
                {"error": "Rate limit exceeded", "retry_after": retry_after}
            ), 429

        if not prompt:
            return jsonify({"error": "Please enter a prompt."}), 400

        use_streaming = bool_payload(data.get("streaming"), True)

        try:
            job_id = submit_api_job(
                prompt,
                deps=submission_deps,
                streaming=use_streaming,
                voiceover=use_voiceover,
                voice=use_voice,
                visual_template=render_template_id,
                intro_outro=intro_outro_settings,
                watermark=watermark_settings,
                video_mode=video_mode,
            )
            return jsonify({"job_id": job_id})
        except Exception as e:
            print(f"[API_ERR] Error initializing generate: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/prompts", methods=["GET"])
    def api_prompts():
        """Returns random example prompts."""
        try:
            from training.questions import questions

            n = request.args.get("n", 4, type=int) or 4
            n = min(max(n, 1), 20)

            k = min(n, len(questions))
            selected = random.sample(questions, k=k)
            return jsonify({"prompts": selected})
        except Exception as e:
            print(f"[API_ERR] Error fetching prompts: {e}")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/batch", methods=["POST"])
    def api_batch():
        """Batch API for multiple animation requests."""
        data = request_json_object(force=True)
        prompts_data = data.get("prompts", [])
        use_voiceover = bool_payload(data.get("voiceover"), False)
        use_voice = data.get("voice", tts_voice)
        try:
            video_mode = parse_video_mode_payload(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        if not prompts_data or not isinstance(prompts_data, list):
            return jsonify({"error": "prompts must be a non-empty array"}), 400

        if len(prompts_data) > 20:
            return jsonify({"error": "Maximum 20 prompts per batch"}), 400

        batch_id, jobs = submit_batch_jobs(
            prompts_data,
            deps=submission_deps,
            voiceover=use_voiceover,
            voice=use_voice,
            video_mode=video_mode,
        )

        return jsonify({"batch_id": batch_id, "jobs": jobs})

    @bp.route("/health")
    def health():
        active_jobs = sum(
            1
            for _, status in list_job_statuses()
            if status.get("status") in ("queued", "generating", "rendering")
        )
        return jsonify(
            {
                "status": "ok",
                "database": bool(database_available()),
                "active_jobs": active_jobs,
                "background_threads": int(background_active_count()),
                "background_running": int(background_running_count())
                if background_running_count
                else int(background_active_count()),
                "background_queued": int(background_queued_count())
                if background_queued_count
                else 0,
                "webhook_threads": int(webhook_active_count())
                if webhook_active_count
                else 0,
            }
        )

    return bp
