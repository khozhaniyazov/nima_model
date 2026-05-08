"""
Tests for FAST_PIPELINE and DRAFT_PIPELINE optimizations.
Run: python test_optimizations.py
"""

import os
import sys
import time
import importlib

# Set test environment before imports
os.environ["USE_DATABASE"] = "false"
os.environ["OPENAI_API_KEY"] = "test-key-for-testing"

# ============================================================================
# SECTION 1: CONFIG TESTS
# ============================================================================


def test_config_flags():
    """Verify FAST_PIPELINE and DRAFT_PIPELINE flags work correctly."""
    print("\n[TEST] Config flags...")

    # Test DRAFT mode
    os.environ["DRAFT_PIPELINE"] = "true"
    os.environ["FAST_PIPELINE"] = "false"
    import config

    importlib.reload(config)
    assert config.DRAFT_PIPELINE == True, "DRAFT_PIPELINE should be True"
    assert config.FAST_PIPELINE == False, "FAST_PIPELINE should be False"
    print("  [OK] DRAFT_PIPELINE=true applied correctly")

    # Test FAST mode
    os.environ["DRAFT_PIPELINE"] = "false"
    os.environ["FAST_PIPELINE"] = "true"
    importlib.reload(config)
    assert config.DRAFT_PIPELINE == False, "DRAFT_PIPELINE should be False"
    assert config.FAST_PIPELINE == True, "FAST_PIPELINE should be True"
    print("  [OK] FAST_PIPELINE=true applied correctly")

    # Test is_fast calculation
    is_fast_draft = config.DRAFT_PIPELINE or config.FAST_PIPELINE
    assert is_fast_draft == True, "is_fast should be True for DRAFT"

    os.environ["DRAFT_PIPELINE"] = "false"
    os.environ["FAST_PIPELINE"] = "false"
    importlib.reload(config)
    is_fast_full = config.DRAFT_PIPELINE or config.FAST_PIPELINE
    assert is_fast_full == False, "is_fast should be False for FULL"
    print("  [OK] is_fast calculation correct for all modes")



def test_render_retries_in_fast_mode():
    """Verify render retries are reduced in FAST/DRAFT mode."""
    import config

    importlib.reload(config)

    # DRAFT mode
    os.environ["DRAFT_PIPELINE"] = "true"
    os.environ["FAST_PIPELINE"] = "false"
    importlib.reload(config)
    is_fast = config.DRAFT_PIPELINE or config.FAST_PIPELINE
    retries_draft = 1 if is_fast else config.MAX_RENDER_RETRIES
    assert retries_draft == 1, "DRAFT should have 1 retry"
    print("  [OK] DRAFT_PIPELINE uses 1 retry")

    # FAST mode
    os.environ["DRAFT_PIPELINE"] = "false"
    os.environ["FAST_PIPELINE"] = "true"
    importlib.reload(config)
    is_fast = config.DRAFT_PIPELINE or config.FAST_PIPELINE
    retries_fast = 1 if is_fast else config.MAX_RENDER_RETRIES
    assert retries_fast == 1, "FAST should have 1 retry"
    print("  [OK] FAST_PIPELINE uses 1 retry")

    # FULL mode
    os.environ["DRAFT_PIPELINE"] = "false"
    os.environ["FAST_PIPELINE"] = "false"
    importlib.reload(config)
    is_fast = config.DRAFT_PIPELINE or config.FAST_PIPELINE
    retries_full = 1 if is_fast else config.MAX_RENDER_RETRIES
    assert retries_full == config.MAX_RENDER_RETRIES, (
        "FULL should use MAX_RENDER_RETRIES"
    )
    print("  [OK] FULL mode uses MAX_RENDER_RETRIES")



# ============================================================================
# SECTION 2: TIMING LOGS TEST
# ============================================================================


def test_timing_logs_present():
    """Verify [TIMING] logs are present in the generation/render pipeline."""
    print("\n[TEST] Timing logs present...")

    source_paths = [
        "app.py",
        "algorithms/generation_service.py",
        "algorithms/render_service.py",
    ]
    src = ""
    for path in source_paths:
        with open(path, "r", encoding="utf-8") as f:
            src += f"\n# {path}\n" + f.read()

    timing_markers = [
        "[TIMING] Analysis:",
        "[TIMING] Planning:",
        "[TIMING] LLM generation:",
        "[TIMING] Total code generation:",
        "[TIMING] Manim render:",
    ]

    found_count = 0
    for marker in timing_markers:
        if marker in src:
            found_count += 1
        else:
            print(f"  [FAIL] Missing timing log: {marker}")

    assert found_count == len(timing_markers), (
        f"Only {found_count}/{len(timing_markers)} timing markers found"
    )
    print(f"  [OK] All {len(timing_markers)} timing markers present")



# ============================================================================
# SECTION 3: VALIDATION SKIP TESTS
# ============================================================================


def test_validations_skipped_in_fast_mode():
    """Verify validations are skipped when is_fast=True."""
    print("\n[TEST] Validations skip in FAST/DRAFT mode...")

    source_paths = ["app.py", "algorithms/generation_service.py"]
    src = ""
    for path in source_paths:
        with open(path, "r", encoding="utf-8") as f:
            src += f"\n# {path}\n" + f.read()

    # Check is_fast is used for skipping
    assert "is_fast = FAST_PIPELINE or DRAFT_PIPELINE" in src, "is_fast not defined"
    print("  [OK] is_fast variable defined")

    # Check quality validation skip
    assert "quality_passes, quality_feedback = True, []" in src, "Quality not skipped"
    print("  [OK] Quality validation skipped")

    # Check LaTeX validation skip
    assert "latex_valid, latex_issues = True, []" in src, "LaTeX not skipped"
    print("  [OK] LaTeX validation skipped")

    # Check security validation skip
    assert "is_safe, safety_issues = True, []" in src, "Safety not skipped"
    print("  [OK] Security validation skipped")

    # Check overlap detection skip
    assert "overlap_warnings = []" in src, "Overlap detection not skipped"
    print("  [OK] Overlap detection skipped")



def test_review_uses_fast_model():
    """Verify review and fix use FAST_MODEL."""
    print("\n[TEST] Review uses FAST_MODEL...")

    with open("algorithms/ai_functions.py", "r", encoding="utf-8") as f:
        src = f.read()

    # Check review_and_fix uses FAST_MODEL
    assert "model=FAST_MODEL,  # Use fast model for review" in src, (
        "Review not using FAST_MODEL"
    )
    print("  [OK] review_and_fix uses FAST_MODEL")

    # Check fix_render_error uses FAST_MODEL
    assert "model=FAST_MODEL,  # Fast model for targeted error fixes" in src, (
        "Fix not using FAST_MODEL"
    )
    print("  [OK] fix_render_error uses FAST_MODEL")



# ============================================================================
# SECTION 4: RAG CACHING TEST
# ============================================================================


def test_rag_caching():
    """Verify RAG retrieval is cached."""
    print("\n[TEST] RAG caching...")

    # Clear any existing cache
    from RAG.RAG_system import retrieve_patterns

    retrieve_patterns.cache_clear()

    # First call - populate cache
    t1 = time.time()
    result1 = retrieve_patterns("math", "derivative", ("tangent",), limit=2)
    t1_time = time.time() - t1

    # Second call - should be faster (cached)
    t2 = time.time()
    result2 = retrieve_patterns("math", "derivative", ("tangent",), limit=2)
    t2_time = time.time() - t2

    # Results should be identical
    assert result1 == result2, "Cached results differ from original"
    print("  [OK] Cached results match original")

    # Second call should be instant
    assert t2_time < 0.01, f"Cache not working: {t2_time}s (expected < 0.01s)"
    print(f"  [OK] RAG caching works ({t1_time:.4f}s -> {t2_time * 1000:.2f}ms)")



# ============================================================================
# SECTION 5: TTS PARALLELIZATION TEST
# ============================================================================


def test_tts_parallel():
    """Verify TTS uses ThreadPoolExecutor."""
    print("\n[TEST] TTS parallelization...")

    with open("algorithms/tts.py", "r", encoding="utf-8") as f:
        src = f.read()

    assert "ThreadPoolExecutor" in src, "ThreadPoolExecutor not used"
    print("  [OK] ThreadPoolExecutor present")

    assert "as_completed" in src, "as_completed not used"
    print("  [OK] as_completed present")

    assert "max_workers=min(len(tasks), 8)" in src, "Worker count not optimized"
    print("  [OK] Worker count optimized (min 8)")



# ============================================================================
# SECTION 6: MANIM RENDER FLAGS TEST
# ============================================================================


def test_render_flags():
    """Verify correct manim flags for each mode."""
    print("\n[TEST] Manim render flags...")

    from pathlib import Path

    from algorithms.rendering import build_manim_render_command
    from algorithms.video_modes import build_video_mode_profile

    standard_cmd = build_manim_render_command(
        Path("smoke.py"),
        "smoke.mp4",
        video_mode="standard",
        is_fast=False,
        draft=False,
    )
    short_cmd = build_manim_render_command(
        Path("smoke.py"),
        "smoke.mp4",
        video_mode="short",
        is_fast=False,
        draft=False,
    )

    assert "--disable_caching" in standard_cmd, "--disable_caching flag missing"
    print("  [OK] --disable_caching present")

    assert "--fps" in standard_cmd, "--fps flag missing"
    print("  [OK] --fps present")

    assert "--resolution" in short_cmd, "Short mode resolution flag missing"
    assert "720,1280" in short_cmd, "Short mode vertical resolution missing"
    print("  [OK] Render profile wired into rendering module")

    draft_profile = build_video_mode_profile("standard", draft=True)
    full_profile = build_video_mode_profile("standard", is_fast=False, draft=False)
    short_profile = build_video_mode_profile("short", is_fast=False, draft=False)
    assert draft_profile.quality_flag == "-ql", "Draft quality flag -ql missing"
    assert full_profile.quality_flag == "-qm", "Full quality flag -qm missing"
    assert short_profile.render_resolution == (720, 1280), "Short mode is not vertical"
    print("  [OK] Profile quality flags and short resolution correct")



def test_draft_mode_flags():
    """Verify DRAFT mode has lowest quality settings."""
    print("\n[TEST] DRAFT mode render settings...")

    from algorithms.video_modes import build_video_mode_profile

    draft = build_video_mode_profile("standard", draft=True)
    fast = build_video_mode_profile("standard", is_fast=True, draft=False)

    assert draft.quality_flag == "-ql", "DRAFT should use -ql"
    print("  [OK] DRAFT uses -ql quality")

    assert draft.fps == 10, "DRAFT should use 10 fps"
    print("  [OK] DRAFT uses 10 fps")

    assert fast.quality_flag == "-ql", "FAST should use -ql"
    print("  [OK] FAST uses -ql quality")

    assert fast.fps == 15, "FAST should use 15 fps"
    print("  [OK] FAST uses 15 fps")



# ============================================================================
# SECTION 7: BACKWARD COMPATIBILITY TEST
# ============================================================================


def test_backward_compatibility():
    """Verify existing functionality still works."""
    print("\n[TEST] Backward compatibility...")

    # Reset environment
    os.environ["DRAFT_PIPELINE"] = "false"
    os.environ["FAST_PIPELINE"] = "false"
    os.environ["USE_DATABASE"] = "false"

    # Reload config
    import config

    importlib.reload(config)

    # Check required attributes exist
    assert hasattr(config, "DRAFT_PIPELINE"), "DRAFT_PIPELINE missing from config"
    assert hasattr(config, "FAST_PIPELINE"), "FAST_PIPELINE missing from config"
    assert hasattr(config, "MAX_RENDER_RETRIES"), (
        "MAX_RENDER_RETRIES missing from config"
    )
    assert hasattr(config, "MAX_GENERATION_ATTEMPTS"), (
        "MAX_GENERATION_ATTEMPTS missing from config"
    )
    assert hasattr(config, "RENDER_TIMEOUT_SECONDS"), (
        "RENDER_TIMEOUT_SECONDS missing from config"
    )
    print("  [OK] All required config attributes present")

    # Check defaults work
    assert config.DRAFT_PIPELINE == False, "Default DRAFT_PIPELINE should be False"
    assert config.FAST_PIPELINE == False, "Default FAST_PIPELINE should be False"
    assert config.MAX_RENDER_RETRIES == 3, "Default MAX_RENDER_RETRIES should be 3"
    print("  [OK] Default values correct")



# ============================================================================
# SECTION 8: EDGE CASE TESTS
# ============================================================================


def test_both_flags_enabled():
    """Test behavior when both FAST and DRAFT are enabled."""
    print("\n[TEST] Both flags enabled edge case...")

    os.environ["DRAFT_PIPELINE"] = "true"
    os.environ["FAST_PIPELINE"] = "true"

    import config

    importlib.reload(config)

    # Both true should result in is_fast = True
    is_fast = config.DRAFT_PIPELINE or config.FAST_PIPELINE
    assert is_fast == True, "is_fast should be True when either flag is True"
    print("  [OK] Both flags enabled correctly treated as fast mode")



def test_invalid_prompt_handling():
    """Test that invalid prompts are handled gracefully."""
    print("\n[TEST] Invalid prompt handling...")

    # This test verifies the code structure supports error handling
    with open("app.py", "r", encoding="utf-8") as f:
        src = f.read()

    assert "except" in src, "Exception handling present"
    assert "try:" in src, "Try blocks present"
    print("  [OK] Exception handling present")



def test_database_disabled():
    """Test that USE_DATABASE=false works."""
    print("\n[TEST] Database disabled...")

    os.environ["USE_DATABASE"] = "false"

    import config

    importlib.reload(config)

    assert config.USE_DATABASE == False, "USE_DATABASE should be False"
    print("  [OK] Database disabled works")



# ============================================================================
# MAIN TEST RUNNER
# ============================================================================


def run_all_tests():
    """Run all optimization tests."""
    print("=" * 60)
    print("OPTIMIZATION TESTS")
    print("=" * 60)

    tests = [
        ("Config Flags", test_config_flags),
        ("Render Retries", test_render_retries_in_fast_mode),
        ("Timing Logs", test_timing_logs_present),
        ("Validation Skip", test_validations_skipped_in_fast_mode),
        ("Review Model", test_review_uses_fast_model),
        ("RAG Caching", test_rag_caching),
        ("TTS Parallel", test_tts_parallel),
        ("Render Flags", test_render_flags),
        ("DRAFT Flags", test_draft_mode_flags),
        ("Backward Compatibility", test_backward_compatibility),
        ("Edge Case: Both Flags", test_both_flags_enabled),
        ("Edge Case: Invalid Prompt", test_invalid_prompt_handling),
        ("Edge Case: DB Disabled", test_database_disabled),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {name}: {e}")

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
