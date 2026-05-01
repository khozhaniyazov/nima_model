"""Local frame-level video quality checks.

This is intentionally dependency-light: frames are sampled with ffmpeg and PNGs
are decoded with the standard library. The goal is not a full vision model; it is
to catch obvious bad renders that static code checks and file-existence checks
miss: blank frames, severe edge crowding, and visually overloaded frames.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from algorithms.media_tools import ffmpeg_command, probe_media_duration_seconds
from algorithms.vision_adapters import analyze_frame_ocr_paths


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _paeth(left: int, up: int, up_left: int) -> int:
    p = left + up - up_left
    pa = abs(p - left)
    pb = abs(p - up)
    pc = abs(p - up_left)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return up
    return up_left


def _read_png_rgb(path: Path) -> tuple[int, int, list[tuple[int, int, int]]]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG file")

    pos = len(PNG_SIGNATURE)
    width = height = color_type = bit_depth = interlace = None
    compressed = bytearray()

    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]
        pos += 12 + length

        if chunk_type == b"IHDR":
            width = int.from_bytes(chunk_data[0:4], "big")
            height = int.from_bytes(chunk_data[4:8], "big")
            bit_depth = chunk_data[8]
            color_type = chunk_data[9]
            interlace = chunk_data[12]
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    if not width or not height:
        raise ValueError("PNG missing IHDR")
    if bit_depth != 8:
        raise ValueError(f"unsupported PNG bit depth: {bit_depth}")
    if interlace:
        raise ValueError("interlaced PNG is unsupported")

    channels_by_color = {0: 1, 2: 3, 6: 4}
    channels = channels_by_color.get(color_type)
    if not channels:
        raise ValueError(f"unsupported PNG color type: {color_type}")

    raw = zlib.decompress(bytes(compressed))
    stride = width * channels
    rows: list[bytearray] = []
    cursor = 0

    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        scanline = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        previous = rows[-1] if rows else bytearray(stride)

        for i in range(stride):
            left = scanline[i - channels] if i >= channels else 0
            up = previous[i]
            up_left = previous[i - channels] if i >= channels else 0
            if filter_type == 0:
                value = scanline[i]
            elif filter_type == 1:
                value = scanline[i] + left
            elif filter_type == 2:
                value = scanline[i] + up
            elif filter_type == 3:
                value = scanline[i] + ((left + up) // 2)
            elif filter_type == 4:
                value = scanline[i] + _paeth(left, up, up_left)
            else:
                raise ValueError(f"unsupported PNG filter: {filter_type}")
            scanline[i] = value & 0xFF
        rows.append(scanline)

    pixels: list[tuple[int, int, int]] = []
    for row in rows:
        for x in range(width):
            idx = x * channels
            if channels == 1:
                value = row[idx]
                pixels.append((value, value, value))
            else:
                pixels.append((row[idx], row[idx + 1], row[idx + 2]))

    return width, height, pixels


def _mean_rgb(pixels: Iterable[tuple[int, int, int]]) -> tuple[float, float, float]:
    count = 0
    r_total = g_total = b_total = 0.0
    for r, g, b in pixels:
        count += 1
        r_total += r
        g_total += g
        b_total += b
    if not count:
        return (0.0, 0.0, 0.0)
    return (r_total / count, g_total / count, b_total / count)


def _dominant_rgb(pixels: Iterable[tuple[int, int, int]]) -> tuple[float, float, float]:
    buckets: Counter[tuple[int, int, int]] = Counter()
    bucket_values: defaultdict[tuple[int, int, int], list[tuple[int, int, int]]] = (
        defaultdict(list)
    )
    for pixel in pixels:
        bucket = tuple(channel // 24 for channel in pixel)
        buckets[bucket] += 1
        if len(bucket_values[bucket]) < 200:
            bucket_values[bucket].append(pixel)
    if not buckets:
        return (0.0, 0.0, 0.0)
    dominant_bucket = buckets.most_common(1)[0][0]
    return _mean_rgb(bucket_values[dominant_bucket])


def _luma(pixel: tuple[int, int, int]) -> float:
    r, g, b = pixel
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def analyze_frame_pixels(
    width: int, height: int, pixels: list[tuple[int, int, int]]
) -> dict:
    """Return simple local visual metrics for one RGB frame."""
    if width <= 0 or height <= 0 or len(pixels) != width * height:
        raise ValueError("invalid frame dimensions")

    sample_stride = max(1, int(math.sqrt((width * height) / 20000)))
    corner = max(2, min(width, height) // 12)
    sampled_pixels = []
    corner_pixels = []
    for y in range(0, height, sample_stride):
        for x in range(0, width, sample_stride):
            sampled_pixels.append(pixels[y * width + x])
            if (x < corner or x >= width - corner) and (
                y < corner or y >= height - corner
            ):
                corner_pixels.append(pixels[y * width + x])
    background = _dominant_rgb(sampled_pixels) or _mean_rgb(corner_pixels)

    edge_band = max(2, min(width, height) // 20)
    total = foreground = edge_total = edge_foreground = 0
    lumas = []
    min_x, min_y = width, height
    max_x = max_y = -1

    for y in range(0, height, sample_stride):
        for x in range(0, width, sample_stride):
            pixel = pixels[y * width + x]
            lumas.append(_luma(pixel))
            total += 1

            dist = math.sqrt(
                (pixel[0] - background[0]) ** 2
                + (pixel[1] - background[1]) ** 2
                + (pixel[2] - background[2]) ** 2
            )
            is_foreground = dist >= 32
            is_edge = (
                x < edge_band
                or x >= width - edge_band
                or y < edge_band
                or y >= height - edge_band
            )
            if is_edge:
                edge_total += 1
            if is_foreground:
                foreground += 1
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
                if is_edge:
                    edge_foreground += 1

    mean_luma = sum(lumas) / max(1, len(lumas))
    variance = sum((value - mean_luma) ** 2 for value in lumas) / max(1, len(lumas))
    luma_std = math.sqrt(variance)
    foreground_ratio = foreground / max(1, total)
    edge_ratio = edge_foreground / max(1, edge_total)
    if foreground:
        bbox_width_ratio = min(1.0, (max_x - min_x + sample_stride) / width)
        bbox_height_ratio = min(1.0, (max_y - min_y + sample_stride) / height)
        bbox_area_ratio = bbox_width_ratio * bbox_height_ratio
    else:
        bbox_width_ratio = 0.0
        bbox_height_ratio = 0.0
        bbox_area_ratio = 0.0
    touches_left = foreground > 0 and min_x <= edge_band
    touches_top = foreground > 0 and min_y <= edge_band
    touches_right = foreground > 0 and max_x >= width - edge_band
    touches_bottom = foreground > 0 and max_y >= height - edge_band
    touched_edges = sum([touches_left, touches_top, touches_right, touches_bottom])
    touches_border = foreground_ratio > 0.03 and touched_edges >= 2

    return {
        "width": width,
        "height": height,
        "foreground_ratio": round(foreground_ratio, 4),
        "foreground_bbox_ratio": round(bbox_area_ratio, 4),
        "foreground_bbox_width_ratio": round(bbox_width_ratio, 4),
        "foreground_bbox_height_ratio": round(bbox_height_ratio, 4),
        "edge_foreground_ratio": round(edge_ratio, 4),
        "luma_std": round(luma_std, 2),
        "blank": luma_std < 2.0 or foreground_ratio < 0.001,
        "tiny_content": foreground_ratio < 0.008 or bbox_area_ratio < 0.025,
        "cluttered": foreground_ratio > 0.42,
        "edge_crowded": edge_ratio > 0.34 or touches_border,
        "touched_edges": touched_edges,
    }


def analyze_video_frames(video_path: str | Path, *, max_frames: int = 12) -> dict:
    """Sample rendered video frames and return a local quality report."""
    path = Path(video_path)
    disabled_ocr = {
        "enabled": False,
        "backend": None,
        "sampled_frames": 0,
        "text_frames": 0,
        "warnings": [],
        "error": "not run",
    }
    if not path.exists():
        return {
            "ok": False,
            "score": 0,
            "warnings": [f"video missing: {path}"],
            "sampled_frames": 0,
            "frames": [],
            "ocr": disabled_ocr,
        }

    tmp_dir = Path(tempfile.mkdtemp(prefix="nima-frame-quality-"))
    try:
        frame_pattern = tmp_dir / "frame_%03d.png"
        duration = probe_media_duration_seconds(path)
        target_frames = max(1, int(max_frames))
        if duration and duration > target_frames:
            sample_fps = max(0.001, target_frames / duration)
        else:
            sample_fps = 1.0
        result = subprocess.run(
            [
                *ffmpeg_command(),
                "-y",
                "-i",
                str(path),
                "-vf",
                f"fps={sample_fps:.6f},scale=320:-2:flags=fast_bilinear",
                "-frames:v",
                str(target_frames),
                str(frame_pattern),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "frame extraction failed").strip()
            return {
                "ok": False,
                "score": 0,
                "warnings": [error[-1000:]],
                "sampled_frames": 0,
                "frames": [],
                "ocr": disabled_ocr,
            }

        frame_metrics = []
        warnings = []
        frame_paths = sorted(tmp_dir.glob("frame_*.png"))
        for frame_path in frame_paths:
            try:
                width, height, pixels = _read_png_rgb(frame_path)
                frame_metrics.append(analyze_frame_pixels(width, height, pixels))
            except Exception as exc:
                warnings.append(f"{frame_path.name}: {exc}")

        ocr_report = analyze_frame_ocr_paths(frame_paths, timeout=8)

        sampled = len(frame_metrics)
        if not sampled:
            return {
                "ok": False,
                "score": 0,
                "warnings": warnings or ["no frames extracted"],
                "sampled_frames": 0,
                "frames": [],
                "ocr": ocr_report,
            }

        blank_count = sum(1 for frame in frame_metrics if frame["blank"])
        tiny_count = sum(
            1
            for frame in frame_metrics
            if frame.get("tiny_content") and not frame["blank"]
        )
        clutter_count = sum(1 for frame in frame_metrics if frame["cluttered"])
        edge_count = sum(1 for frame in frame_metrics if frame["edge_crowded"])

        if blank_count:
            warnings.append(f"{blank_count}/{sampled} sampled frames look blank")
        if tiny_count:
            warnings.append(f"{tiny_count}/{sampled} sampled frames have tiny content")
        if clutter_count:
            warnings.append(f"{clutter_count}/{sampled} sampled frames look cluttered")
        if edge_count:
            warnings.append(f"{edge_count}/{sampled} sampled frames crowd frame edges")
        for warning in ocr_report.get("layout_warnings", []):
            warnings.append(f"OCR: {warning}")

        score = 100
        score -= min(45, blank_count * 10)
        score -= min(40, tiny_count * 6)
        score -= min(35, clutter_count * 12)
        score -= min(25, edge_count * 8)
        ocr_summary = ocr_report.get("summary") or {}
        score -= min(25, float(ocr_summary.get("max_overlap_ratio") or 0) * 120)
        score -= min(15, float(ocr_summary.get("max_edge_clip_ratio") or 0) * 20)
        score -= min(20, len(warnings) * 2)
        score = int(max(0, min(100, round(score))))

        if sampled <= 2:
            severe_blank = blank_count == sampled
            severe_tiny = tiny_count == sampled
            severe_clutter = clutter_count == sampled
        else:
            severe_blank = blank_count >= max(2, math.ceil(sampled * 0.5))
            severe_tiny = tiny_count >= max(3, math.ceil(sampled * 0.65))
            severe_clutter = clutter_count >= max(2, math.ceil(sampled * 0.5))
        severe = severe_blank or severe_tiny or severe_clutter
        severe = severe or float(ocr_summary.get("max_overlap_ratio") or 0) >= 0.32
        severe = severe or score < 70
        return {
            "ok": not severe,
            "score": score,
            "warnings": warnings,
            "sampled_frames": sampled,
            "frames": frame_metrics,
            "ocr": ocr_report,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def short_video_quality_requires_fallback(report: dict) -> bool:
    """Return true when a 9:16 short has a severe visual failure."""
    if not report.get("ok", False):
        return True

    if int(report.get("score") or 0) < 75:
        return True

    frames = report.get("frames") or []
    tiny_count = sum(1 for frame in frames if frame.get("tiny_content"))
    edge_count = sum(1 for frame in frames if frame.get("edge_crowded"))
    clutter_count = sum(1 for frame in frames if frame.get("cluttered"))
    sampled = max(1, int(report.get("sampled_frames") or len(frames) or 1))
    if tiny_count >= max(2, int(sampled * 0.65)) or clutter_count >= max(2, int(sampled * 0.5)):
        return True
    if edge_count >= max(3, int(sampled * 0.75)):
        return True

    ocr_summary = ((report.get("ocr") or {}).get("summary") or {})
    if float(ocr_summary.get("max_overlap_ratio") or 0.0) >= 0.2:
        return True
    if float(ocr_summary.get("max_edge_clip_ratio") or 0.0) >= 0.4:
        return True

    return False


def video_quality_requires_mode_recovery(
    report: dict, mode: str | None, *, final: bool = False
) -> bool:
    """Return true when a rendered scene deserves one mode-aware retry.

    This is intentionally stricter than the final hard-failure gate but looser
    than short-mode fallback. The goal is to repair obvious layout problems
    while preserving a usable render if the retry is not better.
    """
    mode = (mode or "").lower()
    if mode not in {"standard", "course", "lecture"}:
        return False

    if video_quality_requires_hard_failure(report):
        return True

    if final:
        frames = report.get("frames") or []
        sampled = max(1, int(report.get("sampled_frames") or len(frames) or 1))
        score = int(report.get("score") or 0)
        edge_count = sum(1 for frame in frames if frame.get("edge_crowded"))
        clutter_count = sum(1 for frame in frames if frame.get("cluttered"))
        ocr_summary = ((report.get("ocr") or {}).get("summary") or {})
        max_overlap = float(ocr_summary.get("max_overlap_ratio") or 0.0)
        max_edge_clip = float(ocr_summary.get("max_edge_clip_ratio") or 0.0)

        if score and score < (58 if mode == "standard" else 62):
            return True
        if edge_count >= max(4, math.ceil(sampled * 0.75)):
            return True
        if clutter_count >= max(3, math.ceil(sampled * 0.5)):
            return True
        if max_overlap >= (0.30 if mode == "standard" else 0.24):
            return True
        if max_edge_clip >= 0.58:
            return True
        return False

    if not report.get("ok", False):
        return True

    frames = report.get("frames") or []
    sampled = max(1, int(report.get("sampled_frames") or len(frames) or 1))
    tiny_count = sum(1 for frame in frames if frame.get("tiny_content"))
    edge_count = sum(1 for frame in frames if frame.get("edge_crowded"))
    clutter_count = sum(1 for frame in frames if frame.get("cluttered"))
    score = int(report.get("score") or 0)
    ocr_summary = ((report.get("ocr") or {}).get("summary") or {})
    max_overlap = float(ocr_summary.get("max_overlap_ratio") or 0.0)
    max_edge_clip = float(ocr_summary.get("max_edge_clip_ratio") or 0.0)

    if score and score < (76 if mode == "standard" else 72):
        return True
    if edge_count >= max(3, math.ceil(sampled * 0.75)):
        return True
    if clutter_count >= max(2, math.ceil(sampled * 0.5)):
        return True
    if tiny_count >= max(3, math.ceil(sampled * 0.75)):
        return True
    if max_overlap >= (0.18 if mode == "standard" else 0.16):
        return True
    if max_edge_clip >= 0.4:
        return True

    return False


def video_quality_requires_hard_failure(report: dict) -> bool:
    """Return true only for severe integrity failures, not aesthetic warnings."""
    sampled = max(1, int(report.get("sampled_frames") or 0))
    frames = report.get("frames") or []
    if not frames and not report.get("ok", False):
        return True

    blank_count = sum(1 for frame in frames if frame.get("blank"))
    tiny_count = sum(
        1 for frame in frames if frame.get("tiny_content") and not frame.get("blank")
    )
    clutter_count = sum(1 for frame in frames if frame.get("cluttered"))

    if blank_count >= max(2, (sampled + 1) // 2):
        return True
    if tiny_count >= max(3, int(sampled * 0.85)):
        return True
    if clutter_count >= max(3, int(sampled * 0.75)):
        return True
    if int(report.get("score") or 0) < 45:
        return True

    ocr_summary = ((report.get("ocr") or {}).get("summary") or {})
    if float(ocr_summary.get("max_overlap_ratio") or 0.0) >= 0.5:
        return True
    if float(ocr_summary.get("max_edge_clip_ratio") or 0.0) >= 0.65:
        return True

    return False
