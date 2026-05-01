"""Deterministic Manim render helpers shared by app and tests."""

from __future__ import annotations

import subprocess
import shutil
import time
from pathlib import Path

from config import (
    DRAFT_PIPELINE,
    MANIM_SCRIPTS,
    OUTPUTS,
    RENDER_TIMEOUT_SECONDS,
    DEFAULT_VIDEO_MODE,
)
from algorithms.media_tools import manim_command
from algorithms.code_digest import downgrade_tex_to_text_if_needed
from algorithms.video_modes import build_video_mode_profile


def _safe_render_stem(filename: str) -> str | None:
    normalized = str(filename or "").replace("\\", "/")
    if not normalized or "/" in normalized or normalized in {".", ".."}:
        return None
    if any(ch in normalized for ch in '<>:"|?*'):
        return None
    path = Path(normalized)
    if path.suffix and path.suffix.lower() != ".mp4":
        return None
    return path.stem if path.suffix else path.name


def _matches_render_stem(path: Path, stem: str) -> bool:
    """Return true for exact render artifacts without prefix collisions."""
    if path.suffix.lower() != ".mp4":
        return False
    if path.stem == stem:
        return True
    if not path.stem.startswith(stem):
        return False
    suffix = path.stem[len(stem) :]
    return bool(suffix) and suffix[0] in {"_", "-", "."}


def _matching_render_files(stem: str) -> list[Path]:
    return [mp4 for mp4 in OUTPUTS.rglob(f"{stem}*.mp4") if _matches_render_stem(mp4, stem)]


def inject_manim_frame_config(
    code: str,
    render_resolution: tuple[int, int] | None,
    *,
    frame_width: float = 8.0,
) -> str:
    """Inject a coordinate frame matching vertical render resolution."""
    if not render_resolution or len(render_resolution) != 2:
        return code
    width, height = render_resolution
    if width <= 0 or height <= 0 or width >= height:
        return code
    if "config.frame_width" in code or "config.frame_height" in code:
        return code

    frame_height = frame_width * (height / width)
    snippet = (
        f"config.frame_width = {frame_width:.6g}\n"
        f"config.frame_height = {frame_height:.6g}\n"
        "_NIMA_ORIGINAL_TEXT = Text\n"
        "def Text(*args, **kwargs):\n"
        "    mob = _NIMA_ORIGINAL_TEXT(*args, **kwargs)\n"
        "    max_width = config.frame_width - 0.7\n"
        "    if getattr(mob, 'width', 0) and mob.width > max_width:\n"
        "        mob.scale(max_width / mob.width)\n"
        "    return mob"
    )
    lines = code.splitlines()
    insert_at = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("from ", "import ")):
            insert_at = index + 1
            continue
        if not stripped:
            continue
        break
    lines[insert_at:insert_at] = [snippet]
    return "\n".join(lines) + ("\n" if code.endswith("\n") else "")


def cleanup_manim_partials(video_path: str | Path) -> None:
    """Remove Manim partial movie cache next to a completed final MP4."""
    partial_dir = Path(video_path).parent / "partial_movie_files"
    if not partial_dir.exists() or not partial_dir.is_dir():
        return
    shutil.rmtree(partial_dir, ignore_errors=True)


def find_video_file(filename: str, max_age_seconds: int | None = 300) -> Path | None:
    """Search for a rendered video file in common Manim output locations."""
    filename = _safe_render_stem(filename)
    if not filename:
        return None

    direct = OUTPUTS / f"{filename}.mp4"
    if direct.exists():
        return direct

    now = time.time()
    matches = sorted(
        _matching_render_files(filename),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for mp4 in matches:
        if max_age_seconds is None or now - mp4.stat().st_mtime < max_age_seconds:
            return mp4
    return None


def build_manim_render_command(
    script_path: Path,
    output_file: str,
    *,
    video_mode: str = DEFAULT_VIDEO_MODE,
    is_fast: bool | None = None,
    draft: bool | None = None,
    scene_class: str = "GeneratedScene",
) -> list[str]:
    """Build the Manim command for a full-scene render."""
    output_stem = _safe_render_stem(output_file)
    if not output_stem:
        raise ValueError("Unsafe render output filename")

    profile = build_video_mode_profile(
        video_mode,
        is_fast=is_fast,
        draft=DRAFT_PIPELINE if draft is None else draft,
        streaming=False,
    )
    cmd = [
        *manim_command(),
        str(script_path),
        scene_class,
        profile.quality_flag,
        "--format=mp4",
        "--media_dir",
        str(OUTPUTS),
        "--output_file",
        f"{output_stem}.mp4",
        "--disable_caching",
        "--fps",
        str(profile.fps),
    ]
    if profile.render_resolution:
        width, height = profile.render_resolution
        cmd.extend(["--resolution", f"{width},{height}"])
    return cmd


def render_manim_code(
    code: str,
    filename: str,
    *,
    is_fast: bool | None = None,
    video_mode: str = DEFAULT_VIDEO_MODE,
    draft: bool | None = None,
    scene_class: str = "GeneratedScene",
    timeout_seconds: int = RENDER_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """Write a Manim script, remove stale outputs, and render it."""
    safe_filename = _safe_render_stem(filename)
    if not safe_filename:
        raise ValueError("Unsafe render filename")

    MANIM_SCRIPTS.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    profile = build_video_mode_profile(video_mode, is_fast=is_fast, draft=draft)
    code = downgrade_tex_to_text_if_needed(code)
    code = inject_manim_frame_config(code, profile.render_resolution)

    script_path = MANIM_SCRIPTS / f"{safe_filename}.py"
    script_path.write_text(code, encoding="utf-8", errors="replace")

    for old_file in _matching_render_files(safe_filename):
        try:
            old_file.unlink()
        except OSError:
            pass

    cmd = build_manim_render_command(
        script_path,
        f"{safe_filename}.mp4",
        video_mode=video_mode,
        is_fast=is_fast,
        draft=draft,
        scene_class=scene_class,
    )
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode == 0:
        video_path = find_video_file(safe_filename)
        if video_path:
            cleanup_manim_partials(video_path)
    return result
