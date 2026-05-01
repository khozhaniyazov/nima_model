#!/usr/bin/env python3
"""Edge-case stress test for NIMA streaming pipeline."""

from __future__ import annotations

import argparse
import random

from prompt_pool import EDGE_PROMPTS
from test_streaming_reliability import backend_available, run_one


def main() -> int:
    ap = argparse.ArgumentParser(description="Edge-case stress test")
    ap.add_argument("--host", default="http://localhost:5000")
    ap.add_argument("--count", type=int, default=5, help="Number of prompts to run")
    ap.add_argument("--timeout", type=int, default=1200, help="Per-job timeout")
    ap.add_argument("--poll", type=float, default=2.0)
    ap.add_argument("--voiceover", action="store_true")
    ap.add_argument(
        "--mode",
        choices=("short", "standard", "course", "lecture"),
        default="standard",
        help="Video mode to request from backend",
    )
    ap.add_argument("--pick", type=int, default=0, help="Random pick N from pool")
    ap.add_argument("--domain", default=None, help="Filter by domain")
    ap.add_argument(
        "--key",
        action="append",
        default=[],
        help="Run a specific prompt key. Can be passed more than once.",
    )
    ap.add_argument("--list", action="store_true", help="List all prompts and exit")
    ap.add_argument(
        "--require-server",
        action="store_true",
        help="Fail instead of skipping when the backend is not reachable",
    )
    args = ap.parse_args()

    if args.list:
        for key, val in EDGE_PROMPTS.items():
            print(f"  {key:30s} [{val['domain']:20s}] {val['edge']}")
        print(f"\n{len(EDGE_PROMPTS)} prompts available")
        return 0

    if args.key:
        missing = [key for key in args.key if key not in EDGE_PROMPTS]
        if missing:
            print(f"Unknown prompt key(s): {', '.join(missing)}")
            return 2
        pool = [(key, EDGE_PROMPTS[key]) for key in args.key]
    else:
        pool = list(EDGE_PROMPTS.items())

    if args.domain:
        pool = [(k, v) for k, v in pool if v["domain"] == args.domain]

    if not args.key:
        random.shuffle(pool)
        if args.pick > 0:
            pool = pool[: min(args.pick, len(pool))]
        else:
            pool = pool[: min(args.count, len(pool))]

    available, unavailable_reason = backend_available(args.host)
    if not available:
        print("NIMA Edge-Case Stress Test")
        print(f"Host: {args.host}")
        print(f"SKIP: backend is not reachable: {unavailable_reason}")
        return 1 if args.require_server else 0

    print("NIMA Edge-Case Stress Test")
    print(f"Host: {args.host}")
    print(f"Jobs: {len(pool)}")
    print(f"Voiceover: {args.voiceover}")
    print(f"Mode: {args.mode}")
    print("-" * 72)

    results = []
    for i, (key, spec) in enumerate(pool):
        prompt = spec["prompt"]
        print(f"\n[{i + 1}/{len(pool)}] [{spec['domain']}] {key}")
        print(f"  prompt: {prompt}")
        print(f"  edge:   {spec['edge']}")

        try:
            res = run_one(
                args.host,
                prompt,
                args.timeout,
                args.poll,
                args.voiceover,
                mode=args.mode,
            )
        except Exception as e:
            res = {
                "job_id": None,
                "status": "error",
                "message": f"Unhandled: {e}",
                "elapsed": 0.0,
                "video_file": "",
                "video_exists": False,
                "repetition_pairs": [],
                "max_repetition": 0.0,
            }

        res["key"] = key
        res["domain"] = spec["domain"]
        res["edge"] = spec["edge"]
        results.append(res)

        success = res["status"] == "done" and res["video_exists"]
        icon = "OK" if success else "FAIL"
        print(
            f"  {icon} status={res['status']} job={res.get('job_id')} "
            f"time={res['elapsed']:.1f}s exists={res['video_exists']} scenes={res.get('rendered_scenes', 0)}/{res.get('planned_scenes', 0)} "
            f"repeat={res.get('max_repetition', 0.0):.3f}"
        )
        if not success and res.get("message"):
            print(f"    error: {res['message']}")

    ok = [r for r in results if r["status"] == "done" and r["video_exists"]]
    fail = [r for r in results if r not in ok]
    repeat_flag = [r for r in results if r.get("max_repetition", 0.0) >= 0.75]
    partial_scene_fail = [r for r in results if r.get("failed_scenes", 0) > 0]
    avg = sum(r["elapsed"] for r in ok) / len(ok) if ok else 0.0

    print("\n" + "=" * 72)
    print("EDGE-CASE RESULTS")
    print(f"Success:    {len(ok)}/{len(results)}")
    print(f"Failure:    {len(fail)}/{len(results)}")
    print(f"Avg time:   {avg:.1f}s")
    print(f"Repeats:    {len(repeat_flag)}")
    print(f"Partials:   {len(partial_scene_fail)}")
    return 0 if (len(ok) == len(results) and len(repeat_flag) == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
