# Technology Stack

**Analysis Date:** 2026-04-12

## Languages

**Primary:**
- Python (3.11 in CI) - backend API, generation pipeline, rendering orchestration in `app.py`, `algorithms/*.py`, and CI workflow `.github/workflows/test.yml`

**Secondary:**
- TypeScript - Next.js frontend in `nima-frontend/src/**/*.ts` and `nima-frontend/src/**/*.tsx`
- SQL (PostgreSQL dialect) - schema and persistence model in `database_schema.sql`

## Runtime

**Environment:**
- Python runtime (CI uses `python-version: '3.11'`) in `.github/workflows/test.yml`
- Node.js runtime for frontend (dependency engine ranges indicate Node 18.18+ family) in `nima-frontend/package-lock.json`

**Package Manager:**
- pip - Python dependencies from `requirements.txt`
- npm - frontend dependencies from `nima-frontend/package.json`
- Lockfile: present (`nima-frontend/package-lock.json`)

## Frameworks

**Core:**
- Flask (`flask>=3.0`) - HTTP server and API routes in `app.py`
- Next.js (`next@16.1.6`) - frontend web app in `nima-frontend/package.json`
- React (`react@19.2.3`, `react-dom@19.2.3`) - UI layer in `nima-frontend/package.json`

**Testing:**
- Python script-based tests executed directly (`python test_imports.py`, `python test_optimizations.py`) in `.github/workflows/test.yml`

**Build/Dev:**
- ESLint (`eslint@^9`, `eslint-config-next@16.1.6`) in `nima-frontend/package.json` and `nima-frontend/eslint.config.mjs`
- Tailwind CSS v4 + PostCSS (`tailwindcss@^4.2.1`, `@tailwindcss/postcss`) in `nima-frontend/package.json` and `nima-frontend/postcss.config.mjs`
- TypeScript (`typescript@^5`) in `nima-frontend/package.json` and `nima-frontend/tsconfig.json`
- Ruff, Black, mypy installed in CI lint job in `.github/workflows/test.yml`

## Key Dependencies

**Critical:**
- `openai>=1.30` - LLM generation and streaming clients in `app.py`, `algorithms/ai_functions.py`, `algorithms/streaming.py`, `algorithms/request_analysis.py`
- `manim>=0.18` - animation generation/rendering target used throughout generation code (for example `algorithms/ai_functions.py`)
- `psycopg2-binary>=2.9` - PostgreSQL connectivity in `app.py`

**Infrastructure:**
- `python-dotenv>=1.0` - environment loading in `config.py`, `app.py`, `algorithms/*.py`
- `numpy>=1.26` - numeric operations used in animation/analysis modules (for example `RAG/RAG_system.py`)
- `flask-cors` import used for CORS middleware in `app.py` (imported, not listed in root `requirements.txt`)
- `edge_tts` import used for narration generation in `algorithms/tts.py` (imported, not listed in root `requirements.txt`)
- `requests` import used for webhook delivery in `app.py` (imported lazily inside `deliver_webhook_background`, not listed in root `requirements.txt`)
- `jwt` import used for LTI launch parsing in `app.py` (imported lazily inside `lti_launch`, not listed in root `requirements.txt`)

## Configuration

**Environment:**
- Centralized env configuration is loaded from `config.py` via `load_dotenv(override=True)`
- `.env` file is present at repository root (`.env`) and used as environment source (contents not analyzed)
- Key backend settings include OpenAI provider settings, database toggle/connection envs, pipeline mode flags, caching flags, CDN base URL, and multi-provider streaming settings in `config.py`

**Build:**
- Frontend compile/lint config: `nima-frontend/tsconfig.json`, `nima-frontend/eslint.config.mjs`, `nima-frontend/postcss.config.mjs`, `nima-frontend/next.config.ts`
- CI configuration: `.github/workflows/test.yml`

## Platform Requirements

**Development:**
- Python environment with packages from `requirements.txt`
- Node/npm environment for frontend in `nima-frontend/package.json`
- Local PostgreSQL when `USE_DATABASE=true` (connection configured via `DB_CONNECTION_STRING` in `config.py`)
- `ffmpeg`/`ffprobe` binaries required by media pipeline in `algorithms/tts.py`, `algorithms/streaming.py`, and `app.py`

**Production:**
- Flask backend process serving API routes from `app.py`
- Next.js frontend process built from `nima-frontend` (scripts `dev/build/start` in `nima-frontend/package.json`)

---

*Stack analysis: 2026-04-12*
