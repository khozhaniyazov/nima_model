"""
Performance benchmark for optimization changes.
Run: python benchmark.py

This script measures:
1. Import/setup time for each pipeline mode
2. RAG retrieval time (with and without cache)
3. Validation skip effectiveness
4. Render flag configuration
"""

import os
import sys
import time
import json
import importlib
from datetime import datetime
from pathlib import Path

# Set base environment
os.environ["USE_DATABASE"] = "false"
os.environ["OPENAI_API_KEY"] = "test-key-for-benchmark"

# ============================================================================
# CONFIGURATION
# ============================================================================

MODES = {
    "DRAFT": {
        "DRAFT_PIPELINE": "true",
        "FAST_PIPELINE": "false",
        "description": "Ultra-fast preview (lowest quality, 10fps)",
    },
    "FAST": {
        "DRAFT_PIPELINE": "false",
        "FAST_PIPELINE": "true",
        "description": "Fast mode (low quality, 15fps)",
    },
    "FULL": {
        "DRAFT_PIPELINE": "false",
        "FAST_PIPELINE": "false",
        "description": "Full quality (low quality, 30fps)",
    },
}

TEST_PROMPTS = [
    "Draw a blue circle",
    "Show derivative of x squared",
    "Explain matrix multiplication",
]

# ============================================================================
# BENCHMARK FUNCTIONS
# ============================================================================


def benchmark_import_time(mode_name, env_vars):
    """Benchmark import and setup time for a given mode."""
    # Clear modules
    for mod in list(sys.modules.keys()):
        if mod.startswith(("app", "config", "algorithms", "RAG")):
            del sys.modules[mod]

    # Set environment
    for k, v in env_vars.items():
        os.environ[k] = v

    start = time.perf_counter()
    import config

    importlib.reload(config)
    import_time = time.perf_counter() - start

    return {
        "import_time_ms": import_time * 1000,
    }


def benchmark_rag_caching():
    """Benchmark RAG retrieval with and without cache."""
    # Clear cache
    from RAG.RAG_system import retrieve_patterns

    retrieve_patterns.cache_clear()

    # First call (cold) — discard the result; we only care about wall time.
    start = time.perf_counter()
    retrieve_patterns("math", "derivative", ("tangent", "secant"), limit=3)
    cold_time = time.perf_counter() - start

    # Second call (cached) — same query so the lru_cache should hit.
    start = time.perf_counter()
    retrieve_patterns("math", "derivative", ("tangent", "secant"), limit=3)
    hot_time = time.perf_counter() - start

    return {
        "cold_time_ms": cold_time * 1000,
        "hot_time_ms": hot_time * 1000,
        "speedup": cold_time / hot_time if hot_time > 0 else float("inf"),
    }


def benchmark_validation_skip():
    """Check which validations are skipped in each mode."""
    results = {}

    for mode_name, env_vars in MODES.items():
        # Set environment
        for k, v in env_vars.items():
            os.environ[k] = v

        # Reload config
        for mod in list(sys.modules.keys()):
            if mod == "config":
                del sys.modules[mod]
        import config

        importlib.reload(config)

        is_fast = config.DRAFT_PIPELINE or config.FAST_PIPELINE

        results[mode_name] = {
            "is_fast": is_fast,
            "expected_retries": 1 if is_fast else config.MAX_RENDER_RETRIES,
        }

    return results


def analyze_render_flags():
    """Analyze render flags from the same profile builder used by production."""
    flags = {}

    for mode_name, env_vars in MODES.items():
        for k, v in env_vars.items():
            os.environ[k] = v

        for mod in list(sys.modules.keys()):
            if mod in {"config", "algorithms.video_modes", "algorithms.rendering"}:
                del sys.modules[mod]

        from algorithms.rendering import build_manim_render_command
        from algorithms.video_modes import build_video_mode_profile

        profile = build_video_mode_profile("standard", is_fast=None, draft=None)
        short_profile = build_video_mode_profile("short", is_fast=None, draft=None)
        cmd = build_manim_render_command(
            Path("benchmark_smoke.py"),
            "benchmark_smoke.mp4",
            video_mode="standard",
            draft=None,
        )

        flags[mode_name] = {
            "quality": profile.quality_flag,
            "fps": profile.fps,
            "retries": profile.render_retries,
            "disable_caching": "--disable_caching" in cmd,
            "short_resolution": short_profile.render_resolution,
        }

    return flags


def benchmark_tts_parallelization():
    """Check TTS parallelization settings."""
    with open("algorithms/tts.py", "r", encoding="utf-8") as f:
        src = f.read()

    result = {
        "has_threadpool": "ThreadPoolExecutor" in src,
        "max_workers": None,
    }

    # Extract max_workers
    if "max_workers=min(len(tasks), 8)" in src:
        result["max_workers"] = "min(tasks, 8)"

    return result


def run_performance_comparison():
    """Run actual performance comparison between modes."""
    print("\n" + "=" * 60)
    print("PERFORMANCE COMPARISON")
    print("=" * 60)

    results = {}

    for mode_name, env_vars in MODES.items():
        print(f"\n[MODE: {mode_name}]")
        print(f"  Description: {MODES[mode_name]['description']}")

        # Benchmark import time
        import_result = benchmark_import_time(mode_name, env_vars)
        print(f"  Import time: {import_result['import_time_ms']:.2f}ms")

        results[mode_name] = import_result

    return results


def generate_report(
    benchmark_results, rag_results, validation_results, flag_results, tts_results
):
    """Generate a comprehensive benchmark report."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "benchmark_results": benchmark_results,
        "rag_caching": rag_results,
        "validation_config": validation_results,
        "render_flags": flag_results,
        "tts_parallelization": tts_results,
    }

    # Save JSON report
    with open("benchmark_results.json", "w") as f:
        json.dump(report, f, indent=2)

    return report


def print_summary(report):
    """Print a human-readable summary."""
    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)

    # Import times
    print("\n[Import Times]")
    for mode, data in report["benchmark_results"].items():
        print(f"  {mode}: {data['import_time_ms']:.2f}ms")

    # RAG caching
    print("\n[RAG Caching]")
    rag = report["rag_caching"]
    print(f"  Cold (first call): {rag['cold_time_ms']:.2f}ms")
    print(f"  Hot (cached): {rag['hot_time_ms']:.4f}ms")
    print(f"  Speedup: {rag['speedup']:.1f}x")

    # Validation config
    print("\n[Validation Configuration]")
    for mode, data in report["validation_config"].items():
        fast_status = "FAST" if data["is_fast"] else "FULL"
        print(f"  {mode}: {fast_status}, retries={data['expected_retries']}")

    # Render flags
    print("\n[Render Flags]")
    for mode, flags in report["render_flags"].items():
        print(
            f"  {mode}: quality={flags['quality']}, fps={flags['fps']}, "
            f"retries={flags['retries']}, "
            f"disable_caching={flags['disable_caching']}, "
            f"short_resolution={flags['short_resolution']}"
        )

    # TTS
    print("\n[TTS Parallelization]")
    tts = report["tts_parallelization"]
    print(f"  ThreadPoolExecutor: {tts['has_threadpool']}")
    print(f"  Max workers: {tts['max_workers']}")

    # Performance recommendations
    print("\n[Recommendations]")
    print("  - Use DRAFT_PIPELINE=true for fastest preview")
    print("  - Use FAST_PIPELINE=true for quick iterations")
    print("  - Use FULL mode for final renders")

    print("\n" + "=" * 60)


def run_full_benchmark():
    """Run the complete benchmark suite."""
    print("=" * 60)
    print("NIMA PERFORMANCE BENCHMARK")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Run benchmarks
    benchmark_results = run_performance_comparison()
    rag_results = benchmark_rag_caching()
    validation_results = benchmark_validation_skip()
    flag_results = analyze_render_flags()
    tts_results = benchmark_tts_parallelization()

    # Generate report
    report = generate_report(
        benchmark_results, rag_results, validation_results, flag_results, tts_results
    )

    # Print summary
    print_summary(report)

    print("\n[Benchmark complete. Results saved to benchmark_results.json]")

    return report


if __name__ == "__main__":
    run_full_benchmark()
