"""Smoke tests for job submission orchestration."""

from algorithms.job_submission import (
    JobSubmissionDeps,
    submit_api_job,
    submit_batch_jobs,
    submit_form_job,
)


class _Recorder:
    def __init__(self):
        self.statuses = {}
        self.requests = {}
        self.finished = []
        self.generated = []
        self.streamed = []
        self.rendered = []
        self.dispatched = []
        self.webhooks = []
        self.fail_stream = False

    def set_status(self, job_id, status):
        self.statuses[job_id] = status

    def finish_status(self, job_id, **updates):
        self.finished.append((job_id, updates))
        self.statuses.setdefault(job_id, {}).update(updates)
        return self.statuses[job_id]

    def set_request(self, job_id, request):
        self.requests[job_id] = request

    def generate(self, prompt, job_id, **kwargs):
        self.generated.append((prompt, job_id, kwargs))
        return (
            "from manim import *",
            [],
            "request-1",
            "attempt-1",
            {},
            [],
            False,
            {"domain": "general"},
        )

    def stream(self, prompt, job_id, **kwargs):
        if self.fail_stream:
            raise RuntimeError("stream failed")
        self.streamed.append((prompt, job_id, kwargs))
        return "video.mp4", [], None

    def render(self, *args):
        self.rendered.append(args)

    def dispatch_now(self, target, *, name=None, **kwargs):
        self.dispatched.append(name)
        target()

    def dispatch_later(self, target, *, name=None, **kwargs):
        self.dispatched.append(name)

    def trigger_webhook(self, job_id, event, payload):
        self.webhooks.append((job_id, event, payload))

    def deps(self, dispatch=None):
        return JobSubmissionDeps(
            set_status=self.set_status,
            finish_status=self.finish_status,
            set_request=self.set_request,
            generate_and_validate_code=self.generate,
            stream_generate_and_render=self.stream,
            render_async=self.render,
            dispatch_background=dispatch or self.dispatch_now,
            max_generation_attempts=1,
            trigger_webhooks=self.trigger_webhook,
        )


def test_submit_form_job_runs_generation_and_render():
    recorder = _Recorder()
    job_id = submit_form_job(
        "Explain eigenvectors",
        deps=recorder.deps(),
        voiceover=False,
        video_mode="standard",
    )

    assert recorder.statuses[job_id]["status"] == "generating"
    assert recorder.generated[0][0] == "Explain eigenvectors"
    assert recorder.generated[0][2]["video_mode"] == "standard"
    assert recorder.requests[job_id]["request_id"] == "request-1"
    assert recorder.rendered[0][2] == job_id
    print("[OK] job submission — form job generated and scheduled render")


def test_submit_api_job_streaming_dispatches_background_work():
    recorder = _Recorder()
    job_id = submit_api_job(
        "Explain supply and demand",
        deps=recorder.deps(),
        streaming=True,
        voiceover=True,
        voice="test-voice",
        visual_template="default",
        intro_outro={},
        watermark={},
        video_mode="short",
    )

    assert recorder.dispatched == [f"generate-{job_id}"]
    assert recorder.streamed[0][1] == job_id
    assert recorder.streamed[0][2]["video_mode"] == "short"
    assert recorder.requests[job_id]["request_id"] is None
    assert recorder.statuses[job_id]["status"] == "generating"
    print("[OK] job submission — streaming API job dispatched")


def test_submit_api_job_reports_queued_before_worker_runs():
    recorder = _Recorder()
    job_id = submit_api_job(
        "Explain delayed work",
        deps=recorder.deps(dispatch=recorder.dispatch_later),
        streaming=True,
        voiceover=False,
        voice="test-voice",
        visual_template=None,
        intro_outro={},
        watermark={},
        video_mode="standard",
    )

    assert recorder.dispatched == [f"generate-{job_id}"]
    assert recorder.statuses[job_id]["status"] == "queued"
    assert recorder.statuses[job_id]["message"] == "Queued for processing..."
    print("[OK] job submission — API jobs stay queued until worker starts")


def test_submit_api_job_failure_emits_error_webhook():
    recorder = _Recorder()
    recorder.fail_stream = True
    job_id = submit_api_job(
        "Explain supply and demand",
        deps=recorder.deps(),
        streaming=True,
        voiceover=False,
        voice="test-voice",
        visual_template=None,
        intro_outro={},
        watermark={},
        video_mode="course",
    )

    assert recorder.statuses[job_id]["status"] == "error"
    assert recorder.finished[0][0] == job_id
    assert recorder.webhooks[0][1] == "render.error"
    assert recorder.webhooks[0][2]["error"] == "stream failed"
    assert recorder.webhooks[0][2]["timestamp"]
    print("[OK] job submission — failed background job emits error webhook")


def test_submit_batch_jobs_sets_batch_statuses_without_running_background():
    recorder = _Recorder()
    batch_id, jobs = submit_batch_jobs(
        [{"prompt": "One"}, "", {"prompt": "Two"}],
        deps=recorder.deps(dispatch=recorder.dispatch_later),
        voiceover=False,
        voice="test-voice",
        video_mode="course",
    )

    assert len(jobs) == 2
    assert recorder.dispatched == [f"batch-{job['job_id']}" for job in jobs]
    assert all(recorder.statuses[job["job_id"]]["batch_id"] == batch_id for job in jobs)
    assert all(
        recorder.statuses[job["job_id"]]["video_mode"] == "course" for job in jobs
    )
    print("[OK] job submission — batch jobs queued with shared batch id")


if __name__ == "__main__":
    test_submit_form_job_runs_generation_and_render()
    test_submit_api_job_streaming_dispatches_background_work()
    test_submit_api_job_reports_queued_before_worker_runs()
    test_submit_api_job_failure_emits_error_webhook()
    test_submit_batch_jobs_sets_batch_statuses_without_running_background()
    print("\nALL JOB SUBMISSION CHECKS PASSED")
