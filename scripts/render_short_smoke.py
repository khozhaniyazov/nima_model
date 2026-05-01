"""End-to-end render smoke (no Flask): one short streaming job.

Drives `algorithms.stream_service.stream_generate_and_render_job` directly
with the configured LLM provider. Prints status updates inline and validates
the resulting MP4.

Sets `DRAFT_PIPELINE=true` + `SHORT_DRAFT_FAST_PATH=true` + `FAST_PIPELINE=true`
*before* importing config so the heuristic analysis + deterministic plan
path skips two LLM round-trips. Per-scene generation still hits the LLM,
but plan + analyze are local.

Promoted from `.tmp/render_short_smoke.py` (gitignored) so the fix that
reads `status == "done"` (instead of the old `"ok"` mismatch) is actually
tracked in the repo and visible in PR reviews. See issue #12.

Usage:
    python -u scripts/render_short_smoke.py

Optional env override:
    SMOKE_PROMPT="..."  # override the default morph prompt
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

os.environ.setdefault("DRAFT_PIPELINE", "true")
os.environ.setdefault("SHORT_DRAFT_FAST_PATH", "true")
os.environ.setdefault("FAST_PIPELINE", "true")

# Make the repo root importable when invoked from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algorithms.media_tools import validate_video_file  # noqa: E402
from algorithms.stream_service import (  # noqa: E402
    StreamServiceDeps,
    stream_generate_and_render_job,
)


def _print_status(job_id: str, **updates):
    msg = updates.get("message")
    status = updates.get("status")
    if msg:
        print(f"  [{job_id}] {status or '...'}: {msg}")
    return updates


def _print_finish(job_id: str, **updates):
    return _print_status(job_id, **updates)


def main() -> int:
    job_id = f"smoke-{uuid.uuid4().hex[:8]}"
    prompt = os.environ.get(
        "SMOKE_PROMPT", "Animate a blue circle morphing into a green square."
    )
    print(f"[smoke] job_id={job_id}")
    print(f"[smoke] prompt: {prompt}")
    print(
        "[smoke] mode=short, voiceover=False, "
        "DRAFT_PIPELINE+SHORT_DRAFT_FAST_PATH+FAST_PIPELINE on\n"
    )

    deps = StreamServiceDeps(
        update_status=_print_status,
        finish_status=_print_finish,
    )

    started = time.time()
    try:
        final_video, scene_results, _final_context = stream_generate_and_render_job(
            prompt,
            job_id,
            voiceover=False,
            video_mode="short",
            deps=deps,
        )
    except Exception as exc:
        elapsed = time.time() - started
        print(f"\n[smoke] FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
        return 2

    elapsed = time.time() - started
    print(f"\n[smoke] pipeline finished in {elapsed:.1f}s")
    print(f"[smoke] final_video = {final_video}")
    # The pipeline returns per-scene dicts whose `status` is "done" or
    # "failed" (see algorithms/stream_service.py around line 758). The
    # original copy of this script checked for "ok" and always printed
    # 0/N even when the pipeline reported full success — closes #12.
    ok_scenes = sum(1 for r in scene_results if r.get("status") == "done")
    print(f"[smoke] scenes ok: {ok_scenes}/{len(scene_results)}")

    if not final_video or not Path(final_video).exists():
        print("[smoke] FAIL: no final video produced")
        return 3

    integrity = validate_video_file(final_video)
    print(
        f"[smoke] integrity ok={integrity.ok} "
        f"size={integrity.size_bytes}B duration={integrity.duration_seconds}s"
    )
    if integrity.error:
        print(f"[smoke] integrity error: {integrity.error}")
        return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
