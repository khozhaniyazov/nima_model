"""Cache key regression checks."""

import tempfile
from pathlib import Path

import cache as cache_module
from algorithms.media_tools import VideoValidationResult
from cache import PromptCache, RenderCache


def test_render_cache_keys_include_render_variant():
    original_enabled = cache_module.RENDER_CACHE_ENABLED
    original_validate = cache_module.validate_video_file
    cache_module.RENDER_CACHE_ENABLED = True
    cache_module.validate_video_file = lambda path: VideoValidationResult(
        ok=True, size_bytes=2048, duration_seconds=1.0
    )
    with tempfile.TemporaryDirectory() as tmp:
        try:
            cache = RenderCache(Path(tmp))
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"video")
            code = "from manim import *\n"

            standard = {"mode": "standard", "fps": 30, "render_resolution": None}
            short = {"mode": "short", "fps": 10, "render_resolution": [720, 1280]}

            standard_path = cache.store(code, video, variant=standard)

            assert cache.check(code, variant=standard) == standard_path
            assert cache.check(code, variant=short) is None
            assert cache.get_code_hash(code, standard) != cache.get_code_hash(code, short)
        finally:
            cache_module.RENDER_CACHE_ENABLED = original_enabled
            cache_module.validate_video_file = original_validate
        print("[OK] cache - render keys include mode/fps/resolution variant")


def test_render_cache_rejects_invalid_video_artifacts():
    original_enabled = cache_module.RENDER_CACHE_ENABLED
    cache_module.RENDER_CACHE_ENABLED = True
    with tempfile.TemporaryDirectory() as tmp:
        try:
            cache = RenderCache(Path(tmp))
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"x")

            stored = cache.store("code", video)

            assert stored == video
            assert list(Path(tmp).glob("*.mp4")) == [video]
            assert cache.check("code") is None
        finally:
            cache_module.RENDER_CACHE_ENABLED = original_enabled
    print("[OK] cache - invalid render artifacts are not cached")


def test_prompt_cache_keys_include_video_mode_extra():
    original_enabled = cache_module.PROMPT_CACHE_ENABLED
    cache_module.PROMPT_CACHE_ENABLED = True
    with tempfile.TemporaryDirectory() as tmp:
        try:
            cache = PromptCache(Path(tmp))
            prompt = "Explain eigenvectors"
            short_extra = {
                "video_mode": "short",
                "target_duration": 58,
                "aspect": "9:16",
            }
            course_extra = {
                "video_mode": "course",
                "target_duration": 900,
                "aspect": "16:9",
            }

            cache.store(
                prompt,
                {"code": "short-code"},
                domain="math",
                voiceover=False,
                extra=short_extra,
            )

            assert (
                cache.check(
                    prompt, domain="math", voiceover=False, extra=short_extra
                )["code"]
                == "short-code"
            )
            assert (
                cache.check(prompt, domain="math", voiceover=False, extra=course_extra)
                is None
            )
        finally:
            cache_module.PROMPT_CACHE_ENABLED = original_enabled
        print("[OK] cache - prompt keys include video mode context")


def test_cache_disabled_flags_skip_writes():
    original_render_enabled = cache_module.RENDER_CACHE_ENABLED
    original_prompt_enabled = cache_module.PROMPT_CACHE_ENABLED
    cache_module.RENDER_CACHE_ENABLED = False
    cache_module.PROMPT_CACHE_ENABLED = False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            video = cache_dir / "source.mp4"
            video.write_bytes(b"video")

            render_cache = RenderCache(cache_dir / "renders")
            prompt_cache = PromptCache(cache_dir / "prompts")

            assert render_cache.store("code", video) == video
            assert list((cache_dir / "renders").glob("*.mp4")) == []
            assert prompt_cache.store("prompt", {"code": "x"}) is None
            assert list((cache_dir / "prompts").glob("*.meta")) == []
    finally:
        cache_module.RENDER_CACHE_ENABLED = original_render_enabled
        cache_module.PROMPT_CACHE_ENABLED = original_prompt_enabled
    print("[OK] cache - disabled flags skip reads and writes")


if __name__ == "__main__":
    test_render_cache_keys_include_render_variant()
    test_render_cache_rejects_invalid_video_artifacts()
    test_prompt_cache_keys_include_video_mode_extra()
    test_cache_disabled_flags_skip_writes()
    print("\nALL CACHE CHECKS PASSED")
