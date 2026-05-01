# NIMA — Manim AI Generator

NIMA turns a natural-language prompt into a rendered [Manim CE](https://www.manim.community/) animation. It exposes a Flask API plus a Next.js frontend, runs an LLM-driven generation pipeline (analyze → plan → generate → review → render), self-heals render errors, and supports streaming scene-by-scene generation with optional TTS voiceover.

> Backend: Python 3.11 + Flask · Frontend: Next.js (in `nima-frontend/`) · LLM: OpenAI-compatible · TTS: edge-tts (free)

## Project layout

```
.
├── app.py                  # Thin Flask bootstrap (factory + blueprints)
├── config.py               # Single source of truth for env-driven config
├── algorithms/             # Pipeline core
│   ├── generation_service  # analyze → plan → generate → review
│   ├── render_service      # save + manim render + self-heal
│   ├── stream_service      # scene-by-scene streaming pipeline (Phase 13)
│   ├── webhook_service     # webhook delivery (with retries)
│   ├── job_dispatcher      # background worker pool
│   ├── job_state           # in-memory + persistent job state
│   ├── job_submission      # request validation + intake
│   ├── batch_completion    # batch lifecycle hooks
│   ├── rate_limiter        # sliding-window per-client limits
│   ├── manim_warmup        # pre-warm planes/templates at boot
│   ├── media_tools         # ffmpeg/manim CLI helpers
│   ├── rendering           # output discovery + paths
│   ├── video_modes         # DRAFT/FAST/FULL/SHORT/COURSE/LECTURE
│   ├── video_quality       # quality scoring
│   ├── vision_adapters     # image/video probing
│   ├── streaming           # streaming planner + scene templates
│   ├── tts                 # edge-tts wrapper + audio mux
│   ├── overlap_detector    # static layout / scene-hygiene checks
│   ├── ai_functions        # OpenAI tool / function-call wrappers
│   ├── code_digest         # code summarization for prompts
│   ├── request_analysis    # prompt intent + plan extraction
│   ├── error_parser        # parse manim/python error output
│   ├── template_registry   # Manim scene templates
│   └── database            # ManimDatabase adapter (psycopg2)
├── api_routes/             # Flask blueprints
│   ├── core, batches, media, templates, webhooks
│   ├── api_keys, lti, payload
├── RAG/                    # Retrieval-augmented examples + fine-tuning
├── tests/                  # pytest suite (with conftest.py)
├── scripts/                # benchmark, streaming sweeps, dev helpers
├── docs/                   # design docs, big-picture roadmap
├── .planning/              # phase plans (01-foundation-stability ... 13-streaming)
├── nima-frontend/          # Next.js dashboard / library / generator UI
├── skills/                 # agentic skill bundles (changelog, MCP, etc.)
├── templates/              # legacy server-rendered templates
├── outputs/, media/, .tmp/ # runtime artifacts (gitignored)
└── database_schema.sql     # PostgreSQL schema
```

## Requirements

- Python 3.11+
- Manim CE (with a working LaTeX install for math rendering)
- ffmpeg
- Optional: PostgreSQL for run logging, an OpenAI-compatible API key

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` in the project root:

```
OPENAI_API_KEY=sk-...
DB_CONNECTION_STRING=postgresql://user:pass@host:5432/nima
USE_DATABASE=true            # set false to disable Postgres logging

# Pipeline
DRAFT_PIPELINE=false         # fastest, lowest quality
FAST_PIPELINE=false          # single-pass, deterministic for math
MAX_GENERATION_ATTEMPTS=3
MAX_RENDER_RETRIES=3

# Streaming + TTS
ENABLE_VOICEOVER=true
TTS_VOICE=en-US-AndrewNeural

# Throughput
BACKGROUND_MAX_WORKERS=4
WEBHOOK_MAX_WORKERS=2
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=20
RATE_LIMIT_WINDOW=60
```

`config.py` is the only module that reads `os.environ`; everywhere else imports from `config`.

## Running

Backend:

```bash
python app.py
# http://localhost:5000  (stats: /stats)
```

Frontend:

```bash
cd nima-frontend
npm install
npm run dev
# http://localhost:3000
```

## Testing

```bash
pip install pytest
pytest tests/ -q
```

CI runs `tests/` (excluding the network-heavy reliability + edge-case stress
suites) plus `ruff check .` on every push / PR. Heavy suites can be triggered
manually:

```bash
python scripts/benchmark.py
python scripts/run_streaming_3_tts.py
python scripts/video_mode_sweep.py
```

## Pipeline overview

1. **Analyze** the prompt (`algorithms/request_analysis`) to detect intent, domain, and pace.
2. **Plan** scenes / beats — deterministic templates for math, LLM-driven otherwise.
3. **Generate** Manim code (`algorithms/generation_service`) with RAG-retrieved examples.
4. **Review** for layout, API misuse, pacing (`algorithms/overlap_detector`, etc.).
5. **Render** via `manim` (`algorithms/render_service`); on failure, feed stderr back to the model and retry up to `MAX_RENDER_RETRIES`.
6. **Stream mode** (Phase 13) renders scene by scene, mixes per-scene TTS, and stitches the final video.

Outputs land in `outputs/`; intermediate Manim media in `media/`. Both are gitignored.

## Notes

- Manim CE must be installed locally; rendering is shelled out via `manim` CLI.
- Use a real WSGI server (gunicorn / waitress) in production — `app.py` runs the dev server.
- See `docs/BIGGER-PICTURE.md` and `.planning/phases/` for roadmap and phase plans.

**Example output:** ![Narrated demonstration](./example.mp4)
