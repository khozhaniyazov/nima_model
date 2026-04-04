# Technology Stack

**Analysis Date:** 2026-04-04

## Languages

**Primary:**
- Python 3.11+ - Backend server, AI pipeline, algorithms, code generation
- TypeScript 5 - Frontend type safety
- JavaScript (ESNext) - Frontend React components

**Secondary:**
- SQL - Database schema and queries (PostgreSQL)

## Runtime

**Backend:**
- Python 3.11 - Flask application server, runs on localhost:5000

**Frontend:**
- Node.js 20+ - Next.js development server
- Next.js 16.1.6 runtime (Edge/Serverless compatible)

**Package Manager:**
- pip (Python) - requirements.txt
- npm (Node.js) - package.json in nima-frontend/

## Frameworks

**Backend:**
- Flask 3.0+ - HTTP server and API endpoints (`app.py`)
- Flask-CORS - Cross-origin resource sharing for frontend API

**Frontend:**
- Next.js 16.1.6 - React 19 framework with App Router
- React 19.2.3 - UI components
- Tailwind CSS 4.2.1 - Utility-first styling (via @tailwindcss/postcss)

**Build/Dev Tools:**
- ESLint 9 - Frontend linting (eslint-config-next)
- TypeScript 5 - Type checking
- PostCSS 8.5.8 - CSS processing for Tailwind

## Key Dependencies

**AI & Code Generation:**
- openai>=1.30 - OpenAI API client (GPT-4o, GPT-4o-mini, GPT-5.2-codex models)
- anthropic>=0.39.0 - Anthropic API client (for evaluation in skills/mcp-builder)
- numpy>=1.26 - Numerical computing for code analysis

**Animation Generation:**
- manim>=0.18 - Mathematical animation engine (3b1b-style videos)

**Database:**
- psycopg2-binary>=2.9 - PostgreSQL database adapter

**Configuration:**
- python-dotenv>=1.0 - Environment variable loading from .env

**Media Processing:**
- ffmpeg (external) - Audio/video concatenation and merging via subprocess

**Frontend Styling:**
- @tailwindcss/postcss - Tailwind CSS v4 PostCSS plugin
- autoprefixer - CSS vendor prefixing

## Configuration

**Environment Variables (.env):**
- `OPENAI_API_KEY` - OpenAI API key for GPT models
- `OPENAI_BASE_URL` - Optional custom OpenAI endpoint
- `GENERATION_MODEL` - Main code generation model (default: gpt-5.2-codex)
- `FAST_MODEL` - Light tasks model (default: gpt-5.2-codex)
- `DB_CONNECTION_STRING` - PostgreSQL connection string
- `USE_DATABASE` - Enable/disable database (default: true)
- `FAST_PIPELINE` - Fast mode flag (default: false)
- `DRAFT_PIPELINE` - Ultra-fast preview mode (default: false)
- `ENABLE_VOICEOVER` - TTS voiceover generation (default: true)
- `TTS_MODEL` - OpenAI TTS model (default: gpt-4o-mini-tts)
- `TTS_VOICE` - Voice preset (default: alloy)

**Build Configuration:**
- `nima-frontend/next.config.ts` - Next.js configuration (minimal, no special options)
- `nima-frontend/tsconfig.json` - TypeScript configuration (inherited from eslint-config-next)
- `nima-frontend/postcss.config.mjs` - PostCSS with Tailwind CSS 4 plugin

**Path Configuration (config.py):**
- `MANIM_SCRIPTS` - `C:/temp/manim_scripts` - Temporary script storage
- `OUTPUTS` - `C:/temp/outputs` - Rendered video output directory
- `RENDER_TIMEOUT_SECONDS` - 900 (15 minutes)
- `MAX_GENERATION_ATTEMPTS` - 2
- `MAX_RENDER_RETRIES` - 3

## Platform Requirements

**Development:**
- Python 3.11+
- Node.js 20+
- PostgreSQL instance (localhost:5432/manim_db)
- ffmpeg in PATH (for TTS and video merging)
- OpenAI API access

**Production:**
- Flask server on port 5000
- Next.js production build (or托管 platform)
- PostgreSQL database
- Persistent storage for outputs and scripts

---

*Stack analysis: 2026-04-04*
