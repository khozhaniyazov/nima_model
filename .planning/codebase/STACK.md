# Technology Stack

**Analysis Date:** 2026-04-04

## Languages

**Primary:**
- Python 3.x - Backend server, AI pipeline, algorithms
- TypeScript 5 - Frontend Next.js application

**Secondary:**
- JavaScript (JSX) - React components

## Runtime

**Environment:**
- Node.js 20+ (for Next.js frontend)
- Python 3.x (for Flask backend)

**Package Managers:**
- npm (frontend) - `nima-frontend/package.json`
- pip (backend) - `requirements.txt`
- Lockfiles: Not detected in repository

## Frameworks

**Frontend:**
- Next.js 16.1.6 - React framework for web UI
- React 19.2.3 - UI library
- Tailwind CSS 4.2.1 - Styling
- PostCSS 8.5.8 - CSS processing

**Backend:**
- Flask 3.0+ - Python web server
- Flask-CORS - Cross-origin resource sharing

**AI/ML:**
- OpenAI Python SDK 1.30+ - LLM API client
- Manim 0.18+ - Mathematical animation engine

**Testing:**
- Not configured in package.json (no test scripts defined)

**Build/Dev:**
- TypeScript 5 - Type checking
- ESLint 9 - Linting (frontend)
- Autoprefixer 10.4.27 - CSS vendor prefixes

## Key Dependencies

**Critical:**
- `openai>=1.30` - AI code generation and TTS
- `manim>=0.18` - Animation rendering engine
- `flask>=3.0` - Backend API server
- `flask-cors` - CORS support for frontend API calls

**Database:**
- `psycopg2-binary>=2.9` - PostgreSQL adapter for Python

**Data Processing:**
- `numpy>=1.26` - Numerical computations

**Frontend:**
- `next@16.1.6` - Web framework
- `react@19.2.3` - UI library
- `tailwindcss@4.2.1` - CSS framework

**Utilities:**
- `python-dotenv>=1.0` - Environment variable loading

## Configuration

**Environment:**
- `.env` file present at project root (contains secrets - not read)
- `python-dotenv` loads `.env` for backend
- Next.js uses default environment handling

**Key environment variables (from config.py):**
- `OPENAI_API_KEY` - OpenAI API authentication
- `OPENAI_BASE_URL` - OpenAI endpoint (custom or default)
- `DB_CONNECTION_STRING` - PostgreSQL connection
- `GENERATION_MODEL` - Primary LLM for code generation
- `FAST_MODEL` - Lightweight LLM for triage/analysis
- `FAST_PIPELINE` / `DRAFT_PIPELINE` - Pipeline mode flags

**Build:**
- `nima-frontend/tsconfig.json` - TypeScript config with path alias `@/*`
- `nima-frontend/next.config.ts` - Next.js configuration
- `nima-frontend/postcss.config.mjs` - PostCSS with Tailwind plugin
- `nima-frontend/eslint.config.mjs` - ESLint with Next.js rules

## Platform Requirements

**Development:**
- Node.js 20+ (Next.js 16 requirement)
- Python 3.x with pip
- PostgreSQL server (for USE_DATABASE=true)

**Production:**
- Node.js runtime for Next.js (or Vercel/deployed hosting)
- Python 3.x runtime for Flask
- PostgreSQL database
- Manim CLI available in PATH for rendering

---

*Stack analysis: 2026-04-04*
