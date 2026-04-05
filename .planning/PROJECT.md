# NIMA — Manim AI Generator

**What This Is**

NIMA is an AI-powered system that generates educational mathematical animations using Manim CE. Users provide a text prompt describing what they want to teach, and NIMA produces a rendered video explaining the concept with dynamic visualizations.

**Core Value**

Single command → animated educational video. No animation expertise required.

**Why This Exists**

Creating quality educational animations (like 3Blue1Brown) requires both mathematical expertise and animation skill. NIMA automates the animation generation using AI, letting educators focus on content rather than production.

---

## Context

**Problem:** Educators and content creators spend hours manually creating mathematical animations. Tools like Manim are powerful but require steep learning curves and significant time investment.

**Solution:** NIMA accepts natural language prompts and produces complete, renderable Manim code that generates educational animations automatically.

**Users:**
- Educators creating online course content
- Students explaining concepts to peers
- Content creators building educational YouTube/TikTok content
- Researchers visualizing concepts for papers

**Current State:** Full-stack application with Flask backend, Next.js frontend, OpenAI integration, and Manim rendering pipeline. Supports video hosting with CDN, theme system, caching, webhooks, LTI integration, and batch processing.

---

## Requirements

### Validated

- ✓ Flask server on localhost:5000 — existing
- ✓ Next.js frontend on localhost:3000 — existing
- ✓ AI pipeline: analyze → plan → generate → validate → render — existing
- ✓ Self-healing render loop (up to 3 retries with LLM error fixing) — existing
- ✓ PostgreSQL persistence for requests, attempts, renders, evaluations — existing
- ✓ TTS voiceover generation and audio-video merge — existing
- ✓ RAG system for golden example retrieval — existing
- ✓ Deterministic plan compiler for math domain — existing
- ✓ Overlap detector for layout validation — existing

### Active

- [ ] Streaming scene-by-scene generation (Milestone 4)
- [ ] Parallel render-while-generate pipeline (Milestone 4)
- [ ] Scene-level retry instead of full video (Milestone 4)
- [ ] Valid Manim API generation (Milestone 4)

### Out of Scope

- Native mobile app — web-only for now
- Real-time collaborative editing — single user per request
- 3D animations — 2D Manim only
- Auto-deployment to hosting — manual deployment required

---

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Flask + Next.js architecture | Proven stack, easy deployment | Working |
| Self-healing render loop | Manim errors common, automatic recovery saves time | 3 retries with LLM fix |
| PostgreSQL for persistence | Structured data for quality tracking | Working |
| Codex models for generation | Latest code generation capabilities | Primary model |
| Zone-based deterministic layout | Predictable placement for math visuals | Working |

---

## Stack

**Backend:** Python 3.x / Flask 3.0+ / OpenAI SDK 1.30+ / Manim 0.18+

**Frontend:** Next.js 16.1.6 / React 19.2.3 / Tailwind CSS 4.2.1 / TypeScript 5

**Database:** PostgreSQL with psycopg2

**AI Models:** OpenAI (configurable: GENERATION_MODEL, FAST_MODEL)

**External Services:** OpenAI API (code generation, TTS), Manim CLI (video rendering), ffmpeg (audio-video merge)

---

## Architecture

```
User Prompt → Flask API → Background Thread
                              ↓
                        analyze_request_type() [LLM classification]
                              ↓
                        create_animation_plan() [storyboard] OR create_plan_json() [deterministic]
                              ↓
                        generate_manim_code() [LLM code generation]
                              ↓
                        validate_*() [AST validation, security, quality]
                              ↓
                        review_and_fix() [LLM review]
                              ↓
                        save_and_render() [Manim CLI + self-healing retry]
                              ↓
                        evaluate_with_gpt4() [quality scoring]
                              ↓
                        Video + Database Record
```

**Key Abstractions:**
- `ManimDatabase` — Database interface (CRUD for all pipeline tables)
- `generate_and_validate_code()` — Full AI pipeline orchestration
- `save_and_render()` — Render loop with LLM-powered error recovery
- `Plan Compiler` — JSON plan → deterministic Manim code

---

## Milestone 2 (2026-04-05) ✓ COMPLETE

**Focus:** RAG & Quality v2, Template Expansion, Evaluation Dashboard

### All Requirements Complete

#### RAG & Quality v2
- [x] M2-RAG-01: Semantic embeddings for pattern retrieval
- [x] M2-RAG-02: High-scorer fine-tuning pipeline (placeholder)
- [x] M2-RAG-03: Error pattern learning from failed renders
- [x] M2-QUAL-01: Quality score prediction before render

#### Template Expansion
- [x] M2-TEMP-01: Expand physics domain templates (wave, field, oscillation)
- [x] M2-TEMP-02: Expand CS domain templates (sorting, trees, graphs)
- [x] M2-TEMP-03: Expand chemistry domain templates (reactions, orbitals)
- [x] M2-TEMP-04: User template contribution system

#### Evaluation Dashboard
- [x] M2-DASH-01: Quality metrics dashboard (Next.js frontend)
- [x] M2-DASH-02: Trend charts (renders per day, quality over time)
- [x] M2-DASH-03: Top examples showcase with playback
- [x] M2-DASH-04: Error pattern visualization

---

## Milestone 3 (2026-04-05) ✓ COMPLETE

**Focus:** Video Hosting, Custom Styling/Branding, Performance Optimization, API/Integrations

### All Requirements Complete

#### Video Hosting
- [x] M3-VID-01: Local video storage with organized directory structure
- [x] M3-VID-02: Video playback within the web interface
- [x] M3-VID-03: CDN integration for faster video delivery
- [x] M3-VID-04: Video metadata and search capabilities

#### Custom Styling/Branding
- [x] M3-STYLE-01: Theme system (light/dark/custom)
- [x] M3-STYLE-02: Watermark/logo customization
- [x] M3-STYLE-03: Intro/outro animation templates
- [x] M3-STYLE-04: Custom color palette support

#### Performance Optimization
- [x] M3-PERF-01: Render caching (skip re-renders for same code)
- [x] M3-PERF-02: Parallel pipeline execution
- [x] M3-PERF-03: Code generation caching
- [x] M3-PERF-04: Asset preloading and optimization

#### API/Integrations
- [x] M3-API-01: Webhook notifications for render completion
- [x] M3-API-02: LMS integration API (Canvas, Moodle)
- [x] M3-API-03: Public API with API key authentication
- [x] M3-API-04: Batch processing improvements

---

## Milestone 4 (TBD)

**Goal:** Eliminate LLM timeout/invalid-API issues with streaming scene-by-scene generation.

### Target Features
1. **Streaming LLM Generation** — Scene-by-scene output, not bulk 10K+ chars
2. **Parallel Render Pipeline** — Render previous scenes while generating next
3. **Narrative Context** — Maintain coherence across all scenes
4. **Scene-Level Retry** — Failed scene re-generates without full video restart

### Active Requirements

#### Streaming Generation (M4-STREAM)
- [ ] M4-STREAM-01: Scene-by-scene streaming generation
- [ ] M4-STREAM-02: Parallel render-while-generate pipeline
- [ ] M4-STREAM-03: Narrative context preservation across scenes
- [ ] M4-STREAM-04: Scene-level retry (not full video)

#### Code Quality (M4-CODE)
- [ ] M4-CODE-01: Valid Manim API generation (no invalid calls like `start_section()`)
- [ ] M4-CODE-02: Scene-level code validation before render
- [ ] M4-CODE-03: Automatic API correction/hints for common mistakes

---

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---

*Last updated: 2026-04-05 after Milestone 4 initialization*
