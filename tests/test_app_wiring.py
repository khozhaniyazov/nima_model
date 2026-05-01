"""App wiring regression checks."""

import os

os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["USE_DATABASE"] = "false"
os.environ["JOB_STATE_PERSISTENCE"] = "false"


def test_stream_render_async_error_path_has_timestamp():
    import app

    originals = {
        "stream_generate_and_render": app.stream_generate_and_render,
        "finish_job_status": app.finish_job_status,
        "get_job_field": app.get_job_field,
        "trigger_webhooks": app.trigger_webhooks,
        "submit": app._dispatcher.submit,
    }
    finished = []
    webhooks = []

    def fail_stream(*args, **kwargs):
        raise RuntimeError("boom")

    def finish(job_id, **updates):
        finished.append((job_id, updates))
        return updates

    def get_field(job_id, key, default=None):
        return "batch-1" if key == "batch_id" else default

    def trigger(job_id, event, payload):
        webhooks.append((job_id, event, payload))

    def submit_now(target, *args, **kwargs):
        target()
        return None

    try:
        app.stream_generate_and_render = fail_stream
        app.finish_job_status = finish
        app.get_job_field = get_field
        app.trigger_webhooks = trigger
        app._dispatcher.submit = submit_now

        app.stream_render_async("prompt", "job-1", video_mode="short")
    finally:
        app.stream_generate_and_render = originals["stream_generate_and_render"]
        app.finish_job_status = originals["finish_job_status"]
        app.get_job_field = originals["get_job_field"]
        app.trigger_webhooks = originals["trigger_webhooks"]
        app._dispatcher.submit = originals["submit"]

    assert finished[0][0] == "job-1"
    assert finished[0][1]["video_mode"] == "short"
    assert webhooks[0][1] == "render.error"
    assert webhooks[0][2]["timestamp"]
    print("[OK] app wiring — stream error path emits timestamped webhook payload")


if __name__ == "__main__":
    test_stream_render_async_error_path_has_timestamp()
    print("\nALL APP WIRING CHECKS PASSED")
