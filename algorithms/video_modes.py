"""Runtime video-mode profiles for planning and rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from config import (
    DEFAULT_VIDEO_MODE,
    DRAFT_PIPELINE,
    FAST_PIPELINE,
    MAX_RENDER_RETRIES,
    RENDER_TIMEOUT_SECONDS,
    STREAM_SCENE_RETRIES,
    VIDEO_MODES,
)


VERTICAL_SHORT_RESOLUTION = (720, 1280)
DRAFT_QUALITY_FLAG = "-ql"
FAST_QUALITY_FLAG = "-ql"
FULL_QUALITY_FLAG = "-qm"


@dataclass(frozen=True)
class VideoModeProfile:
    mode: str
    label: str
    target_duration: int
    duration_range: tuple[int, int]
    min_scenes: int
    max_scenes: int
    aspect: str
    render_resolution: Optional[tuple[int, int]]
    quality_flag: str
    fps: int
    scene_retries: int
    render_retries: int
    scene_timeout_seconds: int
    min_success_ratio: float
    questions: Mapping[str, Any]
    narration_style: str
    complexity_cap: Optional[str]
    capped: bool = False
    raw: Mapping[str, Any] | None = None


def normalize_video_mode(value: str | None) -> str:
    mode = (value or DEFAULT_VIDEO_MODE).strip().lower()
    return mode if mode in VIDEO_MODES else DEFAULT_VIDEO_MODE


def _effective_duration(mode_cfg: Mapping[str, Any]) -> tuple[int, tuple[int, int], bool]:
    target = int(mode_cfg.get("target_duration", 240))
    lo, hi = mode_cfg.get("duration_range", (target, target))
    capped = False
    cap = mode_cfg.get("stub_cap_seconds")
    if mode_cfg.get("stub") and cap:
        cap = int(cap)
        target = min(target, cap)
        lo = min(int(lo), target)
        hi = min(int(hi), cap)
        capped = True
    return target, (int(lo), int(hi)), capped


def build_video_mode_profile(
    video_mode: str | None,
    *,
    is_fast: bool | None = None,
    draft: bool | None = None,
    streaming: bool = True,
) -> VideoModeProfile:
    mode = normalize_video_mode(video_mode)
    cfg = VIDEO_MODES[mode]
    is_fast = FAST_PIPELINE if is_fast is None else bool(is_fast)
    draft = DRAFT_PIPELINE if draft is None else bool(draft)
    speed_mode = is_fast or draft

    target_duration, duration_range, capped = _effective_duration(cfg)

    if draft:
        quality_flag = DRAFT_QUALITY_FLAG
        fps = 10
    elif speed_mode:
        quality_flag = FAST_QUALITY_FLAG
        fps = 15
    else:
        # Full mode should not default production renders to 480p.
        quality_flag = FULL_QUALITY_FLAG
        fps = 30

    aspect = str(cfg.get("aspect", "16:9"))
    render_resolution = VERTICAL_SHORT_RESOLUTION if aspect == "9:16" else None

    max_scenes = int(cfg.get("max_scenes", 20))
    min_scenes = int(cfg.get("min_scenes", 1))
    if capped and mode == "lecture":
        # Lecture mode is intentionally capped until the long-form renderer is
        # proven reliable enough for 30+ minute outputs. It still needs enough
        # scenelets to avoid one giant academic board accumulating stale text.
        max_scenes = min(max_scenes, 30)
        min_scenes = min(min_scenes, 15)

    if mode == "short":
        min_success_ratio = 1.0
    elif mode == "standard":
        min_success_ratio = 0.875
    else:
        min_success_ratio = 0.90

    scene_timeout = max(90, RENDER_TIMEOUT_SECONDS // 3)
    if mode == "course":
        # Course mode now uses chaptered 10-30s scenelets. A long timeout hides
        # hangs and makes one bad scene consume several minutes before recovery.
        scene_timeout = max(scene_timeout, 240)
    elif mode == "lecture":
        scene_timeout = max(scene_timeout, 300)

    return VideoModeProfile(
        mode=mode,
        label=str(cfg.get("label", mode.title())),
        target_duration=target_duration,
        duration_range=duration_range,
        min_scenes=min_scenes,
        max_scenes=max_scenes,
        aspect=aspect,
        render_resolution=render_resolution,
        quality_flag=quality_flag,
        fps=fps,
        scene_retries=1 if speed_mode else int(STREAM_SCENE_RETRIES),
        render_retries=1 if speed_mode else int(MAX_RENDER_RETRIES),
        scene_timeout_seconds=scene_timeout,
        min_success_ratio=min_success_ratio,
        questions=cfg.get("questions", {}),
        narration_style=str(cfg.get("narration_style", "clear, educational")),
        complexity_cap=cfg.get("complexity_cap"),
        capped=capped,
        raw=cfg,
    )


def apply_video_mode_to_analysis(analysis: dict | None, video_mode: str | None) -> dict:
    profile = build_video_mode_profile(video_mode)
    merged = dict(analysis or {})
    merged["video_mode"] = profile.mode
    merged["mode_label"] = profile.label
    merged["duration"] = profile.target_duration
    merged["target_duration"] = profile.target_duration
    merged["duration_range"] = profile.duration_range
    merged["min_scenes"] = profile.min_scenes
    merged["max_scenes"] = profile.max_scenes
    merged["aspect"] = profile.aspect
    merged["render_resolution"] = profile.render_resolution
    merged["questions"] = dict(profile.questions)
    if profile.complexity_cap:
        merged["complexity_cap"] = profile.complexity_cap
    if profile.capped:
        merged["mode_cap_seconds"] = profile.target_duration
    return merged
