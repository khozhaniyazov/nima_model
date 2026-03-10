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
GENERATION_MODEL = os.getenv("GENERATION_MODEL", "gpt-5.2-codex")          # main code generation model
FAST_MODEL       = os.getenv("FAST_MODEL", "gpt-5.2-codex")     # light tasks (analysis, fix triage)

# ── Filesystem ───────────────────────────────────────────────────────────────
MANIM_SCRIPTS = Path("C:/temp/manim_scripts")
OUTPUTS       = Path("C:/temp/outputs")
MANIM_SCRIPTS.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)

# ── Database ─────────────────────────────────────────────────────────────────
DB_CONNECTION_STRING = os.environ.get(
    "DB_CONNECTION_STRING",
    "postgresql://postgres:Zk201910902!@localhost:5432/manim_db"
)
USE_DATABASE = os.environ.get("USE_DATABASE", "true").lower() == "true"

# ── Render pipeline ───────────────────────────────────────────────────────────
MAX_GENERATION_ATTEMPTS = 2   # AI generation retries
MAX_RENDER_RETRIES      = 3   # manim render retries (with LLM error-fix between each)
RENDER_TIMEOUT_SECONDS  = 900 # 15 min max per render
FAST_PIPELINE = os.environ.get("FAST_PIPELINE", "false").lower() == "true"

# ── Voiceover (TTS) ──────────────────────────────────────────────────────────
TTS_MODEL  = "gpt-4o-mini-tts"      # OpenAI TTS model
TTS_VOICE  = "alloy"                 # voice preset (alloy/ash/coral/echo/fable/nova/onyx/sage/shimmer)
ENABLE_VOICEOVER = True              # global default — can be overridden per request
