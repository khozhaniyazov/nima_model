"""Deterministic local pipeline smoke test.

This intentionally avoids live LLM calls. It exercises the Flask-facing render
wrapper, shared render service, status helpers, and Manim output discovery.
"""

import os
import sys

os.environ["USE_DATABASE"] = "false"
os.environ["PYTHONUTF8"] = "1"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["DRAFT_PIPELINE"] = "true"
os.environ["JOB_STATE_PERSISTENCE"] = "false"

import algorithms.render_service as render_service
from app import get_job_status, save_and_render, set_job_status


render_service.evaluate_with_gpt4 = lambda *args, **kwargs: {
    "overall": 100,
    "notes": "local smoke stub",
}


CODE = """
from manim import *


class GeneratedScene(Scene):
    def construct(self):
        circle = Circle(radius=1.3, color=BLUE)
        label = Text("Pipeline smoke", font_size=36).next_to(circle, DOWN)
        self.play(Create(circle), FadeIn(label), run_time=0.5)
        self.wait(0.2)
"""


def main() -> int:
    job_id = "test001"
    set_job_status(
        job_id, {"status": "generating", "message": "Starting...", "video_file": ""}
    )

    save_and_render(
        CODE,
        "video_test001",
        job_id,
        prompt="Draw a simple blue circle",
        is_fast=True,
        analysis={"video_mode": "standard", "domain": "general"},
    )
    status = get_job_status(job_id)
    print(f"Final status: {status}")
    if status.get("status") != "done":
        print(f"ERROR: render did not complete: {status}")
        return 1
    if not status.get("video_file"):
        print(f"ERROR: render did not produce a video file: {status}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
