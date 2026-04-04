# External Integrations

**Analysis Date:** 2026-04-04

## APIs & External Services

**AI Code Generation:**
- OpenAI API - Primary LLM for code generation
  - SDK: `openai` Python package
  - Models: `gpt-5.2-codex` (generation), `gpt-4o-mini` (fallback), `gpt-4o` (evaluation)
  - Auth: `OPENAI_API_KEY` environment variable
  - Base URL: `OPENAI_BASE_URL` (supports custom endpoints like OpenRouter)

**Text-to-Speech:**
- OpenAI TTS API - Voiceover narration generation
  - SDK: `openai.audio.speech.create()`
  - Model: `gpt-4o-mini-tts`
  - Voice: `alloy` (configurable: ash/coral/echo/fable/nova/onyx/sage/shimmer)
  - Auth: Same `OPENAI_API_KEY`

**AI Evaluation (Skills/MCP):**
- Anthropic API - Alternative AI for evaluation tasks
  - SDK: `anthropic` Python package
  - Used in: `skills/mcp-builder/scripts/evaluation.py`
  - Auth: `ANTHROPIC_API_KEY` (inferred from usage)

**RAG System:**
- Local file-based RAG - Curated Manim pattern corpus
  - Location: `RAG/RAG_system.py`
  - No external API - uses local JSON corpus of ~30 proven Manim patterns

## Data Storage

**PostgreSQL Database:**
- Type: PostgreSQL (local or hosted)
- Connection: `postgresql://postgres:***@localhost:5432/manim_db`
- Client: `psycopg2` Python package
- Schema: `database_schema.sql`

**Tables:**
- `requests` - User animation requests with analysis metadata
- `generation_attempts` - Code generation attempts per request
- `render_jobs` - Manim render job status and outputs
- `ai_evaluations` - Quality evaluation scores per render
- `error_patterns` - Known error signatures for retry optimization
- `training_examples` - High-quality examples for training

**File Storage:**
- Local filesystem - `C:/temp/outputs/` for rendered videos
- Local filesystem - `C:/temp/manim_scripts/` for generated Python scripts
- Local filesystem - `C:/temp/outputs/audio/{job_id}/` for TTS audio segments

**Caching:**
- Manim cache disabled (`--disable_caching` flag) for fresh renders

## Authentication & Identity

**Auth Provider:**
- None implemented - System is open to all users
- No user authentication or authorization layer

**API Security:**
- CORS enabled on Flask backend (`flask_cors`)
- Frontend communicates with backend via `http://localhost:5000`
- No API key or token authentication on Flask endpoints

## Monitoring & Observability

**Logging:**
- Python `print()` statements to stdout/stderr
- Log files: `manim_generator.log`, `flask.log` (rotated/archived)
- No structured logging framework (logging module available but not used)

**Error Tracking:**
- Custom error pattern recording in `error_patterns` table
- Render error self-healing with LLM feedback loop
- Database tracks: `error_category`, `error_signature`, `root_cause`, `fix_description`

**Metrics:**
- `/stats` endpoint returns aggregate metrics:
  - `total_requests` - All requests count
  - `successful_renders` - Done renders count
  - `avg_quality_score` - Average AI evaluation score
  - `unique_error_patterns` - Distinct error types
  - `top_domains` - Most common animation domains

**Health Check:**
- `/health` endpoint - Returns database availability and active job count

## CI/CD & Deployment

**Hosting:**
- Self-hosted on localhost (development)
- Flask app.run on `0.0.0.0:5000`
- No containerization (Dockerfile not present)

**CI Pipeline:**
- GitHub Actions - `.github/workflows/test.yml`
- Runs on: Ubuntu latest
- Python version: 3.11

**Pipeline Steps:**
1. **Test job** - Runs `test_imports.py`, `test_optimizations.py`, `benchmark.py`
2. **Lint job** - Runs `ruff check`, `black --check`
3. **Pipeline modes job** - Tests DRAFT, FAST, FULL modes
4. **Benchmark comparison** - Manual workflow dispatch for PR comparison

## Environment Configuration

**Required env vars:**
- `OPENAI_API_KEY` - OpenAI API authentication
- `OPENAI_BASE_URL` - (optional) Custom API endpoint
- `DB_CONNECTION_STRING` - PostgreSQL connection
- `GENERATION_MODEL` - (optional) Override default gpt-5.2-codex
- `FAST_MODEL` - (optional) Override default gpt-5.2-codex
- `USE_DATABASE` - (optional) true/false, default true
- `FAST_PIPELINE` - (optional) true/false, default false
- `DRAFT_PIPELINE` - (optional) true/false, default false
- `ENABLE_VOICEOVER` - (optional) true/false, default true
- `TTS_MODEL` - (optional) Override TTS model
- `TTS_VOICE` - (optional) Override voice preset

**Secrets location:**
- `.env` file at project root (contains `OPENAI_API_KEY`, `DB_CONNECTION_STRING`)
- `.env` is in `.gitignore` - never committed

## Webhooks & Callbacks

**Incoming:**
- None - Flask API accepts direct POST requests

**Outgoing:**
- None - No outbound webhooks or callback integrations

**Frontend-Backend Communication:**
- REST polling - Frontend polls `/status/{job_id}` every 1.5 seconds
- JSON API - `/api/generate` for job creation, `/api/prompts` for example prompts
- Video delivery - `/outputs/{filename}` endpoint for rendered MP4 downloads

---

*Integration audit: 2026-04-04*
