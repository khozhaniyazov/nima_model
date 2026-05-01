#!/usr/bin/env python3
"""
Run a local reliability sweep for the streaming pipeline.

Usage:
  python test_streaming_reliability.py
  python test_streaming_reliability.py --count 10 --host http://localhost:5000
  python test_streaming_reliability.py --voiceover
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

from config import OUTPUTS
from prompt_pool import COURSE_PROMPTS, EDGE_PROMPTS, LONG_RUN_PROMPTS


PROMPT_POOLS = {
    "course": [spec["prompt"] for spec in COURSE_PROMPTS.values()],
    "edge": [spec["prompt"] for spec in EDGE_PROMPTS.values()],
    "all": [spec["prompt"] for spec in LONG_RUN_PROMPTS.values()],
}


def post_json(url: str, payload: dict, timeout: float = 20.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_json(url: str, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def backend_available(host: str, timeout: float = 3.0) -> tuple[bool, str]:
    """Return whether a running backend is reachable at host."""
    try:
        health = get_json(f"{host}/health", timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    if (health.get("status") or "").lower() != "ok":
        return False, f"unexpected health payload: {health}"
    return True, ""


def video_exists(video_file: str) -> bool:
    if not video_file:
        return False
    direct_path = OUTPUTS / video_file
    if direct_path.exists():
        return True
    try:
        return any(OUTPUTS.rglob(video_file))
    except OSError:
        return False


def run_one(
    host: str,
    prompt: str,
    timeout_s: int,
    poll_interval: float,
    voiceover: bool,
    intro_outro: dict | None = None,
    mode: str = "standard",
) -> dict:
    t0 = time.time()
    payload = {
        "prompt": prompt,
        "voiceover": bool(voiceover),
        "streaming": True,
        "mode": mode,
    }
    if intro_outro:
        payload["intro_outro"] = intro_outro
    start = post_json(f"{host}/api/generate", payload)
    job_id = start.get("job_id")
    if not job_id:
        return {
            "job_id": None,
            "status": "error",
            "message": f"No job_id in response: {start}",
            "elapsed": time.time() - t0,
            "video_file": "",
            "video_exists": False,
        }

    deadline = t0 + timeout_s
    last = {}
    while time.time() < deadline:
        try:
            last = get_json(f"{host}/status/{job_id}")
        except urllib.error.URLError as e:
            last = {"status": "error", "message": f"status poll failed: {e}"}
            time.sleep(poll_interval)
            continue

        status = (last.get("status") or "").lower()
        if status in ("done", "error"):
            vf = last.get("video_file", "")
            repetition_pairs = last.get("repetition_pairs", [])
            scene_results = last.get("scene_results", []) or []
            planned_scenes = len(scene_results)
            failed_scenes = sum(
                1 for s in scene_results if (s.get("status") or "").lower() == "failed"
            )
            rendered_scenes = sum(
                1 for s in scene_results if (s.get("status") or "").lower() == "done"
            )
            success_ratio = rendered_scenes / max(1, planned_scenes)
            max_repetition = 0.0
            for pair in repetition_pairs:
                try:
                    max_repetition = max(max_repetition, float(pair.get("score", 0.0)))
                except Exception:
                    pass
            return {
                "job_id": job_id,
                "status": status,
                "message": last.get("message", ""),
                "elapsed": time.time() - t0,
                "video_file": vf,
                "video_exists": video_exists(vf),
                "repetition_pairs": repetition_pairs,
                "max_repetition": max_repetition,
                "planned_scenes": planned_scenes,
                "rendered_scenes": rendered_scenes,
                "failed_scenes": failed_scenes,
                "scene_success_ratio": success_ratio,
                "scene_results": scene_results,
                "video_mode": last.get("video_mode", mode),
            }

        time.sleep(poll_interval)

    scene_results = last.get("scene_results", []) if isinstance(last, dict) else []
    planned_scenes = len(scene_results)
    failed_scenes = sum(
        1 for s in scene_results if (s.get("status") or "").lower() == "failed"
    )
    rendered_scenes = sum(
        1 for s in scene_results if (s.get("status") or "").lower() == "done"
    )
    success_ratio = rendered_scenes / max(1, planned_scenes) if planned_scenes else 0.0
    repetition_pairs = (
        last.get("repetition_pairs", []) if isinstance(last, dict) else []
    )
    max_repetition = 0.0
    for pair in repetition_pairs:
        try:
            max_repetition = max(max_repetition, float(pair.get("score", 0.0)))
        except Exception:
            pass

    return {
        "job_id": job_id,
        "status": "timeout_partial" if planned_scenes > 0 else "timeout",
        "message": f"No terminal status within {timeout_s}s",
        "elapsed": time.time() - t0,
        "video_file": last.get("video_file", "") if isinstance(last, dict) else "",
        "video_exists": video_exists(last.get("video_file", ""))
        if isinstance(last, dict)
        else False,
        "repetition_pairs": repetition_pairs,
        "max_repetition": max_repetition,
        "planned_scenes": planned_scenes,
        "rendered_scenes": rendered_scenes,
        "failed_scenes": failed_scenes,
        "scene_success_ratio": success_ratio,
        "scene_results": scene_results,
        "video_mode": last.get("video_mode", mode) if isinstance(last, dict) else mode,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Streaming reliability harness")
    ap.add_argument("--host", default="http://localhost:5000", help="Backend base URL")
    ap.add_argument("--count", type=int, default=10, help="Number of jobs to run")
    ap.add_argument("--timeout", type=int, default=900, help="Per-job timeout seconds")
    ap.add_argument(
        "--poll", type=float, default=2.0, help="Status poll interval seconds"
    )
    ap.add_argument(
        "--voiceover", action="store_true", help="Enable voiceover in requests"
    )
    ap.add_argument("--seed", type=int, default=None, help="Optional RNG seed")
    ap.add_argument(
        "--branding", action="store_true", help="Enable default intro/outro branding"
    )
    ap.add_argument(
        "--pool",
        choices=("course", "edge", "all"),
        default="course",
        help="Prompt pool to sample from (default: course)",
    )
    ap.add_argument(
        "--mode",
        choices=("short", "standard", "course", "lecture"),
        default="standard",
        help="Video mode to request from backend",
    )
    ap.add_argument(
        "--require-server",
        action="store_true",
        help="Fail instead of skipping when the backend is not reachable",
    )
    args = ap.parse_args()

    available, unavailable_reason = backend_available(args.host)
    if not available:
        print("Streaming Reliability Harness")
        print(f"Host: {args.host}")
        print(f"SKIP: backend is not reachable: {unavailable_reason}")
        return 1 if args.require_server else 0

    print("Streaming Reliability Harness")
    print(f"Host: {args.host}")
    print(f"Jobs: {args.count}")
    print(f"Timeout/job: {args.timeout}s")
    print(f"Voiceover: {args.voiceover}")
    print(f"Branding: {args.branding}")
    print(f"Pool: {args.pool}")
    print(f"Mode: {args.mode}")
    print("-" * 72)

    prompt_pool = list(PROMPT_POOLS[args.pool])
    rng = random.Random(args.seed)
    rng.shuffle(prompt_pool)
    intro_outro = None
    if args.branding:
        intro_outro = {
            "enabled": True,
            "introText": "NIMA Course Video",
            "outroText": "Generated by NIMA",
        }

    results = []
    for i in range(args.count):
        prompt = prompt_pool[i % len(prompt_pool)]
        print(f"[{i + 1}/{args.count}] {prompt}")
        try:
            res = run_one(
                args.host,
                prompt,
                args.timeout,
                args.poll,
                args.voiceover,
                intro_outro=intro_outro,
                mode=args.mode,
            )
        except Exception as e:  # noqa: BLE001
            res = {
                "job_id": None,
                "status": "error",
                "message": f"Unhandled: {e}",
                "elapsed": 0.0,
                "video_file": "",
                "video_exists": False,
                "repetition_pairs": [],
                "max_repetition": 0.0,
                "planned_scenes": 0,
                "rendered_scenes": 0,
                "failed_scenes": 0,
                "scene_success_ratio": 0.0,
                "scene_results": [],
            }

        results.append(res)
        print(
            f"  -> status={res['status']} job={res.get('job_id')} "
            f"time={res['elapsed']:.1f}s video={res.get('video_file', '')} "
            f"exists={res['video_exists']} scenes={res.get('rendered_scenes', 0)}/{res.get('planned_scenes', 0)} "
            f"max_repeat={res.get('max_repetition', 0.0):.3f}"
        )
        if res.get("message"):
            print(f"     message: {res['message']}")

    ok = [r for r in results if r["status"] == "done" and r["video_exists"]]
    fail = [r for r in results if r not in ok]
    repeat_flag = [r for r in results if r.get("max_repetition", 0.0) >= 0.75]
    partial_scene_fail = [r for r in results if r.get("failed_scenes", 0) > 0]
    avg = sum(r["elapsed"] for r in ok) / len(ok) if ok else 0.0

    print("\n" + "=" * 72)
    print("RESULTS")
    print(f"Success: {len(ok)}/{len(results)}")
    print(f"Failure: {len(fail)}/{len(results)}")
    print(f"Avg successful runtime: {avg:.1f}s")
    print(f"Repetition-flagged jobs (>=0.75): {len(repeat_flag)}")
    print(f"Jobs with failed scenes: {len(partial_scene_fail)}")

    if fail:
        print("\nFailures:")
        for idx, r in enumerate(fail, 1):
            print(
                f"  {idx}. job={r.get('job_id')} status={r['status']} "
                f"exists={r['video_exists']} msg={r.get('message', '')}"
            )

    if repeat_flag:
        print("\nRepetition flags:")
        for idx, r in enumerate(repeat_flag, 1):
            print(
                f"  {idx}. job={r.get('job_id')} max_repeat={r.get('max_repetition', 0.0):.3f} "
                f"pairs={r.get('repetition_pairs', [])}"
            )

    if partial_scene_fail:
        print("\nJobs with failed scenes:")
        for idx, r in enumerate(partial_scene_fail, 1):
            print(
                f"  {idx}. job={r.get('job_id')} scenes={r.get('rendered_scenes', 0)}/{r.get('planned_scenes', 0)} "
                f"failed={r.get('failed_scenes', 0)} msg={r.get('message', '')}"
            )
            failed_scene_details = [
                s
                for s in r.get("scene_results", [])
                if (s.get("status") or "").lower() == "failed"
            ]
            for s in failed_scene_details:
                print(
                    f"     - scene={s.get('scene_num')} id={s.get('scene_id')} reason={s.get('error') or 'unknown'}"
                )

    # Exit non-zero if not 100% reliable or repetition too high
    return 0 if (len(ok) == len(results) and len(repeat_flag) == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
