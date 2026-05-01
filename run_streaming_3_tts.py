#!/usr/bin/env python3
"""Run 3 streaming generation jobs in a row with TTS enabled."""

from __future__ import annotations

import argparse
from test_streaming_reliability import PROMPTS, run_one


def main() -> int:
    ap = argparse.ArgumentParser(description="Run 3 streaming jobs with TTS")
    ap.add_argument("--host", default="http://localhost:5000", help="Backend base URL")
    ap.add_argument("--timeout", type=int, default=1200, help="Per-job timeout seconds")
    ap.add_argument(
        "--poll", type=float, default=2.0, help="Status poll interval seconds"
    )
    args = ap.parse_args()

    print("Run 3 Streaming Jobs (TTS ON)")
    print(f"Host: {args.host}")
    print("-" * 60)

    ok = 0
    for i in range(3):
        prompt = PROMPTS[i]
        print(f"[{i + 1}/3] {prompt}")
        res = run_one(args.host, prompt, args.timeout, args.poll, voiceover=True)
        success = res["status"] == "done" and res["video_exists"]
        if success:
            ok += 1
        print(
            f"  -> status={res['status']} job={res.get('job_id')} "
            f"time={res['elapsed']:.1f}s video={res.get('video_file', '')} exists={res['video_exists']}"
        )
        if res.get("message"):
            print(f"     message: {res['message']}")

    print("\n" + "=" * 60)
    print(f"Done: {ok}/3 successful")
    return 0 if ok == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
