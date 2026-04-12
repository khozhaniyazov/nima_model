# External Integrations

**Analysis Date:** 2026-04-12

## APIs & External Services

**LLM Providers:**
- OpenAI-compatible API - generation, review, and streaming fallback in `app.py`, `algorithms/ai_functions.py`, `algorithms/request_analysis.py`, `algorithms/streaming.py`
  - SDK/Client: `openai` (`OpenAI` client)
  - Auth: `OPENAI_API_KEY`
- ZJUBAPI endpoint (OpenAI-compatible) - primary streaming provider option in `config.py` and `algorithms/streaming.py`
  - SDK/Client: `openai` (`OpenAI` client against custom base URL)
  - Auth: `ZJUBAPI_API_KEY`
- Wenwen API endpoint (OpenAI-compatible wrapper usage) - alternate streaming provider in `config.py` and `algorithms/streaming.py`
  - SDK/Client: `openai` (`OpenAI` client against custom base URL)
  - Auth: `WENWEN_API_KEY`

**Speech/Media Tooling:**
- Microsoft Edge TTS service via `edge_tts` Python package - narration generation in `algorithms/tts.py`
  - SDK/Client: `edge_tts`
  - Auth: Not required by current code path (voice configured by `EDGE_TTS_VOICE` in `algorithms/tts.py`)
- FFmpeg/FFprobe binaries - media probing, concatenation, and muxing in `algorithms/tts.py`, `algorithms/streaming.py`, `app.py`
  - SDK/Client: CLI subprocess calls
  - Auth: Not applicable

## Data Storage

**Databases:**
- PostgreSQL
  - Connection: `DB_CONNECTION_STRING`
  - Client: `psycopg2` (`psycopg2.connect`, `RealDictCursor`) in `app.py`
  - Schema: `database_schema.sql`

**File Storage:**
- Local filesystem for scripts, outputs, and cache directories in `config.py` and `cache.py`
- Optional CDN URL indirection via `CDN_BASE_URL`/`CDN_ENABLED` in `config.py` and `/api/videos/cdn-url` routes in `app.py`

**Caching:**
- Local filesystem cache (render cache and prompt cache) in `cache.py`
  - Backed by `OUTPUTS/.cache/*`
  - Toggles: `RENDER_CACHE_ENABLED`, `PROMPT_CACHE_ENABLED` in `config.py`

## Authentication & Identity

**Auth Provider:**
- Custom API-key auth for selected API endpoints in `app.py`
  - Implementation: hashed key storage in PostgreSQL (`api_keys`, `api_usage` tables in `database_schema.sql`), request validation in `require_api_key` decorator in `app.py`

- LTI 1.3 style LMS integration in `app.py`
  - Implementation: login/launch/config/JWKS routes (`/api/lti/*`) with platform records in `lti_platforms` table in `database_schema.sql`
  - Token handling: `jwt.decode(..., options={"verify_signature": False})` in `app.py`

## Monitoring & Observability

**Error Tracking:**
- None detected (no Sentry/Rollbar/Bugsnag integration found)

**Logs:**
- Application and pipeline logging via print-based logs in `app.py`, `algorithms/tts.py`, `algorithms/streaming.py`
- Persisted operational metadata in PostgreSQL tables such as `render_jobs`, `ai_evaluations`, `error_patterns`, `webhook_deliveries` from `database_schema.sql`

## CI/CD & Deployment

**Hosting:**
- Not explicitly defined in repository configuration files

**CI Pipeline:**
- GitHub Actions workflow in `.github/workflows/test.yml`
  - Python tests and benchmark scripts
  - Lint pipeline using Ruff and Black

## Environment Configuration

**Required env vars:**
- Backend AI/provider settings: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `GENERATION_MODEL`, `FAST_MODEL` in `config.py`
- Streaming provider settings: `STREAM_PROVIDER`, `ZJUBAPI_BASE_URL`, `ZJUBAPI_API_KEY`, `ZJUBAPI_MODEL`, `WENWEN_BASE_URL`, `WENWEN_API_KEY`, `WENWEN_MODEL` in `config.py`
- Database settings: `DB_CONNECTION_STRING`, `USE_DATABASE` in `config.py`
- Pipeline flags: `DRAFT_PIPELINE`, `FAST_PIPELINE`, `ENABLE_VOICEOVER` in `config.py`
- Storage/CDN/cache settings: `MANIM_SCRIPTS`, `OUTPUTS`, `CDN_BASE_URL`, `RENDER_CACHE_ENABLED`, `PROMPT_CACHE_ENABLED` in `config.py`

**Secrets location:**
- Root `.env` file present (`.env`) and loaded by `load_dotenv` in `config.py` and `app.py` (values not inspected)

## Webhooks & Callbacks

**Incoming:**
- Backend API receives incoming requests at Flask routes in `app.py` including `/api/generate`, `/status/<job_id>`, `/api/videos/*`, `/api/templates*`, `/api/lti/*`

**Outgoing:**
- Configurable webhook delivery to third-party URLs via `requests.post` in `deliver_webhook_background` (`app.py`)
  - Event registration/listing endpoints: `/api/webhooks` and `/api/webhooks/<webhook_id>` in `app.py`
  - Delivery metadata persisted in `webhook_deliveries` table (`database_schema.sql`)

---

*Integration audit: 2026-04-12*
