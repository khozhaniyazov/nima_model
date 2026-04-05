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

**Current State:** Full-stack application with Flask backend, Next.js frontend, OpenAI integration, and Manim rendering pipeline.

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

- [x] Add batch processing for multiple requests (Phase 5, V2-02)
- [ ] Implement user authentication
- [ ] Add video hosting/integration options
- [ ] Improve RAG with semantic search (Milestone 2)
- [ ] Fine-tune model on high-scorers (Milestone 2)
- [ ] Support additional animation domains (Milestone 2 - expanded templates)
- [ ] Build evaluation dashboard (Milestone 2)
- [ ] Add custom styling/branding options

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

*Last updated: 2026-04-05 after Milestone 2 completion*
