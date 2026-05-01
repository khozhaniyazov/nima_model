"""Deterministic local Manim render smoke test.

This avoids LLM calls and verifies the local render toolchain plus video-mode
render settings end to end.
"""

from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path

from config import MANIM_SCRIPTS
from algorithms.media_tools import validate_video_file
from algorithms.rendering import find_video_file, render_manim_code
from algorithms.video_modes import build_video_mode_profile
from algorithms.video_quality import analyze_video_frames


SMOKE_CODE = """from manim import *


class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = "#101418"
        circle = Circle(radius=1.2, color=BLUE).shift(LEFT * 1.3)
        square = Square(side_length=1.7, color=GREEN).shift(RIGHT * 1.3)
        arrow = Arrow(circle.get_right(), square.get_left(), color=YELLOW)
        self.play(Create(circle), Create(square), GrowArrow(arrow), run_time=1.0)
        self.play(circle.animate.set_fill(BLUE, opacity=0.35), run_time=0.5)
        self.play(Transform(square, Triangle(color=GREEN).shift(RIGHT * 1.3)), run_time=0.8)
        self.wait(0.4)
"""


def run_smoke(mode: str, keep: bool = False) -> Path:
    profile = build_video_mode_profile(mode, is_fast=False, draft=True, streaming=False)

    stamp = f"{mode}_{uuid.uuid4().hex[:8]}"
    output_name = f"smoke_{stamp}"

    started = time.time()
    result = render_manim_code(
        SMOKE_CODE,
        output_name,
        video_mode=mode,
        is_fast=False,
        draft=True,
        timeout_seconds=180,
    )
    elapsed = time.time() - started
    if result.returncode != 0:
        raise RuntimeError(
            "Manim smoke render failed\n"
            f"stderr: {result.stderr[-1200:]}"
        )

    video = find_video_file(output_name)
    if not video or not video.exists():
        raise RuntimeError(f"Manim returned success but no output matched {output_name}")
    if video.stat().st_size <= 0:
        raise RuntimeError(f"Rendered video is empty: {video}")
    integrity = validate_video_file(video)
    if not integrity.ok:
        raise RuntimeError(f"Rendered video failed integrity check: {integrity.error}")
    quality = analyze_video_frames(video, max_frames=4)
    if not quality.get("ok", False):
        raise RuntimeError(
            "Rendered video failed frame-quality check: "
            + "; ".join(quality.get("warnings") or ["unknown issue"])
        )

    print(
        f"[OK] render smoke mode={profile.mode} aspect={profile.aspect} "
        f"quality={profile.quality_flag} fps={profile.fps} "
        f"resolution={profile.render_resolution or 'default'} "
        f"duration={integrity.duration_seconds:.2f}s "
        f"score={quality.get('score')} "
        f"elapsed={elapsed:.2f}s path={video}"
    )

    if not keep:
        script_path = MANIM_SCRIPTS / f"{output_name}.py"
        try:
            script_path.unlink()
        except OSError:
            pass
    return video


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="short", choices=["short", "standard", "course", "lecture"])
    parser.add_argument("--keep", action="store_true", help="Keep the generated Manim script")
    args = parser.parse_args()
    run_smoke(args.mode, keep=args.keep)


if __name__ == "__main__":
    main()
