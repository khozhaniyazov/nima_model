"""
Central configuration for NIMA.
All modules should import from here instead of duplicating settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

# ── OpenAI ──────────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "120"))
GENERATION_MODEL = os.getenv(
    "GENERATION_MODEL", "gpt-5.2-codex"
)  # main code generation model
FAST_MODEL = os.getenv(
    "FAST_MODEL", "gpt-5.2-codex"
)  # light tasks (analysis, fix triage)

# ── Filesystem ───────────────────────────────────────────────────────────────
MANIM_SCRIPTS = Path(os.environ.get("MANIM_SCRIPTS", "C:/temp/manim_scripts"))
OUTPUTS = Path(os.environ.get("OUTPUTS", "C:/temp/outputs"))
MANIM_SCRIPTS.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)

# ── Database ─────────────────────────────────────────────────────────────────
DB_CONNECTION_STRING = os.environ.get(
    "DB_CONNECTION_STRING", "postgresql://postgres:Zk201910902!@localhost:5432/manim_db"
)
USE_DATABASE = os.environ.get("USE_DATABASE", "true").lower() == "true"

# ── Render pipeline ───────────────────────────────────────────────────────────
MAX_GENERATION_ATTEMPTS = 2  # AI generation retries
MAX_RENDER_RETRIES = 3  # manim render retries (with LLM error-fix between each)
RENDER_TIMEOUT_SECONDS = 900  # 15 min max per render
FAST_PIPELINE = os.environ.get("FAST_PIPELINE", "false").lower() == "true"
DRAFT_PIPELINE = (
    os.environ.get("DRAFT_PIPELINE", "false").lower() == "true"
)  # Ultra-fast preview mode

# ── Voiceover (TTS) ──────────────────────────────────────────────────────────
TTS_API_KEY = os.getenv("TTS_API_KEY") or OPENAI_API_KEY
TTS_BASE_URL = os.getenv("TTS_BASE_URL") or OPENAI_BASE_URL
TTS_MODEL = "tts-1"  # OpenAI-compatible TTS model
TTS_VOICE = "nova"  # voice preset
ENABLE_VOICEOVER = os.environ.get("ENABLE_VOICEOVER", "true").lower() == "true"

# ── Rate Limiting ────────────────────────────────────────────────────────────
RATE_LIMIT_ENABLED = True
RATE_LIMIT_REQUESTS = 10  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds

# ── CDN Configuration ──────────────────────────────────────────────────────
CDN_BASE_URL = os.getenv("CDN_BASE_URL", "")  # e.g., "https://cdn.example.com/videos"
CDN_ENABLED = bool(CDN_BASE_URL)

# ── Cache Configuration ──────────────────────────────────────────────────────
RENDER_CACHE_ENABLED = os.environ.get("RENDER_CACHE_ENABLED", "true").lower() == "true"
PROMPT_CACHE_ENABLED = os.environ.get("PROMPT_CACHE_ENABLED", "true").lower() == "true"
CACHE_DIR = OUTPUTS / ".cache"

# ── Asset Preloading ──────────────────────────────────────────────────────
ASSET_PRELOAD_ENABLED = True
WARMUP_LATEX = True
WARMUP_PLANES = True

# ── Streaming Generation (Phase 13) ────────────────────────────────────────
# Multi-provider streaming LLM configuration for scene-by-scene generation
# Providers are tried in order until one responds

# ZJUBAPI (Zhejiang University) — gpt-5.4 (confirmed working)
ZJUBAPI_BASE_URL = os.getenv("ZJUBAPI_BASE_URL", "https://ai-cfs.zju.edu.cn")
ZJUBAPI_API_KEY = os.getenv("ZJUBAPI_API_KEY", "")
ZJUBAPI_MODEL = os.getenv("ZJUBAPI_MODEL", "gpt-5.4")
ZJUBAPI_TIMEOUT = int(os.getenv("ZJUBAPI_TIMEOUT", "45"))

# Wenwen AI — claude-opus-4-6 (confirmed working)
WENWEN_BASE_URL = os.getenv("WENWEN_BASE_URL", "https://api.wenwen-ai.com")
WENWEN_API_KEY = os.getenv("WENWEN_API_KEY", "")
WENWEN_MODEL = os.getenv("WENWEN_MODEL", "claude-opus-4-6")
WENWEN_TIMEOUT = int(os.getenv("WENWEN_TIMEOUT", "45"))

# Streaming provider selection
# Options: "auto" (try zjuapi → wenwen → openai), "zjuapi", "wenwen", "openai"
STREAM_PROVIDER = os.getenv("STREAM_PROVIDER", "auto")

# Streaming pipeline settings
STREAM_SCENE_TIMEOUT = 30  # Max seconds per scene generation
STREAM_MAX_SCENES = 20  # Max scenes to split a video into
STREAM_SCENE_RETRIES = 2  # Max retries per scene on failure
STREAM_PARALLEL_RENDERS = 2  # Number of scenes to render in parallel
