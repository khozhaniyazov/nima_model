"""Webhook delivery and subscription dispatch helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from datetime import datetime
from typing import Any

import requests


def _db_available(db: Any) -> bool:
    return bool(db and getattr(db, "available", False))


def render_event_payload(
    job_id: str,
    batch_id: str | None,
    status: str,
    *,
    video_file: str | None = None,
    error: str | None = None,
) -> dict:
    payload = {
        "event": "render.complete" if status == "done" else "render.error",
        "job_id": job_id,
        "batch_id": batch_id,
        "status": status,
        "timestamp": datetime.now().isoformat(),
    }
    if video_file:
        payload["video_url"] = f"/outputs/{video_file}"
    if error:
        payload["error"] = error
    return payload


def deliver_webhook_background(
    db: Any,
    webhook_id: str | None,
    url: str,
    secret: str | None,
    job_id: str,
    payload: dict,
    max_retries: int = 3,
) -> None:
    """Non-blocking-compatible webhook delivery with exponential backoff retry."""
    headers = {"Content-Type": "application/json"}
    if secret:
        signature = hmac.new(
            secret.encode(), json.dumps(payload).encode(), hashlib.sha256
        ).hexdigest()
        headers["X-Webhook-Signature"] = signature

    last_error = "No webhook attempts completed"
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code in (200, 201, 204):
                if _db_available(db):
                    try:
                        db.save_webhook_delivery(
                            webhook_id,
                            job_id,
                            payload,
                            "delivered",
                            attempt,
                            response.status_code,
                            response.text[:500],
                        )
                    except Exception:
                        pass
                print(f"[WEBHOOK] Delivered to {url} for job {job_id}")
                return

            last_error = f"HTTP {response.status_code}: {response.text[:500]}"
            if attempt < max_retries:
                time.sleep([1, 5, 30][attempt - 1])
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                time.sleep([1, 5, 30][attempt - 1])
            print(f"[WEBHOOK] Failed: {e}")

    if _db_available(db):
        try:
            db.save_webhook_delivery(
                webhook_id, job_id, payload, "failed", max_retries, None, last_error
            )
        except Exception:
            pass
    print(f"[WEBHOOK] All retries exhausted for job {job_id}")


def trigger_webhooks(
    db: Any,
    job_id: str,
    event: str,
    payload: dict,
    dispatch_background: Any = None,
) -> None:
    """Trigger all active webhooks subscribed to an event."""
    if not _db_available(db):
        return
    try:
        webhooks = db.get_webhooks_for_event(event)
        for webhook in webhooks:
            if webhook.get("active"):
                args = (
                    db,
                    str(webhook["id"]),
                    webhook["url"],
                    webhook.get("secret", ""),
                    job_id,
                    payload,
                )
                if dispatch_background:
                    dispatch_background(
                        deliver_webhook_background,
                        name=f"webhook-{job_id}-{webhook['id']}",
                        args=args,
                    )
                else:
                    thread = threading.Thread(
                        target=deliver_webhook_background,
                        args=args,
                        daemon=True,
                    )
                    thread.start()
    except Exception as e:
        print(f"[WEBHOOK] Trigger error: {e}")
