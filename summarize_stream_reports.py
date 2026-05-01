#!/usr/bin/env python3
"""Aggregate persisted streaming reports from the stream_reports directory."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

REPORT_DIR = Path(r"C:\temp\outputs\stream_reports")


def classify_signature(error_text: str) -> str:
    """Classify error text into a machine-readable signature.

    Kept in sync with algorithms.streaming.classify_render_error.
    """
    text = (error_text or "").lower()
    if "camera" in text and "frame" in text:
        return "camera_frame"
    if "interpolate" in text and "str" in text:
        return "color_string_interpolate"
    if "indexerror" in text or "list index out of range" in text:
        return "index_out_of_range"
    if "timeout" in text:
        return "timeout"
    if "syntax error" in text or "was never closed" in text:
        return "syntax_error"
    if "nameerror" in text or "is not defined" in text:
        return "name_error"
    if "attributeerror" in text or "has no attribute" in text:
        return "attribute_error"
    if "typeerror" in text:
        return "type_error"
    if "latex" in text or "emergency stop" in text or "mathtex" in text:
        return "latex_error"
    if "valueerror" in text:
        return "value_error"
    if "importerror" in text or "modulenotfounderror" in text:
        return "import_error"
    if "recursionerror" in text:
        return "recursion_error"
    if "zerodivisionerror" in text:
        return "zero_division"
    if "ffmpeg" in text:
        return "ffmpeg_error"
    if "memoryerror" in text:
        return "memory_error"
    if "keyerror" in text:
        return "key_error"
    if "cairo" in text or "pango" in text:
        return "rendering_engine_error"
    if "file not found" in text or "video file not found" in text:
        return "video_not_found"
    return "other_render"


def main() -> int:
    if not REPORT_DIR.exists():
        print(f"No reports found: {REPORT_DIR}")
        return 1

    files = sorted(REPORT_DIR.glob("*.json"))
    if not files:
        print(f"No reports found: {REPORT_DIR}")
        return 1

    total = 0
    full_success = 0
    prompts = []
    fail_counter = Counter()
    domain_stats = defaultdict(lambda: {"jobs": 0, "rendered": 0, "planned": 0})

    for fp in files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue

        total += 1
        planned = int(data.get("planned_scenes", 0) or 0)
        rendered = int(data.get("rendered_scenes", 0) or 0)
        failed = int(data.get("failed_scenes", 0) or 0)
        domain = data.get("domain") or "unknown"
        prompt = data.get("prompt") or ""
        prompts.append((rendered / max(1, planned), rendered, planned, prompt[:80]))

        domain_stats[domain]["jobs"] += 1
        domain_stats[domain]["rendered"] += rendered
        domain_stats[domain]["planned"] += planned

        if failed == 0 and rendered == planned:
            full_success += 1

        for err in data.get("errors", []):
            fail_counter[classify_signature(err.get("error", ""))] += 1

        # Also count per-scene error_type when available (new field)
        for sr in data.get("scene_results", []):
            if sr.get("status") == "failed":
                etype = sr.get("error_type") or classify_signature(sr.get("error", ""))
                fail_counter[etype] += 1

    print("Streaming Report Summary")
    print("=" * 72)
    print(f"Reports: {total}")
    print(f"Full success jobs: {full_success}/{total}")
    print()

    print("Domain stats:")
    for domain, stats in sorted(domain_stats.items()):
        ratio = stats["rendered"] / max(1, stats["planned"])
        print(
            f"  {domain:18s} jobs={stats['jobs']:3d} rendered={stats['rendered']:4d}/{stats['planned']:4d} ({ratio:.0%})"
        )

    print("\nTop error signatures:")
    for name, count in fail_counter.most_common(10):
        print(f"  {name:20s} {count}")

    print("\nWorst prompts:")
    for ratio, rendered, planned, prompt in sorted(prompts, key=lambda x: x[0])[:10]:
        print(f"  {rendered:2d}/{planned:2d} ({ratio:.0%})  {prompt}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
