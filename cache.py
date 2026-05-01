"""
Caching module for NIMA performance optimization.

Provides:
- RenderCache: Caches rendered videos by code hash
- PromptCache: Caches AI generation responses by prompt hash
"""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Optional

from algorithms.media_tools import validate_video_file

try:
    from config import OUTPUTS, RENDER_CACHE_ENABLED, PROMPT_CACHE_ENABLED
except ImportError:
    OUTPUTS = Path("C:/temp/outputs")
    RENDER_CACHE_ENABLED = True
    PROMPT_CACHE_ENABLED = True


class RenderCache:
    """Cache for rendered videos by code hash."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or OUTPUTS / ".cache" / "renders"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_code_hash(self, code: str, variant: dict | None = None) -> str:
        """Get hash for code."""
        data = {"code": code}
        if variant:
            data["variant"] = variant
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[
            :16
        ]

    def check(self, code: str, variant: dict | None = None) -> Optional[Path]:
        """Check if cached render exists. Returns path if hit, None if miss."""
        if not RENDER_CACHE_ENABLED:
            return None
        h = self.get_code_hash(code, variant)
        cached = self.cache_dir / f"{h}.mp4"
        if not cached.exists():
            return None
        validation = validate_video_file(cached)
        if not validation.ok:
            try:
                cached.unlink()
            except OSError:
                pass
            return None
        return cached

    def store(self, code: str, video_path: Path, variant: dict | None = None) -> Path:
        """Store video in cache."""
        if not RENDER_CACHE_ENABLED:
            return video_path
        validation = validate_video_file(video_path)
        if not validation.ok:
            return video_path
        h = self.get_code_hash(code, variant)
        cached = self.cache_dir / f"{h}.mp4"
        if video_path.resolve() != cached.resolve():
            shutil.copy2(video_path, cached)
        return cached

    def invalidate(self, code: str, variant: dict | None = None):
        """Remove cached render."""
        h = self.get_code_hash(code, variant)
        cached = self.cache_dir / f"{h}.mp4"
        if cached.exists():
            cached.unlink()

    def clear(self):
        """Clear entire render cache."""
        for f in self.cache_dir.glob("*.mp4"):
            f.unlink()


class PromptCache:
    """Cache for AI generation responses by prompt hash."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or OUTPUTS / ".cache" / "prompts"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_prompt_hash(
        self, prompt: str, domain: str = "", voiceover: bool = False, extra: dict = None
    ) -> str:
        """Get hash for prompt + params."""
        data = {
            "prompt": prompt,
            "domain": domain,
            "voiceover": voiceover,
        }
        if extra:
            data.update(extra)
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[
            :24
        ]

    def check(
        self, prompt: str, domain: str = "", voiceover: bool = False, extra: dict = None
    ) -> Optional[dict]:
        """Check if cached response exists. Returns cached data if hit, None if miss."""
        if not PROMPT_CACHE_ENABLED:
            return None
        h = self.get_prompt_hash(prompt, domain, voiceover, extra)
        meta_file = self.cache_dir / f"{h}.meta"
        if meta_file.exists():
            try:
                with open(meta_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return None
        return None

    def store(
        self,
        prompt: str,
        result: dict,
        domain: str = "",
        voiceover: bool = False,
        extra: dict = None,
    ):
        """Store generation result in cache."""
        if not PROMPT_CACHE_ENABLED:
            return None
        h = self.get_prompt_hash(prompt, domain, voiceover, extra)
        meta_file = self.cache_dir / f"{h}.meta"
        with open(meta_file, "w") as f:
            json.dump(result, f)
        return meta_file

    def invalidate_all(self):
        """Clear entire prompt cache."""
        for f in self.cache_dir.glob("*.meta"):
            f.unlink()


render_cache = RenderCache()
prompt_cache = PromptCache()
