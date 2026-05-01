from __future__ import annotations

import subprocess
import tempfile
import threading
from collections.abc import Callable
from typing import Any


def prewarm_manim(
    *,
    draft_pipeline: bool,
    warmup_planes: bool,
    manim_command: Callable[[], list[str]],
    run_command: Callable[..., Any] = subprocess.run,
) -> None:
    """Warm up Manim by rendering a minimal scene and optionally a NumberPlane."""
    try:
        if draft_pipeline:
            print("[WARMUP] Skipping manim warmup in DRAFT mode")
            return

        warmup_code = """from manim import *
class WarmupScene(Scene):
    def construct(self):
        circle = Circle()
        self.play(Create(circle))
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(warmup_code)
            warmup_path = f.name

        print("[WARMUP] Pre-warming Manim (first render is slow)...")
        result = run_command(
            [*manim_command(), warmup_path, "WarmupScene", "-ql", "--disable_caching"],
            capture_output=True,
            timeout=120,
        )
        print(f"[WARMUP] {'OK' if result.returncode == 0 else 'FAILED'}")

        if warmup_planes:
            print("[WARMUP] Preloading planes and axes...")
            plane_code = """from manim import *
class PlaneWarmup(Scene):
    def construct(self):
        plane = NumberPlane(x_range=[-4,4], y_range=[-3,3])
        self.add(plane)
"""
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(plane_code)
                plane_path = f.name
            run_command(
                [
                    *manim_command(),
                    plane_path,
                    "PlaneWarmup",
                    "-ql",
                    "--disable_caching",
                ],
                capture_output=True,
                timeout=60,
            )

    except Exception as e:
        print(f"[WARMUP] [ERR] Manim warmup failed: {e}", flush=True)


def start_manim_warmup_background(
    *,
    draft_pipeline: bool,
    warmup_planes: bool,
    manim_command: Callable[[], list[str]],
    completion_timeout: int = 30,
) -> threading.Thread:
    warmup_thread = threading.Thread(
        target=prewarm_manim,
        kwargs={
            "draft_pipeline": draft_pipeline,
            "warmup_planes": warmup_planes,
            "manim_command": manim_command,
        },
        daemon=True,
        name="manim-warmup",
    )
    warmup_thread.start()

    def check_warmup() -> None:
        warmup_thread.join(timeout=completion_timeout)
        if warmup_thread.is_alive():
            print(
                "[WARMUP] [WARN] Manim warmup did not complete within "
                f"{completion_timeout}s - first render will pay cold-start cost",
                flush=True,
            )
        else:
            print("[WARMUP] [OK] Manim warmup completed", flush=True)

    threading.Thread(target=check_warmup, daemon=True, name="manim-warmup-watch").start()
    return warmup_thread
