"""
Central configuration for NIMA.
All modules should import from here instead of duplicating settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=False)

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
TTS_MODEL = "edge-tts"  # Using edge-tts (free, no API key)
TTS_VOICE = "en-US-GuyNeural"  # Microsoft neural voice
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

# ── Job State ────────────────────────────────────────────────────────────────
JOB_STATE_PERSISTENCE = (
    os.environ.get("JOB_STATE_PERSISTENCE", "true").lower() == "true"
)
JOB_STATE_PATH = Path(os.environ.get("JOB_STATE_PATH", str(OUTPUTS / "job_state.json")))
BACKGROUND_MAX_WORKERS = int(os.environ.get("BACKGROUND_MAX_WORKERS", "2"))
WEBHOOK_MAX_WORKERS = int(os.environ.get("WEBHOOK_MAX_WORKERS", "4"))

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

# ── Streaming pipeline settings
STREAM_SCENE_TIMEOUT = 30  # Max seconds per scene generation
STREAM_MAX_SCENES = 20  # Max scenes to split a video into
STREAM_SCENE_RETRIES = 2  # Max retries per scene on failure
STREAM_PARALLEL_RENDERS = (
    1  # Keep TeX renders serialized to avoid MiKTeX file locks on Windows
)
SHORT_DRAFT_FAST_PATH = (
    os.environ.get("SHORT_DRAFT_FAST_PATH", "false").lower() == "true"
)

# ── Video Modes ──────────────────────────────────────────────────────────────
# Each mode defines duration, scene budget, question behaviour, and aspect ratio.
# Modes are selected explicitly via API parameter `mode`.
VIDEO_MODES = {
    "short": {
        "label": "Short (Instagram/TikTok)",
        "duration_range": (55, 60),  # seconds — strict
        "target_duration": 58,
        "max_scenes": 5,
        "min_scenes": 2,
        "aspect": "9:16",
        "questions": {
            "enabled": True,
            "count": 1,  # exactly 1 open question
            "placement": "end",  # only at the very end
            "pause_seconds": 0,  # no pause — just the question text
            "cta_text": "Type your answer in the comments!",
        },
        "narration_style": "punchy, fast-paced, hook-first, social-media-friendly",
        "complexity_cap": "BASIC",
    },
    "standard": {
        "label": "Standard (2–5 min)",
        "duration_range": (120, 300),
        "target_duration": 240,
        "max_scenes": 12,
        "min_scenes": 4,
        "aspect": "16:9",
        "questions": {
            "enabled": False,  # pure information, no questions
        },
        "narration_style": "clear, educational, well-paced",
        "complexity_cap": None,  # no cap
    },
    "course": {
        "label": "Course (≈15 min)",
        "duration_range": (600, 900),
        "target_duration": 900,
        "max_scenes": 40,
        "min_scenes": 25,
        "aspect": "16:9",
        "questions": {
            "enabled": True,
            "placement": "spaced",  # distributed throughout
            "pause_seconds": 10,  # 10s thinking pause per question
            "min_questions": 8,
            "max_questions": 14,
        },
        "narration_style": "thorough, builds intuition step-by-step, uses recap transitions",
        "complexity_cap": None,
    },
    "lecture": {
        "label": "Lecture (30+ min)",
        "duration_range": (1200, 2400),
        "target_duration": 1800,
        "max_scenes": 40,
        "min_scenes": 15,
        "aspect": "16:9",
        "questions": {
            "enabled": True,
            "placement": "spaced",
            "pause_seconds": 10,
            "min_questions": 5,
            "max_questions": 12,
        },
        "narration_style": "formal academic, thorough derivations, lecture-hall pacing",
        "complexity_cap": None,
        "stub": True,  # not fully implemented yet
        "stub_cap_seconds": 900,  # cap at 15 min until full implementation
    },
}

DEFAULT_VIDEO_MODE = "standard"
