"""Core route validation checks that avoid live generation."""

from flask import Flask

from api_routes.core import create_core_blueprint
from api_routes.payload import bool_payload, dict_payload, request_json_object


def _make_app(*, rate_allowed=True, initial_statuses=None):
    calls = {"generate": 0, "stream": 0, "render": 0, "dispatch": 0}
    statuses = dict(initial_statuses or {})

    def parse_mode(payload):
        mode = payload.get("mode", "standard")
        if mode not in {"standard", "short", "course", "lecture"}:
            raise ValueError("Invalid mode")
        return mode

    def generate(*args, **kwargs):
        calls["generate"] += 1
        return ("code", [], "req", "att", {}, [], False, {})

    def stream(*args, **kwargs):
        calls["stream"] += 1
        return "video.mp4", [], None

    def render(*args, **kwargs):
        calls["render"] += 1

    def dispatch(target, *args, **kwargs):
        calls["dispatch"] += 1

    app = Flask(__name__)
    app.register_blueprint(
        create_core_blueprint(
            request_json_object=request_json_object,
            dict_payload=dict_payload,
            bool_payload=bool_payload,
            parse_video_mode_payload=parse_mode,
            check_rate_limit=lambda client_id: (rate_allowed, 42),
            get_job_status=lambda job_id: statuses.get(job_id),
            set_job_status=lambda job_id, status: statuses.setdefault(job_id, status),
            finish_job_status=lambda job_id, **updates: statuses.setdefault(job_id, {}).update(updates) or statuses[job_id],
            list_job_statuses=lambda: list(statuses.items()),
            set_job_request=lambda job_id, req: None,
            generate_and_validate_code=generate,
            stream_generate_and_render=stream,
            render_async=render,
            dispatch_background=dispatch,
            database_available=lambda: False,
            background_active_count=lambda: 0,
            max_generation_attempts=1,
            enable_voiceover=False,
            tts_voice="test-voice",
            default_video_mode="standard",
        )
    )
    return app, calls


def test_generate_rejects_empty_prompt_before_dispatch():
    app, calls = _make_app()
    response = app.test_client().post("/api/generate", json={})

    assert response.status_code == 400
    assert calls["dispatch"] == 0
    assert calls["generate"] == 0
    print("[OK] core routes — empty prompt rejected before generation")


def test_generate_rejects_invalid_mode_before_dispatch():
    app, calls = _make_app()
    response = app.test_client().post(
        "/api/generate",
        json={"prompt": "test", "mode": "bad"},
    )

    assert response.status_code == 400
    assert calls["dispatch"] == 0
    print("[OK] core routes — invalid mode rejected before dispatch")


def test_generate_rate_limit_blocks_before_dispatch():
    app, calls = _make_app(rate_allowed=False)
    response = app.test_client().post("/api/generate", json={"prompt": "test"})

    assert response.status_code == 429
    assert response.get_json()["retry_after"] == 42
    assert calls["dispatch"] == 0
    print("[OK] core routes — rate limit blocks before dispatch")


def test_batch_validation_rejects_bad_prompt_lists():
    app, calls = _make_app()
    client = app.test_client()

    empty = client.post("/api/batch", json={"prompts": []})
    too_many = client.post("/api/batch", json={"prompts": ["x"] * 21})

    assert empty.status_code == 400
    assert too_many.status_code == 400
    assert calls["dispatch"] == 0
    print("[OK] core routes — batch prompt list validation blocks dispatch")


def test_batch_validation_rejects_malformed_items_before_dispatch():
    """Every item in /api/batch must be validated before we kick off any
    background work — otherwise submit_batch_jobs silently drops bad items
    and the client sees a partial response it can't reconcile."""
    app, calls = _make_app()
    client = app.test_client()

    cases = [
        ["good", ""],                               # empty string item
        ["good", "   "],                            # whitespace-only item
        ["good", 42],                                # wrong type
        ["good", {"topic": "no-prompt-field"}],     # dict missing 'prompt'
        ["good", {"prompt": 42}],                   # 'prompt' is not a string
        ["good", {"prompt": "x" * 5001}],          # exceeds per-prompt cap
    ]

    for bad_payload in cases:
        response = client.post("/api/batch", json={"prompts": bad_payload})
        assert response.status_code == 400, (bad_payload, response.get_json())
        assert "error" in response.get_json()

    assert calls["dispatch"] == 0
    print("[OK] core routes — batch item validation blocks dispatch")


def test_batch_accepts_mixed_valid_items_and_dispatches_once_per_item():
    """Well-formed batches must still pass through to submit_batch_jobs."""
    app, calls = _make_app()
    client = app.test_client()

    response = client.post(
        "/api/batch",
        json={"prompts": ["first", {"prompt": "second"}]},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert "batch_id" in body
    assert len(body["jobs"]) == 2
    assert calls["dispatch"] == 2
    print("[OK] core routes — batch dispatches one background job per valid item")


def test_health_counts_queued_jobs_as_active():
    app, _ = _make_app(
        initial_statuses={
            "queued-job": {"status": "queued"},
            "running-job": {"status": "generating"},
            "done-job": {"status": "done"},
        }
    )

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.get_json()["active_jobs"] == 2
    print("[OK] core routes — health counts queued jobs as active")


if __name__ == "__main__":
    test_generate_rejects_empty_prompt_before_dispatch()
    test_generate_rejects_invalid_mode_before_dispatch()
    test_generate_rate_limit_blocks_before_dispatch()
    test_batch_validation_rejects_bad_prompt_lists()
    test_health_counts_queued_jobs_as_active()
    print("\nALL CORE ROUTE CHECKS PASSED")
