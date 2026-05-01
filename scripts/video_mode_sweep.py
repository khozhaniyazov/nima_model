#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from config import OUTPUTS, VIDEO_MODES
from algorithms.media_tools import (
    ffmpeg_command,
    ffprobe_command,
    media_has_audio_stream,
    probe_media_duration_seconds,
    validate_video_file,
)
from algorithms.video_modes import build_video_mode_profile
from algorithms.video_quality import analyze_video_frames
from prompt_pool import EDGE_PROMPTS, COURSE_PROMPTS


API_DEFAULT = "http://localhost:5000"
REPORT_DIR = OUTPUTS / "qa_reports"

PROMPTS_BY_MODE = {
    "short": [
        EDGE_PROMPTS["edge_very_short"]["prompt"],
        EDGE_PROMPTS["linalg_orthogonality"]["prompt"],
        EDGE_PROMPTS["cs_binary_search"]["prompt"],
        EDGE_PROMPTS["physics_projectile"]["prompt"],
        EDGE_PROMPTS["chem_reaction_rate"]["prompt"],
    ],
    "standard": [
        EDGE_PROMPTS["calc_taylor_series"]["prompt"],
        EDGE_PROMPTS["physics_wave_superposition"]["prompt"],
        EDGE_PROMPTS["cs_bfs_vs_dfs"]["prompt"],
        EDGE_PROMPTS["chem_equilibrium"]["prompt"],
        EDGE_PROMPTS["prob_bayes"]["prompt"],
    ],
    "course": [
        COURSE_PROMPTS["course_limits"]["prompt"],
        COURSE_PROMPTS["course_data_structures"]["prompt"],
        COURSE_PROMPTS["course_mechanics"]["prompt"],
        COURSE_PROMPTS["course_chem_bonding"]["prompt"],
        COURSE_PROMPTS["course_microeconomics"]["prompt"],
    ],
    "lecture": [
        COURSE_PROMPTS["course_real_analysis"]["prompt"],
        COURSE_PROMPTS["course_graph_algorithms"]["prompt"],
        COURSE_PROMPTS["course_thermo"]["prompt"],
        COURSE_PROMPTS["course_chem_acid_base"]["prompt"],
        COURSE_PROMPTS["course_game_theory"]["prompt"],
    ],
}


def post_json(
    url: str, payload: dict[str, Any], timeout: float = 30.0
) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def probe_media_streams(video_path: Path) -> dict[str, Any]:
    cmd = [
        *ffprobe_command(),
        "-v",
        "error",
        "-show_streams",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed")
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams", [])
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        return {
            "ok": True,
            "audio_streams": len(audio_streams),
            "video_streams": len(video_streams),
            "has_audio": bool(audio_streams),
        }
    except Exception as exc:
        try:
            fallback = subprocess.run(
                [*ffmpeg_command(), "-i", str(video_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            stderr = fallback.stderr or ""
            return {
                "ok": True,
                "audio_streams": 1 if "Audio:" in stderr else 0,
                "video_streams": 1 if "Video:" in stderr else 0,
                "has_audio": "Audio:" in stderr,
                "probe_warning": str(exc),
            }
        except Exception as fallback_exc:
            return {"ok": False, "error": str(fallback_exc), "probe_warning": str(exc)}


class VideoQAEvaluator:
    def __init__(self, sample_seconds: float = 1.0):
        self.sample_seconds = sample_seconds
        # Keep the old CLI flag but use a bounded frame count so QA works even
        # when OpenCV/EasyOCR are not installed. analyze_video_frames will use
        # optional local OCR backends when they are available.
        self.max_frames = max(4, min(24, int(round(18 / max(sample_seconds, 0.5)))))

    def analyze(self, video_path: Path) -> dict[str, Any]:
        report = analyze_video_frames(video_path, max_frames=self.max_frames)
        ocr_summary = ((report.get("ocr") or {}).get("summary") or {})
        frames = report.get("frames") or []
        duration = probe_media_duration_seconds(video_path) or 0.0
        return {
            "video_path": str(video_path),
            "duration_seconds": round(duration, 2),
            "sampled_frames": int(report.get("sampled_frames") or 0),
            "qa_score": int(report.get("score") or 0),
            "ok": bool(report.get("ok")),
            "warnings": report.get("warnings") or [],
            "summary": {
                "mean_text_boxes": ocr_summary.get("mean_text_boxes", 0.0),
                "mean_overlap_ratio": ocr_summary.get("mean_overlap_ratio", 0.0),
                "max_overlap_ratio": ocr_summary.get("max_overlap_ratio", 0.0),
                "max_edge_clip_ratio": ocr_summary.get("max_edge_clip_ratio", 0.0),
                "blank_frames": sum(1 for frame in frames if frame.get("blank")),
                "tiny_content_frames": sum(
                    1 for frame in frames if frame.get("tiny_content")
                ),
                "cluttered_frames": sum(
                    1 for frame in frames if frame.get("cluttered")
                ),
                "edge_crowded_frames": sum(
                    1 for frame in frames if frame.get("edge_crowded")
                ),
            },
            "ocr": report.get("ocr") or {},
            "frames": frames[:20],
        }


def wait_for_job(
    host: str, job_id: str, timeout_s: int, poll_s: float
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        try:
            last = get_json(f"{host}/status/{job_id}")
        except urllib.error.URLError:
            time.sleep(poll_s)
            continue
        if (last.get("status") or "").lower() in {"done", "error", "failed"}:
            return last
        time.sleep(poll_s)
    return {
        "status": "timeout",
        "message": f"No terminal state in {timeout_s}s",
        **last,
    }


def run_mode_sweep(
    host: str,
    mode: str,
    prompts: list[str],
    timeout_s: int,
    voiceover: bool,
    sample_seconds: float,
) -> dict[str, Any]:
    qa = VideoQAEvaluator(sample_seconds=sample_seconds)
    mode_results = []
    profile = build_video_mode_profile(mode)
    duration_min, duration_max = profile.duration_range
    for idx, prompt in enumerate(prompts, start=1):
        print(f"[{mode}] {idx}/{len(prompts)} :: {prompt}")
        start = post_json(
            f"{host}/api/generate",
            {"prompt": prompt, "voiceover": voiceover, "streaming": True, "mode": mode},
        )
        job_id = start.get("job_id")
        if not job_id:
            mode_results.append(
                {"prompt": prompt, "status": "error", "message": f"No job_id: {start}"}
            )
            continue

        status = wait_for_job(host, job_id, timeout_s=timeout_s, poll_s=2.0)
        result = {
            "prompt": prompt,
            "job_id": job_id,
            "status": status.get("status"),
            "message": status.get("message", ""),
            "video_file": status.get("video_file", ""),
            "scene_results": status.get("scene_results", []),
            "video_mode": status.get("video_mode", mode),
        }

        if result["status"] == "done" and result["video_file"]:
            video_path = OUTPUTS / result["video_file"]
            if video_path.exists():
                validation = validate_video_file(
                    video_path,
                    min_duration_seconds=max(0, duration_min - 5),
                )
                result["integrity"] = validation.as_dict()
                result["media"] = probe_media_streams(video_path)
                result["media"]["has_audio"] = media_has_audio_stream(video_path)
                try:
                    result["qa"] = qa.analyze(video_path)
                    duration = result["qa"].get("duration_seconds")
                    if duration is not None:
                        if duration < duration_min:
                            result["duration_flag"] = "too_short"
                        elif duration > duration_max:
                            result["duration_flag"] = "too_long"
                        else:
                            result["duration_flag"] = "on_target"
                except Exception as exc:
                    result["qa_error"] = str(exc)
            else:
                result["qa_error"] = f"Missing output file: {video_path}"
        mode_results.append(result)

    scores = [r["qa"]["qa_score"] for r in mode_results if r.get("qa")]
    return {
        "mode": mode,
        "requested": len(prompts),
        "completed": len([r for r in mode_results if r.get("status") == "done"]),
        "qa_scored": len(scores),
        "audio_verified": len(
            [r for r in mode_results if r.get("media", {}).get("has_audio")]
        ),
        "duration_flags": {
            "too_short": len(
                [r for r in mode_results if r.get("duration_flag") == "too_short"]
            ),
            "on_target": len(
                [r for r in mode_results if r.get("duration_flag") == "on_target"]
            ),
            "too_long": len(
                [r for r in mode_results if r.get("duration_flag") == "too_long"]
            ),
        },
        "mean_qa_score": round(statistics.mean(scores), 2) if scores else None,
        "min_qa_score": round(min(scores), 2) if scores else None,
        "max_qa_score": round(max(scores), 2) if scores else None,
        "results": mode_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run local render + visual QA sweep by video mode"
    )
    parser.add_argument("--host", default=API_DEFAULT)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=tuple(VIDEO_MODES.keys()),
        default=list(VIDEO_MODES.keys()),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Prompts per mode (5 recommended, 10 expensive)",
    )
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--voiceover", action="store_true")
    parser.add_argument("--sample-seconds", type=float, default=1.5)
    parser.add_argument(
        "--report", default=str(REPORT_DIR / "video_mode_sweep_report.json")
    )
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "host": args.host,
        "count_per_mode": args.count,
        "voiceover": args.voiceover,
        "sample_seconds": args.sample_seconds,
        "modes": [],
    }

    for mode in args.modes:
        prompts = PROMPTS_BY_MODE[mode][: args.count]
        mode_report = run_mode_sweep(
            host=args.host,
            mode=mode,
            prompts=prompts,
            timeout_s=args.timeout,
            voiceover=args.voiceover,
            sample_seconds=args.sample_seconds,
        )
        report["modes"].append(mode_report)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
