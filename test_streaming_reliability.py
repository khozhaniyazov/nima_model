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
import time
import urllib.error
import urllib.request
from pathlib import Path

from config import OUTPUTS


PROMPTS = [
    "Explain what a subgroup is using the even integers inside all integers.",
    "Explain adjacency matrices using a 4-node graph example.",
    "Explain partial derivatives using temperature T(x,y) on a metal plate.",
    "Explain chain rule by differentiating (3x^2 + 1)^5.",
    "Explain eigenvalues and eigenvectors using stretching in one direction.",
    "Explain uniform continuity using f(x)=x^2 on [0,1].",
    "Explain Laplace transform for solving y' + 3y = 2.",
    "Explain probability distribution with a loaded die example.",
    "Explain integral as area under y=2x from x=0 to x=3.",
    "Explain Eulerian vs Hamiltonian paths with a graph example.",
    "Explain kernel of a linear transformation that squashes to a line.",
    "Explain Markov transition matrix with 3 mood states.",
]


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


def video_exists(video_file: str) -> bool:
    if not video_file:
        return False
    return (OUTPUTS / video_file).exists()


def run_one(
    host: str, prompt: str, timeout_s: int, poll_interval: float, voiceover: bool
) -> dict:
    t0 = time.time()
    payload = {
        "prompt": prompt,
        "voiceover": bool(voiceover),
        "streaming": True,
    }
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
            return {
                "job_id": job_id,
                "status": status,
                "message": last.get("message", ""),
                "elapsed": time.time() - t0,
                "video_file": vf,
                "video_exists": video_exists(vf),
            }

        time.sleep(poll_interval)

    return {
        "job_id": job_id,
        "status": "timeout",
        "message": f"No terminal status within {timeout_s}s",
        "elapsed": time.time() - t0,
        "video_file": last.get("video_file", "") if isinstance(last, dict) else "",
        "video_exists": False,
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
    args = ap.parse_args()

    print("Streaming Reliability Harness")
    print(f"Host: {args.host}")
    print(f"Jobs: {args.count}")
    print(f"Timeout/job: {args.timeout}s")
    print(f"Voiceover: {args.voiceover}")
    print("-" * 72)

    results = []
    for i in range(args.count):
        prompt = PROMPTS[i % len(PROMPTS)]
        print(f"[{i + 1}/{args.count}] {prompt}")
        try:
            res = run_one(args.host, prompt, args.timeout, args.poll, args.voiceover)
        except Exception as e:  # noqa: BLE001
            res = {
                "job_id": None,
                "status": "error",
                "message": f"Unhandled: {e}",
                "elapsed": 0.0,
                "video_file": "",
                "video_exists": False,
            }

        results.append(res)
        print(
            f"  -> status={res['status']} job={res.get('job_id')} "
            f"time={res['elapsed']:.1f}s video={res.get('video_file', '')} exists={res['video_exists']}"
        )
        if res.get("message"):
            print(f"     message: {res['message']}")

    ok = [r for r in results if r["status"] == "done" and r["video_exists"]]
    fail = [r for r in results if r not in ok]
    avg = sum(r["elapsed"] for r in ok) / len(ok) if ok else 0.0

    print("\n" + "=" * 72)
    print("RESULTS")
    print(f"Success: {len(ok)}/{len(results)}")
    print(f"Failure: {len(fail)}/{len(results)}")
    print(f"Avg successful runtime: {avg:.1f}s")

    if fail:
        print("\nFailures:")
        for idx, r in enumerate(fail, 1):
            print(
                f"  {idx}. job={r.get('job_id')} status={r['status']} "
                f"exists={r['video_exists']} msg={r.get('message', '')}"
            )

    # Exit non-zero if not 100% reliable
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
