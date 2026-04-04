# NIMA Feature Categorization

**Analysis Date:** 2026-04-04

**Context:** AI-powered educational animation generation from natural-language prompts using Manim CE.

---

## Table Stakes Features

*Features users expect as baseline. Competitors have these. NIMA must have these to be considered viable.*

| Feature | Implementation | File |
|---------|---------------|------|
| Natural language → animation code | `analyze_request_type()` classifies prompt into domain/complexity/topic, then `generate_manim_code()` produces Manim Python | `algorithms/request_analysis.py`, `algorithms/ai_functions.py` |
| Video rendering | `save_and_render()` calls `manim` CLI, outputs `.mp4` | `app.py` |
| Progress/status tracking | `render_status` dict polled via `/status/<job_id>` | `app.py`, `nima-frontend/src/app/page.tsx` |
| Error messages on failure | `fix_render_error()` + `evaluate_with_gpt4()` for quality scoring | `algorithms/ai_functions.py` |
| Basic prompt input | HTML form (`templates/index.html`) + JSON API (`/api/generate`) | `app.py`, `templates/index.html` |
| Video playback | `/outputs/<path>` endpoint streams `.mp4` | `app.py` |
| Download generated video | Frontend "DL_ASSET" link to `/outputs/` | `nima-frontend/src/app/page.tsx` |
| Syntax validation | `validate_python_syntax()` + `validate_manim_code()` | `algorithms/code_digest.py` |
| Scene class validation | `ensure_scene_class()` guarantees valid `GeneratedScene(Scene)` | `algorithms/code_digest.py` |

**Why table stakes:** A user evaluating NIMA against any other text-to-animation tool expects all of these. Absence = rejection.

---

## Differentiators

*Features that give NIMA competitive advantage. These are why a user would choose NIMA over alternatives.*

### 1. Self-Healing Render Loop

**What:** Up to 3 render attempts with LLM-powered error fixing between each failure.

**How:** `save_and_render()` captures Manim stderr → `fix_render_error()` feeds it to LLM → regenerated code re-rendered. No human intervention.

**Files:**
- `app.py` — `save_and_render()` (lines 782–947)
- `algorithms/ai_functions.py` — `fix_render_error()` (lines 738–769)

**Competitive value:** Manim errors are common. Competitors fail visibly. NIMA recovers automatically — dramatically better user experience.

---

### 2. RAG-Based Golden Example Retrieval

**What:** Curated corpus of 30+ proven Manim patterns (function graphing, ValueTracker, linear transformations, Riemann sums, etc.) retrieved by domain/topic/subtopic matching. Falls back to real high-scoring DB examples.

**Files:**
- `RAG/RAG_system.py` — `retrieve_golden_example()` (lines 1242–1276)
- `RAG/RAG_system.py` — `CORPUS` (lines 26–1123)

**Competitive value:** Generation quality directly tied to pattern library. NIMA doesn't hallucinate — it builds from proven 3b1b-style patterns.

---

### 3. Deterministic Plan Compiler for Math Domain

**What:** JSON plan → deterministic Manim code. Template registry (`two_panel_comparison`, `step_by_step_derivation`, `graph_and_formula`, etc.) guides layout. Fast path bypasses expensive LLM generation.

**Files:**
- `algorithms/plan/compiler.py` — `compile_plan()` (lines 126–237)
- `algorithms/template_registry.py` — `TEMPLATES` dict + `choose_template()` (lines 8–106)
- `algorithms/plan/schema.py` — plan validation

**Competitive value:** Deterministic = reproducible, auditable. Template-based = consistent quality for common patterns.

---

### 4. Domain-Specific Guidance Engine

**What:** Separate guidance prompts for math, physics, CS, chemistry — each with specific Manim techniques (e.g., linear algebra: always show i_hat/j_hat basis vectors first, then apply transformation to unit square).

**Files:**
- `algorithms/ai_functions.py` — `get_domain_specific_guidance()` (lines 236–285)

**Supported domains:** math, physics, computer_science, chemistry, general

**Competitive value:** Generic models produce generic animations. Domain-aware generation produces discipline-appropriate visualizations.

---

### 5. Overlap/Scene-Hygiene Detector

**What:** Static analysis before rendering catches position collisions, object accumulation, missing cleanup, stale copies, and long construct() without section helpers.

**Files:**
- `algorithms/overlap_detector.py` — `run_all_checks()` (lines 191–199)

**Checks performed:**
- `detect_position_collisions()` — multiple objects at same coords
- `detect_object_accumulation()` — too many creates without FadeOut
- `detect_missing_section_cleanup()` — sections without cleanup
- `detect_long_construct()` — 25+ play() calls without helpers
- `detect_stale_copies()` — `.copy()` without removing original

**Competitive value:** Catches layout bugs before rendering wastes 5+ minutes.

---

### 6. Voiceover + Audio-Video Sync

**What:** TTS narration generated per scene segment; audio duration drives animation timing; ffmpeg merges audio + video.

**Files:**
- `algorithms/tts.py` — `generate_voiceover()`, `merge_audio_video()`
- `algorithms/request_analysis.py` — `create_narrated_plan()` (lines 261–376)
- `config.py` — `TTS_MODEL`, `TTS_VOICE`, `ENABLE_VOICEOVER`

**Pipeline:** narration segments → parallel TTS generation → measure durations → pass timing contract to generation → merge with video

**Competitive value:** Complete narrated educational video from a single prompt.

---

### 7. PostgreSQL Quality Tracking & Evaluation

**What:** All requests, generation attempts, render jobs, and AI evaluations persisted. Error patterns tracked with occurrence counts. High-quality examples (≥80 score) retrieved for future RAG.

**Tables:** `requests`, `generation_attempts`, `render_jobs`, `ai_evaluations`, `error_patterns`

**Files:**
- `app.py` — `ManimDatabase` class (lines 104–299)
- `database_schema.sql`

**Competitive value:** NIMA learns. Error patterns inform generation. High-scorers become future examples.

---

### 8. AI-Powered Quality Evaluation

**What:** `evaluate_with_gpt4()` scores layout, educational value, technical accuracy, pacing, and Manim quality. Scores stored for RAG retrieval and analytics.

**Files:**
- `algorithms/ai_functions.py` — `evaluate_with_gpg4()` (lines 816–897)

**Competitive value:** Quantitative quality tracking enables continuous improvement.

---

### 9. Short-Prompt Expansion

**What:** Detects truncated/problem-statement prompts ("Solve log_3(x) = 2…", "Compute lim...") and expands them into full animation descriptions with visual guidance.

**Files:**
- `algorithms/request_analysis.py` — `expand_short_prompt()` (lines 379–426)

**Competitive value:** Users can paste exam problems; NIMA turns them into complete lessons.

---

### 10. Section Lifecycle Helpers

**What:** Auto-injected `start_section()`/`end_section()` helpers track object cleanup across multi-step scenes. Prevents object accumulation and stale visuals.

**Files:**
- `algorithms/ai_functions.py` — `LAYOUT_HELPERS` (lines 119–220)
- `algorithms/overlap_detector.py` — `detect_long_construct()`, `detect_object_accumulation()`

**Competitive value:** Multi-step educational animations (prerequisite → build up → full concept → insight) require rigorous cleanup. Helpers make this reliable.

---

### 11. FAST_PIPELINE / DRAFT_PIPELINE Modes

**What:** Configurable quality/speed tradeoff. DRAFT = ultra-fast preview (10fps, -qk flag). FAST = low quality (15fps, -ql). FULL = production render.

**Files:**
- `config.py` — `FAST_PIPELINE`, `DRAFT_PIPELINE`
- `app.py` — `_run_manim()` adjusts quality/fps per mode (lines 747–760)

**Competitive value:** Quick iteration during content creation, high-quality final output.

---

### 12. Pedagogical Planning Structure

**What:** Storyboard generation enforces conceptual ladder: prerequisite → simple case → build up → full concept → takeaway. Never just "show formula then result."

**Files:**
- `algorithms/request_analysis.py` — `create_animation_plan()` system prompt (lines 134–175)

**Competitive value:** Animations that actually teach, not just display.

---

## Anti-Features

*Things to deliberately NOT build. These are distractions, resource sinks, or contrary to NIMA's core mission.*

### 1. 3D Animations
**Reason:** Manim CE 2D focus is intentional. 3D support would fragment the codebase, complicate templates, and dilute quality. Manim's 3D is a different tool.
**Status:** Explicitly out of scope in `.planning/PROJECT.md`

### 2. Real-Time Collaborative Editing
**Reason:** Single-prompt → single-video is the core workflow. Collaborative editing adds enormous complexity (CRDTs, presence, conflict resolution) with no educational animation use case.
**Status:** Explicitly out of scope

### 3. Native Mobile App
**Reason:** Web-only is correct priority. Mobile animation creation is not a real use case. Responsive web covers mobile viewing.
**Status:** Explicitly out of scope

### 4. Auto-Deployment / Hosting Integration
**Reason:** Manual deployment is acceptable for target users (educators, developers). Automated hosting would lock NIMA into one platform and add DevOps burden.
**Status:** Explicitly out of scope

### 5. Video Hosting / Social Sharing
**Reason:** Users download and upload to their platform of choice. Building video hosting adds infrastructure cost, content moderation liability, and ties NIMA to a single hosting platform.
**Status:** `video hosting/integration options` in Active backlog — do not promote to validated

### 6. User Authentication / Accounts
**Reason:** No multi-user features exist or are planned. Rate limiting via API key is sufficient. Accounts add database complexity and UX friction for a tool used ad-hoc.
**Status:** Not in roadmap

### 7. Generated Video Editing
**Reason:** Post-generation editing (trim, add text, modify scene) would require a video editor UI, frame-accurate manipulation, and re-encoding pipeline. Against the "single prompt → complete video" simplicity.
**Status:** Not in roadmap

### 8. Real-Time Generation Streaming
**Reason:** Manim rendering is inherently batch. Streaming partial frames would require architecture overhaul (WebSocket, frame buffer, progressive rendering). Not worth the complexity.
**Status:** Not in roadmap

### 9. Multiple Animation Styles / Themes
**Reason:** 3b1b-style is the brand. Custom themes (cartoon, whiteboard, sketchy) would fragment the template registry, multiply test cases, and dilute visual consistency. Pick one aesthetic and own it.
**Status:** Not in roadmap

### 10. Script/Code Export Beyond Download
**Reason:** Users already get the `.py` file via `/outputs/`. Building a "share code as Gist" or "export to Colab" feature adds integration complexity without educational value.
**Status:** Not in roadmap

---

## Summary Matrix

| Category | Count | Key Examples |
|----------|-------|-------------|
| Table Stakes | 9 | NL→animation, video render, status tracking, syntax validation |
| Differentiators | 12 | Self-healing render, RAG patterns, deterministic compiler, domain guidance, overlap detector, voiceover, quality tracking |
| Anti-Features | 10 | 3D, collaboration, mobile app, hosting, auth, video editing, streaming, themes |

**Bottom line:** NIMA's moat is reliability (self-healing) + quality (RAG patterns + domain guidance) + completeness (voiceover + evaluation). Build differentiation, avoid anti-features.
