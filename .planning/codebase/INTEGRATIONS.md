# External Integrations

**Analysis Date:** 2026-04-04

## APIs & External Services

**AI Code Generation:**
- OpenAI API - Primary LLM for code generation
  - SDK: `openai>=1.30`
  - Auth: `OPENAI_API_KEY` env var
  - Models: `gpt-5.2-codex` (generation), `gpt-4o-mini` (fallback), `gpt-4o-mini-tts` (TTS)
  - Base URL: `OPENAI_BASE_URL` env var (custom endpoint support)

**TTS/Voiceover:**
- OpenAI TTS - Text-to-speech for voiceover generation
  - Model: `gpt-4o-mini-tts`
  - Voice: `alloy` (configurable via `TTS_VOICE`)

**Animation Rendering:**
- Manim - Mathematical animation engine
  - Package: `manim>=0.18`
  - Execution: Subprocess calls to `manim` CLI
  - Output: MP4 video files

## Data Storage

**PostgreSQL Database:**
- Type: Relational database (PostgreSQL)
- Client: `psycopg2-binary>=2.9`
- Connection: `DB_CONNECTION_STRING` env var
  - Default: `postgresql://postgres:***@localhost:5432/manim_db`
- Feature flag: `USE_DATABASE` env var (default: true)

**Database Tables (via `ManimDatabase` class in `app.py`):**
- `requests` - User prompts and analysis
- `generation_attempts` - Code generation attempts
- `render_jobs` - Manim render jobs
- `ai_evaluations` - Quality evaluations
- `error_patterns` - Known error signatures

**File Storage:**
- Local filesystem
  - Scripts: `C:/temp/manim_scripts/` (configurable via `MANIM_SCRIPTS`)
  - Outputs: `C:/temp/outputs/` (configurable via `OUTPUTS`)
- No cloud storage integration detected

**Caching:**
- None detected (Manim caching disabled via `--disable_caching` flag)

## Authentication & Identity

**No external authentication provider detected**
- API is publicly accessible (Flask default)
- No JWT, OAuth, or session authentication
- No user identity tracking (user_id fields are nullable)

## Monitoring & Observability

**Error Tracking:**
- None detected
- No Sentry, Rollbar, or similar services configured

**Logs:**
- Console/stdout logging via `print()` statements
- Log levels: `INFO`, `WARN`, `ERR`, `DEBUG` via bracket prefixes
- Example: `[DB] [OK]`, `[TIMING]`, `[STARTUP]`

**Quality Evaluation:**
- OpenAI-based quality scoring (`evaluate_with_gpt4` function)
- Stored in `ai_evaluations` table

## CI/CD & Deployment

**Hosting:**
- Not detected
- No cloud hosting configuration found
- Local development server: `flask run` on port 5000
- Frontend dev server: `next dev` on default Next.js port

**CI Pipeline:**
- None detected
- No GitHub Actions, Travis, CircleCI, or similar configs found

**Deployment:**
- Manual deployment via Flask WSGI server
- Next.js can be deployed to Vercel or similar

## Environment Configuration

**Required env vars:**
- `OPENAI_API_KEY` - OpenAI authentication (critical)
- `OPENAI_BASE_URL` - API endpoint (optional, defaults to OpenAI)
- `DB_CONNECTION_STRING` - PostgreSQL connection string

**Optional env vars:**
- `GENERATION_MODEL` - Primary code generation model (default: gpt-5.2-codex)
- `FAST_MODEL` - Light model for analysis (default: gpt-5.2-codex)
- `USE_DATABASE` - Enable/disable DB (default: true)
- `FAST_PIPELINE` - Fast mode (default: false)
- `DRAFT_PIPELINE` - Ultra-fast preview (default: false)
- `ENABLE_VOICEOVER` - TTS generation (default: true)
- `TTS_MODEL` / `TTS_VOICE` - Voice settings
- `MAX_RENDER_RETRIES` / `MAX_GENERATION_ATTEMPTS` - Retry limits
- `RENDER_TIMEOUT_SECONDS` - Render timeout (default: 900)

**Secrets location:**
- `.env` file at project root (NOT committed - should be in .gitignore)
- Config loaded via `python-dotenv`

## Webhooks & Callbacks

**Incoming:**
- None detected
- No webhook endpoints configured

**Outgoing:**
- OpenAI API calls (upstream)
- Manim CLI subprocess execution (local)

---

*Integration audit: 2026-04-04*
