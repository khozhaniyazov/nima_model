"""
TTS module for NIMA voiceover pipeline.
Generates narration audio segments using edge-tts (Microsoft Edge TTS),
measures durations, and merges audio with rendered Manim video via ffmpeg.
"""

import os
import subprocess
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

load_dotenv()

# Default voice for edge-tts (Microsoft neural voices)
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "en-US-GuyNeural")


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIO GENERATION (edge-tts)
# ═══════════════════════════════════════════════════════════════════════════════


def generate_segment_audio(text: str, output_path: str, voice: str = None) -> float:
    """
    Generate a single TTS audio segment using edge-tts.
    Returns the duration in seconds.
    """
    voice = voice or EDGE_TTS_VOICE
    print(f'[TTS] Generating: "{text[:60]}..." → {Path(output_path).name}')

    import edge_tts

    async def _generate():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)

    # Run async edge-tts in sync context
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in async context — run in new thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(_generate())).result(timeout=30)
    else:
        asyncio.run(_generate())

    duration = _get_audio_duration(output_path)
    print(f"[TTS] [OK] {Path(output_path).name}: {duration:.2f}s")
    return duration


def _get_audio_duration(path: str) -> float:
    """Get audio duration using ffprobe (comes with ffmpeg)."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        # Fallback: estimate from file size (~16kbps for speech mp3)
        size = os.path.getsize(path)
        return size / 2000.0  # rough estimate


# ═══════════════════════════════════════════════════════════════════════════════
# VOICEOVER PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════


def _generate_single_segment(args: tuple) -> tuple:
    """Worker function for parallel TTS generation."""
    seg_id, text, output_path, voice = args
    try:
        duration = generate_segment_audio(text, output_path, voice=voice)
        return seg_id, {"path": output_path, "duration": duration, "error": None}
    except Exception as e:
        print(f"[TTS] [ERR] {seg_id}: {e}")
        return seg_id, {"path": None, "duration": 5.0, "error": str(e)}


def generate_voiceover(
    segments: List[dict],
    output_dir: str,
    voice: str = None,
) -> Dict[str, dict]:
    """
    Generate TTS audio for all narration segments (parallelized).

    Args:
        segments: list of {"id": "scene_1", "narration": "text..."}
        output_dir: directory to save audio files
        voice: override voice preset

    Returns:
        dict mapping segment_id → {"path": str, "duration": float}
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    results = {}

    # Prepare tasks for parallel execution
    tasks = []
    for seg in segments:
        seg_id = seg["id"]
        text = seg.get("narration", "").strip()
        if not text:
            print(f"[TTS] [SKIP] {seg_id}: no narration text")
            results[seg_id] = {
                "path": None,
                "duration": seg.get("estimated_duration", 5.0),
            }
            continue

        audio_path = str(Path(output_dir) / f"{seg_id}.mp3")
        tasks.append((seg_id, text, audio_path, voice or TTS_VOICE))

    # Generate all audio segments in parallel
    if tasks:
        with ThreadPoolExecutor(max_workers=min(len(tasks), 8)) as executor:
            futures = {
                executor.submit(_generate_single_segment, task): task[0]
                for task in tasks
            }
            for future in as_completed(futures):
                seg_id, result = future.result()
                results[seg_id] = result

    total_duration = sum(r["duration"] for r in results.values())
    print(f"[TTS] [OK] All segments generated — total narration: {total_duration:.1f}s")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIO + VIDEO MERGE
# ═══════════════════════════════════════════════════════════════════════════════


def merge_audio_video(
    video_path: str,
    audio_segments: Dict[str, dict],
    segment_order: List[str],
    output_path: str,
) -> str:
    """
    Concatenate audio segments and merge with the silent Manim video.

    Args:
        video_path: path to the rendered .mp4 (silent)
        audio_segments: dict from generate_voiceover()
        segment_order: ordered list of segment IDs
        output_path: where to save the final narrated video

    Returns:
        path to the merged video
    """
    output_dir = str(Path(output_path).parent)

    # Collect audio files in order
    audio_files = []
    for seg_id in segment_order:
        seg = audio_segments.get(seg_id, {})
        if seg.get("path") and Path(seg["path"]).exists():
            audio_files.append(seg["path"])

    if not audio_files:
        print("[MERGE] [WARN] No audio segments — returning original video")
        return video_path

    # Concatenate all audio segments into one narration file
    narration_path = str(Path(output_dir) / "narration_combined.mp3")

    if len(audio_files) == 1:
        narration_path = audio_files[0]
    else:
        # Create ffmpeg concat list
        concat_list = str(Path(output_dir) / "concat_list.txt")
        with open(concat_list, "w") as f:
            for ap in audio_files:
                f.write(f"file '{ap}'\n")

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list,
                "-c",
                "copy",
                narration_path,
            ],
            capture_output=True,
            timeout=60,
        )

    # Merge narration with video
    print(f"[MERGE] Merging audio + video → {Path(output_path).name}")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-i",
            narration_path,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            output_path,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode == 0 and Path(output_path).exists():
        print(f"[MERGE] [OK] Narrated video: {output_path}")
        return output_path
    else:
        print(f"[MERGE] [ERR] ffmpeg failed: {result.stderr[:300]}")
        return video_path  # fall back to silent video
