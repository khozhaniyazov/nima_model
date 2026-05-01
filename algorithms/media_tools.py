"""Shared media command and post-processing helpers."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path


@dataclass(frozen=True)
class VideoValidationResult:
    ok: bool
    error: str = ""
    size_bytes: int = 0
    duration_seconds: float | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "error": self.error,
            "size_bytes": self.size_bytes,
            "duration_seconds": self.duration_seconds,
        }


def manim_command() -> list[str]:
    """Return the preferred command prefix for invoking Manim."""
    manim_bin = shutil.which("manim")
    if manim_bin:
        return [manim_bin]
    return [sys.executable, "-m", "manim"]


def ffmpeg_command() -> list[str]:
    """Return the preferred command prefix for invoking ffmpeg."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        return [ffmpeg_bin]
    try:
        import imageio_ffmpeg

        return [imageio_ffmpeg.get_ffmpeg_exe()]
    except Exception:
        return ["ffmpeg"]


def ffprobe_command() -> list[str]:
    """Return the preferred command prefix for invoking ffprobe."""
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        return [ffprobe_bin]
    try:
        import imageio_ffmpeg

        ffmpeg_exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
        ffprobe_exe = ffmpeg_exe.with_name("ffprobe.exe")
        if ffprobe_exe.exists():
            return [str(ffprobe_exe)]
    except Exception:
        pass
    return ["ffprobe"]


def escape_drawtext_text(value: str) -> str:
    """Escape text for ffmpeg drawtext filter syntax."""
    return (
        value.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def probe_media_duration_seconds(
    media_path: str | Path, *, timeout: int = 15
) -> float | None:
    """Return media duration in seconds, or None if probing is unavailable."""
    path = Path(media_path)
    if not path.exists():
        return None

    try:
        result = subprocess.run(
            [
                *ffprobe_command(),
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        value = float((result.stdout or "").strip())
        if math.isfinite(value) and value >= 0:
            return value
    except Exception:
        pass

    try:
        result = subprocess.run(
            [*ffmpeg_command(), "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        text = f"{result.stderr}\n{result.stdout}"
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))
            return hours * 3600 + minutes * 60 + seconds
    except Exception:
        pass

    return None


def media_has_audio_stream(media_path: str | Path, *, timeout: int = 15) -> bool:
    """Return true when ffprobe or ffmpeg can see at least one audio stream."""
    path = Path(media_path)
    if not path.exists():
        return False

    try:
        result = subprocess.run(
            [
                *ffprobe_command(),
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and (result.stdout or "").strip():
            return True
    except Exception:
        pass
    try:
        result = subprocess.run(
            [
                *ffmpeg_command(),
                "-hide_banner",
                "-i",
                str(path),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stream_info = f"{result.stderr}\n{result.stdout}"
        return bool(re.search(r"Stream #\d+:\d+.*Audio:", stream_info))
    except Exception:
        pass
    return False


def pad_video_to_min_duration(
    video_path: str | Path,
    min_duration_seconds: float,
    *,
    output_path: str | Path | None = None,
    fps: int | None = None,
    timeout: int | None = None,
) -> str:
    """Clone the final frame when a completed video is slightly under target."""
    source = Path(video_path)
    if not source.exists():
        return str(video_path)

    try:
        target = float(min_duration_seconds)
    except (TypeError, ValueError):
        return str(video_path)
    if target <= 0:
        return str(video_path)

    current = probe_media_duration_seconds(source)
    if current is None or current + 0.2 >= target:
        return str(video_path)

    pad_by = max(0.0, target - current)
    output = (
        Path(output_path)
        if output_path is not None
        else source.with_name(f"{source.stem}_padded{source.suffix}")
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    video_filter = f"tpad=stop_mode=clone:stop_duration={pad_by:.3f}"
    if fps:
        video_filter = f"{video_filter},fps={int(fps)}"

    has_audio = media_has_audio_stream(source)
    if has_audio:
        cmd = [
            *ffmpeg_command(),
            "-y",
            "-i",
            str(source),
            "-filter_complex",
            f"[0:v]{video_filter}[v];[0:a]apad=pad_dur={pad_by:.3f}[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output),
        ]
    else:
        cmd = [
            *ffmpeg_command(),
            "-y",
            "-i",
            str(source),
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-movflags",
            "+faststart",
            str(output),
        ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout or max(90, int(pad_by * 8) + 45),
        )
    except Exception as exc:
        print(f"[MEDIA] [WARN] final-duration padding skipped: {exc}")
        return str(video_path)

    if result.returncode != 0 or not output.exists():
        print(
            "[MEDIA] [WARN] final-duration padding failed: "
            f"{(result.stderr or result.stdout)[-500:]}"
        )
        return str(video_path)

    validation = validate_video_file(
        output,
        min_duration_seconds=max(0.25, target - 0.2),
    )
    if not validation.ok:
        print(
            "[MEDIA] [WARN] padded final video failed validation: "
            f"{validation.error}"
        )
        return str(video_path)

    print(
        f"[MEDIA] Padded final video from {current:.2f}s "
        f"to {validation.duration_seconds or target:.2f}s"
    )
    return str(output)


def validate_video_file(
    video_path: str | Path,
    *,
    min_bytes: int = 1024,
    min_duration_seconds: float | None = 0.25,
    timeout: int = 120,
    decode: bool = True,
) -> VideoValidationResult:
    """Verify that a final MP4 exists, is non-trivial, and can be decoded."""
    path = Path(video_path)
    if not path.exists():
        return VideoValidationResult(False, f"missing file: {path}")
    if not path.is_file():
        return VideoValidationResult(False, f"not a file: {path}")

    size = path.stat().st_size
    if size < min_bytes:
        return VideoValidationResult(
            False, f"file too small to be a valid render: {size} bytes", size
        )
    duration = probe_media_duration_seconds(path)
    if (
        min_duration_seconds is not None
        and duration is not None
        and duration < min_duration_seconds
    ):
        return VideoValidationResult(
            False,
            f"video duration too short: {duration:.3f}s",
            size,
            duration,
        )
    if not decode:
        return VideoValidationResult(True, size_bytes=size, duration_seconds=duration)

    try:
        result = subprocess.run(
            [
                *ffmpeg_command(),
                "-v",
                "error",
                "-i",
                str(path),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return VideoValidationResult(
            False, "ffmpeg validation timed out", size, duration
        )
    except Exception as exc:
        return VideoValidationResult(
            False, f"ffmpeg validation failed: {exc}", size, duration
        )

    if result.returncode != 0:
        error = (result.stderr or result.stdout or "ffmpeg decode failed").strip()
        return VideoValidationResult(False, error[-1000:], size, duration)
    return VideoValidationResult(True, size_bytes=size, duration_seconds=duration)


def apply_watermark_to_video(video_path: str, watermark: dict | None) -> str:
    """Apply a text watermark to a video when enabled.

    Returns the original path on any failure so post-processing cannot destroy a
    successful render.
    """
    if not isinstance(watermark, dict):
        return video_path
    watermark = watermark or {}
    if not watermark.get("enabled"):
        return video_path

    text = str(watermark.get("text") or "").strip()
    if not text:
        return video_path

    source = Path(video_path)
    if not source.exists():
        return video_path

    opacity = watermark.get("opacity", 50)
    try:
        opacity_float = max(0.1, min(1.0, float(opacity) / 100.0))
    except (TypeError, ValueError):
        opacity_float = 0.5

    position = str(watermark.get("position") or "bottom-right").lower()
    pad = "24"
    position_exprs = {
        "top-left": (pad, pad),
        "top-right": (f"w-tw-{pad}", pad),
        "bottom-left": (pad, f"h-th-{pad}"),
        "bottom-right": (f"w-tw-{pad}", f"h-th-{pad}"),
    }
    x_expr, y_expr = position_exprs.get(position, position_exprs["bottom-right"])
    output = source.with_name(f"{source.stem}_watermarked{source.suffix}")

    drawtext = (
        "drawtext="
        f"text='{escape_drawtext_text(text)}':"
        f"fontcolor=white@{opacity_float:.2f}:"
        "fontsize=max(20\\,h*0.035):"
        "box=1:"
        f"boxcolor=black@{min(0.35, opacity_float):.2f}:"
        "boxborderw=10:"
        f"x={x_expr}:y={y_expr}"
    )

    try:
        result = subprocess.run(
            [
                *ffmpeg_command(),
                "-y",
                "-i",
                str(source),
                "-vf",
                drawtext,
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0 and output.exists():
            return str(output)
        print(f"[WATERMARK] [WARN] ffmpeg failed: {result.stderr[-300:]}")
    except Exception as exc:
        print(f"[WATERMARK] [WARN] Could not apply watermark: {exc}")

    return video_path
