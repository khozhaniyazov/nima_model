#!/usr/bin/env python3
"""Run 3 streaming generation jobs in a row with TTS enabled.

The reliability harness was relocated to ``scripts/reliability_streaming.py``
in commit 8052a51 (2026-05-01 cleanup) and exposes named prompt pools via
``PROMPT_POOLS`` rather than a flat ``PROMPTS`` list. This driver picks the
first three prompts from the requested pool (``edge`` by default) and runs
them sequentially with voiceover enabled.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Put the repo root first on ``sys.path`` so ``from config import OUTPUTS`` in
# ``reliability_streaming`` resolves to THIS repo, not to a like-named module
# elsewhere on the user's ``PYTHONPATH``. Then make ``scripts/`` importable so
# ``reliability_streaming`` can find its sibling ``prompt_pool``.
_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
for _path in (str(_REPO_ROOT), str(_SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from reliability_streaming import PROMPT_POOLS, run_one  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Run 3 streaming jobs with TTS")
    ap.add_argument("--host", default="http://localhost:5000", help="Backend base URL")
    ap.add_argument("--timeout", type=int, default=1200, help="Per-job timeout seconds")
    ap.add_argument(
        "--poll", type=float, default=2.0, help="Status poll interval seconds"
    )
    ap.add_argument(
        "--pool",
        default="edge",
        choices=sorted(PROMPT_POOLS.keys()),
        help="Prompt pool to draw the first three prompts from (default: edge)",
    )
    args = ap.parse_args()

    prompts = PROMPT_POOLS[args.pool][:3]
    if len(prompts) < 3:
        print(
            f"Prompt pool '{args.pool}' has only {len(prompts)} prompts; need 3."
        )
        return 1

    print("Run 3 Streaming Jobs (TTS ON)")
    print(f"Host: {args.host}  |  Pool: {args.pool}")
    print("-" * 60)

    ok = 0
    for i, prompt in enumerate(prompts):
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
