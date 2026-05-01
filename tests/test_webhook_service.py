"""Webhook payload, delivery, and dispatch checks."""

import json

import algorithms.webhook_service as webhook_service
from algorithms.webhook_service import (
    deliver_webhook_background,
    render_event_payload,
    trigger_webhooks,
)


class _Response:
    status_code = 204
    text = ""


class _Db:
    available = True

    def __init__(self):
        self.deliveries = []
        self.events = []

    def save_webhook_delivery(self, *args):
        self.deliveries.append(args)
        return "delivery-1"

    def get_webhooks_for_event(self, event):
        self.events.append(event)
        return [
            {
                "id": "hook-active",
                "url": "https://example.test/hook",
                "secret": "secret",
                "active": True,
            },
            {
                "id": "hook-inactive",
                "url": "https://example.test/inactive",
                "secret": "",
                "active": False,
            },
        ]


def test_render_event_payload_shapes_success_and_error():
    success = render_event_payload("job-1", "batch-1", "done", video_file="v.mp4")
    failure = render_event_payload("job-2", None, "error", error="boom")

    assert success["event"] == "render.complete"
    assert success["video_url"] == "/outputs/v.mp4"
    assert success["timestamp"]
    assert failure["event"] == "render.error"
    assert failure["error"] == "boom"
    print("[OK] webhooks - render event payloads shaped consistently")


def test_deliver_webhook_signs_payload_and_records_success():
    db = _Db()
    observed = {}
    original_post = webhook_service.requests.post

    def fake_post(url, json=None, headers=None, timeout=None):
        observed["url"] = url
        observed["payload"] = json
        observed["headers"] = headers or {}
        observed["timeout"] = timeout
        return _Response()

    try:
        webhook_service.requests.post = fake_post
        payload = {"event": "render.complete", "job_id": "job-1"}
        deliver_webhook_background(
            db,
            "hook-1",
            "https://example.test/hook",
            "secret",
            "job-1",
            payload,
            max_retries=1,
        )
    finally:
        webhook_service.requests.post = original_post

    assert observed["url"] == "https://example.test/hook"
    assert observed["payload"]["job_id"] == "job-1"
    assert observed["headers"]["Content-Type"] == "application/json"
    assert observed["headers"]["X-Webhook-Signature"]
    assert observed["timeout"] == 10
    assert db.deliveries[0][3] == "delivered"
    print("[OK] webhooks - delivery signs payload and records success")


def test_trigger_webhooks_uses_injected_dispatcher():
    db = _Db()
    dispatched = []

    def dispatch(target, *, name=None, args=(), kwargs=None):
        dispatched.append((target, name, args, kwargs or {}))

    payload = {"event": "render.complete", "job_id": "job-1"}
    trigger_webhooks(
        db,
        "job-1",
        "render.complete",
        payload,
        dispatch_background=dispatch,
    )

    assert db.events == ["render.complete"]
    assert len(dispatched) == 1
    assert dispatched[0][0] is deliver_webhook_background
    assert dispatched[0][1] == "webhook-job-1-hook-active"
    assert dispatched[0][2][2] == "https://example.test/hook"
    assert json.dumps(dispatched[0][2][5])
    print("[OK] webhooks - trigger uses injected dispatcher")


if __name__ == "__main__":
    test_render_event_payload_shapes_success_and_error()
    test_deliver_webhook_signs_payload_and_records_success()
    test_trigger_webhooks_uses_injected_dispatcher()
    print("\nALL WEBHOOK CHECKS PASSED")
